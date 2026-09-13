#!/usr/bin/env bash
# Constrained reader for Trunk's merge queue signal.
#
# Trunk publishes no check run in this repository. Queue state lives in one sticky comment per
# PR authored by trunk-io[bot], and each queue attempt is a draft shadow PR whose head ref is
# trunk-merge/pr-<n>/<uuid>. The API authenticates both as the Trunk app, which is the same
# envelope authentication a check run's app.slug gave.
#
# The comment body is free text, so its wording never reaches the agent: this helper classifies
# it and emits only regex-validated fields, plus a one-way digest of an unrecognized wording.
# Anything that fails validation is dropped, not printed. fingerprint() gives the reasoning.
#
# A failed GitHub read exits 5 and never comes back as an empty result. An empty result has to
# mean "GitHub answered, and there is nothing there", or a sweep reports success while blind.
set -euo pipefail

usage() {
    cat >&2 <<'USAGE'
usage: mq-queue-state.sh state    <owner/repo> <pr>              queue state of one PR
       mq-queue-state.sh attempts <owner/repo> <pr> [head_oid]   attempts, newest first:
                                                                 <attempt_pr> <sha> <kind>
                                                                 <created_at> <covers_head>
       mq-queue-state.sh recent   <owner/repo> [pages]           discovery, newest first:
                                                                 <pr> <attempt_pr> <kind>
                                                                 <attempts_seen>

`recent` is one pass over the shadow PR list, so run it once per sweep and read the attempt
columns from it. `state` deliberately does not look attempts up again: that cost three full
pages per PR and made a sweep too slow to finish.

`attempts_seen` counts every attempt on the PR, over all of its head revisions, so it is an
upper bound on the attempts against the current head. For a per-head count, give `attempts` a
head OID: it then keeps only the attempts whose shadow head contains that revision. Without a
head OID it checks against the PR's current head and reports the answer in `covers_head`
(`yes`, `no`, or `unknown`).

`attempts` also returns the attempts the PR was batched into, whose refs name the batch leader
instead. `recent` groups by the ref, so it reports those under the leader's number.

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

# Picks the newest comment that reports merge state, from `<updated_at>\t<body>` lines.
#
# Trunk answers a `/trunk merge` command with a short reply comment ("This PR is already queued as
# a stacked merge"), and that reply outranks the sticky comment by update time until the sticky is
# next rewritten. Every queue state wording carries a merge-queue dashboard link or the sticky's
# own HTML marker, and the replies carry neither, so prefer the comments that do. Falling back to
# the newest line matters: a PR whose sticky has not been written yet has only replies to read.
prefer_queue_comment() {
    local bodies=$1
    if grep -qE 'app\.trunk\.io/|<!-- Trunk Merge -->' "$bodies"; then
        grep -E 'app\.trunk\.io/|<!-- Trunk Merge -->' "$bodies" | sort -r | head -1 | cut -f2-
    else
        sort -r "$bodies" | head -1 | cut -f2-
    fi
}

# Every trunk-io[bot] comment on the PR, newest last. Test Analytics comments share the author
# but report flake counts, not queue state, so they are dropped before the preference runs.
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
    prefer_queue_comment "$TMP/bodies"
}

# Links, HTML, numbers and SHAs are dropped so that no diagnostic built from the wording can
# carry a job URL or a SHA, and so that the same wording always reduces to the same text.
normalize_wording() {
    printf '%s' "$1" |
        sed -E 's#https?://[^ )]+##g; s/<[^>]*>//g; s/\[[^]]*\]\(\)//g; s/[0-9a-f]{40}//g; s/#?[0-9]+//g' |
        tr -c 'A-Za-z .,:;!?()-' ' ' |
        tr -s ' ' |
        cut -c1-160
}

sha256_hex() {
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum
    elif command -v shasum >/dev/null 2>&1; then
        shasum -a 256
    else
        openssl dgst -sha256
    fi | awk '{ for (i = 1; i <= NF; i++) if ($i ~ /^[0-9a-f]{64}$/) { print $i; exit } }'
}

# What reaches the agent on an unrecognized wording, and what deliberately does not.
#
# The wording is untrusted input. Trunk quotes repo-controlled text into its comments, including
# check names and the titles of the PRs in a batch, and anyone can open a PR on this public repo.
# A sweep that holds requeue credentials must never receive that text, and an encoding is not a
# control, because a model can decode one. So the agent gets a one-way digest and nothing else.
#
# The digest is a real diagnostic on its own. It is stable for a given wording, so it says whether
# the same unrecognized wording is recurring across PRs and sweeps, and it lets whoever adds the
# next classify() pattern confirm they wrote it against the wording that produced this `unknown`.
fingerprint() {
    normalize_wording "$1" | sha256_hex | cut -c1-16
}

