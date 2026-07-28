#!/usr/bin/env bash
# `/bet scout <slug>` action: gather the same evidence the scout's periodic sweep
# (products/foundry/backend/tasks/tasks.py::foundry_scout_task) uses — exposure ramp
# progress, guardrail declarations, experiment link, and any verdict.proposed the sweep
# already recorded — for a human (or Claude, on the human's behalf) to narrate. This
# script never triggers the sweep itself (it runs on a beat schedule, or is triggered
# directly against the Django process for testing); it only reads what's already on
# the bet's timeline.
#
# Usage: scout.sh <slug-or-id>
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$SCRIPT_DIR/lib.sh"

if [ -z "${1:-}" ]; then
    echo "Usage: scout.sh <slug-or-id>" >&2
    exit 1
fi

BET_ID="$(resolve_bet_id "$1")"
BET="$(api_call_ok GET "bets/${BET_ID}")"
EVENTS="$(api_call_ok GET "bets/${BET_ID}/events")"

SLUG="$(echo "$BET" | jq -r .slug)"
STATE="$(echo "$BET" | jq -r .state)"
TTL="$(echo "$BET" | jq -r '.ttl // "none"')"
EXPERIMENT_ID="$(echo "$BET" | jq -r '.experiment_id // empty')"

echo "=== Scout report: ${SLUG} (${BET_ID}) ==="
echo "State: ${STATE}   TTL: ${TTL}"
echo

echo "-- Guardrails --"
echo "$BET" | jq -r '
    .guardrails[]? |
    if .metric and (.threshold != null) and .direction then
        "  - \(.name): \(.direction) \(.threshold) (\(.metric.metric_kind // "?"), query_ref=\(.metric.query_ref // "unset"))"
    else
        "  - \(.name): unparameterized (the scout skips this one, with a note)"
    end
'
if [ "$(echo "$BET" | jq '.guardrails | length')" = "0" ]; then
    echo "  (none declared)"
fi
echo

echo "-- Exposure ramp --"
STEPS_TOTAL="$(echo "$BET" | jq '.exposure_plan.steps // [] | length')"
if [ "$STEPS_TOTAL" = "0" ]; then
    echo "  (no exposure_plan.steps configured — rollout is entirely manual)"
else
    AUTO_START="$(echo "$BET" | jq -r '.exposure_plan.auto_start // false')"
    echo "  ${STEPS_TOTAL} step(s) configured, auto_start=${AUTO_START}"
    echo "$EVENTS" | jq -r '
        .[] | select(.kind == "exposure.advanced") |
        "    step \(.payload.step) -> \(.payload.rollout_pct)% at \(.created_at)"
    '
    HALTED="$(echo "$EVENTS" | jq '[.[] | select(.kind == "exposure.halted")] | last')"
    if [ "$HALTED" != "null" ]; then
        echo "$HALTED" | jq -r '.payload as $p | "    HALTED: \($p.reason) - \($p.details // "")"'
    fi
fi
echo

echo "-- Verdict proposals --"
PROPOSALS="$(echo "$EVENTS" | jq '[.[] | select(.kind == "verdict.proposed")]')"
if [ "$(echo "$PROPOSALS" | jq 'length')" = "0" ]; then
    echo "  (none yet — the scout sweeps exposed bets on a schedule; nothing has concluded)"
else
    echo "$PROPOSALS" | jq -r '
        .[] |
        "  - \(.payload.recommendation) (\(.payload.evidence.condition // "?")) at \(.created_at)",
        "    evidence: \(.payload.evidence | tostring)"
    '
fi
echo

echo "-- Experiment --"
if [ -n "$EXPERIMENT_ID" ] && [ "$EXPERIMENT_ID" != "null" ]; then
    EXPERIMENT="$(api_call GET "experiments/${EXPERIMENT_ID}")"
    EXP_STATUS="$(http_status)"
    if [ "${EXP_STATUS:0:1}" = "2" ]; then
        echo "  ${POSTHOG_URL%/}/project/${POSTHOG_PROJECT_ID}/experiments/${EXPERIMENT_ID}"
        echo "$EXPERIMENT" | jq -r '"    name: \(.name)\n    start_date: \(.start_date // "not started")\n    end_date: \(.end_date // "still running")"'
    else
        echo "  experiment ${EXPERIMENT_ID}: could not fetch (HTTP ${EXP_STATUS} — check the experiment:read scope)"
    fi
else
    echo "  none linked"
fi
