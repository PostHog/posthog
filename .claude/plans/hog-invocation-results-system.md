# Hog invocation results system

Status: scoped, ready for build
Owner: Ben White (`ben@posthog.com`)
Branch: `claude/design-hog-results-system-VPxEK`

## Problem

Today, when a CDP `HogFunction` or `HogFlow` invocation runs, we emit two things to ClickHouse:

- Aggregated counts to `app_metrics2` (one row per `(team, source, source_id, instance_id, kind, name, hour)` bucket)
- Free-form log lines to `log_entries` (one row per log line)

What we **don't** have is a per-invocation record that captures the outcome of _that specific invocation_ — its lifecycle (running → succeeded/failed), the error, the attempt number, the original payload it ran against, and a stable handle to re-run it from that payload.

Without it, we can't:

1. Show a user a "runs" view: every invocation for this function in a time window, with status badges, click-to-expand for logs.
2. Programmatically select "all failed invocations for function X in time window Y with N or fewer attempts" and replay them through the worker.
3. See in-flight invocations.

## Decisions (locked)

These were nailed down during scoping; they are not open questions.

1. **One row per invocation lifecycle event.** Write a row when the invocation starts running (`status='running'`) and another when it finishes (`status='succeeded' | 'failed'`). ReplacingMergeTree on `(team_id, function_kind, function_id, invocation_id)` keyed by `version` collapses to the latest.
2. **No row for filtered-out events.** If a function's filters reject an event, nothing is written. Only invocations that actually get queued to run produce rows.
3. **Status vocabulary is exactly three values:** `running`, `succeeded`, `failed`. No `skipped`, `cancelled`, `timed_out`.
4. **The full invocation payload lives on the row** in a column named `invocation_globals`. Stored as `String CODEC(ZSTD(3))` for compactness. Not registered as JSON in HogQL — we don't need to query into it, we just need to rehydrate it on replay.
5. **Promote a few high-value fields** out of the payload into typed top-level columns: `event_uuid`, `distinct_id`, `person_id`. Empty strings when not applicable (batch/manual triggers).
6. **Replay reuses the original `invocation_id`.** A new row is written for the replayed run with the same `invocation_id`, incremented `attempts`, and `is_retry = 1` so the UI can mark it. ReplacingMergeTree collapses to the latest attempt's state.
7. **Hog functions and hog flows share the schema.** No special-casing for hog flows — one row per invocation regardless of source. Future per-step granularity stays in `log_entries`.
8. **Reading is HogQL, not REST.** Register the new table in the HogQL database schema so the UI queries it via `/api/projects/:id/query` like any other table. No bespoke list endpoint.
9. **Writing the replay trigger is a Django → Node proxy that enqueues a wrapper job; it does not run the work.** Django POSTs to a Node endpoint, which creates a `replay`-queue job in cyclotron-v2 with the request serialized into `state` and returns the `replay_job_id`. A dedicated `cdp-replay-worker` service consumes that queue, pages ClickHouse, re-enqueues invocations onto the regular cyclotron queue, and commits progress back via `reschedule({ state })`. Two request shapes:
   - **By IDs** — explicit list of `invocation_id`s with a server-side cap (e.g. 1000).
   - **By filter** — time range + the same top-level filters the list view uses (status, function_id, error_kind, max attempts). The worker keyset-paginates ClickHouse on `(scheduled_at, invocation_id)`.
10. **Logs stay in `log_entries` as-is.** The new "runs" UI is master/detail: click a row → expand → fetch logs via the existing logs API keyed on `instance_id = invocation_id`. Registering `log_entries` in HogQL too is a "maybe later if cheap" follow-up, not v1.
11. **The new UI replaces nothing.** `HogFunctionRuns.tsx` and `HogFunctionLogs.tsx` are untouched. The new "runs" view ships alongside them and is the foundation for eventually subsuming the logs tab.

## Schema

