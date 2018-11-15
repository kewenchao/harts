#!/usr/bin/env python
# !coding=utf8

import logging
import os
import re
import requests
import shutil
import stat
import subprocess
import uuid

logger = logging.getLogger(__name__)

test_suite = "CLA_PCIe_TestSuite_V0_1"
campaign_loc = "/home/hcloud/CLA/testsuites/CLA_PCIe_TestSuite_V0_1/testcases/CLA_PCIe_TestSuite_V0_1.xml"
HARTS_node_list = ["IPC_MEM_PCIE_01", "7560_CDD_PCIE_02"]
config_loc = "/home/hcloud/CLA/config/tc_flow_control.properties"
mail_level = "2"
submitter = "autobuild_server"


def get_iosm_source(url, username, password):
    apply_patch_url = url + "/apply_patch.sh"

    # Get the script
    os.system('wget {} --http-user={} --http-password={}'.format(apply_patch_url, username, password))

    # Read the script file
    patch_script = open('apply_patch.sh', 'r')
    repo_commands = patch_script.read()
    patch_script.close()

    # write commnads to be executed into a new file after chaning the repo sync command
    patch_script_edit = open('apply_patch_edit.sh', 'w')
    for line in repo_commands.splitlines():
        if line[0:9] == 'repo sync':
            line += ' kernel/modules/iosm'
        elif 'wget' in line:
            line += ' --http-user={} --http-password={}'.format(username, password)
        patch_script_edit.write(line + "\n")

    patch_script_edit.close()

    st = os.stat('apply_patch_edit.sh')
    os.chmod('apply_patch_edit.sh', st.st_mode | stat.S_IEXEC)

    # execute the newly created bash file
    subprocess.call(['./apply_patch_edit.sh'], cwd=None)


def get_latest_hcloud_tool_version(url, default):
    try:
        res = r'<a .*?>(.*?.tar.gz)</a>'
        result = requests.get(url)
        content = result.content
        version_list = re.findall(res, content)
        version_list.sort()
        hcloud_tool_version = version_list[-1].replace('.tar.gz', '')
    except Exception as e:
        logger.error("Get hcloud_tool_version fail,Exception: {}".format(e))
        return default
    return hcloud_tool_version


def submit_sessions(**kwargs):
    """
    HARTS Campaign submission script

    Sample command to run it on linux terminal

    python start_external_test.py art_output_URL="https://jfstor001.jf.intel.com/artifactory/cactus-absp-jf/mmr1_ice17-autobuild/1106"

    Kwargs:
        art_output_URL (str): Link to the autobuild page
                owner (str): "patch owner"

    Returns:
        result (bool): result of the submission
        message (str): output message of the submission

    Raises:
        RunTimeError: If invalid key arguments or invalid driver file or invalid test bench name are used or
        creating a driver tarball is failed
    """
    # Maximum test duration in minutes
    timeout = "1440"
    expected_args = ['art_output_URL', 'owner']

    for args in expected_args:
        if args not in kwargs:
            logger.info("Valid Arguments:")
            for arr in expected_args:
                logger.info("{}".format(arr + "\r\n"))
            return False

    temp_dir = "temp-" + str(uuid.uuid4())
    os.mkdir(temp_dir)
    os.chdir(temp_dir)

    # Prepare tar.gz
    get_iosm_source(kwargs['art_output_URL'], kwargs['username'], kwargs['password'])

    # Make a release TAR file
    os.system('make -C kernel/modules/iosm -f Makefile_dev iosm_internal_release ARCHIVE="imc_ipc.tar.gz"')
    for file in os.listdir("kernel/modules/iosm/"):
        if file.endswith(".tar.gz"):
            driver = "kernel/modules/iosm/" + file
            break

    # get hcloud_tool
    url = 'http://musxharts003.imu.intel.com/artifactory/harts-sit-swtools-imc-mu/hcloud_job_submission-release/'
    hcloud_tool_version = get_latest_hcloud_tool_version(
        url, default='hcloud-tools-5.0.2-1840_5_1707')
    os.system("wget {}{}.tar.gz".format(url, hcloud_tool_version))
    os.system("tar -xvzf {}.tar.gz".format(hcloud_tool_version))
    hcloud_tool = "./{}/bin".format(hcloud_tool_version)

    patch_set = kwargs['revision'].split('/')[1]
    patch_num = kwargs['revision'].split('/')[0]
    job_name = "Patch_Set_%s" % patch_set + "_rev_" + patch_num

    mailto = kwargs['owner']

    final_result = True
    returns = ""
    for HARTS_node_name in HARTS_node_list:
        # Submit the campaign
        arguments_for_submission = hcloud_tool + "/hcloud-campaign-submit" + " --node " + HARTS_node_name + " --user-name " \
            + submitter + ' --test-set-name ' + submitter + "_" + job_name + " --mailto " \
            + mailto + ' --mlevel ' + mail_level + ' --exec-time-limit ' + timeout \
            + " --copy-to-target " + driver + ":driver/" + " --test-engine CLA " \
            + "--test-engine-params \"-ts " + campaign_loc

        arguments_for_submission += " -config " + config_loc + "\""

        logger.info("call: %s" % str(arguments_for_submission))

        p = subprocess.Popen(arguments_for_submission, stdout=subprocess.PIPE, shell=True)
        ret, err = p.communicate()
        returns = returns + ("Command output for the submission to HARTS Node %s: " % HARTS_node_name) + ret + "\r\n"
        if err is None:
            result = True
        else:
            logger.info("The command returned error: %s" % err)
            logger.info("The submission to HARTS Node %s has failed!" % HARTS_node_name)
            result = False
        final_result = result and final_result

    #  Remove the temporary directory
    os.chdir("../")
    shutil.rmtree(temp_dir)
    return final_result, returns
