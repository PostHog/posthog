#!/usr/bin/env bash
# Constrained marker I/O for the merge queue triage sweep: the agent must never read
# raw PR comment bodies, so this helper emits/accepts only strictly validated data.
#
# Marker state is only trusted from the identity the sweep posts as: reads and the comment
# chosen for update are restricted to comments authored by MQ_TRIAGE_BOT_LOGIN. A commenter
# can otherwise plant a marker to spoof "already triaged" and skip a PR. Fail closed: with
# the login unset, `get` returns nothing and `set` always creates, so a fuzzy match never
# trusts or overwrites another author's comment.
#
# A failed GitHub read exits 5. "No marker" and "could not look" must not print the same thing:
# the first means triage this PR, the second means the sweep is blind and has to stop.
set -euo pipefail

MARKER_RE='<!-- mq-triage:[0-9a-f]{40}:[0-9]+ -->'
BOT_LOGIN=${MQ_TRIAGE_BOT_LOGIN:-}

usage() {
    echo "usage: $0 get <owner/repo> <pr_number>" >&2
    echo "       $0 set <owner/repo> <pr_number> <head_oid> <attempt_pr> < body.md" >&2
    echo "       $0 verify <owner/repo>" >&2
    echo "requires MQ_TRIAGE_BOT_LOGIN (the login the sweep's comments are authored by)" >&2
    echo "exit codes: 2 usage, 3 marker from a foreign login, 4 author mismatch, 5 read failed" >&2
    exit 2
}

fail() {
    echo "mq-triage-marker.sh: $1" >&2
    exit 5
}

# The routine sandbox has no `gh`, and `gh api --paginate` breaks there even where it exists:
# GitHub's Link header points at repositories/{id}/..., which the sandbox proxy refuses. So
# mirror mq-queue-state.sh — fall back to curl, page by hand, and never let a failed request
# read as an empty page.
api_json() {
    local path=$1 method=${2:-GET} body=${3:-} out
    if command -v gh >/dev/null 2>&1; then
        if [ -n "$body" ]; then
            out=$(gh api -X "$method" "$path" -f body="$body" 2>/dev/null) || return 1
        else
            out=$(gh api -X "$method" "$path" 2>/dev/null) || return 1
        fi
    elif [ -n "$body" ]; then
        out=$(jq -n --arg body "$body" '{body: $body}' |
            curl -sS --fail -X "$method" --data-binary @- \
                -H "Authorization: Bearer ${GITHUB_TOKEN:-${GH_TOKEN:-}}" \
                -H "Accept: application/vnd.github+json" \
                -H "Content-Type: application/json" \
                "https://api.github.com/$path" 2>/dev/null) || return 1
    else
        out=$(curl -sS --fail -X "$method" \
            -H "Authorization: Bearer ${GITHUB_TOKEN:-${GH_TOKEN:-}}" \
            -H "Accept: application/vnd.github+json" \
            "https://api.github.com/$path" 2>/dev/null) || return 1
    fi
    printf '%s' "$out" | jq -e . >/dev/null 2>&1 || return 1
    printf '%s' "$out"
}

# Collect every page of a comment list into $TMP/pages, one JSON array per line. Readers slurp
# the file with `jq -s`, so a marker on page two counts the same as one on page one.
comment_pages() {
    local path=$1 extra=${2:-} pg=1 url out
    : >"$TMP/pages"
    while :; do
        url="$path?per_page=100&page=$pg"
        [ -z "$extra" ] || url="$url&$extra"
        out=$(api_json "$url") || return 1
        printf '%s' "$out" | jq -e 'type == "array"' >/dev/null 2>&1 || return 1
        printf '%s\n' "$out" >>"$TMP/pages"
        printf '%s' "$out" | jq -e 'length == 100' >/dev/null 2>&1 || break
        pg=$((pg + 1))
        [ "$pg" -gt 10 ] && break
    done
}

# The second marker field identifies the queue attempt. It used to be a check run id; Trunk
# publishes no check run here, so it is now the shadow PR number of the attempt. Both are bare
# integers, so markers written under the old meaning still parse.

