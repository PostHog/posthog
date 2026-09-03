#!/usr/bin/env bash
# Constrained reader for Trunk's merge queue signal.
#
# Trunk publishes no check run in this repository. Queue state lives in one sticky comment per
# PR authored by trunk-io[bot], and each queue attempt is a draft shadow PR whose head ref is
# trunk-merge/pr-<n>/<uuid>. The API authenticates both as the Trunk app, which is the same
# envelope authentication a check run's app.slug gave.
#
# The comment body is free text, so it never reaches the agent: this helper classifies it and
# emits only regex-validated fields. Anything that fails validation is dropped, not printed.
#
# A failed GitHub read exits 5 and never comes back as an empty result. An empty result has to
# mean "GitHub answered, and there is nothing there", or a sweep reports success while blind.
set -euo pipefail

usage() {
    cat >&2 <<'USAGE'
usage: mq-queue-state.sh state    <owner/repo> <pr>              queue state of one PR
       mq-queue-state.sh attempts <owner/repo> <pr> [head_oid]   attempts, newest first:
                                                                 <attempt_pr> <sha> <kind>
                                                                 <created_at> <source_head>
       mq-queue-state.sh recent   <owner/repo> [pages]           discovery, newest first:
                                                                 <pr> <attempt_pr> <kind>
                                                                 <attempts_seen>

`recent` is one pass over the shadow PR list, so run it once per sweep and read the attempt
columns from it. `state` deliberately does not look attempts up again: that cost three full
pages per PR and made a sweep too slow to finish.

`attempts_seen` counts every attempt on the PR, over all of its head revisions, so it is an
upper bound on the attempts against the current head. For a per-head count, give `attempts` a
head OID: it then keeps only the attempts that tested that revision.

Exit codes: 2 usage, 5 a GitHub read failed.
USAGE
    exit 2
}

fail() {
    echo "mq-queue-state.sh: $1" >&2
    exit 5
}

# gh is absent from the routine sandbox, and `gh api --paginate` breaks there anyway: GitHub's
# Link header points at repositories/{id}/..., which the sandbox proxy refuses. So always page
# by hand, and fall back to curl when gh is missing.
#
# Both branches must tell a failed request apart from an empty answer. An auth error, a rate
# limit, a proxy rejection or a truncated body all parse as "no data" otherwise, and the caller
# reads that as a PR with nothing to triage.
api_json() {
    local path=$1 out
    if command -v gh >/dev/null 2>&1; then
        out=$(gh api "$path" 2>/dev/null) || return 1
    else
        out=$(curl -sS --fail -H "Authorization: Bearer ${GITHUB_TOKEN:-${GH_TOKEN:-}}" \
            -H "Accept: application/vnd.github+json" \
            "https://api.github.com/$path" 2>/dev/null) || return 1
    fi
    printf '%s' "$out" | jq -e . >/dev/null 2>&1 || return 1
    printf '%s' "$out"
}

api_array() {
    local out
    out=$(api_json "$1") || return 1
    printf '%s' "$out" | jq -e 'type == "array"' >/dev/null 2>&1 || return 1
    printf '%s' "$out"
}

