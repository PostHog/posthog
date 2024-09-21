import argparse
import os
import shutil
import glob
import xml.etree.ElementTree as ET


# For revertible cloud deploys:
# 1. Edit and develop using the top level functions inside of user_scripts, along with `user_defined_function.xml` inside of `docker/clickhouse`
# 1. Increment the version below and run this file every time you make breaking changes to UDFs (likely involving type definitions).
# 2. After running this, you have to copy the `user_defined_function.xml` file in the newly created version folder (e.g. `user_scripts/v4/user_defined_function.xml`) to the `posthog-cloud-infra` repo and deploy it
# 3. After that deploy goes out, it is safe to land and deploy the changes to the `posthog` repo
# If deploys aren't seamless, look into moving the action that copies the `user_scripts` folder to the clickhouse cluster earlier in the deploy process
UDF_VERSION = 0  # Last modified by: @aspicer, 2024-09-20

ROOT_PATH = os.path.abspath(os.path.dirname(__name__))

CLICKHOUSE_XML_FILENAME = "user_defined_function.xml"
ACTIVE_XML_CONFIG = "../../docker/clickhouse/user_defined_function.xml"

format_version_string = lambda version: f"v{version}"
VERSION_STR = format_version_string(UDF_VERSION)
LAST_VERSION_STR = format_version_string(UDF_VERSION - 1)

augment_function_name = lambda name: f"{name}_{VERSION_STR}"

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Create a new version for UDF deployment.")
    parser.add_argument("-f", "--force", action="store_true", help="override existing directories")
    args = parser.parse_args()

    os.chdir("user_scripts")
    if args.force:
        shutil.rmtree(VERSION_STR)
    try:
        os.mkdir(VERSION_STR)
    except FileExistsError:
        if not args.force:
            raise FileExistsError(
                f"A directory already exists for this version at posthog/user_scripts/{VERSION_STR}. Did you forget to increment the version? If not, delete the folder and run this again, or run this script with a -f"
            )
    for file in glob.glob("*.py"):
        shutil.copy(file, VERSION_STR)

    base_xml = ET.parse(ACTIVE_XML_CONFIG)

    if os.path.exists(LAST_VERSION_STR):
        last_version_xml = ET.parse(os.path.join(LAST_VERSION_STR, CLICKHOUSE_XML_FILENAME))
    else:
        last_version_xml = ET.parse(ACTIVE_XML_CONFIG)

    last_version_root = last_version_xml.getroot()
    # We want to update the name and the command to include the version, and add it to last version
    for function in list(base_xml.getroot()):
        name = function.find("name")
        name.text = augment_function_name(name.text)
        command = function.find("command")
        command.text = f"{VERSION_STR}/{command.text}"
        last_version_root.append(function)

    last_version_xml.write(os.path.join(VERSION_STR, CLICKHOUSE_XML_FILENAME))
