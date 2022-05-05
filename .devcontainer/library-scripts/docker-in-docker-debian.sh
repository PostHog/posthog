#!/usr/bin/env bash
#-------------------------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See https://go.microsoft.com/fwlink/?linkid=2090316 for license information.
#-------------------------------------------------------------------------------------------------------------
#
# Docs: https://github.com/microsoft/vscode-dev-containers/blob/main/script-library/docs/docker-in-docker.md
# Maintainer: The VS Code and Codespaces Teams
#
# Syntax: ./docker-in-docker-debian.sh [enable non-root docker access flag] [non-root user] [use moby] [Engine/CLI Version] [Major version for docker-compose]

ENABLE_NONROOT_DOCKER=${1:-"true"}
USERNAME=${2:-"automatic"}
USE_MOBY=${3:-"true"}
DOCKER_VERSION=${4:-"latest"} # The Docker/Moby Engine + CLI should match in version
DOCKER_DASH_COMPOSE_VERSION=${5:-"v1"} # v1 or v2
MICROSOFT_GPG_KEYS_URI="https://packages.microsoft.com/keys/microsoft.asc"
DOCKER_MOBY_ARCHIVE_VERSION_CODENAMES="buster bullseye bionic focal jammy"
DOCKER_LICENSED_ARCHIVE_VERSION_CODENAMES="buster bullseye bionic focal hirsute impish jammy"

# Default: Exit on any failure.
set -e

# Setup STDERR.
err() {
    echo "(!) $*" >&2
}

if [ "$(id -u)" -ne 0 ]; then
    err 'Script must be run as root. Use sudo, su, or add "USER root" to your Dockerfile before running this script.'
    exit 1
fi

###################
# Helper Functions
# See: https://github.com/microsoft/vscode-dev-containers/blob/main/script-library/shared/utils.sh
###################

# Determine the appropriate non-root user
if [ "${USERNAME}" = "auto" ] || [ "${USERNAME}" = "automatic" ]; then
    USERNAME=""
    POSSIBLE_USERS=("vscode" "node" "codespace" "$(awk -v val=1000 -F ":" '$3==val{print $1}' /etc/passwd)")
    for CURRENT_USER in ${POSSIBLE_USERS[@]}; do
        if id -u ${CURRENT_USER} > /dev/null 2>&1; then
            USERNAME=${CURRENT_USER}
            break
        fi
    done
    if [ "${USERNAME}" = "" ]; then
        USERNAME=root
    fi
elif [ "${USERNAME}" = "none" ] || ! id -u ${USERNAME} > /dev/null 2>&1; then
    USERNAME=root
fi

# Get central common setting
get_common_setting() {
    if [ "${common_settings_file_loaded}" != "true" ]; then
        curl -sfL "https://aka.ms/vscode-dev-containers/script-library/settings.env" 2>/dev/null -o /tmp/vsdc-settings.env || echo "Could not download settings file. Skipping."
        common_settings_file_loaded=true
    fi
    if [ -f "/tmp/vsdc-settings.env" ]; then
        local multi_line=""
        if [ "$2" = "true" ]; then multi_line="-z"; fi
        local result="$(grep ${multi_line} -oP "$1=\"?\K[^\"]+" /tmp/vsdc-settings.env | tr -d '\0')"
        if [ ! -z "${result}" ]; then declare -g $1="${result}"; fi
    fi
    echo "$1=${!1}"
}

# Function to run apt-get if needed
apt_get_update_if_needed()
{
    if [ ! -d "/var/lib/apt/lists" ] || [ "$(ls /var/lib/apt/lists/ | wc -l)" = "0" ]; then
        echo "Running apt-get update..."
        apt-get update
    else
        echo "Skipping apt-get update."
    fi
}

# Checks if packages are installed and installs them if not
check_packages() {
    if ! dpkg -s "$@" > /dev/null 2>&1; then
        apt_get_update_if_needed
        apt-get -y install --no-install-recommends "$@"
    fi
}

