# Hog invocation results system

Status: draft for review
Owner: Ben White (`ben@posthog.com`)
Branch: `claude/design-hog-results-system-VPxEK`

## Problem

Today, when a CDP `HogFunction` or `HogFlow` invocation runs, we emit two things to ClickHouse:

- Aggregated counts to `app_metrics2` (one row per `(team, source, source_id, instance_id, kind, name, hour)` bucket)
- Free-form log lines to `log_entries` (one row per log line)

What we **don't** have is a per-invocation record that captures the outcome of *that specific invocation* — success/failure, the error, the attempt number, the trigger payload, the duration, and a stable handle to re-run it.

Without it, we can't:

1. Show a user "here are the last 1,000 invocations for this function, status by status" in the UI (the closest we get today is reconstructing it from log lines).
2. Programmatically select "all failed invocations for function X in time window Y with N or fewer attempts" and feed them back through the worker for a retry.
3. Reflect the outcome of a retry against the original invocation so the UI shows the latest state, not a history of partial attempts.

## Proposal

Add a new ClickHouse table — working name `hog_invocation_results` — that records one logical row per invocation. The row is updated over time as the invocation progresses or is retried; the engine collapses prior versions and a `SELECT` returns the latest state.

### Pattern (mirrors existing PostHog conventions)

- **Engine**: `ReplacingMergeTree` keyed by `(team_id, function_kind, function_id, invocation_id)` with `version` as the merge-time tie-breaker. Same shape as `person_distinct_id2` and `person`. Queries use `argMax(field, version)` to read the latest state, not `FINAL` (consistent with how we read persons).
- **Sharded + distributed + writable + kafka_mv** mirror of `log_entries` (`sharded_hog_invocation_results`, `writable_hog_invocation_results`, `hog_invocation_results` distributed alias, `kafka_hog_invocation_results` + MV).
- **Partition**: `toYYYYMMDD(scheduled_at)` so 30-day TTL drops whole parts.
- **TTL**: 30 days on `scheduled_at` (matches user requirement). `ttl_only_drop_parts = 1`.
- **Kafka topic**: new `KAFKA_HOG_INVOCATION_RESULTS` registered in `posthog/kafka_client/topics.py`, WarpStream MV variant added alongside the MSK one (same pattern as `log_entries` / `app_metrics2`).

### Schema (proposed)

```sql
CREATE TABLE sharded_hog_invocation_results (
    -- Identity
    team_id Int64,
    function_kind LowCardinality(String),   -- 'hog_function' | 'hog_flow'
    function_id String,                     -- HogFunction.id or HogFlow.id (matches today's app_source_id)
    invocation_id String,                   -- CyclotronJobInvocation.id (UUID, stable across retries)
    parent_run_id String,                   -- batch/parent run id, empty string if none

    -- Timing (all UTC microseconds)
    scheduled_at DateTime64(6, 'UTC'),      -- when the invocation was scheduled / first queued
    started_at  Nullable(DateTime64(6, 'UTC')),
    finished_at Nullable(DateTime64(6, 'UTC')),
    duration_ms Nullable(UInt32),

    -- Outcome
    status LowCardinality(String),          -- 'scheduled' | 'running' | 'succeeded' | 'failed' | 'skipped' | 'retrying'
    attempts UInt8,                         -- 1 on first run, increments on retries
    error_kind LowCardinality(String),      -- short bucket: 'http_4xx', 'http_5xx', 'timeout', 'oom', 'hog_error', 'filtered', ''
    error_message String,                   -- truncated (e.g. 4 KiB) — full stack stays in log_entries

    -- Trigger reference (lets retry rebuild input without us re-deriving it)
    trigger_event_uuid String,              -- empty for batch/manual triggers
    trigger_distinct_id String,
    trigger_person_id String,               -- empty if not resolved
    trigger_globals_ref String,             -- S3 / object-storage key, empty if event lookup is enough

    -- Versioning for ReplacingMergeTree
    version UInt64,                         -- monotonic per (team_id, function_kind, function_id, invocation_id)
    is_deleted UInt8 DEFAULT 0,             -- tombstone so reads can hide cancelled/expired records

    -- Standard kafka housekeeping (KAFKA_COLUMNS_WITH_PARTITION)
    _timestamp DateTime,
    _offset    UInt64,
    _partition UInt64
)
ENGINE = ReplicatedReplacingMergeTree(..., version)
PARTITION BY toYYYYMMDD(scheduled_at)
ORDER BY (team_id, function_kind, function_id, invocation_id)
TTL toDate(scheduled_at) + INTERVAL 30 DAY DELETE
SETTINGS index_granularity = 1024, ttl_only_drop_parts = 1
```

