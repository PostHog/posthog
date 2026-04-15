# Logs PII scrubbing — developer implementation guide

This doc orders work the way data flows through the system: **settings → ingestion transform → observability → tests**. It assumes the product plan (Option B, four `json_parse_logs` × `pii_scrub_logs` combinations, no new Kafka headers in v1) is agreed.

---

## 1. Data flow (read this first)

```text
Postgres `posthog_team.logs_settings` (JSON)
    → TeamManager loads team rows (includes `logs_settings`)
    → LogsIngestionConsumer.produceValidLogMessages
          team = getTeam(teamId)
          logsSettings = team?.logs_settings ?? {}
          processedValue = processLogMessageBuffer(message.message.value, logsSettings)
    → Kafka (ClickHouse-bound topic) receives Avro buffer (possibly rewritten)
```

**Invariant:** When both `json_parse_logs` and `pii_scrub_logs` are false, `processLogMessageBuffer` returns the **same** buffer reference without decoding (passthrough). When either is true, run **one** Avro decode → optional enrich → optional scrub → encode.

---

## 2. Settings (do this before PII logic)

### 2.1 TypeScript types (source of truth for plugin server)

**File:** [`nodejs/src/types.ts`](../types.ts)

- Extend `LogsSettings` with:

  ```ts
  pii_scrub_logs?: boolean
  ```

### 2.2 Backend / DB

**No migration.** `Team.logs_settings` is already a `JSONField` ([`posthog/models/team/team.py`](../../../posthog/models/team/team.py)).

**File:** [`posthog/api/team.py`](../../../posthog/api/team.py) — `validate_logs_settings` only constrains retention churn; new keys pass through. No change required unless you add validation (optional).

### 2.3 Frontend types + UI (when exposing the toggle)

**File:** [`frontend/src/types.ts`](../../../frontend/src/types.ts)

- Add `pii_scrub_logs?: boolean` to `LogsSettings`.

**File:** [`frontend/src/scenes/settings/environment/LogsCaptureSettings.tsx`](../../../frontend/src/scenes/settings/environment/LogsCaptureSettings.tsx)

- Add a `LemonSwitch` (same pattern as JSON parse) that calls `updateCurrentTeam({ logs_settings: { ...currentTeam?.logs_settings, pii_scrub_logs: checked } })`.
- Copy should mention lossy redaction and what fields are affected (or link to handbook later).

**OpenAPI / generated TS:** If team serializers expose `logs_settings` as opaque JSON, codegen may not need a regen for a new nested key; confirm if any strict schema blocks unknown keys.

### 2.4 Remote config / SDK (only if product sends this flag to clients)

**File:** [`posthog/models/remote_config.py`](../../../posthog/models/remote_config.py) — today exposes `captureConsoleLogs` from `logs_settings`. **Only touch this** if scrubbing must be client-visible; server-side ingestion does not require it for v1.

---

## 3. PII scrubbing module (pure logic, heavily tested)

**New file:** `nodejs/src/logs-ingestion/log-pii-scrub.ts`

**Responsibilities:**

- Export something like `scrubLogRecord(record: LogRecord): void` (mutate in place, like `enrichLogRecordWithJsonAttributes`).
- Operate on string-bearing fields at minimum: `body`, `attributes`, `resource_attributes` (and optionally `service_name`, `instrumentation_scope`, `severity_text`, `event_name` if you want parity across OTel-ish strings).
- **Body:**
  - If `body` parses as JSON object/array: walk tree, scrub string leaves, `JSON.stringify` back (keeps valid JSON).
  - Else: conservative regex pass on raw text.
- **Maps:** sensitive **key** redaction (e.g. keys containing `password`, `token`, …) + **value** patterns (email, card-like sequences, etc.) with a fixed placeholder e.g. `[REDACTED]`.

**New file:** `nodejs/src/logs-ingestion/log-pii-scrub.test.ts`

- Unit tests for JSON body, plain text body, nested objects, false-positive-prone strings, empty/null fields.

