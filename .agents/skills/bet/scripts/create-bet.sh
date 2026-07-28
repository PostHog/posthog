#!/usr/bin/env bash
# Create a bet in the drafted state.
#
# Usage: create-bet.sh <spec.json>
#
# spec.json matches CreateBetSerializer (products/foundry/backend/presentation/serializers.py):
#   slug, hypothesis, success_metric {name, target?, description?},
#   guardrails? [{name, constraint?}], budget? {usd?, time_hours?, iterations?},
#   exposure_plan? {}, sources? [{label, url?}], ttl?, execution_mode? (external|managed),
#   run_config? {}, memory_repo_url?
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$SCRIPT_DIR/lib.sh"

if [ -z "${1:-}" ] || [ ! -f "$1" ]; then
    echo "Usage: create-bet.sh <spec.json>" >&2
    exit 1
fi

SPEC="$(cat "$1")"
api_call_ok POST "bets/" "$SPEC"
