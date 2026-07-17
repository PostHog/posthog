#!/usr/bin/env bash
# OTLP HTTP/JSON → /v1/logs: deterministic rows to verify head sampling path_drop rules.
#
# Same transport as pii-probe-extensive-curl.sh:
#   OTEL_LOGS_HTTP=http://localhost:4318/v1/logs ./sampling-drop-probe-curl.sh
# Direct to capture (no collector auth injection):
#   OTEL_LOGS_HTTP=http://127.0.0.1:8010/i/v1/logs OTEL_LOGS_TOKEN=phc_... ./sampling-drop-probe-curl.sh
#
# Ingestion worker: LOGS_SAMPLING_ENABLED_TEAMS defaults to * (all teams). Set empty to disable sampling
# evaluation globally, or comma-separated team ids to restrict. Restart worker after overriding env.
#
# Rules live in Postgres table logs_logsexclusionrule (API: project logs drop rules).
# Create rules in UI (Project settings → Logs → Drop rules) or API; enable them.
#
# Logs UI filter: ph.probe.suite = sampling_drop_probe
#                OR body contains "SAMPLE_DROP_PROBE"
#
set -euo pipefail

ENDPOINT="${OTEL_LOGS_HTTP:-http://localhost:4318/v1/logs}"
TOKEN="${OTEL_LOGS_TOKEN:-}"

BASE_NS=$(($(date +%s) * 1000000000))
# One nanosecond apart so time ordering in UI matches send order within each service block.
T1=$((BASE_NS + 1))
T2=$((BASE_NS + 2))
T3=$((BASE_NS + 3))
T4=$((BASE_NS + 4))
T5=$((BASE_NS + 5))
T6=$((BASE_NS + 6))

# Stable trace id (hex = 16 bytes); path_drop does not use it — kept for parity with other probes.
TRACE="0123456789abcdef0123456789abcdef"

payload=$(
    cat <<JSON
{
  "resourceLogs": [
    {
      "resource": {
        "attributes": [
          { "key": "service.name", "value": { "stringValue": "probe-svc-alpha" } },
          { "key": "deployment.environment", "value": { "stringValue": "sampling-drop-probe" } }
        ]
      },
      "scopeLogs": [
        {
          "scope": { "name": "sampling-drop-probe", "version": "1.0.0" },
          "logRecords": [
            {
              "timeUnixNano": "${T1}",
              "traceId": "${TRACE}",
              "severityText": "INFO",
              "body": { "stringValue": "SAMPLE_DROP_PROBE seq=1 expect=KEEP svc=probe-svc-alpha route=/__probe__/alpha-keep-a (before drop-global)" },
              "attributes": [
                { "key": "ph.probe.suite", "value": { "stringValue": "sampling_drop_probe" } },
                { "key": "ph.probe.seq", "value": { "stringValue": "1" } },
                { "key": "ph.probe.expect", "value": { "stringValue": "KEEP" } },
                { "key": "http.route", "value": { "stringValue": "/__probe__/alpha-keep-a" } }
              ]
            },
            {
              "timeUnixNano": "${T2}",
              "traceId": "${TRACE}",
              "severityText": "INFO",
              "body": { "stringValue": "SAMPLE_DROP_PROBE seq=2 expect=DROP svc=probe-svc-alpha route=/__probe__/drop-global (global path_drop)" },
              "attributes": [
                { "key": "ph.probe.suite", "value": { "stringValue": "sampling_drop_probe" } },
                { "key": "ph.probe.seq", "value": { "stringValue": "2" } },
                { "key": "ph.probe.expect", "value": { "stringValue": "DROP" } },
                { "key": "http.route", "value": { "stringValue": "/__probe__/drop-global" } }
              ]
            },
            {
              "timeUnixNano": "${T3}",
              "traceId": "${TRACE}",
              "severityText": "INFO",
              "body": { "stringValue": "SAMPLE_DROP_PROBE seq=3 expect=KEEP svc=probe-svc-alpha route=/__probe__/drop-beta-only (alpha must NOT match beta-scoped rule)" },
              "attributes": [
                { "key": "ph.probe.suite", "value": { "stringValue": "sampling_drop_probe" } },
                { "key": "ph.probe.seq", "value": { "stringValue": "3" } },
                { "key": "ph.probe.expect", "value": { "stringValue": "KEEP" } },
                { "key": "http.route", "value": { "stringValue": "/__probe__/drop-beta-only" } }
              ]
            }
          ]
        }
      ]
    },
    {
      "resource": {
        "attributes": [
          { "key": "service.name", "value": { "stringValue": "probe-svc-beta" } },
          { "key": "deployment.environment", "value": { "stringValue": "sampling-drop-probe" } }
        ]
      },
      "scopeLogs": [
        {
          "scope": { "name": "sampling-drop-probe", "version": "1.0.0" },
          "logRecords": [
            {
              "timeUnixNano": "${T4}",
              "traceId": "${TRACE}",
              "severityText": "INFO",
              "body": { "stringValue": "SAMPLE_DROP_PROBE seq=4 expect=DROP svc=probe-svc-beta route=/__probe__/drop-beta-only (scoped path_drop)" },
              "attributes": [
                { "key": "ph.probe.suite", "value": { "stringValue": "sampling_drop_probe" } },
                { "key": "ph.probe.seq", "value": { "stringValue": "4" } },
                { "key": "ph.probe.expect", "value": { "stringValue": "DROP" } },
                { "key": "http.route", "value": { "stringValue": "/__probe__/drop-beta-only" } }
              ]
            },
            {
              "timeUnixNano": "${T5}",
              "traceId": "${TRACE}",
              "severityText": "INFO",
              "body": { "stringValue": "SAMPLE_DROP_PROBE seq=5 expect=DROP svc=probe-svc-beta route=/__probe__/drop-global (global path_drop)" },
              "attributes": [
                { "key": "ph.probe.suite", "value": { "stringValue": "sampling_drop_probe" } },
                { "key": "ph.probe.seq", "value": { "stringValue": "5" } },
                { "key": "ph.probe.expect", "value": { "stringValue": "DROP" } },
                { "key": "http.route", "value": { "stringValue": "/__probe__/drop-global" } }
              ]
            },
            {
              "timeUnixNano": "${T6}",
              "traceId": "${TRACE}",
              "severityText": "INFO",
              "body": { "stringValue": "SAMPLE_DROP_PROBE seq=6 expect=KEEP svc=probe-svc-beta route=/__probe__/beta-keep (after drops)" },
              "attributes": [
                { "key": "ph.probe.suite", "value": { "stringValue": "sampling_drop_probe" } },
                { "key": "ph.probe.seq", "value": { "stringValue": "6" } },
                { "key": "ph.probe.expect", "value": { "stringValue": "KEEP" } },
                { "key": "http.route", "value": { "stringValue": "/__probe__/beta-keep" } }
              ]
            }
          ]
        }
      ]
    }
  ]
}
JSON
)

