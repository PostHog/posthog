#!/bin/bash
#
# Library for managing files

# shellcheck disable=SC1091

# Load Generic Libraries
. /opt/bitnami/scripts/libos.sh

# Functions

########################
# Replace a regex-matching string in a file
# Arguments:
#   $1 - filename
#   $2 - match regex
#   $3 - substitute regex
#   $4 - use POSIX regex. Default: true
# Returns:
#   None
#########################
replace_in_file() {
    local filename="${1:?filename is required}"
    local match_regex="${2:?match regex is required}"
    local substitute_regex="${3:?substitute regex is required}"
    local posix_regex=${4:-true}

    local result

    # We should avoid using 'sed in-place' substitutions
    # 1) They are not compatible with files mounted from ConfigMap(s)
    # 2) We found incompatibility issues with Debian10 and "in-place" substitutions
    local -r del=$'\001' # Use a non-printable character as a 'sed' delimiter to avoid issues
    if [[ $posix_regex = true ]]; then
        result="$(sed -E "s${del}${match_regex}${del}${substitute_regex}${del}g" "$filename")"
    else
        result="$(sed "s${del}${match_regex}${del}${substitute_regex}${del}g" "$filename")"
    fi
    echo "$result" > "$filename"
}

########################
# Replace a regex-matching multiline string in a file
# Arguments:
#   $1 - filename
#   $2 - match regex
#   $3 - substitute regex
# Returns:
#   None
#########################
replace_in_file_multiline() {
    local filename="${1:?filename is required}"
    local match_regex="${2:?match regex is required}"
    local substitute_regex="${3:?substitute regex is required}"

    local result
    local -r del=$'\001' # Use a non-printable character as a 'sed' delimiter to avoid issues
    result="$(perl -pe "BEGIN{undef $/;} s${del}${match_regex}${del}${substitute_regex}${del}sg" "$filename")"
    echo "$result" > "$filename"
}

########################
# Remove a line in a file based on a regex
# Arguments:
#   $1 - filename
#   $2 - match regex
#   $3 - use POSIX regex. Default: true
# Returns:
#   None
#########################
remove_in_file() {
    local filename="${1:?filename is required}"
    local match_regex="${2:?match regex is required}"
    local posix_regex=${3:-true}
    local result

    # We should avoid using 'sed in-place' substitutions
    # 1) They are not compatible with files mounted from ConfigMap(s)
    # 2) We found incompatibility issues with Debian10 and "in-place" substitutions
    if [[ $posix_regex = true ]]; then
        result="$(sed -E "/$match_regex/d" "$filename")"
    else
        result="$(sed "/$match_regex/d" "$filename")"
    fi
    echo "$result" > "$filename"
}

########################
# Appends text after the last line matching a pattern
# Arguments:
#   $1 - file
#   $2 - match regex
#   $3 - contents to add
# Returns:
#   None
#########################
append_file_after_last_match() {
    local file="${1:?missing file}"
    local match_regex="${2:?missing pattern}"
    local value="${3:?missing value}"

    # We read the file in reverse, replace the first match (0,/pattern/s) and then reverse the results again
    result="$(tac "$file" | sed -E "0,/($match_regex)/s||${value}\n\1|" | tac)"
    echo "$result" > "$file"
}

########################
# Wait until certain entry is present in a log file
# Arguments:
#   $1 - entry to look for
#   $2 - log file
#   $3 - max retries. Default: 12
#   $4 - sleep between retries (in seconds). Default: 5
# Returns:
#   Boolean
#########################
wait_for_log_entry() {
    local -r entry="${1:-missing entry}"
    local -r log_file="${2:-missing log file}"
    local -r retries="${3:-12}"
    local -r interval_time="${4:-5}"
    local attempt=0

    check_log_file_for_entry() {
        if ! grep -qE "$entry" "$log_file"; then
            debug "Entry \"${entry}\" still not present in ${log_file} (attempt $((++attempt))/${retries})"
            return 1
        fi
    }
    debug "Checking that ${log_file} log file contains entry \"${entry}\""
    if retry_while check_log_file_for_entry "$retries" "$interval_time"; then
        debug "Found entry \"${entry}\" in ${log_file}"
        true
    else
        error "Could not find entry \"${entry}\" in ${log_file} after ${retries} retries"
        debug_execute cat "$log_file"
        return 1
    fi
}
