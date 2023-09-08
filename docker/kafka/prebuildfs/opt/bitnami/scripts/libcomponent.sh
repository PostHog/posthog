#!/bin/bash
#
# Library for managing Bitnami components

# Constants
DOWNLOAD_URL="https://downloads.bitnami.com/files/stacksmith"

# Functions

########################
# Download and unpack a Bitnami package
# Globals:
#   OS_NAME
#   OS_ARCH
#   OS_FLAVOUR
# Arguments:
#   $1 - component's name
#   $2 - component's version
# Returns:
#   None
#########################
component_unpack() {
    local name="${1:?name is required}"
    local version="${2:?version is required}"
    local base_name="${name}-${version}-${OS_NAME}-${OS_ARCH}-${OS_FLAVOUR}"
    local directory="/opt/bitnami"

    # Validate arguments
    shift 2
    while [ "$#" -gt 0 ]; do
        case "$1" in
            *)
                echo "Invalid command line flag $1" >&2
                return 1
                ;;
        esac
        shift
    done
    set -x
    echo "Downloading $base_name package"
	curl --remote-name --silent --show-error --fail "${DOWNLOAD_URL}/${base_name}.tar.gz"

    echo "Verifying package integrity"
    curl --remote-name --silent --show-error --fail "${DOWNLOAD_URL}/${base_name}.tar.gz.sha256"
    cat ${base_name}.tar.gz.sha256 | sha256sum --check - || return "$?"
    rm "${base_name}.tar.gz.sha256"

    tar --directory "${directory}" --extract --gunzip --file "${base_name}.tar.gz" --no-same-owner --strip-components=2 || return "$?"
    rm "${base_name}.tar.gz"
}
