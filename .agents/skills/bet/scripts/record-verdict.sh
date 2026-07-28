#!/usr/bin/env bash
# `/bet verdict` action: record the verdict via the API, then run the real
# memory choreography (memory-verdict.sh). Run status.sh first to gather the
# evidence a verdict should be based on — this script only executes the
# decision once a human (or Claude, on the human's behalf) has made it.
#
# Usage: record-verdict.sh <slug-or-id> <promoted|rolled_back|iterate> [reasoning] [--product NAME]
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$SCRIPT_DIR/lib.sh"

if [ -z "${2:-}" ]; then
    echo "Usage: record-verdict.sh <slug-or-id> <promoted|rolled_back|iterate> [reasoning] [--product NAME]" >&2
    exit 1
fi
REF="$1"
VERDICT="$2"
shift 2

BET_ID="$(resolve_bet_id "$REF")"
BET="$(api_call_ok GET "bets/${BET_ID}")"
SLUG="$(echo "$BET" | jq -r .slug)"

BODY="$(jq -n --arg verdict "$VERDICT" '{verdict: $verdict}')"
api_call_ok POST "bets/${BET_ID}/verdict" "$BODY"

"$SCRIPT_DIR/memory-verdict.sh" "$SLUG" "$VERDICT" "$@"
