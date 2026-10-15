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

check "a job that only timed out is weaker evidence than one that failed" \
    "timed_out_only failure failure" \
    "$(pick_evidence timed_out timed_out) $(pick_evidence timed_out failure) $(pick_evidence failure failure)"

printf 'body\n' >"$workdir/body.md"
check "open refuses when the job only timed out in the red runs" \
    "refused=the job only timed out in the red runs, so a person decides on the revert
exit=10" \
    "$( (
        # shellcheck disable=SC2329  # replaces the boundary read that cmd_open calls
        cmd_boundary() { printf 'culprit_sha=%s\nevidence=timed_out_only\n' "$culprit"; }
        cmd_open "$culprit" 42 ci.yml job "$workdir/body.md"
    ) 2>/dev/null || echo "exit=$?")"

check "open reports a failed GitHub read in the boundary recheck as a read failure" \
    "5" \
    "$( (
        # shellcheck disable=SC2329  # replaces the boundary read that cmd_open calls
        cmd_boundary() { fail "GitHub read failed: runs of ci.yml"; }
        cmd_open "$culprit" 42 ci.yml job "$workdir/body.md"
    ) >/dev/null 2>&1 || echo $?)"

export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@example.com GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@example.com

seed_in() {
    git -C "$workdir/seed" "$@"
}

clone_in() {
    git -C "$workdir/clone" "$@"
}

commit_file() {
    local path=$1 content=$2
    mkdir -p "$workdir/seed/$(dirname "$path")"
    printf '%s\n' "$content" >"$workdir/seed/$path"
    seed_in add "$path"
    seed_in commit --quiet -m "change $path"
    seed_in rev-parse HEAD
}

git init --quiet --bare --initial-branch=master "$workdir/origin.git"
git init --quiet --initial-branch=master "$workdir/seed"
seed_in remote add origin "file://$workdir/origin.git"
commit_file app.py "one" >/dev/null
clean_culprit=$(commit_file app.py "two")
workflow_culprit=$(commit_file .github/workflows/ci.yml "on: push")
conflict_culprit=$(commit_file lib.py "first")
commit_file lib.py "second" >/dev/null
tip_culprit=$(commit_file tip.py "new")
seed_in push --quiet origin master
# The task sandbox clones master at depth 1, so the harness does too.
git clone --quiet --depth=1 "file://$workdir/origin.git" "$workdir/clone"

prepare() {
    (cd "$workdir/clone" && cmd_prepare "$1") 2>&1
}

reset_clone() {
    clone_in reset --quiet --hard
    clone_in checkout --quiet master
}

check "prepare refuses a commit that changes workflows" \
    "refused=$workflow_culprit changes .github/workflows, which needs the workflows permission" \
    "$(prepare "$workflow_culprit" || true)"

check "prepare refuses a revert that conflicts with master and leaves the tree clean" \
    "refused=reverting $conflict_culprit conflicts with master|" \
    "$(prepare "$conflict_culprit" || true)|$(clone_in status --porcelain)"

check "prepare stages exactly the revert on the deterministic branch" \
    "branch=$(revert_branch "$clean_culprit")
staged_files=1|one" \
    "$(prepare "$clean_culprit")|$(cat "$workdir/clone/app.py")"
reset_clone

check "prepare reverts the culprit when it is the master tip" \
    "branch=$(revert_branch "$tip_culprit")
staged_files=1|absent" \
    "$(prepare "$tip_culprit" || true)|$([ -e "$workdir/clone/tip.py" ] && echo present || echo absent)"
reset_clone

leftover_branch=$(revert_branch "$clean_culprit")
leftover_state() {
    git -C "$workdir/origin.git" show-ref --quiet --verify "refs/heads/$leftover_branch" && echo present || echo absent
}
seed_in push --quiet origin "master:refs/heads/$leftover_branch"

check "prepare keeps a leftover branch that a pull request uses" \
    "refused=https://github.com/PostHog/posthog/pull/7|present" \
    "$( (
        # shellcheck disable=SC2317,SC2329  # stands in for the pull request lookup
        api() { echo '[{"html_url":"https://github.com/PostHog/posthog/pull/7"}]'; }
        # shellcheck disable=SC2317,SC2329  # a deletion here would close the pull request
        gh() { return 1; }
        prepare "$clean_culprit"
    ) || true)|$(leftover_state)"
reset_clone

check "prepare deletes a leftover branch that no pull request uses, then stages the revert" \
    "deleted_leftover_branch=$leftover_branch
branch=$leftover_branch
staged_files=1|absent" \
    "$( (
        # shellcheck disable=SC2317,SC2329  # stands in for the pull request lookup
        api() { echo '[]'; }
        # shellcheck disable=SC2317,SC2329  # stands in for the GitHub ref deletion
        gh() { git -C "$workdir/origin.git" update-ref -d "refs/heads/$leftover_branch"; }
        prepare "$clean_culprit"
    ) || true)|$(leftover_state)"
reset_clone

seed_in mv app.py renamed.py
seed_in commit --quiet -m "rename app.py"
rename_culprit=$(seed_in rev-parse HEAD)
commit_file other.py "after the rename" >/dev/null

matches() {
    (cd "$workdir/seed" && revert_matches_culprit "$1" "$2") && echo match || echo mismatch
}

seed_in checkout --quiet -b exact-revert master
seed_in revert --no-edit "$rename_culprit" >/dev/null
check "open accepts the exact revert of a rename" "match" "$(matches "$rename_culprit" exact-revert)"

seed_in checkout --quiet -b altered-revert master
seed_in revert --quiet --no-commit "$rename_culprit"
printf 'edited\n' >"$workdir/seed/app.py"
seed_in add app.py
seed_in commit --quiet -m "revert with an edit"
check "open refuses a revert commit that carries other changes" "mismatch" "$(matches "$rename_culprit" altered-revert)"
seed_in checkout --quiet master

if [ "$failures" -gt 0 ]; then
    echo "$failures check(s) failed"
    exit 1
fi
echo "all checks passed"
