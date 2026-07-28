#!/usr/bin/env bash
# Optional step (b) of `/bet`: materialize a "rollout KPIs" dashboard for a
# bet whose user named metrics beyond the single formal success_metric.
# Skip entirely for simple, one-metric bets — don't call this script for those.
#
# Usage: kpi-dashboard.sh <slug-or-id> <kpis.json>
#
# kpis.json is a list of:
#   {"name": "...", "kind": "trends"|"retention", "event": "$pageview", "description": "..."}
# "event" is only used for kind=trends (defaults to $pageview if omitted).
# Insights are filtered to the bet's own flag (property $feature/bet-<slug> = true)
# when the flag already exists (i.e. the bet has been funded) — run fund-bet.sh first.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$SCRIPT_DIR/lib.sh"

if [ -z "${2:-}" ] || [ ! -f "$2" ]; then
    echo "Usage: kpi-dashboard.sh <slug-or-id> <kpis.json>" >&2
    exit 1
fi

BET_ID="$(resolve_bet_id "$1")"
KPIS="$(cat "$2")"
BET="$(api_call_ok GET "bets/${BET_ID}")"
SLUG="$(echo "$BET" | jq -r .slug)"
FLAG_KEY="$(echo "$BET" | jq -r '.feature_flag_key // empty')"

DASHBOARD="$(api_call_ok POST "dashboards/" "$(jq -n --arg name "Bet: ${SLUG}" '{name: $name}')")"
DASHBOARD_ID="$(echo "$DASHBOARD" | jq -r .id)"
DASHBOARD_URL="${POSTHOG_URL%/}/project/${POSTHOG_PROJECT_ID}/dashboard/${DASHBOARD_ID}"

echo "Created dashboard: ${DASHBOARD_URL}"

flag_property_filter() {
    if [ -n "$FLAG_KEY" ]; then
        jq -n --arg key "\$feature/${FLAG_KEY}" '[{key: $key, value: ["true"], operator: "exact", type: "event"}]'
    else
        echo '[]'
    fi
}

echo "$KPIS" | jq -c '.[]' | while read -r kpi; do
    NAME="$(echo "$kpi" | jq -r .name)"
    KIND="$(echo "$kpi" | jq -r .kind)"
    EVENT="$(echo "$kpi" | jq -r '.event // "$pageview"')"
    PROPS="$(flag_property_filter)"

    case "$KIND" in
        trends)
            QUERY="$(jq -n --arg event "$EVENT" --argjson props "$PROPS" '{
                kind: "InsightVizNode",
                source: {
                    kind: "TrendsQuery",
                    interval: "day",
                    series: [{kind: "EventsNode", event: $event}],
                    properties: $props,
                    filterTestAccounts: false
                }
            }')"
            ;;
        retention)
            QUERY="$(jq -n --argjson props "$PROPS" '{
                kind: "InsightVizNode",
                source: {
                    kind: "RetentionQuery",
                    properties: $props,
                    filterTestAccounts: false,
                    retentionFilter: {
                        totalIntervals: 8,
                        period: "Day",
                        aggregationType: "count",
                        aggregationPropertyType: "event",
                        cohortLabelStartIndex: 0
                    }
                }
            }')"
            ;;
        *)
            echo "ERROR: unknown KPI kind '${KIND}' (expected 'trends' or 'retention')" >&2
            exit 1
            ;;
    esac

    BODY="$(jq -n --arg name "$NAME" --argjson query "$QUERY" --argjson dashboards "[${DASHBOARD_ID}]" \
        '{name: $name, query: $query, dashboards: $dashboards}')"
    INSIGHT="$(api_call_ok POST "insights/" "$BODY")"
    echo "  insight: ${NAME} (${KIND}) -> $(echo "$INSIGHT" | jq -r .short_id)"
done

NOTE_PAYLOAD="$(jq -n --arg url "$DASHBOARD_URL" '{dashboard_url: $url}')"
post_event_body="$(jq -n --argjson payload "$NOTE_PAYLOAD" '{kind: "note", payload: $payload}')"
api_call_ok POST "bets/${BET_ID}/events" "$post_event_body" >/dev/null
echo "Linked dashboard on the bet timeline via a 'note' event."
echo "DASHBOARD_URL=${DASHBOARD_URL}"