if [[ -n "${SAMPLING_DROP_PROBE_PRINT_ONLY:-}" ]]; then
    printf '%s\n' "${payload}"
    exit 0
fi

CURL_AUTH=()
if [[ -n "${TOKEN}" ]]; then
    CURL_AUTH=(-H "Authorization: Bearer ${TOKEN}")
fi

echo "POST ${ENDPOINT}" >&2
curl -sS -w '\nHTTP %{http_code}\n' -X POST "${ENDPOINT}" \
    "${CURL_AUTH[@]}" \
    -H 'Content-Type: application/json' \
    -d "${payload}"

echo >&2
cat <<'DOC' >&2
---
Rules to create (enable both; priority 0 runs before 1):

  1) Name: probe global drop /__probe__/drop-global
     rule_type: path_drop
     scope_service: (empty / all services)
     scope_path_pattern: (empty)
     config: {"patterns":["/__probe__/drop-global"]}
     priority: 0

  2) Name: probe beta-only drop /__probe__/drop-beta-only
     rule_type: path_drop
     scope_service: probe-svc-beta
     scope_path_pattern: (empty)
     config: {"patterns":["/__probe__/drop-beta-only"]}
     priority: 1

Expected in Logs UI after ~ingestion delay (filter: ph.probe.suite = sampling_drop_probe):

  seq  body marker                          should appear?
  ---  --------------------------------   --------------
  1    alpha-keep-a                       YES
  2    drop-global on alpha               NO
  3    drop-beta-only on alpha            YES (scoped rule does not apply)
  4    drop-beta-only on beta             NO
  5    drop-global on beta                NO
  6    beta-keep                          YES

Metrics (Prometheus on ingestion-logs): logs_ingestion_sampling_records_dropped_total{team_id="..."}
  should bump by 3 when rules are active (seq 2,4,5 dropped).

If all six lines still appear: sampling not enabled for team, no enabled rules, or worker not restarted.
DOC