# Figure out correct version of a three part version number is not passed
find_version_from_git_tags() {
    local variable_name=$1
    local requested_version=${!variable_name}
    if [ "${requested_version}" = "none" ]; then return; fi
    local repository=$2
    local prefix=${3:-"tags/v"}
    local separator=${4:-"."}
    local last_part_optional=${5:-"false"}    
    if [ "$(echo "${requested_version}" | grep -o "." | wc -l)" != "2" ]; then
        local escaped_separator=${separator//./\\.}
        local last_part
        if [ "${last_part_optional}" = "true" ]; then
            last_part="(${escaped_separator}[0-9]+)?"
        else
            last_part="${escaped_separator}[0-9]+"
        fi
        local regex="${prefix}\\K[0-9]+${escaped_separator}[0-9]+${last_part}$"
        local version_list="$(git ls-remote --tags ${repository} | grep -oP "${regex}" | tr -d ' ' | tr "${separator}" "." | sort -rV)"
        if [ "${requested_version}" = "latest" ] || [ "${requested_version}" = "current" ] || [ "${requested_version}" = "lts" ]; then
            declare -g ${variable_name}="$(echo "${version_list}" | head -n 1)"
        else
            set +e
                declare -g ${variable_name}="$(echo "${version_list}" | grep -E -m 1 "^${requested_version//./\\.}([\\.\\s]|$)")"
            set -e
        fi
    fi
    if [ -z "${!variable_name}" ] || ! echo "${version_list}" | grep "^${!variable_name//./\\.}$" > /dev/null 2>&1; then
        err "Invalid ${variable_name} value: ${requested_version}\nValid values:\n${version_list}" >&2
        exit 1
    fi
    echo "${variable_name}=${!variable_name}"
}

###########################################
# Start docker-in-docker installation
###########################################

# Ensure apt is in non-interactive to avoid prompts
export DEBIAN_FRONTEND=noninteractive


# Source /etc/os-release to get OS info
. /etc/os-release
# Fetch host/container arch.
architecture="$(dpkg --print-architecture)"

# Check if distro is suppported
if [ "${USE_MOBY}" = "true" ]; then
    # 'get_common_setting' allows attribute to be updated remotely
    get_common_setting DOCKER_MOBY_ARCHIVE_VERSION_CODENAMES
    if [[ "${DOCKER_MOBY_ARCHIVE_VERSION_CODENAMES}" != *"${VERSION_CODENAME}"* ]]; then
        err "Unsupported  distribution version '${VERSION_CODENAME}'. To resolve, either: (1) set feature option '\"moby\": false' , or (2) choose a compatible OS distribution"
        err "Support distributions include:  ${DOCKER_MOBY_ARCHIVE_VERSION_CODENAMES}"
        exit 1
    fi
    echo "Distro codename  '${VERSION_CODENAME}'  matched filter  '${DOCKER_MOBY_ARCHIVE_VERSION_CODENAMES}'"
else
    get_common_setting DOCKER_LICENSED_ARCHIVE_VERSION_CODENAMES
    if [[ "${DOCKER_LICENSED_ARCHIVE_VERSION_CODENAMES}" != *"${VERSION_CODENAME}"* ]]; then
        err "Unsupported distribution version '${VERSION_CODENAME}'. To resolve, please choose a compatible OS distribution"
        err "Support distributions include:  ${DOCKER_LICENSED_ARCHIVE_VERSION_CODENAMES}"
        exit 1
    fi
    echo "Distro codename  '${VERSION_CODENAME}'  matched filter  '${DOCKER_LICENSED_ARCHIVE_VERSION_CODENAMES}'"
fi

# Install dependencies
check_packages apt-transport-https curl ca-certificates pigz iptables gnupg2 dirmngr
if ! type git > /dev/null 2>&1; then
    apt_get_update_if_needed
    apt-get -y install git
fi

# Swap to legacy iptables for compatibility
if type iptables-legacy > /dev/null 2>&1; then
    update-alternatives --set iptables /usr/sbin/iptables-legacy
    update-alternatives --set ip6tables /usr/sbin/ip6tables-legacy
fi



# Set up the necessary apt repos (either Microsoft's or Docker's)
if [ "${USE_MOBY}" = "true" ]; then

    # Name of open source engine/cli
    engine_package_name="moby-engine"
    cli_package_name="moby-cli"

    # Import key safely and import Microsoft apt repo
    get_common_setting MICROSOFT_GPG_KEYS_URI
    curl -sSL ${MICROSOFT_GPG_KEYS_URI} | gpg --dearmor > /usr/share/keyrings/microsoft-archive-keyring.gpg
    echo "deb [arch=${architecture} signed-by=/usr/share/keyrings/microsoft-archive-keyring.gpg] https://packages.microsoft.com/repos/microsoft-${ID}-${VERSION_CODENAME}-prod ${VERSION_CODENAME} main" > /etc/apt/sources.list.d/microsoft.list
else
    # Name of licensed engine/cli
    engine_package_name="docker-ce"
    cli_package_name="docker-ce-cli"

    # Import key safely and import Docker apt repo
    curl -fsSL https://download.docker.com/linux/${ID}/gpg | gpg --dearmor > /usr/share/keyrings/docker-archive-keyring.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/${ID} ${VERSION_CODENAME} stable" > /etc/apt/sources.list.d/docker.list
fi

# Refresh apt lists
apt-get update

# Soft version matching
if [ "${DOCKER_VERSION}" = "latest" ] || [ "${DOCKER_VERSION}" = "lts" ] || [ "${DOCKER_VERSION}" = "stable" ]; then
    # Empty, meaning grab whatever "latest" is in apt repo
    engine_version_suffix=""
    cli_version_suffix=""
else
    # Fetch a valid version from the apt-cache (eg: the Microsoft repo appends +azure, breakfix, etc...)
    docker_version_dot_escaped="${DOCKER_VERSION//./\\.}"
    docker_version_dot_plus_escaped="${docker_version_dot_escaped//+/\\+}"
    # Regex needs to handle debian package version number format: https://www.systutorials.com/docs/linux/man/5-deb-version/
    docker_version_regex="^(.+:)?${docker_version_dot_plus_escaped}([\\.\\+ ~:-]|$)"
    set +e # Don't exit if finding version fails - will handle gracefully
        cli_version_suffix="=$(apt-cache madison ${cli_package_name} | awk -F"|" '{print $2}' | sed -e 's/^[ \t]*//' | grep -E -m 1 "${docker_version_regex}")"
        engine_version_suffix="=$(apt-cache madison ${engine_package_name} | awk -F"|" '{print $2}' | sed -e 's/^[ \t]*//' | grep -E -m 1 "${docker_version_regex}")"
    set -e
    if [ -z "${engine_version_suffix}" ] || [ "${engine_version_suffix}" = "=" ] || [ -z "${cli_version_suffix}" ] || [ "${cli_version_suffix}" = "=" ] ; then
        err "No full or partial Docker / Moby version match found for \"${DOCKER_VERSION}\" on OS ${ID} ${VERSION_CODENAME} (${architecture}). Available versions:"
        apt-cache madison ${cli_package_name} | awk -F"|" '{print $2}' | grep -oP '^(.+:)?\K.+'
        exit 1
    fi
    echo "engine_version_suffix ${engine_version_suffix}"
    echo "cli_version_suffix ${cli_version_suffix}"
fi

# Install Docker / Moby CLI if not already installed
if type docker > /dev/null 2>&1 && type dockerd > /dev/null 2>&1; then
    echo "Docker / Moby CLI and Engine already installed."
else
    if [ "${USE_MOBY}" = "true" ]; then
        # Install engine
        set +e # Handle error gracefully
            apt-get -y install --no-install-recommends moby-cli${cli_version_suffix} moby-buildx moby-engine${engine_version_suffix}
            if [ $? -ne 0 ]; then
                err "Packages for moby not available in OS ${ID} ${VERSION_CODENAME} (${architecture}). To resolve, either: (1) set feature option '\"moby\": false' , or (2) choose a compatible OS version (eg: 'ubuntu-20.04')."
                exit 1
            fi
        set -e

        # Install compose
        apt-get -y install --no-install-recommends moby-compose || err "Package moby-compose (Docker Compose v2) not available for OS ${ID} ${VERSION_CODENAME} (${architecture}). Skipping."
    else
        apt-get -y install --no-install-recommends docker-ce-cli${cli_version_suffix} docker-ce${engine_version_suffix}
    fi
fi

echo "Finished installing docker / moby!"

# Install Docker Compose if not already installed and is on a supported architecture
if type docker-compose > /dev/null 2>&1; then
    echo "Docker Compose v1 already installed."
else
    target_compose_arch="${architecture}"
    if [ "${target_compose_arch}" = "amd64" ]; then
        target_compose_arch="x86_64"
    fi
    if [ "${target_compose_arch}" != "x86_64" ]; then
        # Use pip to get a version that runs on this architecture
        if ! dpkg -s python3-minimal python3-pip libffi-dev python3-venv > /dev/null 2>&1; then
            apt_get_update_if_needed
            apt-get -y install python3-minimal python3-pip libffi-dev python3-venv
        fi
        export PIPX_HOME=/usr/local/pipx
        mkdir -p ${PIPX_HOME}
        export PIPX_BIN_DIR=/usr/local/bin
        export PYTHONUSERBASE=/tmp/pip-tmp
        export PIP_CACHE_DIR=/tmp/pip-tmp/cache
        pipx_bin=pipx
        if ! type pipx > /dev/null 2>&1; then
            pip3 install --disable-pip-version-check --no-cache-dir --user pipx
            pipx_bin=/tmp/pip-tmp/bin/pipx
        fi
        ${pipx_bin} install --pip-args '--no-cache-dir --force-reinstall' docker-compose
        rm -rf /tmp/pip-tmp
    else
        compose_v1_version="1"
        find_version_from_git_tags compose_v1_version "https://github.com/docker/compose" "tags/"
        echo "(*) Installing docker-compose ${compose_v1_version}..."
        curl -fsSL "https://github.com/docker/compose/releases/download/${compose_v1_version}/docker-compose-Linux-x86_64" -o /usr/local/bin/docker-compose
        chmod +x /usr/local/bin/docker-compose
    fi
fi

# Install docker-compose switch if not already installed - https://github.com/docker/compose-switch#manual-installation
current_v1_compose_path="$(which docker-compose)"
target_v1_compose_path="$(dirname "${current_v1_compose_path}")/docker-compose-v1"
if ! type compose-switch > /dev/null 2>&1; then
    echo "(*) Installing compose-switch..."
    compose_switch_version="latest"
    find_version_from_git_tags compose_switch_version "https://github.com/docker/compose-switch"
    curl -fsSL "https://github.com/docker/compose-switch/releases/download/v${compose_switch_version}/docker-compose-linux-${architecture}" -o /usr/local/bin/compose-switch
    chmod +x /usr/local/bin/compose-switch
    # TODO: Verify checksum once available: https://github.com/docker/compose-switch/issues/11

    # Setup v1 CLI as alternative in addition to compose-switch (which maps to v2)
    mv "${current_v1_compose_path}" "${target_v1_compose_path}"
    update-alternatives --install /usr/local/bin/docker-compose docker-compose /usr/local/bin/compose-switch 99
    update-alternatives --install /usr/local/bin/docker-compose docker-compose "${target_v1_compose_path}" 1
fi
if [ "${DOCKER_DASH_COMPOSE_VERSION}" = "v1" ]; then
    update-alternatives --set docker-compose "${target_v1_compose_path}"
else
    update-alternatives --set docker-compose /usr/local/bin/compose-switch
fi

# If init file already exists, exit
if [ -f "/usr/local/share/docker-init.sh" ]; then
    echo "/usr/local/share/docker-init.sh already exists, so exiting."
    exit 0
fi
echo "docker-init doesnt exist, adding..."

# Add user to the docker group
if [ "${ENABLE_NONROOT_DOCKER}" = "true" ]; then
    if ! getent group docker > /dev/null 2>&1; then
        groupadd docker
    fi

    usermod -aG docker ${USERNAME}
fi

tee /usr/local/share/docker-init.sh > /dev/null \
<< 'EOF'
#!/bin/sh
#-------------------------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See https://go.microsoft.com/fwlink/?linkid=2090316 for license information.
#-------------------------------------------------------------------------------------------------------------

set -e

dockerd_start="$(cat << 'INNEREOF'
    # explicitly remove dockerd and containerd PID file to ensure that it can start properly if it was stopped uncleanly
    # ie: docker kill <ID>
    find /run /var/run -iname 'docker*.pid' -delete || :
    find /run /var/run -iname 'container*.pid' -delete || :

    ## Dind wrapper script from docker team, adapted to a function
    # Maintained: https://github.com/moby/moby/blob/master/hack/dind

    export container=docker

    if [ -d /sys/kernel/security ] && ! mountpoint -q /sys/kernel/security; then
        mount -t securityfs none /sys/kernel/security || {
            echo >&2 'Could not mount /sys/kernel/security.'
            echo >&2 'AppArmor detection and --privileged mode might break.'
        }
    fi

    # Mount /tmp (conditionally)
    if ! mountpoint -q /tmp; then
        mount -t tmpfs none /tmp
    fi

    # cgroup v2: enable nesting
    if [ -f /sys/fs/cgroup/cgroup.controllers ]; then
        # move the processes from the root group to the /init group,
        # otherwise writing subtree_control fails with EBUSY.
        # An error during moving non-existent process (i.e., "cat") is ignored.
        mkdir -p /sys/fs/cgroup/init
        xargs -rn1 < /sys/fs/cgroup/cgroup.procs > /sys/fs/cgroup/init/cgroup.procs || :
        # enable controllers
        sed -e 's/ / +/g' -e 's/^/+/' < /sys/fs/cgroup/cgroup.controllers \
            > /sys/fs/cgroup/cgroup.subtree_control
    fi
    ## Dind wrapper over.

    # Handle DNS
    set +e
    cat /etc/resolv.conf | grep -i 'internal.cloudapp.net'
    if [ $? -eq 0 ]
    then
        echo "Setting dockerd Azure DNS."
        CUSTOMDNS="--dns 168.63.129.16"
    else
        echo "Not setting dockerd DNS manually."
        CUSTOMDNS=""
    fi
    set -e

    # Start docker/moby engine
    ( dockerd $CUSTOMDNS > /tmp/dockerd.log 2>&1 ) &
INNEREOF
)"

# Start using sudo if not invoked as root
if [ "$(id -u)" -ne 0 ]; then
    sudo /bin/sh -c "${dockerd_start}"
else
    eval "${dockerd_start}"
fi

set +e

# Execute whatever commands were passed in (if any). This allows us
# to set this script to ENTRYPOINT while still executing the default CMD.
exec "$@"
EOF

chmod +x /usr/local/share/docker-init.sh
chown ${USERNAME}:root /usr/local/share/docker-init.sh

echo 'docker-in-docker-debian script has completed!'