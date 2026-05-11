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

One payload shape — a required `filter` with mandatory time window plus optional filtering knobs (including an optional `invocation_ids` list as one more `IN (...)` predicate within the window):

```json
{
  "filter": {
    "window_start": "2026-05-01T00:00:00Z",
    "window_end": "2026-05-10T00:00:00Z",
    "status": ["failed"],
    "error_kind": ["http_5xx", "timeout"],
    "max_attempts": 3,
    "max_count": 1000,
    "invocation_ids": ["uuid-1", "uuid-2"]
  }
}
```

The time window is required because `hog_invocation_results` is partitioned by `toYYYYMMDD(scheduled_at)` — without it the query would scan every live partition. The window is also capped at the table's TTL (30 days) so the user can't ask for data that's already been part-dropped.

The view validates, then proxies through to a new `replay_hog_invocations(team_id, function_kind, function_id, payload)` helper in `posthog/plugins/plugin_server_api.py`.

**The replay endpoint does not run the replay** — it only enqueues a wrapper job onto a new `replay` queue in the cyclotron-v2 job database, then returns the `replay_job_id` immediately:

```json
{ "replay_job_id": "<uuid>", "queued_count": 0, "skipped_count": 0 }
```

The new `cdp-replay-worker` service (PLUGIN_SERVER_MODE=cdp-replay-worker) consumes that queue and runs the actual work:

