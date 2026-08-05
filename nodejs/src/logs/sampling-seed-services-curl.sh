#!/usr/bin/env bash
# OTLP HTTP/JSON → /v1/logs: seed multiple service.name values + routes + severities for local
# Logs "Services" tab and head sampling (path_drop, severity_sampling, scoped rules).
#
# Prerequisites (same path as pii-probe-extensive-curl.sh):
#   - OTLP endpoint reachable (otel-collector on 4318, or capture-logs / dev proxy).
#   - ingestion-logs consumer running.
#
# For sampling evaluation in the Node worker you also need:
#   - LOGS_SAMPLING_ENABLED_TEAMS defaults to * (restrict via env if needed).
#   - At least one enabled rule in logs_logsexclusionrule (otherwise the consumer keeps passthrough).
#
# Usage:
#   OTEL_LOGS_HTTP=http://localhost:4318/v1/logs ./sampling-seed-services-curl.sh
#   OTEL_LOGS_TOKEN=phc_... ./sampling-seed-services-curl.sh   # direct to capture-logs / proxy without collector-injected auth
#   SAMPLING_SEED_PRINT_ONLY=1 ./sampling-seed-services-curl.sh  # print JSON only
#
# Logs UI filter: body contains "sampling seed dev" OR ph.probe.suite = sampling_services_seed
#
# traceId values are 32-char hex (16 bytes) so ingestion matches OTLP → Kafka row → Avro decode;
# hashing in severity sample uses trace_id bytes when present (see evaluate.ts).

set -euo pipefail

ENDPOINT="${OTEL_LOGS_HTTP:-http://localhost:4318/v1/logs}"
TOKEN="${OTEL_LOGS_TOKEN:-}"

BASE_NS=$(($(date +%s) * 1000000000))
T1=$((BASE_NS + 1))
T2=$((BASE_NS + 2))
T3=$((BASE_NS + 3))
T4=$((BASE_NS + 4))
T5=$((BASE_NS + 5))
T6=$((BASE_NS + 6))
T7=$((BASE_NS + 7))
T8=$((BASE_NS + 8))
T9=$((BASE_NS + 9))
T10=$((BASE_NS + 10))
T11=$((BASE_NS + 11))
T12=$((BASE_NS + 12))
T13=$((BASE_NS + 13))
T14=$((BASE_NS + 14))

# Distinct 128-bit trace ids (hex) for stable sample_kept / sample_dropped when testing rates.
TRACE_A="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
TRACE_B="bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"

