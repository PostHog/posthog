#!/usr/bin/env bash
#-------------------------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See https://go.microsoft.com/fwlink/?linkid=2090316 for license information.
#-------------------------------------------------------------------------------------------------------------
#
# Docs: https://github.com/microsoft/vscode-dev-containers/blob/main/script-library/docs/docker-in-docker.md
# Maintainer: The Dev Container spec maintainers


DOCKER_VERSION="${VERSION:-"latest"}" # The Docker/Moby Engine + CLI should match in version
USE_MOBY="${MOBY:-"true"}"
MOBY_BUILDX_VERSION="${MOBYBUILDXVERSION:-"latest"}"
DOCKER_DASH_COMPOSE_VERSION="${DOCKERDASHCOMPOSEVERSION:-"latest"}" #latest, v2 or none
AZURE_DNS_AUTO_DETECTION="${AZUREDNSAUTODETECTION:-"true"}"
DOCKER_DEFAULT_ADDRESS_POOL="${DOCKERDEFAULTADDRESSPOOL:-""}"
USERNAME="${USERNAME:-"${_REMOTE_USER:-"automatic"}"}"
INSTALL_DOCKER_BUILDX="${INSTALLDOCKERBUILDX:-"true"}"
INSTALL_DOCKER_COMPOSE_SWITCH="${INSTALLDOCKERCOMPOSESWITCH:-"true"}"
MICROSOFT_GPG_KEYS_URI="https://packages.microsoft.com/keys/microsoft.asc"
DOCKER_MOBY_ARCHIVE_VERSION_CODENAMES="bookworm buster bullseye bionic focal jammy noble"
DOCKER_LICENSED_ARCHIVE_VERSION_CODENAMES="bookworm buster bullseye bionic focal hirsute impish jammy noble"
DISABLE_IP6_TABLES="${DISABLEIP6TABLES:-false}"

# Default: Exit on any failure.
set -e

