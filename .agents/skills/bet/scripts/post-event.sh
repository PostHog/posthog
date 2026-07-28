#!/usr/bin/env bash
# Append a typed event to a bet's log. This is the same endpoint external
# orchestrators use (see print-contract.sh) — the skill uses it too so
# manual steps (gate.result, exposure.started, ...) go through one path.
#
# Usage: post-event.sh <slug-or-id> <kind> <payload-json>
#   post-event.sh checkout-friction gate.result '{"pass": true, "violations": []}'
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$SCRIPT_DIR/lib.sh"

if [ -z "${3:-}" ]; then
    echo "Usage: post-event.sh <slug-or-id> <kind> <payload-json>" >&2
    exit 1
fi

BET_ID="$(resolve_bet_id "$1")"
KIND="$2"
PAYLOAD="$3"

BODY="$(jq -n --arg kind "$KIND" --argjson payload "$PAYLOAD" '{kind: $kind, payload: $payload}')"
api_call_ok POST "bets/${BET_ID}/events" "$BODY"
