#!/usr/bin/env bash
# Constrained marker I/O for the merge queue triage sweep: the agent must never read
# raw PR comment bodies, so this helper emits/accepts only strictly validated data.
#
# Marker state is only trusted from the identity the sweep posts as: reads and the comment
# chosen for update are restricted to comments authored by MQ_TRIAGE_BOT_LOGIN. A commenter
# can otherwise plant a marker to spoof "already triaged" and skip a PR. Fail closed: with
# the login unset, `get` returns nothing and `set` always creates, so a fuzzy match never
# trusts or overwrites another author's comment.
set -euo pipefail

MARKER_RE='<!-- mq-triage:[0-9a-f]{40}:[0-9]+ -->'
BOT_LOGIN=${MQ_TRIAGE_BOT_LOGIN:-}

usage() {
    echo "usage: $0 get <owner/repo> <pr_number>" >&2
    echo "       $0 set <owner/repo> <pr_number> <head_oid> <attempt_pr> < body.md" >&2
    echo "       $0 verify" >&2
    echo "requires MQ_TRIAGE_BOT_LOGIN (the login the sweep's comments are authored by)" >&2
    exit 2
}

# The second marker field identifies the queue attempt. It used to be a check run id; Trunk
# publishes no check run here, so it is now the shadow PR number of the attempt. Both are bare
# integers, so markers written under the old meaning still parse.

# A token that authenticates as a real user account authors comments as that user, always. So
# when /user reports a User whose login differs from MQ_TRIAGE_BOT_LOGIN, the login is provably
# wrong and every marker read would miss. An App installation token reports no such identity,
# which is why a failed or non-User lookup infers nothing instead of guessing.
verify_identity() {
    local me type
    me=$(gh api user --jq .login 2>/dev/null || true)
    type=$(gh api user --jq .type 2>/dev/null || true)
    if [ -z "$me" ] || [ "$type" != "User" ]; then
        echo "identity: not a user token; cannot check MQ_TRIAGE_BOT_LOGIN=$BOT_LOGIN this way" >&2
        return 0
    fi
    if [ "$me" != "$BOT_LOGIN" ]; then
        echo "MQ_TRIAGE_BOT_LOGIN=$BOT_LOGIN but this token authenticates as the user '$me'." >&2
        echo "Comments would be authored by '$me', which the marker helper neither reads nor" >&2
        echo "updates, so every sweep would append a new verdict comment. Set" >&2
        echo "MQ_TRIAGE_BOT_LOGIN=$me, or give the routine the intended bot's credentials." >&2
        return 4
    fi
    echo "identity: ok ($me)"
}

cmd=${1:-}
repo=${2:-}
pr=${3:-}
[ -n "$BOT_LOGIN" ] || usage
if [ "$cmd" = "verify" ]; then
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

# Bodies of this PR's comments authored by our own identity only.
own_comment_bodies() {
    gh api "repos/$repo/issues/$pr/comments" --paginate \
        --jq '.[] | select(.user.login == env.BOT_LOGIN) | .body' 2>/dev/null
}

# A marker written under a different login is invisible to `get` and unreachable by the
# `set` upsert, so the sweep re-triages every PR and appends a comment each time. That is
# indistinguishable from "never triaged", so report it instead of returning empty.
#
# Another App identity, or this token's own user account, can mean that: a user token authors
# comments as its user whatever MQ_TRIAGE_BOT_LOGIN says. Match those two and a complete
# marker. A human who pastes marker-shaped text would otherwise halt every sweep on their PR.
warn_on_foreign_marker() {
    local me
    me=$(gh api user --jq 'select(.type == "User") | .login' 2>/dev/null || true)
    ME="$me" gh api "repos/$repo/issues/$pr/comments" --paginate \
        --jq '[.[] | select(.user.login != env.BOT_LOGIN)
                   | select(.user.type == "Bot" or (env.ME != "" and .user.login == env.ME))
                   | select(.body | test("<!-- mq-triage:[0-9a-f]{40}:[0-9]+ -->"))
                   | .user.login] | unique | join(", ")' 2>/dev/null
}

case "$cmd" in
    get)
        found=$(BOT_LOGIN="$BOT_LOGIN" own_comment_bodies |
            grep -oE "$MARKER_RE" |
            tail -1 |
            grep -oE '[0-9a-f]{40}:[0-9]+' || true)
        if [ -z "$found" ]; then
            others=$(BOT_LOGIN="$BOT_LOGIN" warn_on_foreign_marker)
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