# Clean up
rm -rf /var/lib/apt/lists/*

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
    for CURRENT_USER in "${POSSIBLE_USERS[@]}"; do
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

apt_get_update()
{
    if [ "$(find /var/lib/apt/lists/* | wc -l)" = "0" ]; then
        echo "Running apt-get update..."
        apt-get update -y
    fi
}

# Checks if packages are installed and installs them if not
check_packages() {
    if ! dpkg -s "$@" > /dev/null 2>&1; then
        apt_get_update
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

# Use semver logic to decrement a version number then look for the closest match
find_prev_version_from_git_tags() {
    local variable_name=$1
    local current_version=${!variable_name}
    local repository=$2
    # Normally a "v" is used before the version number, but support alternate cases
    local prefix=${3:-"tags/v"}
    # Some repositories use "_" instead of "." for version number part separation, support that
    local separator=${4:-"."}
    # Some tools release versions that omit the last digit (e.g. go)
    local last_part_optional=${5:-"false"}
    # Some repositories may have tags that include a suffix (e.g. actions/node-versions)
    local version_suffix_regex=$6
    # Try one break fix version number less if we get a failure. Use "set +e" since "set -e" can cause failures in valid scenarios.
    set +e
        major="$(echo "${current_version}" | grep -oE '^[0-9]+' || echo '')"
        minor="$(echo "${current_version}" | grep -oP '^[0-9]+\.\K[0-9]+' || echo '')"
        breakfix="$(echo "${current_version}" | grep -oP '^[0-9]+\.[0-9]+\.\K[0-9]+' 2>/dev/null || echo '')"

        if [ "${minor}" = "0" ] && [ "${breakfix}" = "0" ]; then
            ((major=major-1))
            declare -g ${variable_name}="${major}"
            # Look for latest version from previous major release
            find_version_from_git_tags "${variable_name}" "${repository}" "${prefix}" "${separator}" "${last_part_optional}"
        # Handle situations like Go's odd version pattern where "0" releases omit the last part
        elif [ "${breakfix}" = "" ] || [ "${breakfix}" = "0" ]; then
            ((minor=minor-1))
            declare -g ${variable_name}="${major}.${minor}"
            # Look for latest version from previous minor release
            find_version_from_git_tags "${variable_name}" "${repository}" "${prefix}" "${separator}" "${last_part_optional}"
        else
            ((breakfix=breakfix-1))
            if [ "${breakfix}" = "0" ] && [ "${last_part_optional}" = "true" ]; then
                declare -g ${variable_name}="${major}.${minor}"
            else 
                declare -g ${variable_name}="${major}.${minor}.${breakfix}"
            fi
        fi
    set -e
}

# Function to fetch the version released prior to the latest version
get_previous_version() {
    local url=$1
    local repo_url=$2
    local variable_name=$3
    prev_version=${!variable_name}
    
    output=$(curl -s "$repo_url");
    message=$(echo "$output" | jq -r '.message')
    
    if [[ $message == "API rate limit exceeded"* ]]; then
        echo -e "\nAn attempt to find latest version using GitHub Api Failed... \nReason: ${message}"
        echo -e "\nAttempting to find latest version using GitHub tags."
        find_prev_version_from_git_tags prev_version "$url" "tags/v"
        declare -g ${variable_name}="${prev_version}"
    else 
        echo -e "\nAttempting to find latest version using GitHub Api."
        version=$(echo "$output" | jq -r '.tag_name')
        declare -g ${variable_name}="${version#v}"
    fi  
    echo "${variable_name}=${!variable_name}"
}

get_github_api_repo_url() {
    local url=$1
    echo "${url/https:\/\/github.com/https:\/\/api.github.com\/repos}/releases/latest"
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

# Check if distro is supported
if [ "${USE_MOBY}" = "true" ]; then
    if [[ "${DOCKER_MOBY_ARCHIVE_VERSION_CODENAMES}" != *"${VERSION_CODENAME}"* ]]; then
        err "Unsupported  distribution version '${VERSION_CODENAME}'. To resolve, either: (1) set feature option '\"moby\": false' , or (2) choose a compatible OS distribution"
        err "Support distributions include:  ${DOCKER_MOBY_ARCHIVE_VERSION_CODENAMES}"
        exit 1
    fi
    echo "Distro codename  '${VERSION_CODENAME}'  matched filter  '${DOCKER_MOBY_ARCHIVE_VERSION_CODENAMES}'"
else
    if [[ "${DOCKER_LICENSED_ARCHIVE_VERSION_CODENAMES}" != *"${VERSION_CODENAME}"* ]]; then
        err "Unsupported distribution version '${VERSION_CODENAME}'. To resolve, please choose a compatible OS distribution"
        err "Support distributions include:  ${DOCKER_LICENSED_ARCHIVE_VERSION_CODENAMES}"
        exit 1
    fi
    echo "Distro codename  '${VERSION_CODENAME}'  matched filter  '${DOCKER_LICENSED_ARCHIVE_VERSION_CODENAMES}'"
fi

# Install dependencies
check_packages apt-transport-https curl ca-certificates pigz iptables gnupg2 dirmngr wget jq
if ! type git > /dev/null 2>&1; then
    check_packages git
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

# Version matching for moby-buildx
if [ "${USE_MOBY}" = "true" ]; then
    if [ "${MOBY_BUILDX_VERSION}" = "latest" ]; then
        # Empty, meaning grab whatever "latest" is in apt repo
        buildx_version_suffix=""
    else
        buildx_version_dot_escaped="${MOBY_BUILDX_VERSION//./\\.}"
        buildx_version_dot_plus_escaped="${buildx_version_dot_escaped//+/\\+}"
        buildx_version_regex="^(.+:)?${buildx_version_dot_plus_escaped}([\\.\\+ ~:-]|$)"
        set +e
            buildx_version_suffix="=$(apt-cache madison moby-buildx | awk -F"|" '{print $2}' | sed -e 's/^[ \t]*//' | grep -E -m 1 "${buildx_version_regex}")"
        set -e
        if [ -z "${buildx_version_suffix}" ] || [ "${buildx_version_suffix}" = "=" ]; then
            err "No full or partial moby-buildx version match found for \"${MOBY_BUILDX_VERSION}\" on OS ${ID} ${VERSION_CODENAME} (${architecture}). Available versions:"
            apt-cache madison moby-buildx | awk -F"|" '{print $2}' | grep -oP '^(.+:)?\K.+'
            exit 1
        fi
        echo "buildx_version_suffix ${buildx_version_suffix}"
    fi
