#!/usr/bin/env bash
# Shared helpers for the /bet skill scripts. Sourced, not executed directly.
#
# Loads ~/.config/foundry/bet.env (required) and ~/.config/foundry/memory.env
# (optional — memory steps degrade gracefully when it's missing) and exposes:
#   api_call METHOD PATH [JSON_BODY]   -> prints response body; http_status prints the code
#   bet_url PATH                       -> builds a full API URL under /api/projects/:id/
#   resolve_bet_id SLUG_OR_ID          -> prints the bet's UUID (looks up by slug if needed)
#   require_jq / require_curl
#   memory_available                   -> 0 if memory.env is loaded, 1 otherwise

set -euo pipefail

BET_ENV="${BET_ENV:-$HOME/.config/foundry/bet.env}"
MEMORY_ENV="${MEMORY_ENV:-$HOME/.config/foundry/memory.env}"

require_jq() { command -v jq >/dev/null 2>&1 || { echo "ERROR: jq is required but not found on PATH." >&2; exit 1; }; }
require_curl() { command -v curl >/dev/null 2>&1 || { echo "ERROR: curl is required but not found on PATH." >&2; exit 1; }; }
require_jq
require_curl

if [ ! -f "$BET_ENV" ]; then
    cat >&2 <<EOF
ERROR: missing $BET_ENV

The /bet skill needs POSTHOG_URL, POSTHOG_PROJECT_ID, and POSTHOG_PERSONAL_API_KEY
in that file before it can call the API. See references/setup.md, or run:

    scripts/mint-api-key.sh <your-dev-user-email>

from the posthog repo root to mint a key and write this file.
EOF
    exit 1
fi
# shellcheck disable=SC1090
source "$BET_ENV"

for var in POSTHOG_URL POSTHOG_PROJECT_ID POSTHOG_PERSONAL_API_KEY; do
    if [ -z "${!var:-}" ]; then
        echo "ERROR: $BET_ENV is missing $var. See references/setup.md for how to get it." >&2
        exit 1
    fi
done

MEMORY_LOADED=0
if [ -f "$MEMORY_ENV" ]; then
    # shellcheck disable=SC1090
    source "$MEMORY_ENV"
    if [ -n "${MEMORY_GIT_BASE:-}" ] && [ -n "${MEMORY_GIT_USER:-}" ] && [ -n "${MEMORY_GIT_TOKEN:-}" ]; then
        MEMORY_LOADED=1
    fi
fi
memory_available() { [ "$MEMORY_LOADED" = "1" ]; }

# Builds the tokened https clone URL for a product's memory repo, e.g.
#   memory_repo_url foundry  ->  https://user:token@git.host/memory/foundry.git
memory_repo_url() {
    local product="$1"
    local proto="${MEMORY_GIT_BASE%%://*}"
    local rest="${MEMORY_GIT_BASE#*://}"
    echo "${proto}://${MEMORY_GIT_USER}:${MEMORY_GIT_TOKEN}@${rest}/${product}.git"
}

bet_url() {
    local path="$1"
    echo "${POSTHOG_URL%/}/api/projects/${POSTHOG_PROJECT_ID}/${path#/}"
}

# api_call/api_call_ok are often invoked as `x="$(api_call_ok ...)"`, which runs
# them in a command-substitution subshell — plain variable assignments inside
# don't survive back to the caller. The status code is therefore threaded
# through a temp file (which does survive) instead of a shell variable.
API_STATUS_FILE="$(mktemp)"
trap 'rm -f "$API_STATUS_FILE"' EXIT

# Last response status code, valid after any api_call/api_call_ok invocation
# (even one captured via command substitution).
http_status() { cat "$API_STATUS_FILE"; }

# api_call METHOD PATH [JSON_BODY] -> stdout is the response body; http_status prints the code.
api_call() {
    local method="$1" path="$2" body="${3:-}"
    local url; url="$(bet_url "$path")"
    local tmp; tmp="$(mktemp)"
    local args=(-sS -o "$tmp" -w "%{http_code}" -X "$method" \
        -H "Authorization: Bearer ${POSTHOG_PERSONAL_API_KEY}" \
        -H "Content-Type: application/json")
    if [ -n "$body" ]; then
        args+=(--data "$body")
    fi
    curl "${args[@]}" "$url" > "$API_STATUS_FILE"
    cat "$tmp"
    rm -f "$tmp"
}

# api_call_ok METHOD PATH [JSON_BODY] -> like api_call, but exits non-zero with a
# readable error on non-2xx instead of leaving the caller to check http_status.
api_call_ok() {
    local out status
    out="$(api_call "$@")"
    status="$(http_status)"
    if [ "${status:0:1}" != "2" ]; then
        echo "ERROR: $1 $2 -> HTTP $status" >&2
        echo "$out" >&2
        exit 1
    fi
    echo "$out"
}

# resolve_bet_id SLUG_OR_ID -> prints the bet UUID. Accepts a UUID as-is,
# otherwise looks it up by slug via the list endpoint (there is no
# get-by-slug route — the API is UUID-keyed).
resolve_bet_id() {
    local ref="$1"
    if [[ "$ref" =~ ^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$ ]]; then
        echo "$ref"
        return 0
    fi
    local bets id
    bets="$(api_call_ok GET "bets/")"
    id="$(echo "$bets" | jq -r --arg slug "$ref" '[.[] | select(.slug == $slug)][0].id // empty')"
    if [ -z "$id" ]; then
        echo "ERROR: no bet with slug '$ref' found in project ${POSTHOG_PROJECT_ID}." >&2
        exit 1
    fi
    echo "$id"
}
