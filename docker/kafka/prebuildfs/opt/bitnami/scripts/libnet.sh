#!/bin/bash
#
# Library for network functions

# shellcheck disable=SC1091

# Load Generic Libraries
. /opt/bitnami/scripts/liblog.sh

# Functions

########################
# Resolve IP address for a host/domain (i.e. DNS lookup)
# Arguments:
#   $1 - Hostname to resolve
#   $2 - IP address version (v4, v6), leave empty for resolving to any version
# Returns:
#   IP
#########################
dns_lookup() {
    local host="${1:?host is missing}"
    local ip_version="${2:-}"
    getent "ahosts${ip_version}" "$host" | awk '/STREAM/ {print $1 }' | head -n 1
}

#########################
# Wait for a hostname and return the IP
# Arguments:
#   $1 - hostname
#   $2 - number of retries
#   $3 - seconds to wait between retries
# Returns:
#   - IP address that corresponds to the hostname
#########################
wait_for_dns_lookup() {
    local hostname="${1:?hostname is missing}"
    local retries="${2:-5}"
    local seconds="${3:-1}"
    check_host() {
        if [[ $(dns_lookup "$hostname") == "" ]]; then
            false
        else
            true
        fi
    }
    # Wait for the host to be ready
    retry_while "check_host ${hostname}" "$retries" "$seconds"
    dns_lookup "$hostname"
}

########################
# Get machine's IP
# Arguments:
#   None
# Returns:
#   Machine IP
#########################
get_machine_ip() {
    local -a ip_addresses
    local hostname
    hostname="$(hostname)"
    read -r -a ip_addresses <<< "$(dns_lookup "$hostname" | xargs echo)"
    if [[ "${#ip_addresses[@]}" -gt 1 ]]; then
        warn "Found more than one IP address associated to hostname ${hostname}: ${ip_addresses[*]}, will use ${ip_addresses[0]}"
    elif [[ "${#ip_addresses[@]}" -lt 1 ]]; then
        error "Could not find any IP address associated to hostname ${hostname}"
        exit 1
    fi
    echo "${ip_addresses[0]}"
}

########################
# Check if the provided argument is a resolved hostname
# Arguments:
#   $1 - Value to check
# Returns:
#   Boolean
#########################
is_hostname_resolved() {
    local -r host="${1:?missing value}"
    if [[ -n "$(dns_lookup "$host")" ]]; then
        true
    else
        false
    fi
}

########################
# Parse URL
# Globals:
#   None
# Arguments:
#   $1 - uri - String
#   $2 - component to obtain. Valid options (scheme, authority, userinfo, host, port, path, query or fragment) - String
# Returns:
#   String
parse_uri() {
    local uri="${1:?uri is missing}"
    local component="${2:?component is missing}"

    # Solution based on https://tools.ietf.org/html/rfc3986#appendix-B with
    # additional sub-expressions to split authority into userinfo, host and port
    # Credits to Patryk Obara (see https://stackoverflow.com/a/45977232/6694969)
    local -r URI_REGEX='^(([^:/?#]+):)?(//((([^@/?#]+)@)?([^:/?#]+)(:([0-9]+))?))?(/([^?#]*))?(\?([^#]*))?(#(.*))?'
    #                    ||            |  |||            |         | |            | |         |  |        | |
    #                    |2 scheme     |  ||6 userinfo   7 host    | 9 port       | 11 rpath  |  13 query | 15 fragment
    #                    1 scheme:     |  |5 userinfo@             8 :...         10 path     12 ?...     14 #...
    #                                  |  4 authority
    #                                  3 //...
    local index=0
    case "$component" in
        scheme)
            index=2
            ;;
        authority)
            index=4
            ;;
        userinfo)
            index=6
            ;;
        host)
            index=7
            ;;
        port)
            index=9
            ;;
        path)
            index=10
            ;;
        query)
            index=13
            ;;
        fragment)
            index=14
            ;;
        *)
            stderr_print "unrecognized component $component"
            return 1
            ;;
    esac
    [[ "$uri" =~ $URI_REGEX ]] && echo "${BASH_REMATCH[${index}]}"
}

########################
# Wait for a HTTP connection to succeed
# Globals:
#   *
# Arguments:
#   $1 - URL to wait for
#   $2 - Maximum amount of retries (optional)
#   $3 - Time between retries (optional)
# Returns:
#   true if the HTTP connection succeeded, false otherwise
#########################
wait_for_http_connection() {
    local url="${1:?missing url}"
    local retries="${2:-}"
    local sleep_time="${3:-}"
    if ! retry_while "debug_execute curl --silent ${url}" "$retries" "$sleep_time"; then
        error "Could not connect to ${url}"
        return 1
    fi
}
