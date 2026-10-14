#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=.agents/skills/debugging-ci-failures/scripts/master-red-revert.sh
source "$script_dir/master-red-revert.sh"

workdir="$(mktemp -d)"
trap 'rm -rf "$workdir"' EXIT

failures=0

check() {
    local name="$1" expected="$2" actual="$3"
    if [ "$expected" != "$actual" ]; then
        echo "FAIL: $name"
        echo "  expected: $expected"
        echo "  actual:   $actual"
        failures=$((failures + 1))
        return
    fi
    echo "ok: $name"
}

run() {
    local id=$1 sha=$2 status=$3 conclusion=$4 created=$5
    printf '{"id":%s,"head_sha":"%s","status":"%s","conclusion":%s,"created_at":"%s"}' \
        "$id" "$sha" "$status" "$conclusion" "$created"
}

runs_page() {
    local IFS=,
    printf '{"workflow_runs":[%s]}\n' "$*"
}

# The boundary is the oldest failure after the newest success. A cancelled or in-progress run
# between them was pushed over, so counting it as green would name the wrong commit.
check "boundary skips cancelled and in-progress runs" \
    "1 green 3 red1 5" \
    "$(runs_page \
        "$(run 6 tip in_progress null 2026-01-01T06:00:00Z)" \
        "$(run 5 red2 completed '"failure"' 2026-01-01T05:00:00Z)" \
        "$(run 4 mid completed '"cancelled"' 2026-01-01T04:00:00Z)" \
        "$(run 3 red1 completed '"timed_out"' 2026-01-01T03:00:00Z)" \
        "$(run 2 pushed-over completed '"cancelled"' 2026-01-01T02:00:00Z)" \
        "$(run 1 green completed '"success"' 2026-01-01T01:00:00Z)" | pick_boundary)"

check "boundary reports a recovered lane" \
    "green" \
    "$(runs_page \
        "$(run 2 fixed completed '"success"' 2026-01-01T02:00:00Z)" \
        "$(run 1 red completed '"failure"' 2026-01-01T01:00:00Z)" | pick_boundary)"

check "boundary needs a green run in reach" \
    "" \
    "$(runs_page "$(run 1 red completed '"failure"' 2026-01-01T01:00:00Z)" | pick_boundary)"

check "boundary reads every fetched page" \
    "1 green 2 red 3" \
    "$({
        runs_page "$(run 3 red2 completed '"failure"' 2026-01-01T03:00:00Z)" \
            "$(run 2 red completed '"failure"' 2026-01-01T02:00:00Z)"
        runs_page "$(run 1 green completed '"success"' 2026-01-01T01:00:00Z)"
    } | pick_boundary)"

culprit=1111111111111111111111111111111111111111
check "pull request is the one that merged the culprit" \
    "42" \
    "$(printf '[%s,%s]' \
        "{\"number\":41,\"merged_at\":null,\"merge_commit_sha\":\"$culprit\",\"base\":{\"ref\":\"master\"}}" \
        "{\"number\":42,\"merged_at\":\"2026-01-01T00:00:00Z\",\"merge_commit_sha\":\"$culprit\",\"base\":{\"ref\":\"master\"}}" |
        pick_merged_pr "$culprit")"

check "a commit merged elsewhere names no pull request" \
    "" \
    "$(printf '[%s]' \
        "{\"number\":43,\"merged_at\":\"2026-01-01T00:00:00Z\",\"merge_commit_sha\":\"$culprit\",\"base\":{\"ref\":\"release\"}}" |
        pick_merged_pr "$culprit")"

search_item() {
    jq -n --arg url "$1" --arg title "$2" --arg body "$3" \
        '{html_url: $url, title: $title, body: $body, pull_request: {}}'
}

check "existing reverts match the marker and human reverts, not near misses" \
    "a
b
c" \
    "$(jq -s '{items: .}' \
        <(search_item a "anything" "<!-- master-red-revert:$culprit -->") \
        <(search_item b 'Revert "feat: thing (#42)"' "Reverts PostHog/posthog#42") \
        <(search_item c "chore(ci): revert the thing" "Reverts https://github.com/PostHog/posthog/pull/42 exactly.") \
        <(search_item d "Revert something else" "Reverts PostHog/posthog#420") \
        <(search_item e "feat: follow-up to #42" "Builds on #42") |
        pick_existing_reverts "$culprit" 42)"

export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@example.com GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@example.com

git_in() {
    git -C "$workdir/clone" "$@"
}

commit_file() {
    local path=$1 content=$2
    mkdir -p "$workdir/clone/$(dirname "$path")"
    printf '%s\n' "$content" >"$workdir/clone/$path"
    git_in add "$path"
    git_in commit --quiet -m "change $path"
    git_in rev-parse HEAD
}

git init --quiet --bare --initial-branch=master "$workdir/origin.git"
git init --quiet --initial-branch=master "$workdir/clone"
git_in remote add origin "file://$workdir/origin.git"
commit_file app.py "one" >/dev/null
clean_culprit=$(commit_file app.py "two")
workflow_culprit=$(commit_file .github/workflows/ci.yml "on: push")
conflict_culprit=$(commit_file lib.py "first")
commit_file lib.py "second" >/dev/null
git_in push --quiet origin master

prepare() {
    (cd "$workdir/clone" && cmd_prepare "$1") 2>&1
}

check "prepare refuses without the opt-in" \
    "refused=MASTER_RED_ALLOW_REVERT_PR is not 1" \
    "$(MASTER_RED_ALLOW_REVERT_PR='' prepare "$clean_culprit" || true)"

export MASTER_RED_ALLOW_REVERT_PR=1

check "prepare refuses a commit that changes workflows" \
    "refused=$workflow_culprit changes .github/workflows, which needs the workflows permission" \
    "$(prepare "$workflow_culprit" || true)"

check "prepare refuses a revert that conflicts with master and leaves the tree clean" \
    "refused=reverting $conflict_culprit conflicts with master|" \
    "$(prepare "$conflict_culprit" || true)|$(git_in status --porcelain)"

check "prepare stages exactly the revert on the deterministic branch" \
    "branch=$(revert_branch "$clean_culprit")
staged_files=1|one" \
    "$(prepare "$clean_culprit")|$(cat "$workdir/clone/app.py")"

if [ "$failures" -gt 0 ]; then
    echo "$failures check(s) failed"
    exit 1
fi
echo "all checks passed"
