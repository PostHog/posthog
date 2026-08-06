#!/usr/bin/env bash
# Smoke-test the metrics ingest chain by POSTing a synthetic OTLP payload to
# capture-logs. Same shape as nodejs/src/logs-ingestion/sampling-seed-services-curl.sh.
#
# Usage:
#   # Local dev (default — same path logs scripts use):
#   TOKEN=phc_yourtoken bin/send-dev-metrics.sh
#   TOKEN=phc_yourtoken bin/send-dev-metrics.sh loop   # send every 5s
#
#   # Cloud dev via kubectl port-forward (capture-logs Service inside the cluster):
#   aws login
#   kubectl port-forward -n posthog svc/capture-logs 4320:4318
#   ENDPOINT=http://localhost:4320/v1/metrics TOKEN=phc_yourtoken bin/send-dev-metrics.sh
#
#   # Prod (once the public ingress is live):
#   ENDPOINT=https://us.i.posthog.com/i/v1/metrics TOKEN=phc_yourtoken bin/send-dev-metrics.sh
#   ENDPOINT=https://eu.i.posthog.com/i/v1/metrics TOKEN=phc_yourtoken bin/send-dev-metrics.sh
set -euo pipefail

# Default to the same local-OTel-collector endpoint the logs seed scripts use.
# `otel-collector-config.dev.yaml` routes /v1/metrics to capture-logs:4320 internally.
ENDPOINT="${ENDPOINT:-http://localhost:4318/v1/metrics}"
TOKEN="${TOKEN:-}"

if [ -z "$TOKEN" ]; then
    echo "Set TOKEN=phc_... (project API token — for local dev, any phc_... from your local project works)" >&2
    exit 1
fi

TRACE_ID="${TRACE_ID:-$(openssl rand -hex 16)}"
SPAN_ID="${SPAN_ID:-$(openssl rand -hex 8)}"
SUFFIX="${METRIC_SUFFIX:-$(date +%s)}"

send_one() {
    local now_ns=$(($(date +%s) * 1000000000))
    local body
    body=$(cat <<EOF
{
  "resourceMetrics": [{
    "resource": {"attributes": [
      {"key":"service.name","value":{"stringValue":"e2e-dev-test"}},
      {"key":"deployment.environment","value":{"stringValue":"dev"}}
    ]},
    "scopeMetrics": [{
      "scope": {"name":"send-dev-metrics-sh","version":"v1"},
      "metrics": [
        {
          "name": "e2e_dev_test_counter",
          "unit": "1",
          "sum": {
            "aggregationTemporality": 2,
            "isMonotonic": true,
            "dataPoints": [{
              "timeUnixNano": "${now_ns}",
              "asDouble": 42.0,
              "attributes": [{"key":"endpoint","value":{"stringValue":"/api/test"}}],
              "exemplars": [{
                "timeUnixNano": "${now_ns}",
                "asDouble": 42.0,
                "traceId": "${TRACE_ID}",
                "spanId":  "${SPAN_ID}"
              }]
            }]
          }
        },
        {
          "name": "e2e_dev_test_gauge",
          "unit": "By",
          "gauge": {
            "dataPoints": [{
              "timeUnixNano": "${now_ns}",
              "asDouble": $((RANDOM % 1000)),
              "attributes": [{"key":"host","value":{"stringValue":"host-1"}}]
            }]
          }
        },
        {
          "name": "e2e_dev_test_histogram",
          "unit": "ms",
          "histogram": {
            "aggregationTemporality": 2,
            "dataPoints": [{
              "timeUnixNano": "${now_ns}",
              "count": 100,
              "sum": 12345.67,
              "bucketCounts": [10, 30, 40, 15, 5],
              "explicitBounds": [10, 50, 100, 500],
              "attributes": [{"key":"route","value":{"stringValue":"/api/x"}}],
              "exemplars": [{
                "timeUnixNano": "${now_ns}",
                "asDouble": 42.0,
                "traceId": "${TRACE_ID}",
                "spanId":  "${SPAN_ID}"
              }]
            }]
          }
        }
      ]
    }]
  }]
}
EOF
)
    printf "→ POST %s ... " "$ENDPOINT"
    local http
    http=$(curl -sS -o /tmp/send-dev-metrics.out -w "%{http_code}" \
        -X POST "$ENDPOINT" \
        -H "Authorization: Bearer ${TOKEN}" \
        -H "Content-Type: application/json" \
        --data-binary "$body")
    printf "%s\n" "$http"
    if [ "$http" = "302" ]; then
        echo "  ⚠️  302 — endpoint is behind an auth proxy (e.g. cloud dev's Cognito ALB). Use a port-forward or local endpoint instead. See script header." >&2
        return 1
    fi
    if [ "$http" = "000" ] || [ "$http" = "" ]; then
        echo "  ⚠️  Could not reach $ENDPOINT — is your local OTel collector / capture-logs running? (\`hogli start\`)" >&2
        return 1
    fi
    if [ "$http" != "200" ] && [ "$http" != "202" ]; then
        echo "  Response body:" >&2
        cat /tmp/send-dev-metrics.out >&2
        echo >&2
        return 1
    fi
    return 0
}

case "${1:-once}" in
    once)
        send_one
        echo
        echo "trace_id: ${TRACE_ID}"
        echo "span_id:  ${SPAN_ID}"
        echo
        echo "Verify in the dev PostHog SQL editor:"
        echo
        cat <<SQL
  SELECT metric_name, value, service_name, metric_type,
         trace_id, hex(tryBase64Decode(trace_id)) AS trace_id_hex,
         span_id, timestamp
  FROM posthog.metrics
  WHERE metric_name LIKE 'e2e_dev_test_%'
    AND timestamp >= now() - INTERVAL 5 MINUTE
  ORDER BY timestamp DESC
  LIMIT 10
  FORMAT Vertical
SQL
        ;;
    loop)
        echo "Sending every 5s (Ctrl-C to stop)..."
        while true; do
            send_one || true
            sleep 5
        done
        ;;
    *)
        echo "Usage: TOKEN=phc_... $0 [once|loop]" >&2
        exit 2
        ;;
esac
