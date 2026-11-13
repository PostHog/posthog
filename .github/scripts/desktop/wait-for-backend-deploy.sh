#!/usr/bin/env bash
# Waits until the Django backend in every listed environment runs a build that
# contains COMMIT_SHA. The desktop app auto-updates users as soon as a release
# is tagged, so a release that ships before the backend can call endpoints that
# do not exist yet.
#
# The charts deploy writes a GitHub Deployment for the Django image in each
# environment, with task TASK. It posts `success` after the rollout and marks
# the previous record of the same task `inactive`. A deploy of a sha that was
# deployed before reuses that sha's old record, so a rollback posts `success`
# on an old record. A record's updated_at is the time of its newest status.
# So the live build is the most recently updated record whose newest status is
# `success`. A newer record that is in progress or failed does not replace it.
# A rollback done outside the charts deploy writes no record, so the script
# cannot see it.
#
# Any token with `deployments: write`, for example in a pull request workflow,
# can create a record or a status. So the script reads only records and
# statuses that TRUSTED_CREATOR, the App of the charts deploy, created.
#
# master is linear, so the live build contains COMMIT_SHA when COMMIT_SHA is
# an ancestor of the live sha. The compare API answers that, so the script
# needs no git history and no credential other than GH_TOKEN.
#
# Exit codes: 0 every environment contains the commit, 3 timed out, 1 error.
# A GitHub API error during polling counts as "not yet". The script exits 1
# at the timeout only when the last poll had an error.
#
# Rust services do not write these deployments, so this wait does not cover them.
set -euo pipefail

REPOSITORY="${REPOSITORY:?}"
COMMIT_SHA="${COMMIT_SHA:?}"
ENVIRONMENTS="${ENVIRONMENTS:-prod-us prod-eu}"
TASK="${TASK:-deploy}"
TRUSTED_CREATOR="${TRUSTED_CREATOR:-deployment-status-posthog[bot]}"
TIMEOUT_SECONDS="${TIMEOUT_SECONDS:-3600}"
INTERVAL_SECONDS="${INTERVAL_SECONDS:-60}"

EXIT_ERROR=1
EXIT_TIMED_OUT=3
DEPLOYMENTS_PER_PAGE=30
MAX_DEPLOYMENT_PAGES=2

# Bash arithmetic evaluates a variable's value as an expression, which can run a command.
require_whole_number() {
    case "$2" in
        '' | *[!0-9]*)
            echo "::error::$1 must be a whole number, got '$2'." >&2
            exit "$EXIT_ERROR"
            ;;
    esac
}

# Prints the compare status of HEAD against BASE: `ahead` or `identical` means
# HEAD contains BASE, `behind` or `diverged` means it does not.
compare_status() {
    gh api "repos/$REPOSITORY/compare/$1...$2" | jq -r '.status'
}

contains_status() {
    case "$1" in
        ahead | identical) return 0 ;;
        *) return 1 ;;
    esac
}

# Prints the trusted deployments of an environment as "<id> <sha>", most
# recently updated first. Reads up to MAX_DEPLOYMENT_PAGES pages of the list.
list_deployments() {
    local environment="$1" page page_json all_json='[]' count
    for ((page = 1; page <= MAX_DEPLOYMENT_PAGES; page++)); do
        page_json=$(gh api "repos/$REPOSITORY/deployments?environment=$environment&task=$TASK&per_page=$DEPLOYMENTS_PER_PAGE&page=$page") || return 1
        all_json=$(jq -c --argjson page "$page_json" '. + $page' <<<"$all_json") || return 1
        count=$(jq 'length' <<<"$page_json") || return 1
        if [ "$count" -lt "$DEPLOYMENTS_PER_PAGE" ]; then
            break
        fi
    done
    jq -r --arg creator "$TRUSTED_CREATOR" '
        map(select(.creator.login == $creator))
        | sort_by(.updated_at) | reverse
        | .[] | "\(.id) \(.sha)"' <<<"$all_json"
}

# Prints the sha of the live deployment, or nothing when no listed deployment
# has a trusted `success` as its newest status. An empty answer holds the
# release. Returns 1 on an API failure.
find_live_sha() {
    local environment="$1" deployments id sha state
    deployments=$(list_deployments "$environment") || return 1
    while read -r id sha; do
        [ -n "$id" ] || continue
        state=$(gh api "repos/$REPOSITORY/deployments/$id/statuses?per_page=1" |
            jq -r --arg creator "$TRUSTED_CREATOR" '.[0] | select(.creator.login == $creator) | .state') || return 1
        if [ "$state" = "success" ]; then
            echo "$sha"
            return 0
        fi
    done <<<"$deployments"
}

# Returns 0 when COMMIT_SHA is in master, 1 when it is not, and 2 when the
# lookup failed.
check_commit_in_master() {
    local status
    if ! status=$(compare_status "$COMMIT_SHA" master); then
        echo "master: GitHub API request failed, contains ${COMMIT_SHA:0:12}: unknown"
        return 2
    fi
    if contains_status "$status"; then
        return 0
    fi
    return 1
}

# Returns 0 when every environment contains the commit, 1 when one does not
# yet, and 2 when a lookup failed.
check_environments() {
    local environment live status result=0
    for environment in $ENVIRONMENTS; do
        if ! live=$(find_live_sha "$environment"); then
            echo "$environment: GitHub API request failed, contains: unknown"
            result=2
            continue
        fi
        if [ -z "$live" ]; then
            echo "$environment: no live deployment found, contains: no"
            [ "$result" -eq 2 ] || result=1
            continue
        fi
        if ! status=$(compare_status "$COMMIT_SHA" "$live"); then
            echo "$environment: live ${live:0:12}, GitHub API request failed, contains: unknown"
            result=2
            continue
        fi
        if contains_status "$status"; then
            echo "$environment: live ${live:0:12}, contains: yes"
            continue
        fi
        echo "$environment: live ${live:0:12}, contains: no"
        [ "$result" -eq 2 ] || result=1
    done
    return "$result"
}

require_whole_number TIMEOUT_SECONDS "$TIMEOUT_SECONDS"
require_whole_number INTERVAL_SECONDS "$INTERVAL_SECONDS"

echo "Waiting for $ENVIRONMENTS to run a backend build that contains ${COMMIT_SHA:0:12}."
deadline=$(($(date +%s) + TIMEOUT_SECONDS))
commit_in_master=false
while true; do
    result=0
    if [ "$commit_in_master" = false ]; then
        check_commit_in_master || result=$?
        if [ "$result" -eq 1 ]; then
            echo "::error::Commit $COMMIT_SHA is not in master, so the backend deploy cannot be checked." >&2
            exit "$EXIT_ERROR"
        fi
        if [ "$result" -eq 0 ]; then
            commit_in_master=true
        fi
    fi
    if [ "$commit_in_master" = true ]; then
        check_environments || result=$?
    fi
    if [ "$result" -eq 0 ]; then
        echo "Every environment runs a backend build that contains ${COMMIT_SHA:0:12}."
        exit 0
    fi
    if [ "$(date +%s)" -ge "$deadline" ]; then
        break
    fi
    sleep "$INTERVAL_SECONDS"
done

if [ "$result" -eq 2 ]; then
    echo "::error::The last backend deploy check failed after ${TIMEOUT_SECONDS}s." >&2
    exit "$EXIT_ERROR"
fi
echo "The backend does not run ${COMMIT_SHA:0:12} in every environment after ${TIMEOUT_SECONDS}s."
exit "$EXIT_TIMED_OUT"
