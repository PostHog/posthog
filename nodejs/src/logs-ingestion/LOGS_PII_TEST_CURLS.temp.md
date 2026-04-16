# Logs PII scrub — manual curl cheatsheet (temporary)

Delete this file when you are done. OTLP HTTP JSON → your local collector (e.g. `localhost:4318`).

## Prerequisites

- OTLP logs endpoint reachable (example: `http://localhost:4318/v1/logs`).
- Team has **`logs_settings.pii_scrub_logs`** (and optionally **`json_parse_logs`**) enabled if you want the **Node** consumer scrub path on Kafka Avro. Hitting the collector alone does not prove Node scrub unless that path feeds the same pipeline.
- Filter rows in the product by **`PII probe`** in the body and/or **`service.name` = `pii-scrub-manual`**.

## Placeholder token

Scrubber uses **`{{REDACTED}}`**. See `log-pii-scrub.ts` (`PII_REDACTED`).

## ClickHouse / Kafka attribute cells

Kafka MV uses **`JSONExtractString(v)`** on each Avro map value (`bin/clickhouse-logs.sql`). The Node consumer writes **`attributes` / `resource_attributes`** values as **JSON string cells** (`JSON.stringify` of the semantic string) after scrub, matching Rust OTLP encoding, so redacted placeholders **survive** ingest and show as **`{{REDACTED}}`** in Logs.

**Body** is not passed through that map transform; it shows **`{{REDACTED}}`** inline in the body string or JSON.

**`$originalTimestamp`:** still inserted by Rust as plain RFC3339 (not a JSON cell); it may appear empty in CH until Rust encodes it the same way (separate from PII scrub).

---

## 1) One-shot batch (recommended)

Single POST: multiple `logRecords`, shared probe email, **`PII probe`** in every body for search.

```bash
curl -sS -X POST 'http://localhost:4318/v1/logs' \
  -H 'Content-Type: application/json' \
  -d "$(cat <<'EOF'
{
  "resourceLogs": [{
    "resource": {
      "attributes": [
        { "key": "service.name", "value": { "stringValue": "pii-scrub-manual" } },
        { "key": "host.note", "value": { "stringValue": "res scrub-me@pii-test.invalid" } }
      ]
    },
    "scopeLogs": [{
      "scope": { "name": "pii-scrub-batch" },
      "logRecords": [
        {
          "timeUnixNano": "1735689600000000001",
          "severityText": "INFO",
          "body": { "stringValue": "PII probe case=plain_text scrub-me@pii-test.invalid Bearer aa.bb.cc" },
          "attributes": [
            { "key": "ph.test.case", "value": { "stringValue": "plain_body" } },
            { "key": "ph.test.suite", "value": { "stringValue": "pii_scrub_batch" } }
          ]
        },
        {
          "timeUnixNano": "1735689600000000002",
          "severityText": "INFO",
          "body": { "stringValue": "{\"_filter\":\"PII probe\",\"msg\":\"scrub-me@pii-test.invalid\"}" },
          "attributes": [{ "key": "ph.test.case", "value": { "stringValue": "json_body" } }]
        },
        {
          "timeUnixNano": "1735689600000000003",
          "severityText": "INFO",
          "body": { "stringValue": "{\"_filter\":\"PII probe\",\"card_str\":\"4242-4242-4242-4242\",\"e\":\"scrub-me@pii-test.invalid\"}" },
          "attributes": [{ "key": "ph.test.case", "value": { "stringValue": "json_card_string" } }]
        },
        {
          "timeUnixNano": "1735689600000000004",
          "severityText": "INFO",
          "body": { "stringValue": "{\"_filter\":\"PII probe\",\"card_num\":4242424242424242,\"e\":\"scrub-me@pii-test.invalid\"}" },
          "attributes": [{ "key": "ph.test.case", "value": { "stringValue": "json_card_number" } }]
        },
        {
          "timeUnixNano": "1735689600000000005",
          "severityText": "INFO",
          "body": { "stringValue": "PII probe case=invalid_luhn 4242424242424243 scrub-me@pii-test.invalid" },
          "attributes": [{ "key": "ph.test.case", "value": { "stringValue": "invalid_luhn_plain" } }]
        },
        {
          "timeUnixNano": "1735689600000000006",
          "severityText": "INFO",
          "body": { "stringValue": "PII probe case=attr_split scrub-me@pii-test.invalid" },
          "attributes": [
            { "key": "ph.test.case", "value": { "stringValue": "sensitive_key_vs_body" } },
            { "key": "my_api_secret", "value": { "stringValue": "no-patterns-here" } },
            { "key": "note", "value": { "stringValue": "attr scrub-me@pii-test.invalid" } }
          ]
        },
        {
          "timeUnixNano": "1735689600000000007",
          "severityText": "INFO",
          "body": { "stringValue": "{\"_filter\":\"PII probe\",\"my_api_secret\":\"no-patterns-here\",\"e\":\"scrub-me@pii-test.invalid\"}" },
          "attributes": [{ "key": "ph.test.case", "value": { "stringValue": "json_body_sensitive_key" } }]
        }
      ]
    }]
  }]
}
EOF
)"
```

