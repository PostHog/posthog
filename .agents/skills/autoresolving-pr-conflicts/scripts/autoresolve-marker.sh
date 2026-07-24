#!/usr/bin/env bash
# Constrained marker I/O for the autoresolve sweep: the agent must never read raw PR
# comment bodies, so this helper emits/accepts only strictly validated data.
set -euo pipefail

MARKER_RE='<!-- autoresolve-attempt:[0-9a-f]{40}:[0-9a-f]{40} -->'

usage() {
    echo "usage: $0 get <owner/repo> <pr_number>" >&2
    echo "       $0 set <owner/repo> <pr_number> <head_oid> <master_oid> < body.md" >&2
    exit 2
}

cmd=${1:-}
repo=${2:-}
pr=${3:-}
[ -n "$cmd" ] && [ -n "$repo" ] && [ -n "$pr" ] || usage
case "$repo" in
    */*) ;;
    *) usage ;;
esac
case "$pr" in
    '' | *[!0-9]*) usage ;;
esac

case "$cmd" in
    get)
        gh api "repos/$repo/issues/$pr/comments" --paginate --jq '.[].body' 2>/dev/null |
            grep -oE "$MARKER_RE" |
            tail -1 |
            grep -oE '[0-9a-f]{40}:[0-9a-f]{40}' || true
        ;;
    set)
        head_oid=${4:-}
        master_oid=${5:-}
        printf '%s' "$head_oid" | grep -qE '^[0-9a-f]{40}$' || usage
        printf '%s' "$master_oid" | grep -qE '^[0-9a-f]{40}$' || usage
        body="$(cat)

<!-- autoresolve-attempt:${head_oid}:${master_oid} -->"
        existing_id=$(gh api "repos/$repo/issues/$pr/comments" --paginate \
            --jq '[.[] | select(.body | test("<!-- autoresolve-attempt:[0-9a-f]{40}:[0-9a-f]{40} -->")) | .id] | last // empty')
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
