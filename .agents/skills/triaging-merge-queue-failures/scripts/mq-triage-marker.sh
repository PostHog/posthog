#!/usr/bin/env bash
# Constrained marker I/O for the merge queue triage sweep: the agent must never read
# raw PR comment bodies, so this helper emits/accepts only strictly validated data.
#
# Marker state is only trusted from our own App: reads and the comment chosen for update
# are restricted to comments authored by MQ_TRIAGE_BOT_LOGIN (the Loop's `<slug>[bot]`
# login). A commenter can otherwise plant a marker to spoof "already triaged" and skip a
# PR. Fail closed: with the login unset, `get` returns nothing and `set` always creates,
# so a fuzzy match never trusts or overwrites another author's comment.
set -euo pipefail

MARKER_RE='<!-- mq-triage:[0-9a-f]{40}:[0-9]+ -->'
BOT_LOGIN=${MQ_TRIAGE_BOT_LOGIN:-}

usage() {
    echo "usage: $0 get <owner/repo> <pr_number>" >&2
    echo "       $0 set <owner/repo> <pr_number> <head_oid> <check_run_id> < body.md" >&2
    echo "requires MQ_TRIAGE_BOT_LOGIN (the Loop App's <slug>[bot] login)" >&2
    exit 2
}

cmd=${1:-}
repo=${2:-}
pr=${3:-}
[ -n "$cmd" ] && [ -n "$repo" ] && [ -n "$pr" ] || usage
[ -n "$BOT_LOGIN" ] || usage
case "$repo" in
    */*) ;;
    *) usage ;;
esac
case "$pr" in
    '' | *[!0-9]*) usage ;;
esac

own_comment_bodies() {
    gh api "repos/$repo/issues/$pr/comments" --paginate \
        --jq '.[] | select(.user.login == env.BOT_LOGIN) | .body' 2>/dev/null
}

case "$cmd" in
    get)
        BOT_LOGIN="$BOT_LOGIN" own_comment_bodies |
            grep -oE "$MARKER_RE" |
            tail -1 |
            grep -oE '[0-9a-f]{40}:[0-9]+' || true
        ;;
    set)
        head_oid=${4:-}
        check_run_id=${5:-}
        printf '%s' "$head_oid" | grep -qE '^[0-9a-f]{40}$' || usage
        printf '%s' "$check_run_id" | grep -qE '^[0-9]+$' || usage
        body="$(cat)

<!-- mq-triage:${head_oid}:${check_run_id} -->"
        existing_id=$(BOT_LOGIN="$BOT_LOGIN" gh api "repos/$repo/issues/$pr/comments" --paginate \
            --jq '[.[] | select(.user.login == env.BOT_LOGIN)
                       | select(.body | test("<!-- mq-triage:[0-9a-f]{40}:[0-9]+ -->"))
                       | .id] | last // empty')
        case "$existing_id" in
            '' | *[!0-9]*) existing_id='' ;;
        esac
        if [ -n "$existing_id" ]; then
            gh api -X PATCH "repos/$repo/issues/comments/$existing_id" -f body="$body" --jq .id >/dev/null
        else
            gh api -X POST "repos/$repo/issues/$pr/comments" -f body="$body" --jq .id >/dev/null
        fi
        ;;
    *)
        usage
        ;;
esac