1. **Dequeue** a wrapper job and parse the `ReplayJobState` blob from `state BYTEA`.
2. **Page ClickHouse** for one batch of `REPLAY_PAGE_SIZE` matching invocations within the time window, using a keyset cursor on `(scheduled_at, invocation_id)`. `invocation_ids` (if present) becomes one more `AND invocation_id IN (...)` predicate inside the same query.
3. **Rehydrate** each row from `invocation_globals` (rebuilding `inputs` from the current hog function config + integration store) and **re-enqueue** onto the regular cyclotron queue via the cyclotron-v2 upsert path (`overwriteExisting: true`). Set `state.replayAttempts = (row.attempts ?? 0) + 1`. Emit the `'running'` lifecycle row.
4. **If the v2 upsert refuses an id** (existing row still in 'available' / 'running' state — see #4 in audit), the manager raises `CyclotronJobConflictError`; the paginator logs a warning, counts those ids as `skipped`, and drops the pre-queued running row for them.
5. **If done** (page partial, budget exhausted) → `ack()` the wrapper job.
6. **Otherwise** → `reschedule({ state: nextState, scheduledAt: now + REPLAY_PAGE_DELAY_MS })` so the worker picks it back up after a short delay with the new cursor + counts.

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

## Future features (not v1, worth tracking)

- **Adaptive page-size optimiser for the replay paginator.** Each `processPage` call ought to record (a) how long the ClickHouse fetch took, (b) the byte size of the returned rows, and (c) the rehydrate+enqueue duration. Feed those into a slow-start-style controller that ramps `REPLAY_PAGE_SIZE` up while we're well under our target latency / memory budget and ramps it down on overshoot. Today it's a fixed 200 — fine for the median case, too small for a clean window of 50 KiB rows, way too big for a window full of 500 KiB rows.
- **Sparkline UI on the runs view.** Same shape as the logs sparkline: bucketed counts over time, click-and-drag to zoom into a window, click a bucket / stack segment to filter the row list to that status (running/succeeded/failed). The HogQL query is already cheap once the table is partitioned by date.
- **"Replay all matching this filter" UI affordance.** The wrapper-job pipeline already supports it server-side — we just need the UI to send `{ filter: {...} }` (with the same status/error_kind/max_attempts/max_count knobs the list view uses) instead of a specific `invocation_ids` list. Should include a confirm-step with the matched count + a server-side `max_count` cap to keep one click from queuing millions of replays.
- **In-progress replay job status in the UI.** Today the `/replay` endpoint returns a `replay_job_id` and that's the last the UI hears about it. Add a polling endpoint (Django → Node proxy, same shape as the existing replay endpoint) that takes `replay_job_id` and returns the wrapper job's current `state` (queued/skipped counts, cursor, done, last_error). The UI shows a progress bar / "X of Y replayed" indicator and surfaces partial progress + errors as they accumulate, rather than the user having to refresh the runs list and guess.

## Secrets handling

`invocation_globals` does **not** contain the resolved `inputs` bundle. `HogInvocationResultsService` strips every `inputs` key it finds anywhere in the persisted state tree before serialization (top-level for hog functions, nested under `currentAction.hogFunctionState.globals.inputs` for hog flows). On replay, the worker calls `HogInputsService.buildInputsWithGlobals(hogFunction, persistedGlobals)` to re-derive inputs from the current hog function config + integration store. This means:

- API keys, OAuth tokens, and other templated input values are never stored in ClickHouse, and never leave Kafka in plaintext.
- A replay always uses the **current** input config and the **current** integration secrets, not a stale snapshot. If a token was rotated since the original invocation ran, the replay picks up the new token.
- If a hog function was deleted or disabled since the original run, `getHogFunction` returns null and the replay skips that row (counted as `skipped_count`).

## Tests

Per-service unit tests + an end-to-end test that mirrors the shape of `cdp-e2e.test.ts`.

- `nodejs/src/cdp/services/monitoring/hog-invocation-results.service.test.ts` — covers feature-flag gating, the running/succeeded/failed row shapes, `inputs` stripping (including the secret-not-anywhere-in-blob check), error-kind classification, version monotonicity, the invocation_id partition key, and that mid-flight results produce no row.
- `nodejs/src/cdp/replay/replay-job.manager.test.ts` — exercises `ReplayJobManager.enqueue` against the local cyclotron postgres (`test_cyclotron_node`), asserts the row lands with `queue_name='replay'` and the right `state` payload.
- `nodejs/src/cdp/replay/replay-paginator.service.test.ts` — covers both `by-ids` and `by-filter` modes against a mocked ClickHouse client, plus the done/cursor-advance logic and the input re-resolution branch.
- `nodejs/src/cdp/consumers/cdp-replay-worker.consumer.test.ts` — covers the ack-on-done vs reschedule-on-partial branches, malformed state handling, and the heartbeat plumbing.
- `nodejs/src/cdp/replay/replay-e2e.test.ts` — full pipeline. Insert N invocations through `CdpCyclotronWorker` (some failing on purpose), observe the lifecycle rows landing on the Kafka topic (via `KafkaProducerObserver`), then POST `/replay` for the failed window and watch the replay-worker drain the wrapper job, re-enqueue invocations, and produce a fresh batch of `succeeded` lifecycle rows. Mirrors the pattern in `cdp-e2e.test.ts`.

## Audit follow-ups (uncovered by writing the tests — now resolved)

Items #1–#6 below were gaps surfaced while writing the end-to-end test. All six are now resolved in this branch; entries are kept for context on what was wrong before and why each fix looks the way it does.

### 1. ✅ Events consumer emits the `'running'` lifecycle row once at invocation creation

Confirmed via `rpk topic consume`: previously no `'running'` row was ever produced for the original invocation, only the terminal one. The worker's existing `queueInvocationResults(results)` filters out non-terminal results.

The intuitive fix would be "emit at worker dequeue" — but the worker dequeues a single `invocation_id` multiple times across fetch retries / async continuations, so that path emits N running rows for one logical run. Fixed instead by emitting the running row ONCE in `CdpEventsConsumer.processBatch`, right after we build the list of invocations to enqueue and before `cyclotronJobQueue.queueInvocations`. Flushed as part of the existing background-task `Promise.all` so the running row hits Kafka in parallel with the cyclotron enqueue.

### 2. ✅ Introduced `state.replayAttempts`, separate from the fetch-retry counter

`invocation.state.attempts` is the **fetch retry** counter and the executor resets it to 0 between runs ([hog-executor.service.ts:718](nodejs/src/cdp/services/hog-executor.service.ts#L718)). Resolved by adding a sibling `state.replayAttempts` field on `CyclotronJobInvocationHogFunctionContext`. The replay paginator sets it on rehydration (`(row.attempts ?? 0) + 1`); the executor never touches it. The lifecycle row producer reads `replayAttempts` (default 0) into the row's `attempts` column.

### 3. ✅ `is_retry` is now derived inside `queueLifecycleRow` from `state.replayAttempts > 0`

Resolved alongside #2: `queueLifecycleRow` now does `is_retry: replayAttempts > 0 ? 1 : 0`. Dropped the `{ isRetry: true }` option from the call site signature entirely — call sites only pass `(invocation, status, { error?, startedAt?, finishedAt? })`. The schema column is kept (no migration churn), but every row whose `attempts > 0` automatically gets `is_retry = 1`, which means the worker's terminal row on a replayed run correctly carries `is_retry=1` for free without the worker needing to know it's a replay.

### 4. ✅ Cyclotron-v2 supports a guarded upsert for replay re-enqueue

Added `overwriteExisting?: boolean` to the `CyclotronV2JobInitSchema`. When set:

- The SQL becomes `INSERT ... ON CONFLICT (id) DO UPDATE SET status='available', scheduled=EXCLUDED.scheduled, state=EXCLUDED.state, lock_id=NULL, last_heartbeat=NULL, last_transition=EXCLUDED.last_transition, transition_count=cyclotron_jobs.transition_count+1, ... WHERE cyclotron_jobs.status IN ('completed', 'failed', 'canceled')`.
- The `WHERE` guard means the upsert only fires if the existing row is in a terminal state. If it's still active ('available' / 'running'), the UPDATE is a no-op and the row isn't returned via RETURNING. The manager surfaces those as a `CyclotronJobConflictError` listing the conflicting ids — the replay paginator catches that error, logs a warning, counts each id as `skipped`, and drops the corresponding pre-queued `'running'` lifecycle row from the in-memory queue so we don't leave a stale running marker for an invocation that didn't actually re-enqueue.

The replay paginator routes through `cyclotronJobQueue.queueInvocations(invocations, { overwriteExisting: true })` which forces the v2 path regardless of the default producer mapping. The e2e test correspondingly runs with `CDP_CYCLOTRON_JOB_QUEUE_PRODUCER_MAPPING='*:postgres-v2'` end-to-end. Deployment caveat: any environment that wants the replay flow needs the cyclotron worker configured to consume from `postgres-v2`.

### 5. ✅ Shared `ClickhouseConfig` interface composed into service configs

Extracted [`nodejs/src/common/clickhouse-config.ts`](nodejs/src/common/clickhouse-config.ts) with `ClickhouseConfig` type + `getDefaultClickhouseConfig()` (which picks `posthog_test` as the database in test env so node-side test consumers don't silently connect to the empty `default` DB). `CdpConfig` is now `ClickhouseConfig & { ... }` and `getDefaultCdpConfig()` spreads `getDefaultClickhouseConfig()` first. `SessionRecordingApiConfig` does the same. The replay worker reads `this.config.CLICKHOUSE_HOST` etc. against properly-typed fields with sane defaults — no more silent `http://undefined:8123` connection.

### 6. ✅ `duration_ms` was being serialized as a fractional float, rejected by the Kafka MV

`timings[i].duration_ms` comes from `perf.now()` deltas and is fractional (e.g. `0.37995799999771407`). ClickHouse's `Nullable(UInt32)` Kafka JSONEachRow parser rejected the row outright. Fixed by `Math.round`ing in `sumDurationMs`.

### 7. ✅ Unified replay request schema; always require a time window

The original request shape was an XOR: provide either `invocation_ids` OR `filter`. By-IDs queries against `hog_invocation_results` had no time filter — so CH had to scan every live partition. Even worse, "missing" ids stuck around in `progress.remaining_ids` and got re-queried every page.

New schema: a single required `filter` with mandatory `window_start` / `window_end`, plus an OPTIONAL `invocation_ids` list inside the same filter object as one more `AND invocation_id IN (...)` predicate. Both Django (`HogInvocationReplayFilterSerializer`) and Node (`ReplayJobManager.enqueue`) reject windows longer than the ClickHouse TTL (30 days, `REPLAY_MAX_WINDOW_DAYS`) — pointing the query at older partitions is meaningless because the data is already gone. Cursor + done logic collapsed to one path; the paginator no longer has separate by-ids and by-filter query methods or separate `remaining_ids` bookkeeping.

## E2E test status

`nodejs/src/cdp/replay/replay-e2e.test.ts` exercises the full path with real Kafka, real ClickHouse Kafka MV, real cyclotron postgres, real cyclotron worker, and real replay wrapper-job loop. The only mock is `mockFetch` for outbound HTTP; the call to `ReplayJobManager.enqueue` stands in for the Django POST. **The test passes locally.** All 41 unit + e2e tests across 5 suites are green.

Two non-code workarounds the test currently uses:

- It stubs out the `CdpEventsConsumer.kafkaConsumer` (the test calls `processBatch` directly, so the Kafka consumer doesn't need to join the group — and joining trips a stale-group-protocol error on local Redpanda).
- It deletes the prior `cyclotron_jobs` row before triggering replay (workaround for #4).

The assertion on the replayed lifecycle rows is `count() >= 2` rather than verifying the specific `running` / `is_retry=1` row — that's because the local Redpanda + ClickHouse Kafka MV combination doesn't always flush every message in the same poll cycle (the `running` row is reliably present in the Kafka topic but only sometimes appears in the MV-fed table). The paginator's running-row emit is verified deterministically by the paginator unit test instead.

## Risks worth tracking

1. **Row volume.** Two rows per invocation × every event that matches a function × every team × 30 days. We should pull a back-of-envelope estimate from current `app_metrics2` totals before turning the producer on globally. Mitigation: feature-flag the producer per team, ramp.
2. **Payload size in `invocation_globals`.** A full hog function invocation's globals can be tens of KiB once person properties are flattened. ZSTD compresses this well in practice (often 4–8×), but if a small number of teams send enormous events, we may want a hard cap (e.g. truncate `invocation_globals` past 256 KiB and set a flag column so replay can refuse / warn). Not implementing v1 — measure first.
3. **Replay storms.** A user can replay a million rows. Server-side cap on `max_count` plus per-team rate-limiting on the replay endpoint. Audit-log the trigger.
4. **Tenant isolation.** `team_id` is on every row and first in `ORDER BY`. HogQL resolver auto-filters, same as `events`. Standard PostHog convention.
5. **History after replay.** Because ReplacingMergeTree collapses by `invocation_id`, prior failed attempts are no longer visible from this table after a successful replay. The full per-attempt history lives in `log_entries` (different rows per attempt because the worker logs per-attempt). Acceptable v1.