fi

# Install Docker / Moby CLI if not already installed
if type docker > /dev/null 2>&1 && type dockerd > /dev/null 2>&1; then
    echo "Docker / Moby CLI and Engine already installed."
else
    if [ "${USE_MOBY}" = "true" ]; then
        # Install engine
        set +e # Handle error gracefully
            apt-get -y install --no-install-recommends moby-cli${cli_version_suffix} moby-buildx${buildx_version_suffix} moby-engine${engine_version_suffix}
            exit_code=$?
        set -e    
        
        if [ ${exit_code} -ne 0 ]; then
            err "Packages for moby not available in OS ${ID} ${VERSION_CODENAME} (${architecture}). To resolve, either: (1) set feature option '\"moby\": false' , or (2) choose a compatible OS version (eg: 'ubuntu-20.04')."
            exit 1
        fi

        # Install compose
        apt-get -y install --no-install-recommends moby-compose || err "Package moby-compose (Docker Compose v2) not available for OS ${ID} ${VERSION_CODENAME} (${architecture}). Skipping."
    else
        apt-get -y install --no-install-recommends docker-ce-cli${cli_version_suffix} docker-ce${engine_version_suffix}
        # Install compose
        apt-get -y install --no-install-recommends docker-compose-plugin || echo "(*) Package docker-compose-plugin (Docker Compose v2) not available for OS ${ID} ${VERSION_CODENAME} (${architecture}). Skipping."
    fi
fi

echo "Finished installing docker / moby!"

docker_home="/usr/libexec/docker"
cli_plugins_dir="${docker_home}/cli-plugins"

# fallback for docker-compose
fallback_compose(){
    local url=$1
    local repo_url=$(get_github_api_repo_url "$url")
    echo -e "\n(!) Failed to fetch the latest artifacts for docker-compose v${compose_version}..."
    get_previous_version "${url}" "${repo_url}" compose_version
    echo -e "\nAttempting to install v${compose_version}"
    curl -fsSL "https://github.com/docker/compose/releases/download/v${compose_version}/docker-compose-linux-${target_compose_arch}" -o ${docker_compose_path}
}