Plus secondary skipping indexes to support the listing/retry queries cheaply:

```sql
INDEX status_idx       status                  TYPE set(8)     GRANULARITY 4
INDEX function_idx     function_id             TYPE bloom_filter(0.01) GRANULARITY 4
INDEX trigger_event_idx trigger_event_uuid     TYPE bloom_filter(0.01) GRANULARITY 4
```

### Write path

The data we need already exists in `CyclotronJobInvocationResult` inside `nodejs/src/cdp/types.ts:281`. The producer plumbing exists in `nodejs/src/cdp/services/monitoring/hog-function-monitoring.service.ts` and is fanned out by `nodejs/src/cdp/services/invocation-results.service.ts:22`.

Add a new service `HogInvocationResultsService` (sibling of `HogFunctionMonitoringService`) that:

1. On every `result.finished || result.error`, emits **one** row with `status = succeeded | failed`, `attempts = result.invocation.state.attempts`, `duration_ms` summed from `state.timings`, `error_kind/error_message` extracted from `result.error`.
2. (Optional v2) On schedule / start emits a `scheduled` / `running` row with the same `invocation_id` and a lower `version`, so the UI can show "in flight".
3. On retry triggers (see below), emits a row with `attempts = N+1` and an incremented `version`. ReplacingMergeTree collapses prior versions; `argMax(status, version)` returns the latest.

`version` is `now64(6)` (microseconds since epoch). That gives us:

- Natural monotonicity even across CDP workers / regions.
- No coordination needed to allocate it.
- Matches how `log_entries` uses `_timestamp` as the merge tie-breaker.

The row is produced to `KAFKA_HOG_INVOCATION_RESULTS`. A Kafka-engine table + materialized view writes into `writable_hog_invocation_results`, same shape as the `app_metrics2_mv` / `log_entries_mv` pair.

### Read path

**Listing (UI)** — paginated by `(scheduled_at DESC, invocation_id)` keyset:

```sql
SELECT
    invocation_id,
    argMax(status, version)        AS status,
    argMax(attempts, version)      AS attempts,
    argMax(error_kind, version)    AS error_kind,
    argMax(error_message, version) AS error_message,
    argMax(started_at, version)    AS started_at,
    argMax(finished_at, version)   AS finished_at,
    argMax(duration_ms, version)   AS duration_ms,
    max(scheduled_at)              AS scheduled_at
FROM hog_invocation_results
WHERE team_id = %(team_id)s
  AND function_kind = %(function_kind)s
  AND function_id = %(function_id)s
  AND scheduled_at >= %(window_start)s
  AND scheduled_at <  %(window_end)s
GROUP BY invocation_id
HAVING argMax(is_deleted, version) = 0
   {optional_status_filter}
   {optional_attempts_filter}
ORDER BY scheduled_at DESC, invocation_id DESC
LIMIT %(limit)s
```

**Retry candidate selection** — feeds the worker. Same query, projecting only `invocation_id`, `trigger_event_uuid`, `trigger_globals_ref`, plus a max-attempts gate.

### Retry trigger

This part is **not** "re-run the same row in place"; it's "produce a new invocation, link it back". Two paths:

1. **In-place retry (preferred)** — the worker already supports it via Cyclotron job re-enqueue. The retry handler:
   - Pages `hog_invocation_results` with the filter the user provides (`function_id`, time range, `status='failed'`, `attempts <= N`).
   - For each row, reconstructs the `CyclotronJobInvocation` from `trigger_event_uuid` / `trigger_globals_ref`.
   - Re-queues with the **same `invocation_id`** and `attempts += 1`.
   - On completion, the worker writes a new row with the same `invocation_id`, higher `version` → the listing query collapses.

2. **Batch retry** — uses the existing `HogFlowBatchJob` model (`products/workflows/backend/models/hog_flow_batch_job/hog_flow_batch_job.py:13`) as the orchestration record. Adds a new `kind = 'retry'` discriminator and a JSON `filter` that ClickHouse pages against. Pagination is keyset on `(scheduled_at, invocation_id)` so a long-running retry job can resume.

### Why ReplacingMergeTree (and not e.g. CollapsingMergeTree)

- We don't need a sign-based reconciliation, we just want "last write wins".
- `argMax` queries are the existing PostHog idiom (`person`, `person_distinct_id2`, `cohort_membership`, `groups`).
- TTL on partition column lets old parts drop wholesale instead of MUTATE-style deletes.

## Surface area changes