cmd=${1:-}
repo=${2:-}
[ -n "$cmd" ] && [ -n "$repo" ] || usage
case "$repo" in
    */*) ;;
    *) usage ;;
esac

require_pr() {
    case "${1:-}" in
        '' | *[!0-9]*) usage ;;
    esac
}

TAB=$(printf '\t')
URL_RE='https://github\.com/[A-Za-z0-9._-]+/[A-Za-z0-9._-]+/actions/runs/[0-9]+/job/[0-9]+'
CHECK_RE='[A-Za-z0-9 ()._/&,+-]{1,120}'

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

# The newest trunk-io[bot] comment that reports merge state. Test Analytics comments share the
# author but report flake counts, not queue state.
sticky_body() {
    local pr=$1 pg=1 out
    : >"$TMP/bodies"
    while :; do
        out=$(api_array "repos/$repo/issues/$pr/comments?per_page=100&page=$pg") ||
            fail "GitHub read failed: comments page $pg of PR $pr"
        printf '%s' "$out" | jq -e 'length > 0' >/dev/null 2>&1 || break
        printf '%s' "$out" |
            jq -r '.[] | select(.user.login == "trunk-io[bot]") | select(.user.type == "Bot")
                       | select(.body | test("Trunk Test Analytics") | not)
                       | "\(.updated_at)\t\(.body | gsub("[\n\r]"; " "))"' >>"$TMP/bodies" ||
            fail "unreadable comments page $pg of PR $pr"
        printf '%s' "$out" | jq -e 'length == 100' >/dev/null 2>&1 || break
        pg=$((pg + 1))
        [ "$pg" -gt 5 ] && break
    done
    sort -r "$TMP/bodies" | head -1 | cut -f2-
}

# Order matters: every "removed from the merge queue" wording shares a prefix, and the reason
# after it is what picks the verdict.
classify() {
    local body=$1
    if printf '%s' "$body" | grep -qE 'removed from the merge queue because it was pushed to'; then
        echo superseded
    elif printf '%s' "$body" | grep -qE 'removed from the merge queue because it failed tests'; then
        echo kicked_failed
    elif printf '%s' "$body" | grep -qE 'removed from the merge queue'; then
        echo removed
    elif printf '%s' "$body" | grep -qE 'could not start testing.*merge conflict'; then
        echo conflict
    elif printf '%s' "$body" | grep -qE 'could not start testing'; then
        echo blocked
    elif printf '%s' "$body" | grep -qE 'required check .* has failed'; then
        echo failed
    elif printf '%s' "$body" | grep -qE 'Running tests on this (pull request|stack)'; then
        echo testing
    elif printf '%s' "$body" | grep -qE 'Waiting to start tests'; then
        echo queued
    elif printf '%s' "$body" | grep -qE 'is queued for merge as part of'; then
        echo batched
    elif printf '%s' "$body" | grep -qE 'will be merged soon because tests have passed'; then
        echo passing
    elif printf '%s' "$body" | grep -qE 'Submitted to Merge.*added to the merge queue once'; then
        echo submitted
    elif printf '%s' "$body" | grep -qE '(Merged|Stack merged) successfully'; then
        echo merged
    elif printf '%s' "$body" | grep -qE 'was merged into .* as part of stacked PR'; then
        echo merged
    elif printf '%s' "$body" | grep -qE 'Merging to .* is managed by Trunk'; then
        echo idle
    else
        echo unknown
    fi
}

# Shadow PRs are listed newest first, so stop at the first short page rather than always paying
# the full page budget.
pulls_pages() {
    local pages=$1 pg out
    : >"$TMP/pulls"
    for pg in $(seq 1 "$pages"); do
        out=$(api_array "repos/$repo/pulls?state=all&sort=created&direction=desc&per_page=100&page=$pg") ||
            fail "GitHub read failed: pull request list page $pg"
        printf '%s\n' "$out" >>"$TMP/pulls"
        printf '%s' "$out" | jq -e 'length == 100' >/dev/null 2>&1 || break
    done
}

# An attempt's shadow head is a merge commit of the queue base and the PR head it tested, so its
# last parent says which revision of the PR that attempt covered. Nothing on the shadow PR itself
# carries that, and the uuid in its ref is random.
source_head_of() {
    local sha=$1 out
    out=$(api_json "repos/$repo/commits/$sha") || fail "GitHub read failed: commit $sha"
    printf '%s' "$out" | jq -r '.parents[-1].sha // empty' 2>/dev/null ||
        fail "unreadable commit $sha"
}

attempts_for() {
    local pr=$1 want_head=${2:-} attempt sha kind created source
    pulls_pages 3
    jq -r --arg pr "$pr" '.[] | select(.user.login == "trunk-io[bot]")
        | select(.head.ref | startswith("trunk-merge/pr-" + $pr + "/"))
        | "\(.number)\t\(.head.sha)\t\(if (.head.ref | endswith("-bisection")) then "bisection" else "normal" end)\t\(.created_at)"' \
        "$TMP/pulls" >"$TMP/attempts" || fail "unreadable pull request list"
    sort -t"$TAB" -k4,4r "$TMP/attempts" |
        grep -E "^[0-9]+${TAB}[0-9a-f]{40}${TAB}(normal|bisection)${TAB}" >"$TMP/valid" || true
    while IFS="$TAB" read -r attempt sha kind created; do
        source=$(source_head_of "$sha")
        printf '%s' "$source" | grep -qE '^[0-9a-f]{40}$' || source=unknown
        [ -z "$want_head" ] || [ "$source" = "$want_head" ] || continue
        printf '%s\t%s\t%s\t%s\t%s\n' "$attempt" "$sha" "$kind" "$created" "$source"
    done <"$TMP/valid"
}

case "$cmd" in
    state)
        pr=${3:-}
        require_pr "$pr"
        body=$(sticky_body "$pr") || exit $?
        if [ -z "$body" ]; then
            echo "state=none"
            exit 0
        fi
        echo "state=$(classify "$body")"
        # shellcheck disable=SC2016 # the backticks are literal Markdown, not expansion
        check=$(printf '%s' "$body" | grep -oE '\[`'"$CHECK_RE"'`\]' | head -1 | sed -E 's/^\[`//; s/`\]$//' || true)
        if [ -n "$check" ]; then echo "check=$check"; fi
        job_url=$(printf '%s' "$body" | grep -oE "$URL_RE" | head -1 || true)
        if [ -n "$job_url" ]; then echo "job_url=$job_url"; fi
        testing_pr=$(printf '%s' "$body" | grep -oE 'PR \[#[0-9]+' | grep -oE '[0-9]+' | head -1 || true)
        if [ -n "$testing_pr" ]; then echo "testing_pr=$testing_pr"; fi
        ;;
    attempts)
        pr=${3:-}
        head_oid=${4:-}
        require_pr "$pr"
        if [ -n "$head_oid" ]; then
            printf '%s' "$head_oid" | grep -qE '^[0-9a-f]{40}$' || usage
        fi
        attempts_for "$pr" "$head_oid"
        ;;
    recent)
        pages=${3:-2}
        case "$pages" in
            '' | *[!0-9]*) pages=2 ;;
        esac
        [ "$pages" -ge 1 ] || pages=2
        pulls_pages "$pages"
        jq -r '.[] | select(.user.login == "trunk-io[bot]")
            | select(.head.ref | test("^trunk-merge/pr-[0-9]+/"))
            | "\(.head.ref | capture("^trunk-merge/pr-(?<n>[0-9]+)/").n)\t\(.number)\t\(if (.head.ref | endswith("-bisection")) then "bisection" else "normal" end)"' \
            "$TMP/pulls" >"$TMP/recent" || fail "unreadable pull request list"
        grep -E "^[0-9]+${TAB}[0-9]+${TAB}(normal|bisection)$" "$TMP/recent" |
            awk -F"$TAB" 'BEGIN{OFS=FS}
                {n[$1]++; if (!($1 in first)) {first[$1]=$2 OFS $3; order[++k]=$1}}
                END{for (i = 1; i <= k; i++) print order[i], first[order[i]], n[order[i]]}' || true
        ;;
    *)
        usage
        ;;
esac