```sql
CREATE TABLE sharded_hog_invocation_results (
    -- Identity
    team_id Int64,
    function_kind LowCardinality(String),   -- 'hog_function' | 'hog_flow'
    function_id String,                     -- HogFunction.id or HogFlow.id
    invocation_id String,                   -- CyclotronJobInvocation.id (UUID, stable across retries)
    parent_run_id String,                   -- batch/parent run id; empty string if none

    -- Lifecycle
    status LowCardinality(String),          -- 'running' | 'succeeded' | 'failed'
    attempts UInt8,                         -- 1 on first run, increments on replay
    is_retry UInt8,                         -- 0 on the original run, 1 on a replay

    -- Timing (UTC microseconds)
    scheduled_at DateTime64(6, 'UTC'),      -- when this invocation was queued
    started_at  Nullable(DateTime64(6, 'UTC')),
    finished_at Nullable(DateTime64(6, 'UTC')),
    duration_ms Nullable(UInt32),

    -- Outcome
    error_kind LowCardinality(String),      -- '' | 'http_4xx' | 'http_5xx' | 'timeout' | 'oom' | 'hog_error'
    error_message String CODEC(ZSTD(3)),    -- truncated (e.g. 4 KiB) — full stack stays in log_entries

    -- Promoted typed fields (filterable in HogQL without parsing the payload)
    event_uuid   String,
    distinct_id  String,
    person_id    String,

    -- Full invocation payload — what the worker needs to replay this run
    invocation_globals String CODEC(ZSTD(3)),

    -- ReplacingMergeTree versioning
    version UInt64,                         -- now64(6) at write time; latest wins
    is_deleted UInt8 DEFAULT 0,             -- tombstone for explicit cancellation

    -- Standard kafka housekeeping
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

### Partition / ordering rationale

- **`ORDER BY` leads with `team_id`** so every query — UI listing, replay paging, HogQL access — does a bounded range scan rather than scanning all teams. Same convention as `events`, `app_metrics2`, `log_entries`.
- **`PARTITION BY toYYYYMMDD(scheduled_at)`** keeps partition count bounded (30 partitions live at any time given the TTL) so daily TTL drops are part-level (`ttl_only_drop_parts = 1`), not row-level mutations.
- We did consider adding `team_id` into the partition expression (e.g. `(intDiv(team_id, 1000), toYYYYMMDD(scheduled_at))`). Deferred — leading `team_id` in `ORDER BY` already handles tenant isolation and adding it to the partition multiplies the partition count. Revisit only if profiling shows team filters are not fast enough.

### Skipping indexes

```sql
INDEX status_idx      status        TYPE set(8)             GRANULARITY 4
INDEX function_idx    function_id   TYPE bloom_filter(0.01) GRANULARITY 4
INDEX event_uuid_idx  event_uuid    TYPE bloom_filter(0.01) GRANULARITY 4
INDEX is_retry_idx    is_retry      TYPE set(2)             GRANULARITY 4
```

### Standard table layout (mirrors `log_entries` / `app_metrics2`)

- `sharded_hog_invocation_results` — replicated, partitioned, the actual data.
- `writable_hog_invocation_results` — distributed alias used as the MV target.
- `hog_invocation_results` — distributed alias used by readers (and by HogQL).
- `kafka_hog_invocation_results` — Kafka engine table consuming `KAFKA_HOG_INVOCATION_RESULTS`.
- `hog_invocation_results_mv` — materialized view from kafka to writable.
- WarpStream variants of the kafka + MV pair alongside the MSK ones (same coexistence pattern as `log_entries` / `app_metrics2`).

## Write path

Producer plumbing exists in `nodejs/src/cdp/services/invocation-results.service.ts:22` (fan-out service) and `nodejs/src/cdp/services/monitoring/hog-function-monitoring.service.ts` (logs + app_metrics2 producer). Add a sibling service:

- **`nodejs/src/cdp/services/monitoring/hog-invocation-results.service.ts`** — new producer. Consumes `CyclotronJobInvocationResult` (already carries `invocation.id`, `teamId`, `functionId`, `parentRunId`, `state.attempts`, `state.timings`, error, finished flag, and the full globals on `invocation.state.globals`).

Behavior:

1. **On invocation start** (the worker has dequeued and is about to execute): emit a row with `status='running'`, `started_at=now()`, `finished_at=null`, `error_kind=''`, `error_message=''`, and the full payload + promoted fields populated. `version = now64(6)`.
2. **On invocation finish** (`result.finished || result.error`): emit a row with `status` derived from `result.error` (`'failed'` if set, otherwise `'succeeded'`), `started_at` carried through, `finished_at=now()`, `duration_ms` summed from `state.timings`, `error_kind/error_message` extracted from `result.error`, **same `invocation_id`**, higher `version`. Payload + promoted fields repeated (cheap given ZSTD, and avoids a Replacing-merge that strips columns we need).
3. **On replay enqueue** (the Django→Node replay handler): emit `status='running'` for the new attempt with same `invocation_id`, `attempts = N+1`, `is_retry = 1`. Then steps 1–2 repeat as usual.

`version` is `now64(6)` (microseconds since unix epoch). No coordination needed. Same monotonicity trick `log_entries` uses with `_timestamp`.

`KAFKA_HOG_INVOCATION_RESULTS` is registered in `posthog/kafka_client/topics.py` and `nodejs/src/config/kafka-topics.ts`.

## Read path

### HogQL schema registration

Add the table to `posthog/hogql/database/schema/` so HogQL clients can query it. Treated as a team-scoped table (auto-filtered on `team_id` in the resolver, same as `events`).

Promoted typed columns are exposed natively. `invocation_globals` is exposed as `String` only — there's no need to parse it for queries. The UI uses HogQL for the listing/filtering and only reads `invocation_globals` when the user explicitly inspects a row.

### Listing query (UI)

Paginated by `(scheduled_at DESC, invocation_id)` keyset. ReplacingMergeTree collapse is done in HogQL via the standard `argMax(field, version) GROUP BY ...` idiom that we already use for `person`:

```sql
-- HogQL
SELECT
    invocation_id,
    argMax(status, version)        AS status,
    argMax(attempts, version)      AS attempts,
    argMax(is_retry, version)      AS is_retry,
    argMax(error_kind, version)    AS error_kind,
    argMax(error_message, version) AS error_message,
    argMax(started_at, version)    AS started_at,
    argMax(finished_at, version)   AS finished_at,
    argMax(duration_ms, version)   AS duration_ms,
    argMax(event_uuid, version)    AS event_uuid,
    argMax(distinct_id, version)   AS distinct_id,
    argMax(person_id, version)     AS person_id,
    max(scheduled_at)              AS scheduled_at
