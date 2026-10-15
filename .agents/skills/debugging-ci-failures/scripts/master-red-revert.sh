#!/usr/bin/env bash
# Mechanical gates for the master-red task's revert path. The agent decides whether a change
# caused the failure; this helper decides whether the evidence is narrow enough to act on, and
# owns every write so that the write cannot happen with a gate skipped.
#
# Every gate fails closed. Exit 10 means "no confident culprit", 11 means "cannot revert this
# commit mechanically", 12 means "a revert already exists", and 5 means a GitHub read failed.
# A failed read must never read as an empty answer.
set -euo pipefail

REPO=PostHog/posthog
BRANCH_PREFIX=posthog/master-red-revert-
MARKER_PREFIX='<!-- master-red-revert:'
MAX_RUN_PAGES=5
MAX_COMPARE_PAGES=10

usage() {
    echo "usage: $0 boundary <workflow-file> <job-name>" >&2
    echo "       $0 pr <culprit-sha>" >&2
    echo "       $0 existing <culprit-sha> <culprit-pr>" >&2
    echo "       $0 prepare <culprit-sha>" >&2
    echo "       $0 open <culprit-sha> <culprit-pr> <workflow-file> <job-name> <body-file>" >&2
    exit 2
}

fail() {
    echo "master-red-revert.sh: $1" >&2
    exit 5
}

refuse() {
    echo "refused=$2"
    exit "$1"
}

api() {
    local out
    out=$(gh api "$1" 2>/dev/null) || return 1
    printf '%s' "$out" | jq -e . >/dev/null 2>&1 || return 1
    printf '%s' "$out"
}

require_sha() {
    printf '%s' "$1" | grep -qE '^[0-9a-f]{40}$' || usage
}

require_number() {
    case "$1" in
        '' | *[!0-9]*) usage ;;
    esac
}

revert_branch() {
    printf '%s%s' "$BRANCH_PREFIX" "${1:0:12}"
}

# Prints the red streak's boundary as "<green_id> <green_sha> <red_id> <red_sha>
# <newest_red_id>", or "green" when the lane has recovered. Only success, failure and timed_out settle a lane:
# a cancelled run was pushed over and says nothing about the commit it ran on.
pick_boundary() {
    jq -r -s '
        [.[].workflow_runs[]
            | select(.status == "completed")
            | select(.conclusion == "success" or .conclusion == "failure" or .conclusion == "timed_out")]
        | sort_by(.created_at) | reverse
        | if length == 0 then empty
          elif .[0].conclusion == "success" then "green"
          else
            (map(.conclusion == "success") | index(true)) as $g
            | if $g == null then empty
              else "\(.[$g].id) \(.[$g].head_sha) \(.[$g - 1].id) \(.[$g - 1].head_sha) \(.[0].id)"
              end
          end'
}

# The merged pull request whose merge commit is the culprit. A commit can be listed by several
# pull requests, so only the one GitHub recorded as producing this exact commit counts.
pick_merged_pr() {
    local sha=$1
    jq -r --arg sha "$sha" '
        [.[] | select(.merged_at != null and .merge_commit_sha == $sha and .base.ref == "master")]
        | if length == 1 then .[0].number else empty end'
}

