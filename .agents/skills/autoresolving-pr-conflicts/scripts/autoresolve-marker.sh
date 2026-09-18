#!/usr/bin/env bash
# Constrained marker I/O for the autoresolve sweep: the agent must never read raw PR
# comment bodies, so this helper emits/accepts only strictly validated data.
#
# Marker state is only trusted from the identity the sweep posts as: reads and the comment
# chosen for update are restricted to comments authored by AUTORESOLVE_BOT_LOGIN. A commenter
# can otherwise plant a marker to spoof "already attempted" and skip a PR. Fail closed: with
# the login unset, `get` returns nothing and `set` always creates, so a fuzzy match never
# trusts or overwrites another author's comment.
set -euo pipefail

MARKER_RE='<!-- autoresolve-attempt:[0-9a-f]{40}:[0-9a-f]{40} -->'
BOT_LOGIN=${AUTORESOLVE_BOT_LOGIN:-}

usage() {
    echo "usage: $0 get <owner/repo> <pr_number>" >&2
    echo "       $0 set <owner/repo> <pr_number> <head_oid> <master_oid> < body.md" >&2
    echo "requires AUTORESOLVE_BOT_LOGIN (the login the sweep's comments are authored by)" >&2
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

# Bodies of this PR's comments authored by our App only.
own_comment_bodies() {
    gh api "repos/$repo/issues/$pr/comments" --paginate \
        --jq '.[] | select(.user.login == env.BOT_LOGIN) | .body' 2>/dev/null
}

# A marker written under a different login is invisible to `get` and unreachable by the
# `set` upsert, so the sweep re-resolves every PR and appends a comment each time. That is
# indistinguishable from "never attempted", so report it instead of returning empty.
#
# Only another App identity can mean that, so match bot authors and a complete marker. A human
# who pastes marker-shaped text would otherwise halt every sweep that reaches their PR.
warn_on_foreign_marker() {
    gh api "repos/$repo/issues/$pr/comments" --paginate \
        --jq '[.[] | select(.user.login != env.BOT_LOGIN) | select(.user.type == "Bot")
                   | select(.body | test("<!-- autoresolve-attempt:[0-9a-f]{40}:[0-9a-f]{40} -->"))
                   | .user.login] | unique | join(", ")' 2>/dev/null
}

case "$cmd" in
    get)
        found=$(BOT_LOGIN="$BOT_LOGIN" own_comment_bodies |
            grep -oE "$MARKER_RE" |
            tail -1 |
            grep -oE '[0-9a-f]{40}:[0-9a-f]{40}' || true)
        if [ -z "$found" ]; then
            others=$(BOT_LOGIN="$BOT_LOGIN" warn_on_foreign_marker)
            if [ -n "$others" ]; then
                echo "AUTORESOLVE_BOT_LOGIN=$BOT_LOGIN found no marker, but one exists from: $others" >&2
                echo "Set AUTORESOLVE_BOT_LOGIN to the login that authors this sweep's comments." >&2
                exit 3
            fi
        fi
        if [ -n "$found" ]; then
            printf '%s\n' "$found"
        fi
        ;;
    set)
        head_oid=${4:-}
        master_oid=${5:-}
        printf '%s' "$head_oid" | grep -qE '^[0-9a-f]{40}$' || usage
        printf '%s' "$master_oid" | grep -qE '^[0-9a-f]{40}$' || usage
        body="$(cat)

<!-- autoresolve-attempt:${head_oid}:${master_oid} -->"
        existing_id=$(BOT_LOGIN="$BOT_LOGIN" gh api "repos/$repo/issues/$pr/comments" --paginate \
            --jq '[.[] | select(.user.login == env.BOT_LOGIN)
                       | select(.body | test("<!-- autoresolve-attempt:[0-9a-f]{40}:[0-9a-f]{40} -->"))
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