### Backend (Django / Python)

- `posthog/kafka_client/topics.py` — add `KAFKA_HOG_INVOCATION_RESULTS`.
- `posthog/models/hog_invocation_results/sql.py` — new file with the four-table schema (sharded / writable / distributed / kafka + MV), MSK + WarpStream variants. Pattern: copy `posthog/models/app_metrics2/sql.py` for the multi-table layout and `posthog/clickhouse/log_entries.py` for the TTL + sharding choices.
- `posthog/clickhouse/schema.py` — register the new tables.
- `posthog/clickhouse/migrations/0253_hog_invocation_results.py` — new migration creating all of the above. Numbering follows `0252_extend_session_replay_features.py`.
- `posthog/api/hog_function.py` and `posthog/api/hog_flow.py` — add an `invocations` (list) action that pages `hog_invocation_results`, plus an `invocations_retry` action that enqueues retries. Today's `invocations` action on `HogFunctionViewSet` is the *test* invocation endpoint; reuse the name only if we're OK overloading, otherwise call the new ones `runs` and `runs/retry` (more honest given the existing `HogFunctionRuns` UI).

### Worker (Node.js)

- `nodejs/src/cdp/services/monitoring/hog-invocation-results.service.ts` — new producer service that consumes `CyclotronJobInvocationResult` and emits the row.
- `nodejs/src/cdp/services/invocation-results.service.ts` — fan out to the new service (alongside monitoring, warehouse webhooks, captured events).
- `nodejs/src/config/kafka-topics.ts` — register the topic.
- `nodejs/src/cdp/services/retry/` — new module that drives retry execution given a list of `invocation_id`s from ClickHouse.
- `nodejs/src/ingestion/common/outputs.ts` — register the new output channel (mirrors `LOG_ENTRIES_OUTPUT`, `APP_METRICS2_OUTPUT`).

### Frontend

- `frontend/src/scenes/hog-functions/runs/HogFunctionRuns.tsx` — today this is a thin wrapper around `BatchExportRuns`. Replace with a new component sourced from the invocations endpoint.
- New kea logic `hogFunctionInvocationsLogic.ts` for paginated listing + filters (`status`, `attempts`, time range, search by event UUID).
- New "Retry" action on the runs table (multi-select + bulk action), gated behind the hog function's existing edit permission.
- Mirror on the workflows side: `products/workflows/frontend/Workflows/WorkflowLogs.tsx` already exists; add a `WorkflowRuns.tsx` next to it.

### MCP

- Add `hog_function_invocations_list` and `hog_function_invocations_retry` tools (and the `hog_flow_*` equivalents) via `products/cdp/mcp/tools.yaml` so agents can inspect failures and trigger retries the same way.

## Out of scope (for v1)

- Storing the full trigger payload inline — for now we use `trigger_event_uuid` + an S3 reference for non-event triggers. Inline payloads up to ~64 KiB could be a v2 follow-up if event lookups turn out to be too slow.
- Retention beyond 30 days. If product asks for longer, we either bump the TTL globally or add an archival sink — both should be a separate proposal.
- A "live invocations" view powered by `scheduled` / `running` rows. The schema supports it; the worker write-path for it is in v2 because it doubles the row volume.
- Aggregated counters — `app_metrics2` stays as-is. The new table is per-row only.

## Risks / open questions

1. **Row volume.** Hog functions run on every matching event for every team. We need a quick back-of-envelope: how many invocations/sec at peak, what does that look like at 30-day retention? `log_entries` already absorbs multiple rows per invocation; the new table is 1–N rows per invocation depending on whether we write status transitions. v1 = one row at terminal state keeps this conservative.
2. **Trigger payload sourcing for retry.** If the original event has aged out of ClickHouse `events`, we can't reconstruct the invocation. Either:
   - Cap retry window at ClickHouse `events` retention (today: usually >30d, but per-team).
   - Persist the trigger payload to S3 alongside the result row.
   The schema supports either; we need a product call.
3. **Hog flows are multi-step.** A single hog flow invocation can run for hours/days across many `actionStepCount` transitions. Do we want one row per *flow run* or one per *action step*? Recommendation: one per flow run, with action-step granularity staying in `log_entries`.
4. **In-place retries change history.** If user A retries and user B retries again, the first retry's outcome is collapsed by ReplacingMergeTree. We may want a separate `hog_invocation_attempts` audit table if forensic history matters. v1 = no, log_entries already captures the per-attempt detail.
5. **Tenant isolation.** `team_id` is on the row and first in `ORDER BY`. Standard PostHog convention.