# Which login the sweep's comments appear under cannot be derived from the token's own API
# identity. The routine sandbox reports a user account on /user while routing comments through
# the `claude` GitHub App, so they land as claude[bot]. Guessing from /user gets this backwards
# and, acted on, breaks every marker read.
#
# So verify observes instead of inferring: it finds markers this sweep already wrote and reports
# who actually authored them. Before the first comment exists there is nothing to observe, and
# it says so rather than inventing a verdict. A failed read is not that case — it exits 5 — so a
# sandbox that cannot reach GitHub never passes itself off as a clean first run.
verify_identity() {
    local authors
    comment_pages "repos/$repo/issues/comments" "sort=updated&direction=desc" ||
        fail "GitHub read failed: repository issue comments"
    authors=$(jq -s -r --arg re "$MARKER_RE" \
        '[.[][] | select(.body | test($re)) | .user.login] | unique | join(", ")' \
        "$TMP/pages") || fail "unreadable repository issue comments"
    if [ -z "$authors" ]; then
        echo "identity: MQ_TRIAGE_BOT_LOGIN=$BOT_LOGIN, no existing marker to confirm it against."
        echo "identity: unverified until the first verdict comment lands. Check that comment's"
        echo "identity: author, and correct the variable if it is not $BOT_LOGIN."
        return 0
    fi
    if [ "$authors" = "$BOT_LOGIN" ]; then
        echo "identity: ok, existing markers are authored by $BOT_LOGIN"
        return 0
    fi
    echo "MQ_TRIAGE_BOT_LOGIN=$BOT_LOGIN, but existing markers are authored by: $authors" >&2
    echo "The helper reads and updates only $BOT_LOGIN's comments, so every sweep would append" >&2
    echo "a new verdict comment. Set MQ_TRIAGE_BOT_LOGIN to the author above." >&2
    return 4
}

cmd=${1:-}
repo=${2:-}
pr=${3:-}
[ -n "$BOT_LOGIN" ] || usage

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

if [ "$cmd" = "verify" ]; then
    [ -n "$repo" ] || usage
    case "$repo" in
        */*) ;;
        *) usage ;;
    esac
    verify_identity
    exit $?
fi
[ -n "$cmd" ] && [ -n "$repo" ] && [ -n "$pr" ] || usage
case "$repo" in
    */*) ;;
    *) usage ;;
esac
case "$pr" in
    '' | *[!0-9]*) usage ;;
esac

load_pr_comments() {
    comment_pages "repos/$repo/issues/$pr/comments" || fail "GitHub read failed: comments of PR $pr"
}

# Bodies of this PR's comments authored by our own identity only.
own_comment_bodies() {
    jq -s -r --arg login "$BOT_LOGIN" '.[][] | select(.user.login == $login) | .body' \
        "$TMP/pages" || fail "unreadable comments of PR $pr"
}

# A marker written under a different login is invisible to `get` and unreachable by the
# `set` upsert, so the sweep re-triages every PR and appends a comment each time. That is
# indistinguishable from "never triaged", so report it instead of returning empty.
#
# Only another App identity can mean that, so match bot authors and a complete marker. A human
# who pastes marker-shaped text would otherwise halt every sweep that reaches their PR.
foreign_marker_authors() {
    jq -s -r --arg login "$BOT_LOGIN" --arg re "$MARKER_RE" \
        '[.[][] | select(.user.login != $login) | select(.user.type == "Bot")
                | select(.body | test($re)) | .user.login] | unique | join(", ")' \
        "$TMP/pages" || fail "unreadable comments of PR $pr"
}

case "$cmd" in
    get)
        load_pr_comments
        own_comment_bodies >"$TMP/own"
        found=$(grep -oE "$MARKER_RE" "$TMP/own" |
            tail -1 |
            grep -oE '[0-9a-f]{40}:[0-9]+' || true)
        if [ -z "$found" ]; then
            others=$(foreign_marker_authors) || exit $?
            if [ -n "$others" ]; then
                echo "MQ_TRIAGE_BOT_LOGIN=$BOT_LOGIN found no marker, but one exists from: $others" >&2
                echo "Set MQ_TRIAGE_BOT_LOGIN to the login that authors this sweep's comments." >&2
                exit 3
            fi
        fi
        if [ -n "$found" ]; then
            printf '%s\n' "$found"
        fi
        ;;
    set)
        head_oid=${4:-}
        attempt_pr=${5:-}
        printf '%s' "$head_oid" | grep -qE '^[0-9a-f]{40}$' || usage
        printf '%s' "$attempt_pr" | grep -qE '^[0-9]+$' || usage
        body="$(cat)

<!-- mq-triage:${head_oid}:${attempt_pr} -->"
        load_pr_comments
        existing_id=$(jq -s -r --arg login "$BOT_LOGIN" --arg re "$MARKER_RE" \
            '[.[][] | select(.user.login == $login) | select(.body | test($re)) | .id]
             | last // empty' "$TMP/pages") || fail "unreadable comments of PR $pr"
        case "$existing_id" in
            '' | *[!0-9]*) existing_id='' ;;
        esac
        if [ -n "$existing_id" ]; then
            api_json "repos/$repo/issues/comments/$existing_id" PATCH "$body" >/dev/null ||
                fail "could not update comment $existing_id on PR $pr"
        else
            api_json "repos/$repo/issues/$pr/comments" POST "$body" >/dev/null ||
                fail "could not comment on PR $pr"
        fi
        ;;
    *)
        usage
        ;;
esac
