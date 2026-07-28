#!/usr/bin/env bash
# Render the "scout report" for one bet: state, node tree, gate outcome,
# experiment/metric status, guardrails, and any linked KPI dashboard or
# knowledge entries. This is what a human reads instead of code — `/bet
# status` and `/bet verdict` both build on this.
#
# Usage: status.sh <slug-or-id>
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$SCRIPT_DIR/lib.sh"

if [ -z "${1:-}" ]; then
    echo "Usage: status.sh <slug-or-id>" >&2
    exit 1
fi

BET_ID="$(resolve_bet_id "$1")"
BET="$(api_call_ok GET "bets/${BET_ID}")"
EVENTS="$(api_call_ok GET "bets/${BET_ID}/events")"
NODES="$(api_call_ok GET "bets/${BET_ID}/nodes")"

SLUG="$(echo "$BET" | jq -r .slug)"
STATE="$(echo "$BET" | jq -r .state)"
VERDICT="$(echo "$BET" | jq -r '.verdict // "none"')"
ITERATION="$(echo "$BET" | jq -r .iteration)"
HYPOTHESIS="$(echo "$BET" | jq -r .hypothesis)"
METRIC_NAME="$(echo "$BET" | jq -r '.success_metric.name // "n/a"')"
METRIC_TARGET="$(echo "$BET" | jq -r '.success_metric.target // "n/a"')"
FLAG_KEY="$(echo "$BET" | jq -r '.feature_flag_key // "none"')"
EXPERIMENT_ID="$(echo "$BET" | jq -r '.experiment_id // empty')"
EXEC_MODE="$(echo "$BET" | jq -r .execution_mode)"

echo "=== Bet: ${SLUG} (${BET_ID}) ==="
echo "State: ${STATE}   Verdict: ${VERDICT}   Iteration: ${ITERATION}   Mode: ${EXEC_MODE}"
echo "Hypothesis: ${HYPOTHESIS}"
echo "Success metric: ${METRIC_NAME} (target: ${METRIC_TARGET})"
echo

echo "-- Guardrails --"
echo "$BET" | jq -r '.guardrails[]? | "  - \(.name): \(.constraint // "no constraint recorded")"'
if [ "$(echo "$BET" | jq '.guardrails | length')" = "0" ]; then
    echo "  (none declared)"
fi
echo

echo "-- Node tree --"
if [ "$(echo "$NODES" | jq 'length')" = "0" ]; then
    echo "  (no nodes yet — external bets populate this from node.* events, managed bets from the workflow)"
else
    echo "$NODES" | jq -r '
        def tree_lines:
          (group_by(.parent_id) | map({(if .[0].parent_id == null then "root" else .[0].parent_id end): .}) | add) as $bykey
          | def walk(node; depth):
              ("  " * (depth + 1) + "- [\(node.status)] \(node.node_id) (runner: \(node.runner // "n/a"), cost: \(node.cost_so_far))"),
              (($bykey[node.id] // []) | .[] | walk(.; depth + 1));
          (.[] | select(.parent_id == null)) as $root
          | walk($root; 0)
        ;
        tree_lines
    '
fi
echo

GATE_EVENT="$(echo "$EVENTS" | jq '[.[] | select(.kind == "gate.result")] | last')"
echo "-- Gate --"
if [ "$GATE_EVENT" = "null" ]; then
    echo "  (no gate.result event yet)"
else
    echo "$GATE_EVENT" | jq -r '
        .payload as $p
        | if ($p.skipped // false) then
            "  skipped (\($p.reason // "no reason given"))"
          else
            (if ($p.pass // false) then "  PASS" else "  FAIL" end),
            (
              ($p.checks // []) | map(
                "    [\(if .pass then "pass" else "fail" end)]"
                + (if .required then "" else " (optional)" end)
                + " \(.name) (\(.type)): \(.details // "")"
              ) | .[]
            )
          end
    '
fi
echo

echo "-- Knowledge published --"
KNOWLEDGE="$(echo "$EVENTS" | jq '[.[] | select(.kind == "knowledge.published")]')"
if [ "$(echo "$KNOWLEDGE" | jq 'length')" = "0" ]; then
    echo "  (none)"
else
    echo "$KNOWLEDGE" | jq -r '.[] | "  - \(.payload.title // "untitled"): \(.payload.repo // "?")@\(.payload.ref // "?") \(.payload.path // "")"'
fi
echo

echo "-- KPI dashboard --"
DASHBOARD_NOTE="$(echo "$EVENTS" | jq '[.[] | select(.kind == "note" and (.payload.dashboard_url != null))] | last')"
if [ "$DASHBOARD_NOTE" = "null" ]; then
    echo "  (none — this bet has no rollout-KPI dashboard)"
else
    echo "$DASHBOARD_NOTE" | jq -r '"  \(.payload.dashboard_url)"'
fi
echo

echo "-- Feature flag / experiment --"
echo "  flag: ${FLAG_KEY} -> ${POSTHOG_URL%/}/project/${POSTHOG_PROJECT_ID}/feature_flags/$(echo "$BET" | jq -r '.feature_flag_id // "?"')"
if [ -n "$EXPERIMENT_ID" ] && [ "$EXPERIMENT_ID" != "null" ]; then
    EXPERIMENT="$(api_call GET "experiments/${EXPERIMENT_ID}")"
    EXP_STATUS="$(http_status)"
    if [ "${EXP_STATUS:0:1}" = "2" ]; then
        echo "  experiment: ${POSTHOG_URL%/}/project/${POSTHOG_PROJECT_ID}/experiments/${EXPERIMENT_ID}"
        echo "$EXPERIMENT" | jq -r '"    name: \(.name)\n    start_date: \(.start_date // "not started")\n    end_date: \(.end_date // "still running")"'
    else
        echo "  experiment ${EXPERIMENT_ID}: could not fetch (HTTP ${EXP_STATUS} — check the experiment:read scope)"
    fi
else
    echo "  experiment: none linked"
fi