# The wording itself is kept only when the caller opts in by setting MQ_FINGERPRINT_DIR, which the
# unattended sweep leaves unset. An operator reading the file is a person who can judge the text;
# the sweep is not, which is the whole reason the digest exists.
retain_wording() {
    local digest=$1 body=$2 dir=${MQ_FINGERPRINT_DIR:-}
    [ -n "$dir" ] || return 1
    mkdir -p "$dir" || return 1
    normalize_wording "$body" >"$dir/$digest.txt" || return 1
    printf '%s/%s.txt' "$dir" "$digest"
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
    elif printf '%s' "$body" | grep -qE 'already queued as a stacked merge'; then
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

# Whether an attempt tested a given PR revision. The shadow head is a chain of merge commits,
# one per batch member, so its parents name whichever member Trunk merged last, not this PR.
# Ancestry is the only reliable signal: the PR revision is an ancestor of the shadow head when
# the attempt covered it (`ahead` or `identical`), and not when the branch was pushed to after
# the attempt started (`diverged`). Nothing on the shadow PR itself carries this, and the uuid
# in its ref is random.
compare_verdict() {
    case "$1" in
        ahead | identical) echo yes ;;
        behind | diverged) echo no ;;
        *) echo unknown ;;
    esac
}

covers_head() {
    local sha=$1 head=$2 out status
    out=$(api_json "repos/$repo/compare/$head...$sha?per_page=1") ||
        fail "GitHub read failed: compare $head...$sha"
    status=$(printf '%s' "$out" | jq -r '.status // empty' 2>/dev/null) || fail "unreadable compare $head...$sha"
    compare_verdict "$status"
}

current_head_of() {
    local pr=$1 out
    out=$(api_json "repos/$repo/pulls/$pr") || fail "GitHub read failed: PR $pr"
    printf '%s' "$out" | jq -r '.head.sha // empty' 2>/dev/null || fail "unreadable PR $pr"
}

# Trunk names a shadow ref after the batch leader only, so a PR batched behind another one has
# no ref of its own while it is being tested. Selecting on the ref alone therefore reports zero
# attempts for every batch member, and the retry gate reads that as a PR nobody has tried yet.
# The shadow PR body lists the batch as `[PR <n>](https://app.trunk.io/...)` bullets, one per
# member, and the pull request list already carries that body, so membership costs no extra
# request. It is only the candidate filter: covers_head still decides whether the attempt
# reached the revision asked about.
select_attempts() {
    local pr=$1 pulls=$2
    jq -r --arg pr "$pr" '.[] | select(.user.login == "trunk-io[bot]")
        | select(.head.ref | test("^trunk-merge/pr-[0-9]+/"))
        | select((.head.ref | startswith("trunk-merge/pr-" + $pr + "/"))
                 or ((.body // "") | test("\\[PR " + $pr + "\\]\\(https://app\\.trunk\\.io/")))
        | "\(.number)\t\(.head.sha)\t\(if (.head.ref | endswith("-bisection")) then "bisection" else "normal" end)\t\(.created_at)"' \
        "$pulls" || fail "unreadable pull request list"
}

attempts_for() {
    local pr=$1 head=${2:-} attempt sha kind created covers
    if [ -z "$head" ]; then
        head=$(current_head_of "$pr")
        printf '%s' "$head" | grep -qE '^[0-9a-f]{40}$' || fail "PR $pr has no readable head"
    fi
    pulls_pages 3
    select_attempts "$pr" "$TMP/pulls" >"$TMP/attempts"
    sort -t"$TAB" -k4,4r "$TMP/attempts" |
        grep -E "^[0-9]+${TAB}[0-9a-f]{40}${TAB}(normal|bisection)${TAB}" >"$TMP/valid" || true
    while IFS="$TAB" read -r attempt sha kind created; do
        covers=$(covers_head "$sha" "$head")
        [ -z "${2:-}" ] || [ "$covers" = yes ] || continue
        printf '%s\t%s\t%s\t%s\t%s\n' "$attempt" "$sha" "$kind" "$created" "$covers"
    done <"$TMP/valid"
}

# `repo` stays a global because the request helpers read it. Everything else is dispatched from
# here so that the file can be sourced with no arguments, which is how the tests reach classify(),
# fingerprint() and the attempt selection without a GitHub read.
main() {
    local cmd pr head_oid pages body state digest retained check job_url testing_pr
    cmd=${1:-}
    repo=${2:-}
    if [ -z "$cmd" ] || [ -z "$repo" ]; then
        usage
    fi
    case "$repo" in
        */*) ;;
        *) usage ;;
    esac

    case "$cmd" in
        state)
            pr=${3:-}
            require_pr "$pr"
            body=$(sticky_body "$pr") || exit $?
            if [ -z "$body" ]; then
                echo "state=none"
                exit 0
            fi
            state=$(classify "$body")
            echo "state=$state"
            if [ "$state" = unknown ]; then
                digest=$(fingerprint "$body")
                echo "fingerprint_sha=$digest"
                retained=$(retain_wording "$digest" "$body") && echo "fingerprint_file=$retained"
            fi
            if printf '%s' "$body" | grep -qiE '\bstack(ed)?\b'; then echo "stacked=yes"; fi
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
}

if [ "${BASH_SOURCE[0]}" = "$0" ]; then
    main "$@"
fi