### Expected / desired after Node PII scrub (logic target)

| `ph.test.case` | Body (desired) | Attributes (desired, UI shows semantic after CH extract) |
|----------------|----------------|----------------------|
| `plain_body` | `PII probe ... scrub-me@{{REDACTED}} ... Bearer {{REDACTED}}` (email + Bearer tail redacted) | `ph.*` JSON-cells; values look like `plain_body`, `pii_scrub_batch` |
| `json_body` | JSON: `msg` → `{{REDACTED}}`; `_filter` keeps `PII probe` | — |
| `json_card_string` | Luhn-valid PAN string → `{{REDACTED}}`; email → `{{REDACTED}}` | — |
| `json_card_number` | PAN as **number** left as digits (known gap); email string → `{{REDACTED}}` | — |
| `invalid_luhn_plain` | Digit run not Luhn-valid → unchanged; email → `{{REDACTED}}` | — |
| `attr_split` | Same email redaction in body | `my_api_secret` → `{{REDACTED}}` (sensitive key, JSON cell); `note` → `attr {{REDACTED}}` |
| `json_body_sensitive_key` | JSON does **not** full-redact by key name; `my_api_secret` value stays `no-patterns-here` unless pattern hits | Compare to row `attr_split` attribute behavior |

### Attribute keys to avoid in **test labels**

Keys containing substrings like `email`, `token`, `secret`, etc. trigger **full value** redaction. Use **`ph.test.*`** style keys for labels.

---

## 2) Minimal repro: body vs attribute same email

**Desired:** body JSON has `{{REDACTED}}` for email; attribute `user_email` value should show **`{{REDACTED}}`** after scrub (sensitive key, stored as JSON cell).

```bash
curl -sS -X POST 'http://localhost:4318/v1/logs' \
  -H 'Content-Type: application/json' \
  -d '{
  "resourceLogs": [{
    "resource": {
      "attributes": [
        { "key": "service.name", "value": { "stringValue": "pii-scrub-manual" } }
      ]
    },
    "scopeLogs": [{
      "logRecords": [{
        "timeUnixNano": "1735689600000000010",
        "severityText": "INFO",
        "body": { "stringValue": "PII probe {\"user_email\":\"public@example.com\"}" },
        "attributes": [
          { "key": "ph.test.case", "value": { "stringValue": "body_vs_user_email_attr" } },
          { "key": "user_email", "value": { "stringValue": "public@example.com" } }
        ]
      }]
    }]
  }]
}'
```

---

## 3) Stripe-shaped string (synthetic test key)

Use a fake `sk_test_` + 20+ alphanumeric chars (see `STRIPE_SECRET_KEY_RE` in `log-pii-scrub.ts`). Key **`ph.test.stripe`** avoids sensitive-key full wipe.

```bash
curl -sS -X POST 'http://localhost:4318/v1/logs' \
  -H 'Content-Type: application/json' \
  -d '{
  "resourceLogs": [{
    "resource": { "attributes": [{ "key": "service.name", "value": { "stringValue": "pii-scrub-manual" } }] },
    "scopeLogs": [{
      "logRecords": [{
        "timeUnixNano": "1735689600000000020",
        "body": { "stringValue": "PII probe key sk_test_1234567890123456789012 end" },
        "attributes": [
          { "key": "ph.test.case", "value": { "stringValue": "stripe_pattern" } }
        ]
      }]
    }]
  }]
}'
```

**Desired:** body contains `{{REDACTED}}` instead of the synthetic key segment.

---

## 4) Success response

OTLP exporters often return `{"partialSuccess":{}}` with HTTP 200 — that is normal.
