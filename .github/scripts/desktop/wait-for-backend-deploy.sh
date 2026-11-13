#!/usr/bin/env bash
# Waits until the Django backend in every listed environment runs a build that
# contains COMMIT_SHA. The desktop app auto-updates users as soon as a release
# is tagged, so a release that ships before the backend can call endpoints that
# do not exist yet.
#
# The charts deploy writes a GitHub Deployment for the Django image in each
# environment, with task TASK, and marks it `success` after the rollout. So the
# live build of an environment is the newest deployment of that task that ever
# reached `success`. A newer deployment that is in progress or failed does not
# replace it. A rollback is a newer deployment that succeeds, so its older sha
# becomes the live one.
#
# The script ignores `inactive`. GitHub marks every older deployment in the
# same environment `inactive` when any deployment succeeds, whatever its task,
# so a deploy of another service would hide the live Django build.
#
# master is linear, so the live build contains COMMIT_SHA when COMMIT_SHA is
# an ancestor of the live sha.
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
TIMEOUT_SECONDS="${TIMEOUT_SECONDS:-3600}"
INTERVAL_SECONDS="${INTERVAL_SECONDS:-60}"

EXIT_ERROR=1
EXIT_TIMED_OUT=3

# Bash arithmetic evaluates a variable's value as an expression, which can run a command.
require_whole_number() {
    case "$2" in
        '' | *[!0-9]*)
            echo "::error::$1 must be a whole number, got '$2'." >&2
            exit "$EXIT_ERROR"
            ;;
    esac
}

has_commit() {
    git cat-file -e "$1^{commit}" 2>/dev/null
}

# A deployment can be newer than the checkout, so fetch master once before a
# sha is reported as unknown.
ensure_commit() {
    if has_commit "$1"; then
        return 0
    fi
    git fetch --quiet --no-tags origin master >&2 || return 1
    has_commit "$1"
}

# Prints the sha of the live deployment, or nothing when no recent deployment
# reached `success`. Returns 1 on an API failure.
find_live_sha() {
    local environment="$1" deployments id sha succeeded
    deployments=$(gh api "repos/$REPOSITORY/deployments?environment=$environment&task=$TASK&per_page=30" |
        jq -r '.[] | "\(.id) \(.sha)"') || return 1
    while read -r id sha; do
        [ -n "$id" ] || continue
        succeeded=$(gh api "repos/$REPOSITORY/deployments/$id/statuses?per_page=100" |
            jq -r 'any(.[]; .state == "success")') || return 1
        if [ "$succeeded" = "true" ]; then
            echo "$sha"
            return 0
        fi
    done <<<"$deployments"
}

# Returns 0 when every environment contains the commit, 1 when one does not
# yet, and 2 when a lookup failed.
check_environments() {
    local environment live result=0
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
        if ! ensure_commit "$live"; then
            echo "$environment: live ${live:0:12} is not in master, contains: unknown"
            result=2
            continue
        fi
        if git merge-base --is-ancestor "$COMMIT_SHA" "$live"; then
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

if ! ensure_commit "$COMMIT_SHA"; then
    echo "::error::Commit $COMMIT_SHA is not in master, so the backend deploy cannot be checked." >&2
    exit "$EXIT_ERROR"
fi

echo "Waiting for $ENVIRONMENTS to run a backend build that contains ${COMMIT_SHA:0:12}."
deadline=$(($(date +%s) + TIMEOUT_SECONDS))
while true; do
    result=0
    check_environments || result=$?
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