**Import type:** Reuse `LogRecord` from [`log-record-avro.ts`](./log-record-avro.ts) — either export `LogRecord` from there and import in scrub module, or move `LogRecord` to a tiny `log-record-types.ts` if you want to avoid circular imports (unlikely if scrub only imports types).

---

## 4. `processLogMessageBuffer` refactor (wire settings → decode → enrich → scrub → encode)

**File:** [`nodejs/src/logs-ingestion/log-record-avro.ts`](./log-record-avro.ts)

### 4.1 Settings argument type

Replace the narrow `{ json_parse_logs?: boolean }` with the full `LogsSettings` shape (or a local interface that includes at least `json_parse_logs?` and `pii_scrub_logs?`). Call sites already have `logsSettings` from the team.

### 4.2 Control flow (four combinations)

```text
const jsonParse = settings.json_parse_logs ?? false
const piiScrub = settings.pii_scrub_logs ?? false

if (!jsonParse && !piiScrub) {
  return buffer  // passthrough
}

decode → records

if (jsonParse) {
  for (const record of records) {
    enrichLogRecordWithJsonAttributes(record)
  }
}

if (piiScrub) {
  for (const record of records) {
    scrubLogRecord(record)
  }
}

encode → return
```

**Order:** enrich **before** scrub when both are on, so JSON-derived `attributes` are scrubbed too.

### 4.3 Metrics

**Same file:** histogram `logs_ingestion_processing_duration_seconds`.

- **Observe only when** decode ran (`jsonParse || piiScrub`), so passthrough does not emit misleading “zero second” decode samples unless you explicitly want that (plan prefers observe-on-decode-only).
- Histogram `labelNames`: `json_parse_enabled`, `pii_scrub_enabled`, `compression_codec` (string `"true"` / `"false"` for the booleans). Observe only when decode ran.

---

## 5. Consumer (minimal changes)

**File:** [`nodejs/src/logs-ingestion/logs-ingestion-consumer.ts`](./logs-ingestion-consumer.ts)

- `processLogMessageBuffer(message.message.value, logsSettings)` — already passes `logsSettings`; ensure the object includes `pii_scrub_logs` once types are updated.
- **Do not** add Kafka headers for PII in v1.
- Existing header `json-parse` continues to reflect `logsSettings.json_parse_logs ?? false` only; no change required unless product wants a second header later.

---

## 6. Tests to extend

| Area | File | What to add |
|------|------|-------------|
| Four-way matrix | [`log-record-avro.test.ts`](./log-record-avro.test.ts) | Passthrough both off; enrich-only; scrub-only (assert **no** flattened JSON attrs); enrich+scrub (assert attrs exist **and** scrubbed). |
| Scrub rules | `log-pii-scrub.test.ts` | Edge cases isolated from Avro. |
| Consumer | [`logs-ingestion-consumer.test.ts`](./logs-ingestion-consumer.test.ts) | Optional: SQL `logs_settings` with `pii_scrub_logs` true if you assert behavior end-to-end (often redundant if Avro tests are thorough). |

---

## 7. Checklist (implementation order)

1. `LogsSettings.pii_scrub_logs` in `nodejs/src/types.ts` (+ frontend `types.ts` + UI when ready).
2. `log-pii-scrub.ts` + `log-pii-scrub.test.ts`.
3. Refactor `processLogMessageBuffer` in `log-record-avro.ts` + histogram labels + `log-record-avro.test.ts` matrix.
4. Confirm `logs-ingestion-consumer.ts` passes full `logsSettings` (types only if already passing object).
5. Run plugin-server tests for the touched files (`hogli test` on those paths).

---

## 8. Out of scope for v1 (do not block on)

- Kafka headers for scrubbing.
- Per-team regex / path configuration (Hog `pii-hashing`-style configurability).
- Hashing + salt (redaction only is simpler for first ship).
- Changes to ClickHouse consumers unless they assume immutable payloads (they should accept re-encoded Avro).
