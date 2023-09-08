#!/bin/bash
#
# Library for managing Bitnami components

# Constants
CACHE_ROOT="/tmp/bitnami/pkg/cache"
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
    local package_sha256=""
    local directory="/opt/bitnami"

    # Validate arguments
    shift 2
    while [ "$#" -gt 0 ]; do
        case "$1" in
            -c|--checksum)
                shift
                package_sha256="${1:?missing package checksum}"
                ;;
            *)
                echo "Invalid command line flag $1" >&2
                return 1
                ;;
        esac
        shift
    done

    echo "Downloading $base_name package"
    if [ -f "${CACHE_ROOT}/${base_name}.tar.gz" ]; then
        echo "${CACHE_ROOT}/${base_name}.tar.gz already exists, skipping download."
        cp "${CACHE_ROOT}/${base_name}.tar.gz" .
        rm "${CACHE_ROOT}/${base_name}.tar.gz"
        if [ -f "${CACHE_ROOT}/${base_name}.tar.gz.sha256" ]; then
            echo "Using the local sha256 from ${CACHE_ROOT}/${base_name}.tar.gz.sha256"
            package_sha256="$(< "${CACHE_ROOT}/${base_name}.tar.gz.sha256")"
            rm "${CACHE_ROOT}/${base_name}.tar.gz.sha256"
        fi
    else
	curl --remote-name --silent --show-error --fail "${DOWNLOAD_URL}/${base_name}.tar.gz"
    fi
    if [ -n "$package_sha256" ]; then
        echo "Verifying package integrity"
        echo "$package_sha256  ${base_name}.tar.gz" | sha256sum --check - || return "$?"
    fi
    tar --directory "${directory}" --extract --gunzip --file "${base_name}.tar.gz" --no-same-owner --strip-components=2 || return "$?"
    rm "${base_name}.tar.gz"
}
