#!/usr/bin/env bash
# Portfolio one-liner per bet: state, age, metric. Backs `/bet list`.
#
# Usage: list-bets.sh
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$SCRIPT_DIR/lib.sh"

BETS="$(api_call_ok GET "bets/")"

if [ "$(echo "$BETS" | jq 'length')" = "0" ]; then
    echo "(no bets in project ${POSTHOG_PROJECT_ID} yet — run /bet to create one)"
    exit 0
fi

echo "$BETS" | jq -r '
    sort_by(.created_at) | reverse | .[]
    | "\(.slug)\t\(.state)\(if .verdict then " (" + .verdict + ")" else "" end)\t\(.execution_mode)\titer \(.iteration)\t\(.success_metric.name // "n/a")\t\(.created_at)"
' | awk -F'\t' 'BEGIN{printf "%-28s %-22s %-10s %-8s %-24s %s\n", "SLUG", "STATE", "MODE", "ITER", "METRIC", "CREATED"}
{printf "%-28s %-22s %-10s %-8s %-24s %s\n", $1, $2, $3, $4, $5, $6}'