# Revert pull requests that already point at this culprit, open or closed: one this helper
# opened (its marker), or one whose title says revert and whose body names the culprit.
pick_existing_reverts() {
    local sha=$1 pr=$2
    jq -r --arg marker "${MARKER_PREFIX}${sha}" --arg pr "$pr" --arg sha "$sha" '
        .items[]
        | select(.pull_request != null)
        | select((.body // "") as $b
            | ($b | contains($marker))
              or (((.title // "") | test("\\brevert"; "i"))
                  and (($b | test("(#|/pull/)" + $pr + "([^0-9]|$)")) or ($b | contains($sha)))))
        | .html_url'
}

# A job name that appears twice in a run, or not at all, cannot anchor a boundary.
pick_job_conclusion() {
    local job=$1
    jq -r -s --arg job "$job" '[.[].jobs[] | select(.name == $job) | .conclusion]
        | if length == 1 then .[0] else "absent" end'
}

# A slow or lost runner also times out, so a job that only timed out does not prove the culprit.
pick_evidence() {
    if [ "$1" = failure ] || [ "$2" = failure ]; then
        echo failure
    else
        echo timed_out_only
    fi
}

job_conclusion() {
    local run_id=$1 job=$2 page out pages=""
    for page in $(seq 1 "$MAX_RUN_PAGES"); do
        out=$(api "repos/$REPO/actions/runs/$run_id/jobs?filter=latest&per_page=100&page=$page") || return 1
        pages+="$out"$'\n'
        [ "$(printf '%s' "$out" | jq '.jobs | length')" -eq 100 ] || break
    done
    printf '%s' "$pages" | pick_job_conclusion "$job"
}

cmd_boundary() {
    local workflow=$1 job=$2 runs_file boundary green_id green_sha red_id red_sha newest_red_id
    runs_file=$(mktemp)
    for page in $(seq 1 "$MAX_RUN_PAGES"); do
        api "repos/$REPO/actions/workflows/$workflow/runs?branch=master&event=push&per_page=100&page=$page" >>"$runs_file" ||
            fail "GitHub read failed: runs of $workflow"
        printf '\n' >>"$runs_file"
        boundary=$(pick_boundary <"$runs_file") || fail "unreadable runs of $workflow"
        [ -z "$boundary" ] || break
    done
    rm -f "$runs_file"
    [ "$boundary" != "green" ] || refuse 10 "the newest settled run is green"
    [ -n "$boundary" ] || refuse 10 "no green run within $MAX_RUN_PAGES pages of runs"
    read -r green_id green_sha red_id red_sha newest_red_id <<<"$boundary"

    local red_job green_job newest_job ahead status
    red_job=$(job_conclusion "$red_id" "$job") || fail "GitHub read failed: jobs of run $red_id"
    green_job=$(job_conclusion "$green_id" "$job") || fail "GitHub read failed: jobs of run $green_id"
    case "$red_job" in
        failure | timed_out) ;;
        *) refuse 10 "job is $red_job in the first red run $red_id" ;;
    esac
    [ "$green_job" = "success" ] || refuse 10 "job is $green_job in the last green run $green_id"
    newest_job=$red_job
    if [ "$newest_red_id" != "$red_id" ]; then
        newest_job=$(job_conclusion "$newest_red_id" "$job") || fail "GitHub read failed: jobs of run $newest_red_id"
        case "$newest_job" in
            failure | timed_out) ;;
            *) refuse 10 "job is $newest_job in the newest red run $newest_red_id" ;;
        esac
    fi

    read -r status ahead < <(api "repos/$REPO/compare/$green_sha...$red_sha" | jq -r '"\(.status) \(.ahead_by)"') ||
        fail "GitHub read failed: compare $green_sha...$red_sha"
    [ "$status" = "ahead" ] || refuse 10 "the red commit does not descend from the green commit"
    [ "$ahead" = "1" ] || refuse 10 "$ahead commits landed between the last green run and the first red run"

    echo "culprit_sha=$red_sha"
    echo "green_sha=$green_sha"
    echo "green_run=https://github.com/$REPO/actions/runs/$green_id"
    echo "first_red_run=https://github.com/$REPO/actions/runs/$red_id"
    echo "newest_red_run=https://github.com/$REPO/actions/runs/$newest_red_id"
    echo "evidence=$(pick_evidence "$red_job" "$newest_job")"
}

cmd_pr() {
    local sha=$1 pr
    pr=$(api "repos/$REPO/commits/$sha/pulls" | pick_merged_pr "$sha") || fail "GitHub read failed: pulls of $sha"
    [ -n "$pr" ] || refuse 10 "no single merged pull request produced $sha"
    echo "culprit_pr=$pr"
    echo "culprit_pr_url=https://github.com/$REPO/pull/$pr"
}

