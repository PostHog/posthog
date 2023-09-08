#!/bin/bash
#
# Library for managing services

# shellcheck disable=SC1091

# Load Generic Libraries
. /opt/bitnami/scripts/libvalidations.sh
. /opt/bitnami/scripts/liblog.sh

# Functions

########################
# Read the provided pid file and returns a PID
# Arguments:
#   $1 - Pid file
# Returns:
#   PID
#########################
get_pid_from_file() {
    local pid_file="${1:?pid file is missing}"

    if [[ -f "$pid_file" ]]; then
        if [[ -n "$(< "$pid_file")" ]] && [[ "$(< "$pid_file")" -gt 0 ]]; then
            echo "$(< "$pid_file")"
        fi
    fi
}

########################
# Check if a provided PID corresponds to a running service
# Arguments:
#   $1 - PID
# Returns:
#   Boolean
#########################
is_service_running() {
    local pid="${1:?pid is missing}"

    kill -0 "$pid" 2>/dev/null
}

########################
# Stop a service by sending a termination signal to its pid
# Arguments:
#   $1 - Pid file
#   $2 - Signal number (optional)
# Returns:
#   None
#########################
stop_service_using_pid() {
    local pid_file="${1:?pid file is missing}"
    local signal="${2:-}"
    local pid

    pid="$(get_pid_from_file "$pid_file")"
    [[ -z "$pid" ]] || ! is_service_running "$pid" && return

    if [[ -n "$signal" ]]; then
        kill "-${signal}" "$pid"
    else
        kill "$pid"
    fi

    local counter=10
    while [[ "$counter" -ne 0 ]] && is_service_running "$pid"; do
        sleep 1
        counter=$((counter - 1))
    done
}

########################
# Start cron daemon
# Arguments:
#   None
# Returns:
#   true if started correctly, false otherwise
#########################
cron_start() {
    if [[ -x "/usr/sbin/cron" ]]; then
        /usr/sbin/cron
    elif [[ -x "/usr/sbin/crond" ]]; then
        /usr/sbin/crond
    else
        false
    fi
}

########################
# Generate a cron configuration file for a given service
# Arguments:
#   $1 - Service name
#   $2 - Command
# Flags:
#   --run-as - User to run as (default: root)
#   --schedule - Cron schedule configuration (default: * * * * *)
# Returns:
#   None
#########################
generate_cron_conf() {
    local service_name="${1:?service name is missing}"
    local cmd="${2:?command is missing}"
    local run_as="root"
    local schedule="* * * * *"
    local clean="true"

    local clean="true"

    # Parse optional CLI flags
    shift 2
    while [[ "$#" -gt 0 ]]; do
        case "$1" in
            --run-as)
                shift
                run_as="$1"
                ;;
            --schedule)
                shift
                schedule="$1"
                ;;
            --no-clean)
                clean="false"
                ;;
            *)
                echo "Invalid command line flag ${1}" >&2
                return 1
                ;;
        esac
        shift
    done

    mkdir -p /etc/cron.d
    if "$clean"; then
        echo "${schedule} ${run_as} ${cmd}" > /etc/cron.d/"$service_name"
    else
        echo "${schedule} ${run_as} ${cmd}" >> /etc/cron.d/"$service_name"
    fi
}

########################
# Remove a cron configuration file for a given service
# Arguments:
#   $1 - Service name
# Returns:
#   None
#########################
remove_cron_conf() {
    local service_name="${1:?service name is missing}"
    local cron_conf_dir="/etc/monit/conf.d"
    rm -f "${cron_conf_dir}/${service_name}"
}

########################
# Generate a monit configuration file for a given service
# Arguments:
#   $1 - Service name
#   $2 - Pid file
#   $3 - Start command
#   $4 - Stop command
# Flags:
#   --disable - Whether to disable the monit configuration
# Returns:
#   None
#########################
generate_monit_conf() {
    local service_name="${1:?service name is missing}"
    local pid_file="${2:?pid file is missing}"
    local start_command="${3:?start command is missing}"
    local stop_command="${4:?stop command is missing}"
    local monit_conf_dir="/etc/monit/conf.d"
    local disabled="no"

    # Parse optional CLI flags
    shift 4
    while [[ "$#" -gt 0 ]]; do
        case "$1" in
            --disable)
                disabled="yes"
                ;;
            *)
                echo "Invalid command line flag ${1}" >&2
                return 1
                ;;
        esac
        shift
    done

    is_boolean_yes "$disabled" && conf_suffix=".disabled"
    mkdir -p "$monit_conf_dir"
    cat >"${monit_conf_dir}/${service_name}.conf${conf_suffix:-}" <<EOF
check process ${service_name}
  with pidfile "${pid_file}"
  start program = "${start_command}" with timeout 90 seconds
  stop program = "${stop_command}" with timeout 90 seconds
EOF
}

########################
# Remove a monit configuration file for a given service
# Arguments:
#   $1 - Service name
# Returns:
#   None
#########################
remove_monit_conf() {
    local service_name="${1:?service name is missing}"
    local monit_conf_dir="/etc/monit/conf.d"
    rm -f "${monit_conf_dir}/${service_name}.conf"
}

########################
# Generate a logrotate configuration file
# Arguments:
#   $1 - Service name
#   $2 - Log files pattern
# Flags:
#   --period - Period
#   --rotations - Number of rotations to store
#   --extra - Extra options (Optional)
# Returns:
#   None
#########################
generate_logrotate_conf() {
    local service_name="${1:?service name is missing}"
    local log_path="${2:?log path is missing}"
    local period="weekly"
    local rotations="150"
    local extra=""
    local logrotate_conf_dir="/etc/logrotate.d"
    local var_name
    # Parse optional CLI flags
    shift 2
    while [[ "$#" -gt 0 ]]; do
        case "$1" in
            --period|--rotations|--extra)
                var_name="$(echo "$1" | sed -e "s/^--//" -e "s/-/_/g")"
                shift
                declare "$var_name"="${1:?"$var_name" is missing}"
                ;;
            *)
                echo "Invalid command line flag ${1}" >&2
                return 1
                ;;
        esac
        shift
    done

    mkdir -p "$logrotate_conf_dir"
    cat <<EOF | sed '/^\s*$/d' >"${logrotate_conf_dir}/${service_name}"
${log_path} {
  ${period}
  rotate ${rotations}
  dateext
  compress
  copytruncate
  missingok
$(indent "$extra" 2)
}
EOF
}

########################
# Remove a logrotate configuration file
# Arguments:
#   $1 - Service name
# Returns:
#   None
#########################
remove_logrotate_conf() {
    local service_name="${1:?service name is missing}"
    local logrotate_conf_dir="/etc/logrotate.d"
    rm -f "${logrotate_conf_dir}/${service_name}"
}