FROM hog_invocation_results
WHERE function_kind = {function_kind}
  AND function_id = {function_id}
  AND scheduled_at >= {window_start}
  AND scheduled_at <  {window_end}
GROUP BY invocation_id
HAVING argMax(is_deleted, version) = 0
   {optional_status_filter}
   {optional_is_retry_filter}
   {optional_attempts_filter}
ORDER BY scheduled_at DESC, invocation_id DESC
LIMIT {limit}
```

### Detail row → logs

Master/detail. Clicking a row uses the existing logs API with `instance_id = invocation_id`. No HogQL change needed for v1.

### Inspecting the full payload

A "view payload" affordance on the detail panel reads `invocation_globals` (a single-row HogQL `SELECT invocation_globals FROM hog_invocation_results WHERE invocation_id = ... ORDER BY version DESC LIMIT 1`).

## Replay trigger

### Django endpoint

New action on the existing viewsets, mirroring how `HogFlowBatchJob` proxies through to Node today.

- `POST /api/projects/:id/hog_functions/:fid/replay`
- `POST /api/projects/:id/hog_flows/:fid/replay`

Two payload shapes:

```json
{
  "invocation_ids": ["uuid-1", "uuid-2", "..."]
}
```

or

```json
{
  "filter": {
    "window_start": "2026-05-01T00:00:00Z",
    "window_end": "2026-05-10T00:00:00Z",
    "status": ["failed"],
    "error_kind": ["http_5xx", "timeout"],
    "max_attempts": 3,
    "max_count": 1000
  }
}
```

The view validates, then proxies through to a new `replay_hog_invocations(team_id, function_kind, function_id, payload)` helper in `posthog/plugins/plugin_server_api.py`.

**The replay endpoint does not run the replay** — it only enqueues a wrapper job onto a new `replay` queue in the cyclotron-v2 job database, then returns the `replay_job_id` immediately:

```json
{ "replay_job_id": "<uuid>", "queued_count": 0, "skipped_count": 0 }
```

The new `cdp-replay-worker` service (PLUGIN_SERVER_MODE=cdp-replay-worker) consumes that queue and runs the actual work:

1. **Dequeue** a wrapper job and parse the `ReplayJobState` blob from `state BYTEA`.
2. **Page ClickHouse** for one batch of `REPLAY_PAGE_SIZE` matching invocations using either the explicit `invocation_ids` (consuming from `progress.remaining_ids`) or the filter's keyset cursor on `(scheduled_at, invocation_id)`.
3. **Rehydrate** each row from `invocation_globals` and **re-enqueue** it onto the regular cyclotron queue with `is_retry=1`. Emit the `'running'` lifecycle row.
4. **If done** (page partial, budget exhausted, or no more ids) → `ack()` the wrapper job.
5. **Otherwise** → `reschedule({ state: nextState, scheduledAt: now + REPLAY_PAGE_DELAY_MS })` so the worker picks it back up after a short delay with the new cursor + counts.

Why a wrapper job, not an inline HTTP call:

- A by-filter replay can match millions of rows. The HTTP request can't block on that.
- **Resumable** — each page persists progress to `state`, so a crash partway through resumes from the cursor.
- **Observable** — the wrapper job sits in `cyclotron_jobs` like any other job; queue depth metrics and the janitor's stalled-job recovery cover it for free.
- **Throttled** — the worker pulls one wrapper job at a time, and the inter-page delay prevents ClickHouse hot-looping.

### Naming

`replay` (not `retry`) — "retry" implies resuming the same context; what we're doing is re-executing from a stored payload. The endpoint name, queue name, and code paths use `replay` throughout. The row-level marker stays as `is_retry` to match existing CDP terminology in the worker (which already has a notion of "retry" for transient failure re-enqueue).

## Surface area changes

### Backend (Django / Python)

- `posthog/kafka_client/topics.py` — add `KAFKA_HOG_INVOCATION_RESULTS`.
- `posthog/models/hog_invocation_results/sql.py` — new file with the multi-table layout (sharded / writable / distributed / kafka + MV), MSK + WarpStream variants. Mirrors `posthog/models/app_metrics2/sql.py` for the layout and `posthog/clickhouse/log_entries.py` for the TTL + sharding choices.
- `posthog/clickhouse/schema.py` — register the new tables.
- `posthog/clickhouse/migrations/0253_hog_invocation_results.py` — new migration creating all of the above. Numbering follows `0252_extend_session_replay_features.py`.
- `posthog/hogql/database/schema/hog_invocation_results.py` — new HogQL schema definition for the distributed table. Team-scoped resolver.
- `posthog/hogql/database/database.py` — register the new schema.
- `posthog/plugins/plugin_server_api.py` — add `replay_hog_invocations(...)`.
- `posthog/api/hog_function.py` and `posthog/api/hog_flow.py` — add a `replay` action that validates input and proxies through to Node.
- `posthog/api/hog_invocation_replay.py` — shared replay request/response serializers used by both viewsets.

### Worker (Node.js)

- `nodejs/src/cdp/services/monitoring/hog-invocation-results.service.ts` — new producer (start row + finish row).
- `nodejs/src/cdp/services/invocation-results.service.ts` — fan out to the new service alongside monitoring/warehouse/captured-events.
- `nodejs/src/config/kafka-topics.ts` — register the topic.
- `nodejs/src/ingestion/common/outputs/index.ts` — register the new output channel.
- `nodejs/src/cdp/replay/replay-job.types.ts` — shared types for the replay wrapper job (`ReplayJobState`, `ReplayCursor`, queue name, page size, cap).
- `nodejs/src/cdp/replay/replay-job.manager.ts` — `ReplayJobManager.enqueue(...)` used by `cdp-api`. Creates the wrapper job in cyclotron-v2 with the serialized request as `state` and returns the `replay_job_id`.
- `nodejs/src/cdp/replay/replay-paginator.service.ts` — `processPage(teamId, state)` runs one page of ClickHouse + rehydrate + re-enqueue work, returns the next state. Pure-ish, testable in isolation from cyclotron plumbing.
- `nodejs/src/cdp/consumers/cdp-replay-worker.consumer.ts` — `CdpReplayWorkerConsumer` deployed as `PLUGIN_SERVER_MODE=cdp-replay-worker`. Owns its own `CyclotronV2Worker` on `queueName='replay'`, its own ClickHouse client, and drives the paginator. Heartbeats during long pages; ack/reschedule on each tick.
- `nodejs/src/common/config.ts` — add `cdp_replay_worker` to `PluginServerMode`.
- `nodejs/src/capabilities.ts` + `nodejs/src/types.ts` — add the `cdpReplayWorker` capability flag.
- `nodejs/src/server.ts` — wire the new consumer into the service loader.
- `nodejs/src/cdp/cdp-api.ts` — keep the API thin: just instantiates `ReplayJobManager` and enqueues a wrapper job in the `replay` handler. Does **not** instantiate a ClickHouse client, does **not** run paginated work inline.

### Frontend

- `frontend/src/scenes/hog-functions/runs-v2/` (or similar; **separate** directory from the existing `runs/`) — new scene and kea logic. List view + filters (status, time range, is_retry, error_kind, search-by-event-uuid) + detail panel.
- The detail panel uses the existing logs viewer (`LogsViewer.tsx`) bound to `instance_id = invocation_id`.
- A "replay" button on the detail panel and a bulk-replay action on multi-select in the list. Both POST to the new Django endpoints.
- Workflows side: equivalent new scene under `products/workflows/frontend/Workflows/`.

### MCP

- New tools `hog_function_invocations_list` and `hog_function_invocations_replay` (and hog_flow equivalents) via `products/cdp/mcp/tools.yaml`. Agents can inspect failures and trigger replays the same way the UI does.

## Build sequence

Roughly the order I'd ship this in.

1. **ClickHouse schema + migration.** SQL files + `0253_hog_invocation_results.py`. Verifiable locally with `clickhouse_migrate`.
2. **Kafka topic registration** (Python + Node side).
3. **Worker producer service** behind a per-team feature flag — start writing rows but don't read them yet. Lets us land the producer safely and validate row volume before any UI.
4. **HogQL schema registration** for the new table.
5. **Replay endpoint (Django) + ReplayJobManager (Node).** Endpoint only enqueues a wrapper job; returns `replay_job_id`. Testable end-to-end with curl + a `SELECT * FROM cyclotron_jobs WHERE queue_name = 'replay'`.
6. **`cdp-replay-worker` consumer.** Deploys as its own `PLUGIN_SERVER_MODE=cdp-replay-worker`. Drives `ReplayPaginatorService` against ClickHouse, re-enqueues invocations onto the regular cyclotron queue, commits progress via reschedule.
7. **Frontend runs scene** (list + filters + detail panel + logs expansion via existing viewer).
8. **Bulk replay UI** (multi-select on the runs scene → POST `/replay` with `invocation_ids`).
9. **MCP tools.**

Each step is shippable independently. The feature flag in step 3 stays on through step 7 so we only flip it for early teams. Steps 5–6 can be staged separately: step 5 lands the producer + queue plumbing (replay jobs accumulate but no worker drains them), step 6 turns on the worker. That gap is intentional — it lets us validate the wrapper job shape on a small set before pointing real workloads at the paginator.

## Out of scope (v1)

- Promoting `log_entries` into HogQL. Stays as-is; we use it through the existing API. Easy follow-up if cheap.
- Replacing or modifying the existing `HogFunctionLogs.tsx` / `HogFunctionRuns.tsx` UIs. The new runs view ships alongside.
- Retention beyond 30 days. If product asks for longer, separate proposal.
- Action-step-level rows for hog flows. Per-step detail stays in `log_entries`.

## Risks worth tracking

1. **Row volume.** Two rows per invocation × every event that matches a function × every team × 30 days. We should pull a back-of-envelope estimate from current `app_metrics2` totals before turning the producer on globally. Mitigation: feature-flag the producer per team, ramp.
2. **Payload size in `invocation_globals`.** A full hog function invocation's globals can be tens of KiB once person properties are flattened. ZSTD compresses this well in practice (often 4–8×), but if a small number of teams send enormous events, we may want a hard cap (e.g. truncate `invocation_globals` past 256 KiB and set a flag column so replay can refuse / warn). Not implementing v1 — measure first.
3. **Replay storms.** A user can replay a million rows. Server-side cap on `max_count` plus per-team rate-limiting on the replay endpoint. Audit-log the trigger.
4. **Tenant isolation.** `team_id` is on every row and first in `ORDER BY`. HogQL resolver auto-filters, same as `events`. Standard PostHog convention.
5. **History after replay.** Because ReplacingMergeTree collapses by `invocation_id`, prior failed attempts are no longer visible from this table after a successful replay. The full per-attempt history lives in `log_entries` (different rows per attempt because the worker logs per-attempt). Acceptable v1.