find_existing() {
    local sha=$1 pr=$2 owner=${REPO%%/*} branch found
    branch=$(revert_branch "$sha")
    found=$(api "repos/$REPO/pulls?state=all&head=$owner:$branch&per_page=10" | jq -r '.[].html_url') ||
        fail "GitHub read failed: pulls from $branch"
    for query in "$pr+revert+in:title,body" "$sha"; do
        found+=$'\n'$(api "search/issues?q=repo:$REPO+is:pr+$query&per_page=100" |
            pick_existing_reverts "$sha" "$pr") || fail "GitHub read failed: revert pull request search"
    done
    local page out
    for page in $(seq 1 "$MAX_COMPARE_PAGES"); do
        out=$(api "repos/$REPO/compare/$sha...master?per_page=100&page=$page") ||
            fail "GitHub read failed: compare $sha...master"
        found+=$'\n'$(printf '%s' "$out" |
            jq -r --arg sha "$sha" '.commits[] | select(.commit.message | contains("This reverts commit " + $sha)) | .html_url')
        [ "$(printf '%s' "$out" | jq '.commits | length')" -eq 100 ] || break
        [ "$page" -lt "$MAX_COMPARE_PAGES" ] || fail "more than $MAX_COMPARE_PAGES pages of commits follow $sha"
    done
    printf '%s\n' "$found" | grep -v '^$' | sort -u || true
}

cmd_existing() {
    local sha=$1 pr=$2 found
    found=$(find_existing "$sha" "$pr")
    if [ -z "$found" ]; then
        echo "existing=none"
        return 0
    fi
    printf '%s\n' "$found" | sed 's/^/existing=/'
}

# One fetch for both refs: a second, shallower fetch of master marks the culprit shallow again
# when the culprit is the master tip, and its parent disappears.
fetch_culprit_and_master() {
    local sha=$1
    git fetch --quiet --no-tags --depth=2 origin "$sha" "+refs/heads/master:refs/remotes/origin/master" ||
        fail "could not fetch $sha and master"
}

# The tree that reverting the culprit onto the branch's parent produces, which is what
# `git revert` computes. A branch whose tree differs carries something other than the revert.
revert_matches_culprit() {
    local sha=$1 ref=$2 expected
    expected=$(git merge-tree --write-tree --merge-base="$sha" "$ref^" "$sha^" 2>/dev/null) || return 1
    [ "$(printf '%s' "$expected" | head -1)" = "$(git rev-parse "$ref^{tree}")" ]
}

# A refused `open` leaves its signed commit on the branch. The next attempt stages onto a newer
# master, and the signed-commit tool refuses a branch whose tip it does not hold, so the branch
# would block every later attempt for this culprit.
clear_leftover_branch() {
    local branch=$1 owner=${REPO%%/*} status=0 prs
    git ls-remote --exit-code --heads origin "$branch" >/dev/null 2>&1 || status=$?
    [ "$status" -ne 2 ] || return 0
    [ "$status" -eq 0 ] || fail "could not list $branch on origin"
    prs=$(api "repos/$REPO/pulls?state=all&head=$owner:$branch&per_page=10" | jq -r '.[].html_url') ||
        fail "GitHub read failed: pulls from $branch"
    [ -z "$prs" ] || refuse 12 "$(printf '%s' "$prs" | head -1)"
    gh api -X DELETE "repos/$REPO/git/refs/heads/$branch" >/dev/null 2>&1 ||
        fail "could not delete the leftover branch $branch"
    echo "deleted_leftover_branch=$branch"
}

cmd_prepare() {
    local sha=$1 branch parents changed
    branch=$(revert_branch "$sha")
    git rev-parse --is-inside-work-tree >/dev/null 2>&1 || refuse 11 "not inside a git checkout"
    [ -z "$(git status --porcelain --untracked-files=no)" ] || refuse 11 "the checkout has uncommitted changes"
    fetch_culprit_and_master "$sha"

    parents=$(git rev-list --parents -n 1 "$sha" | awk '{print NF - 1}')
    [ "$parents" = "1" ] || refuse 11 "$sha has $parents parents; only a single-parent commit reverts cleanly"
    changed=$(git diff --name-only "$sha^" "$sha") || fail "could not list the files $sha changes"
    if grep -q '^\.github/workflows/' <<<"$changed"; then
        refuse 11 "$sha changes .github/workflows, which needs the workflows permission"
    fi

    clear_leftover_branch "$branch"
    git checkout --quiet -B "$branch" refs/remotes/origin/master
    if ! git revert --no-commit "$sha" >/dev/null 2>&1; then
        git revert --abort >/dev/null 2>&1 || git reset --quiet --hard
        refuse 11 "reverting $sha conflicts with master"
    fi
    if git diff --cached --quiet; then
        git reset --quiet --hard
        refuse 11 "reverting $sha leaves master unchanged"
    fi
    echo "branch=$branch"
    echo "staged_files=$(git diff --cached --name-only | wc -l | tr -d ' ')"
}

cmd_open() {
    local sha=$1 pr=$2 workflow=$3 job=$4 body_file=$5 branch ahead found lane lane_status=0
    [ -s "$body_file" ] || usage
    branch=$(revert_branch "$sha")

    lane=$(cmd_boundary "$workflow" "$job") || lane_status=$?
    [ "$lane_status" -ne 5 ] || exit 5
    [ "$lane_status" -eq 0 ] || refuse 10 "the lane changed since the boundary check: ${lane#refused=}"
    printf '%s\n' "$lane" | grep -qx "culprit_sha=$sha" || refuse 10 "the boundary no longer names $sha"
    printf '%s\n' "$lane" | grep -qx "evidence=failure" ||
        refuse 10 "the job only timed out in the red runs, so a person decides on the revert"

    found=$(find_existing "$sha" "$pr")
    [ -z "$found" ] || refuse 12 "$(printf '%s' "$found" | head -1)"

    ahead=$(api "repos/$REPO/compare/master...$branch" | jq -r '.ahead_by') ||
        fail "GitHub read failed: compare master...$branch"
    [ "$ahead" = "1" ] || refuse 11 "$branch is $ahead commits ahead of master, expected the one revert commit"
    git fetch --quiet --no-tags --depth=2 origin "$sha" "+refs/heads/$branch:refs/remotes/origin/$branch" ||
        fail "could not fetch $sha and $branch"
    revert_matches_culprit "$sha" "refs/remotes/origin/$branch" ||
        refuse 11 "$branch holds something other than the exact revert of $sha"

    { cat "$body_file"; printf '\n%s%s -->\n' "$MARKER_PREFIX" "$sha"; } |
        gh pr create --repo "$REPO" --draft --base master --head "$branch" \
            --title "revert: back out #$pr to fix master" --body-file - ||
        fail "could not open the revert pull request"
}

main() {
    local cmd=${1:-}
    case "$cmd" in
        boundary)
            [ $# -eq 3 ] || usage
            cmd_boundary "$2" "$3"
            ;;
        pr)
            [ $# -eq 2 ] || usage
            require_sha "$2"
            cmd_pr "$2"
            ;;
        existing)
            [ $# -eq 3 ] || usage
            require_sha "$2"
            require_number "$3"
            cmd_existing "$2" "$3"
            ;;
        prepare)
            [ $# -eq 2 ] || usage
            require_sha "$2"
            cmd_prepare "$2"
            ;;
        open)
            [ $# -eq 6 ] || usage
            require_sha "$2"
            require_number "$3"
            cmd_open "$2" "$3" "$4" "$5" "$6"
            ;;
        *)
            usage
            ;;
    esac
}

if [ "${BASH_SOURCE[0]}" = "$0" ]; then
    main "$@"
fi
