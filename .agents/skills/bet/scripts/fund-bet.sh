#!/usr/bin/env bash
# Fund a drafted bet: creates its feature flag ('bet-<slug>') and a draft
# experiment, then moves it to funded. For managed bets, funding is also
# what starts the foundry-run-bet Temporal workflow.
#
# Usage: fund-bet.sh <slug-or-id>
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$SCRIPT_DIR/lib.sh"

if [ -z "${1:-}" ]; then
    echo "Usage: fund-bet.sh <slug-or-id>" >&2
    exit 1
fi

BET_ID="$(resolve_bet_id "$1")"
api_call_ok POST "bets/${BET_ID}/fund"