# If 'docker-compose' command is to be included
if [ "${DOCKER_DASH_COMPOSE_VERSION}" != "none" ]; then
    case "${architecture}" in
        amd64) target_compose_arch=x86_64 ;;
        arm64) target_compose_arch=aarch64 ;;
        *)
            echo "(!) Docker in docker does not support machine architecture '$architecture'. Please use an x86-64 or ARM64 machine."
            exit 1
    esac

    docker_compose_path="/usr/local/bin/docker-compose"
    if [ "${DOCKER_DASH_COMPOSE_VERSION}" = "v1" ]; then
        err "The final Compose V1 release, version 1.29.2, was May 10, 2021. These packages haven't received any security updates since then. Use at your own risk."
        INSTALL_DOCKER_COMPOSE_SWITCH="false"

        if [ "${target_compose_arch}" = "x86_64" ]; then
            echo "(*) Installing docker compose v1..."
            curl -fsSL "https://github.com/docker/compose/releases/download/1.29.2/docker-compose-Linux-x86_64" -o ${docker_compose_path}
            chmod +x ${docker_compose_path}

            # Download the SHA256 checksum
            DOCKER_COMPOSE_SHA256="$(curl -sSL "https://github.com/docker/compose/releases/download/1.29.2/docker-compose-Linux-x86_64.sha256" | awk '{print $1}')"
            echo "${DOCKER_COMPOSE_SHA256}  ${docker_compose_path}" > docker-compose.sha256sum
            sha256sum -c docker-compose.sha256sum --ignore-missing
        elif [ "${VERSION_CODENAME}" = "bookworm" ]; then
            err "Docker compose v1 is unavailable for 'bookworm' on Arm64. Kindly switch to use v2"
            exit 1
        else
            # Use pip to get a version that runs on this architecture
            check_packages python3-minimal python3-pip libffi-dev python3-venv
            echo "(*) Installing docker compose v1 via pip..."
            export PYTHONUSERBASE=/usr/local
            pip3 install --disable-pip-version-check --no-cache-dir --user "Cython<3.0" pyyaml wheel docker-compose --no-build-isolation
        fi
    else
        compose_version=${DOCKER_DASH_COMPOSE_VERSION#v}
        docker_compose_url="https://github.com/docker/compose"
        find_version_from_git_tags compose_version "$docker_compose_url" "tags/v"
        echo "(*) Installing docker-compose ${compose_version}..."
        curl -fsSL "https://github.com/docker/compose/releases/download/v${compose_version}/docker-compose-linux-${target_compose_arch}" -o ${docker_compose_path} || {
            if [[ $DOCKER_DASH_COMPOSE_VERSION == "latest" ]]; then 
                fallback_compose "$docker_compose_url"
            else
                echo -e "Error: Failed to install docker-compose v${compose_version}" 
            fi
        }

        chmod +x ${docker_compose_path}

        # Download the SHA256 checksum
        DOCKER_COMPOSE_SHA256="$(curl -sSL "https://github.com/docker/compose/releases/download/v${compose_version}/docker-compose-linux-${target_compose_arch}.sha256" | awk '{print $1}')"
        echo "${DOCKER_COMPOSE_SHA256}  ${docker_compose_path}" > docker-compose.sha256sum
        sha256sum -c docker-compose.sha256sum --ignore-missing

        mkdir -p ${cli_plugins_dir}
        cp ${docker_compose_path} ${cli_plugins_dir}
    fi
fi

# fallback method for compose-switch
fallback_compose-switch() {
    local url=$1
    local repo_url=$(get_github_api_repo_url "$url")
    echo -e "\n(!) Failed to fetch the latest artifacts for compose-switch v${compose_switch_version}..."
    get_previous_version "$url" "$repo_url" compose_switch_version
    echo -e "\nAttempting to install v${compose_switch_version}"
    curl -fsSL "https://github.com/docker/compose-switch/releases/download/v${compose_switch_version}/docker-compose-linux-${architecture}" -o /usr/local/bin/compose-switch
}

# Install docker-compose switch if not already installed - https://github.com/docker/compose-switch#manual-installation
if [ "${INSTALL_DOCKER_COMPOSE_SWITCH}" = "true" ] && ! type compose-switch > /dev/null 2>&1; then
    if type docker-compose > /dev/null 2>&1; then
        echo "(*) Installing compose-switch..."
        current_compose_path="$(which docker-compose)"
        target_compose_path="$(dirname "${current_compose_path}")/docker-compose-v1"
        compose_switch_version="latest"
        compose_switch_url="https://github.com/docker/compose-switch"
        find_version_from_git_tags compose_switch_version "$compose_switch_url"
        curl -fsSL "https://github.com/docker/compose-switch/releases/download/v${compose_switch_version}/docker-compose-linux-${architecture}" -o /usr/local/bin/compose-switch || fallback_compose-switch "$compose_switch_url"
        chmod +x /usr/local/bin/compose-switch
        # TODO: Verify checksum once available: https://github.com/docker/compose-switch/issues/11
        # Setup v1 CLI as alternative in addition to compose-switch (which maps to v2)
        mv "${current_compose_path}" "${target_compose_path}"
        update-alternatives --install ${docker_compose_path} docker-compose /usr/local/bin/compose-switch 99
        update-alternatives --install ${docker_compose_path} docker-compose "${target_compose_path}" 1
    else
        err "Skipping installation of compose-switch as docker compose is unavailable..."
    fi
fi

# If init file already exists, exit
if [ -f "/usr/local/share/docker-init.sh" ]; then
    echo "/usr/local/share/docker-init.sh already exists, so exiting."
    # Clean up
    rm -rf /var/lib/apt/lists/*
    exit 0
fi
echo "docker-init doesn't exist, adding..."

if ! cat /etc/group | grep -e "^docker:" > /dev/null 2>&1; then
        groupadd -r docker
fi

usermod -aG docker ${USERNAME}

# fallback for docker/buildx
fallback_buildx() {
    local url=$1
    local repo_url=$(get_github_api_repo_url "$url")
    echo -e "\n(!) Failed to fetch the latest artifacts for docker buildx v${buildx_version}..."
    get_previous_version "$url" "$repo_url" buildx_version
    buildx_file_name="buildx-v${buildx_version}.linux-${architecture}"
    echo -e "\nAttempting to install v${buildx_version}"
    wget https://github.com/docker/buildx/releases/download/v${buildx_version}/${buildx_file_name}
}
 
if [ "${INSTALL_DOCKER_BUILDX}" = "true" ]; then
    buildx_version="latest"
    docker_buildx_url="https://github.com/docker/buildx"
    find_version_from_git_tags buildx_version "$docker_buildx_url" "refs/tags/v"
    echo "(*) Installing buildx ${buildx_version}..."
    buildx_file_name="buildx-v${buildx_version}.linux-${architecture}"
    
    cd /tmp
    wget https://github.com/docker/buildx/releases/download/v${buildx_version}/${buildx_file_name} || fallback_buildx "$docker_buildx_url"
    
    docker_home="/usr/libexec/docker"
    cli_plugins_dir="${docker_home}/cli-plugins"

    mkdir -p ${cli_plugins_dir}
    mv ${buildx_file_name} ${cli_plugins_dir}/docker-buildx
    chmod +x ${cli_plugins_dir}/docker-buildx

    chown -R "${USERNAME}:docker" "${docker_home}"
    chmod -R g+r+w "${docker_home}"
    find "${docker_home}" -type d -print0 | xargs -n 1 -0 chmod g+s
fi

DOCKER_DEFAULT_IP6_TABLES=""
if [ "$DISABLE_IP6_TABLES" == true ]; then
    requested_version=""
    # checking whether the version requested either is in semver format or just a number denoting the major version
    # and, extracting the major version number out of the two scenarios
    semver_regex="^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(-([0-9A-Za-z-]+(\.[0-9A-Za-z-]+)*))?(\+([0-9A-Za-z-]+(\.[0-9A-Za-z-]+)*))?$"
    if echo "$DOCKER_VERSION" | grep -Eq $semver_regex; then
        requested_version=$(echo $DOCKER_VERSION | cut -d. -f1)
    elif echo "$DOCKER_VERSION" | grep -Eq "^[1-9][0-9]*$"; then
        requested_version=$DOCKER_VERSION
    fi
    if [ "$DOCKER_VERSION" = "latest" ] || [[ -n "$requested_version" && "$requested_version" -ge 27 ]] ; then
        DOCKER_DEFAULT_IP6_TABLES="--ip6tables=false"
        echo "(!) As requested, passing '${DOCKER_DEFAULT_IP6_TABLES}'"
    fi
fi

tee /usr/local/share/docker-init.sh > /dev/null \
<< EOF
#!/bin/sh
#-------------------------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See https://go.microsoft.com/fwlink/?linkid=2090316 for license information.
#-------------------------------------------------------------------------------------------------------------

set -e

AZURE_DNS_AUTO_DETECTION=${AZURE_DNS_AUTO_DETECTION}
DOCKER_DEFAULT_ADDRESS_POOL=${DOCKER_DEFAULT_ADDRESS_POOL}
DOCKER_DEFAULT_IP6_TABLES=${DOCKER_DEFAULT_IP6_TABLES}
EOF

tee -a /usr/local/share/docker-init.sh > /dev/null \
<< 'EOF'
dockerd_start="AZURE_DNS_AUTO_DETECTION=${AZURE_DNS_AUTO_DETECTION} DOCKER_DEFAULT_ADDRESS_POOL=${DOCKER_DEFAULT_ADDRESS_POOL} DOCKER_DEFAULT_IP6_TABLES=${DOCKER_DEFAULT_IP6_TABLES} $(cat << 'INNEREOF'
    # explicitly remove dockerd and containerd PID file to ensure that it can start properly if it was stopped uncleanly
    find /run /var/run -iname 'docker*.pid' -delete || :
    find /run /var/run -iname 'container*.pid' -delete || :

    # -- Start: dind wrapper script --
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

    set_cgroup_nesting()
    {
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
    }

    # Set cgroup nesting, retrying if necessary
    retry_cgroup_nesting=0

    until [ "${retry_cgroup_nesting}" -eq "5" ];
    do
        set +e
            set_cgroup_nesting

            if [ $? -ne 0 ]; then
                echo "(*) cgroup v2: Failed to enable nesting, retrying..."
            else
                break
            fi

            retry_cgroup_nesting=`expr $retry_cgroup_nesting + 1`
        set -e
    done

    # -- End: dind wrapper script --

    # Handle DNS
    set +e
        cat /etc/resolv.conf | grep -i 'internal.cloudapp.net' > /dev/null 2>&1
        if [ $? -eq 0 ] && [ "${AZURE_DNS_AUTO_DETECTION}" = "true" ]
        then
            echo "Setting dockerd Azure DNS."
            CUSTOMDNS="--dns 168.63.129.16"
        else
            echo "Not setting dockerd DNS manually."
            CUSTOMDNS=""
        fi
    set -e

    if [ -z "$DOCKER_DEFAULT_ADDRESS_POOL" ]
    then
        DEFAULT_ADDRESS_POOL=""
    else
        DEFAULT_ADDRESS_POOL="--default-address-pool $DOCKER_DEFAULT_ADDRESS_POOL"
    fi

    # Start docker/moby engine
    ( dockerd $CUSTOMDNS $DEFAULT_ADDRESS_POOL $DOCKER_DEFAULT_IP6_TABLES > /tmp/dockerd.log 2>&1 ) &
INNEREOF
)"

sudo_if() {
    COMMAND="$*"

    if [ "$(id -u)" -ne 0 ]; then
        sudo $COMMAND
    else
        $COMMAND
    fi
}

retry_docker_start_count=0
docker_ok="false"

until [ "${docker_ok}" = "true"  ] || [ "${retry_docker_start_count}" -eq "5" ];
do
    # Start using sudo if not invoked as root
    if [ "$(id -u)" -ne 0 ]; then
        sudo /bin/sh -c "${dockerd_start}"
    else
        eval "${dockerd_start}"
    fi

    retry_count=0
    until [ "${docker_ok}" = "true"  ] || [ "${retry_count}" -eq "5" ];
    do
        sleep 1s
        set +e
            docker info > /dev/null 2>&1 && docker_ok="true"
        set -e

        retry_count=`expr $retry_count + 1`
    done

    if [ "${docker_ok}" != "true" ] && [ "${retry_docker_start_count}" != "4" ]; then
        echo "(*) Failed to start docker, retrying..."
        set +e
            sudo_if pkill dockerd
            sudo_if pkill containerd
        set -e
    fi

    retry_docker_start_count=`expr $retry_docker_start_count + 1`
done

# Execute whatever commands were passed in (if any). This allows us
# to set this script to ENTRYPOINT while still executing the default CMD.
exec "$@"
EOF

chmod +x /usr/local/share/docker-init.sh
chown ${USERNAME}:root /usr/local/share/docker-init.sh

# Clean up
rm -rf /var/lib/apt/lists/*

echo 'docker-in-docker-debian script has completed!'