payload=$(
    cat <<JSON
{
  "resourceLogs": [
    {
      "resource": {
        "attributes": [
          { "key": "service.name", "value": { "stringValue": "checkout-svc" } },
          { "key": "deployment.environment", "value": { "stringValue": "sampling-seed" } }
        ]
      },
      "scopeLogs": [
        {
          "scope": { "name": "sampling-seed", "version": "1.0.0" },
          "logRecords": [
            {
              "timeUnixNano": "${T1}",
              "traceId": "${TRACE_A}",
              "severityText": "DEBUG",
              "body": { "stringValue": "sampling seed dev checkout debug noise" },
              "attributes": [
                { "key": "ph.probe.suite", "value": { "stringValue": "sampling_services_seed" } },
                { "key": "http.route", "value": { "stringValue": "/checkout/cart" } }
              ]
            },
            {
              "timeUnixNano": "${T2}",
              "traceId": "${TRACE_A}",
              "severityText": "INFO",
              "body": { "stringValue": "sampling seed dev checkout info" },
              "attributes": [
                { "key": "ph.probe.suite", "value": { "stringValue": "sampling_services_seed" } },
                { "key": "http.route", "value": { "stringValue": "/checkout/confirm" } }
              ]
            },
            {
              "timeUnixNano": "${T3}",
              "traceId": "${TRACE_A}",
              "severityText": "WARN",
              "body": { "stringValue": "sampling seed dev checkout warn" },
              "attributes": [
                { "key": "ph.probe.suite", "value": { "stringValue": "sampling_services_seed" } },
                { "key": "http.route", "value": { "stringValue": "/checkout/legacy" } }
              ]
            },
            {
              "timeUnixNano": "${T4}",
              "traceId": "${TRACE_A}",
              "severityText": "ERROR",
              "body": { "stringValue": "sampling seed dev checkout error" },
              "attributes": [
                { "key": "ph.probe.suite", "value": { "stringValue": "sampling_services_seed" } },
                { "key": "http.route", "value": { "stringValue": "/checkout/pay" } }
              ]
            }
          ]
        }
      ]
    },
    {
      "resource": {
        "attributes": [
          { "key": "service.name", "value": { "stringValue": "api-gateway" } },
          { "key": "deployment.environment", "value": { "stringValue": "sampling-seed" } }
        ]
      },
      "scopeLogs": [
        {
          "scope": { "name": "sampling-seed", "version": "1.0.0" },
          "logRecords": [
            {
              "timeUnixNano": "${T5}",
              "traceId": "${TRACE_A}",
              "severityText": "INFO",
              "body": { "stringValue": "sampling seed dev gateway health" },
              "attributes": [
                { "key": "ph.probe.suite", "value": { "stringValue": "sampling_services_seed" } },
                { "key": "http.route", "value": { "stringValue": "/health" } }
              ]
            },
            {
              "timeUnixNano": "${T6}",
              "traceId": "${TRACE_A}",
              "severityText": "INFO",
              "body": { "stringValue": "sampling seed dev gateway noisy api" },
              "attributes": [
                { "key": "ph.probe.suite", "value": { "stringValue": "sampling_services_seed" } },
                { "key": "http.route", "value": { "stringValue": "/api/v1/noisy" } }
              ]
            },
            {
              "timeUnixNano": "${T7}",
              "traceId": "${TRACE_B}",
              "severityText": "INFO",
              "body": { "stringValue": "sampling seed dev gateway trace-b" },
              "attributes": [
                { "key": "ph.probe.suite", "value": { "stringValue": "sampling_services_seed" } },
                { "key": "http.route", "value": { "stringValue": "/api/v1/stable" } }
              ]
            },
            {
              "timeUnixNano": "${T8}",
              "traceId": "${TRACE_A}",
              "severityText": "ERROR",
              "body": { "stringValue": "sampling seed dev gateway 500" },
              "attributes": [
                { "key": "ph.probe.suite", "value": { "stringValue": "sampling_services_seed" } },
                { "key": "url.path", "value": { "stringValue": "/api/v1/fail" } }
              ]
            }
          ]
        }
      ]
    },
    {
      "resource": {
        "attributes": [
          { "key": "service.name", "value": { "stringValue": "worker-batch" } },
          { "key": "deployment.environment", "value": { "stringValue": "sampling-seed" } }
        ]
      },
      "scopeLogs": [
        {
          "scope": { "name": "sampling-seed", "version": "1.0.0" },
          "logRecords": [
            {
              "timeUnixNano": "${T9}",
              "traceId": "${TRACE_A}",
              "severityText": "INFO",
              "body": { "stringValue": "sampling seed dev worker batch" },
              "attributes": [
                { "key": "ph.probe.suite", "value": { "stringValue": "sampling_services_seed" } },
                { "key": "http.route", "value": { "stringValue": "/jobs/run" } }
              ]
            },
            {
              "timeUnixNano": "${T10}",
              "traceId": "${TRACE_A}",
              "severityText": "INFO",
              "body": { "stringValue": "sampling seed dev worker heartbeat" },
              "attributes": [
                { "key": "ph.probe.suite", "value": { "stringValue": "sampling_services_seed" } },
                { "key": "path", "value": { "stringValue": "/internal/heartbeat" } }
              ]
            },
            {
              "timeUnixNano": "${T11}",
              "traceId": "${TRACE_A}",
              "severityText": "DEBUG",
              "body": { "stringValue": "sampling seed dev worker spam" },
              "attributes": [
                { "key": "ph.probe.suite", "value": { "stringValue": "sampling_services_seed" } },
                { "key": "http.route", "value": { "stringValue": "/jobs/poll" } }
              ]
            }
          ]
        }
      ]
    },
    {
      "resource": {
        "attributes": [
          { "key": "service.name", "value": { "stringValue": "billing-svc" } },
          { "key": "deployment.environment", "value": { "stringValue": "sampling-seed" } }
        ]
      },
      "scopeLogs": [
        {
          "scope": { "name": "sampling-seed", "version": "1.0.0" },
          "logRecords": [
            {
              "timeUnixNano": "${T12}",
              "traceId": "${TRACE_A}",
              "severityText": "INFO",
              "body": { "stringValue": "sampling seed dev billing invoice" },
              "attributes": [
                { "key": "ph.probe.suite", "value": { "stringValue": "sampling_services_seed" } },
                { "key": "http.route", "value": { "stringValue": "/billing/invoice" } }
              ]
            },
            {
              "timeUnixNano": "${T13}",
              "traceId": "${TRACE_A}",
              "severityText": "WARN",
              "body": { "stringValue": "sampling seed dev billing dunning" },
              "attributes": [
                { "key": "ph.probe.suite", "value": { "stringValue": "sampling_services_seed" } },
                { "key": "http.route", "value": { "stringValue": "/billing/dunning" } }
              ]
            }
          ]
        }
      ]
    },
    {
      "resource": { "attributes": [] },
      "scopeLogs": [
        {
          "scope": { "name": "sampling-seed", "version": "1.0.0" },
          "logRecords": [
            {
              "timeUnixNano": "${T14}",
              "traceId": "${TRACE_A}",
              "severityText": "INFO",
              "body": { "stringValue": "sampling seed dev no service.name orphan" },
              "attributes": [
                { "key": "ph.probe.suite", "value": { "stringValue": "sampling_services_seed" } },
                { "key": "http.route", "value": { "stringValue": "/orphan" } }
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

if [[ -n "${SAMPLING_SEED_PRINT_ONLY:-}" ]]; then
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
echo "Done. Logs UI: body ~ \"sampling seed dev\" or ph.probe.suite sampling_services_seed" >&2
echo "Services: checkout-svc, api-gateway, worker-batch, billing-svc; empty resource → (no service) in aggregates" >&2
