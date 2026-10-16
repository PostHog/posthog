# Lazy computation

Lazy computation speeds up queries by saving and reusing intermediate computed results. Instead of scanning the raw events table on every query, we compute aggregated data once and reuse it for subsequent queries with the same shape.

This is intended to be used for our most important queries by our biggest customers. It runs against our ClickHouse and Postgres databases — some of the largest in the world — and the design takes that into account.

## How it works

There are two ways that this can work:

- Automatically transforming HogQL queries
- Manual API for query runners to consume

### Automatic HogQL transformation

1. **Pattern detection**: Traverse the AST, check if any SELECT clause matches a supported pattern (e.g., daily unique persons for pageviews)
2. **Hash the query**: Compute a stable hash from the query structure, timezone, and other settings (excluding the time range for the query)
3. **Find existing jobs**: Look up which time ranges already have lazy-computed data in Postgres
4. **Compute missing ranges**: For any missing date ranges, run INSERT queries to populate the lazy-computed table in ClickHouse
5. **Transform the query**: Rewrite the original query to read from the lazy-computed table using aggregate merge functions

The transformation is invisible to the caller. A query like:

```sql
SELECT uniqExact(person_id)
FROM events
WHERE event = '$pageview'
  AND timestamp >= '2024-01-01'
  AND timestamp < '2024-02-01'
GROUP BY toStartOfDay(timestamp)
```

Gets transformed to:

```sql
SELECT uniqExactMerge(uniq_exact_state)
FROM preaggregation_results
WHERE job_id IN (...)
  AND time_window_start >= '2024-01-01'
  AND time_window_start < '2024-02-01'
GROUP BY time_window_start
```

### Manual API

If you are writing a query runner (e.g., for web analytics) and want to precompute a specific set of data which is too complex to automatically transform, you can provide the query string to the executor and have it run the necessary INSERTs to cover the time range.

The query must use `{time_window_min}` and `{time_window_max}` placeholders - these are automatically substituted with the correct time range for each job.

```python
from datetime import datetime
from products.analytics_platform.backend.lazy_computation.lazy_computation_executor import (
    ensure_precomputed,
    LazyComputationTable,
)
from posthog.hogql import ast

# Ensure that the given query is lazy-computed with variable TTLs
result = ensure_precomputed(
    team=self.team,
    insert_query="""
        SELECT
            toStartOfHour(timestamp) as time_window_start,
            [] as breakdown_value,
            uniqExactState(person_id) as uniq_exact_state
        FROM events
        WHERE event = '$pageview'
            AND timestamp >= {time_window_min}
            AND timestamp < {time_window_max}
        GROUP BY time_window_start
    """,
    time_range_start=datetime(2025, 12, 18),
    time_range_end=datetime(2025, 12, 25),
    # Variable TTL: recent data refreshes more often
    ttl_seconds={
        "0d": 15 * 60,  # current day: 15 min
        "1d": 60 * 60,  # previous day: 1 hour
        "7d": 24 * 60 * 60,  # last week: 1 day
        "default": 7 * 24 * 60 * 60,  # older: 7 days
    },
    table=LazyComputationTable.PREAGGREGATION_RESULTS,
    # Custom placeholders can be passed too
    placeholders={"some_filter": ast.Constant(value="filter_value")},
)

# A single int TTL still works for uniform expiry
result = ensure_precomputed(
    team=self.team,
    insert_query="...",
    time_range_start=datetime(2025, 12, 18),
    time_range_end=datetime(2025, 12, 25),
    ttl_seconds=24 * 60 * 60,  # 1 day for all ranges
)

# Then query from this table directly using the job_ids
# Note: You still need to filter by time range since jobs may cover a wider period
# e.g., job covers all of January but you only want the first week
query = parse_select(
    """
    SELECT
        uniqExactMerge(uniq_exact_state) as unique_users,
        toStartOfDay(time_window_start) as day
    FROM preaggregation_results
    WHERE job_id IN {job_ids}
        AND time_window_start >= {time_start}
        AND time_window_start < {time_end}
    GROUP BY day
    """,
    placeholders={
        "job_ids": ast.Tuple(exprs=[ast.Constant(value=str(jid)) for jid in result.job_ids]),
        "time_start": ast.Constant(value=datetime(2025, 12, 18)),
        "time_end": ast.Constant(value=datetime(2025, 12, 25)),
    },
)
# note that this is using HogQL, which automatically adds a team_id condition
```

### Variable TTL

The `ttl_seconds` parameter accepts an `int` (uniform TTL), a `dict` mapping date strings to TTL values in seconds, or a prebuilt `TtlSchedule` (see below). Dict keys are parsed using `relative_date_parse` with the team's timezone:

- `"0d"` — cutoff at start of today: windows from today onward match
- `"1d"` — cutoff at start of yesterday: windows from yesterday onward match
- `"7d"` — cutoff 7 days ago: windows from last week onward match
- `"24h"` — cutoff 24 hours ago
- `"2w"` — cutoff 2 weeks ago
- `"2026-02-15"` — cutoff at a specific date
- `"default"` — fallback TTL for windows older than all cutoffs

Rules are matched most-specific first (shortest period wins). On the **read path**, existing jobs that are too stale for the requested TTL are skipped and recomputed. On the **write path**, each job is created with the TTL appropriate for its date range — ranges with different TTLs are never merged into a single job.

### TTL schedules

`TtlSchedule` (in `lazy_computation_executor.py`) is the parsed form of a TTL spec.
Build one with `parse_ttl_schedule(ttl, team_timezone, ...)` and pass it as `ttl_seconds` when you need more than per-band TTLs.
`ensure_precomputed` uses a passed schedule as is.
In that case it ignores its own `empty_result_ttl_seconds` and `empty_result_max_age_seconds` kwargs, so set those on the schedule instead.

```python
schedule = parse_ttl_schedule(
    {"0d": 4 * 60 * 60, "1d": 6 * 60 * 60, "default": 7 * 24 * 60 * 60},
    team.timezone,
    max_window_days=7,
    settling_period_seconds=24 * 60 * 60,
)
result = ensure_precomputed(
    team=team,
    insert_query="...",
    time_range_start=start,
    time_range_end=end,
    ttl_seconds=schedule,
)
```

| Field                          | What it does                                                                                                                                                                                                                                                                                          |
| ------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `max_window_days`              | Caps how many days `split_ranges_by_ttl` merges into one job, independent of TTL bands. Use it to bound the GROUP BY of a single INSERT. `None` leaves job width uncapped.                                                                                                                            |
| `settling_period_seconds`      | How long after `time_range_end` the window's data can still change. A job computed before `time_range_end + settling_period` is fresh only until that moment, so it recomputes once the data is final instead of keeping an in-motion snapshot for a long band TTL.                                   |
| `invalidate_at_window_start`   | Rejects a job computed before its window started once the window start passes, even within the stale grace. Use it when you warm future windows in advance.                                                                                                                                           |
| `empty_result_ttl_seconds`     | Caps the TTL of a job whose INSERT wrote zero rows. Use it for sources that can lag (data warehouse tables), where empty can mean "not synced yet". Leave it unset for event tables, where empty means empty. The job counters label these jobs `ready_empty`.                                        |
| `empty_result_max_age_seconds` | Limits the empty-result cap to windows whose end is at most this old when the job is computed. Older empty windows keep their full band TTL.                                                                                                                                                          |
| `default_ttl_jitter_seconds`   | Adds a stable per-window offset in `[0, jitter)` to the `default` band TTL, so windows built on the same day do not all expire together. The offset comes from the window start date, so a rebuild gets the same offset. Use it only for immutable data. Rule-matched (recent) windows get no jitter. |

All TTL values must be positive; `parse_ttl_schedule` raises `ValueError` otherwise.

### Freshness and expiry

Each job carries two clocks, and they come from different callers:

- **`expires_at`** is stamped once, by the caller that creates the job: creation time plus that caller's band TTL for the window (`create_lazy_computation_job`).
  `find_existing_jobs` drops every job past its `expires_at`, so no reader can use a job beyond the creator's TTL.
  ClickHouse keeps the rows `EXPIRY_BUFFER_SECONDS` (48 hours) longer, so reads already in flight still find their data.
- **Freshness** is judged by each reader, as `created_at` plus the reader's own TTL for the window (`LazyComputationExecutor._filter_by_freshness`).
  The settling period and `invalidate_at_window_start` of the reader's schedule apply here too.
  A reader with a stricter schedule rejects a job that a more lenient creator made, and builds a replacement.

There is no force-rebuild or refresh-ahead parameter.
A builder that wants to rebuild a window before its TTL runs out uses a shorter TTL for that window, because a shorter TTL makes the existing job stale for that builder.
The shorter TTL also stamps a shorter `expires_at` on the job it builds, so other readers lose that job sooner.
Readers bridge the gap between expiry and the next build with stale-while-revalidate.

### Stale-while-revalidate

`stale_while_revalidate_seconds` follows the HTTP `stale-while-revalidate` directive (RFC 5861).
When a request would otherwise build inline or wait on another executor's PENDING job, the executor looks for READY jobs that expired at most N seconds ago.
If those jobs cover the whole range, it returns them at once with `stale=True` and logs the outcome `stale_hit`.
The caller then has to trigger a background rebuild, or it serves stale data until the grace runs out.

- The value must stay below `EXPIRY_BUFFER_SECONDS`, because ClickHouse deletes the rows after that buffer. The executor raises `ValueError` otherwise.
- A background refresher must never take the grace. A refresher that gets its own stale rows does not recompute them, so nothing refreshes again.
- Use `stale_policy.resolve_stale_while_revalidate_seconds(grace, extra_triggers)` to pick the value. It returns `None` for refreshers and the grace for user reads.
- `stale_policy.is_background_warming_request` treats a request as a refresher when it carries the `CACHE_WARMUP` feature tag or a known warmer trigger (`SHARED_BACKGROUND_WARMING_TRIGGERS`, plus the product's own triggers).

### Check-only mode

`run_inserts=False` makes the call read-only.
It never creates a job and never waits on a PENDING one.
The result is `ready=True` when fresh READY jobs (or stale ones within the grace) cover the range.
Otherwise it is `ready=False` at once, with the outcome `check_miss`.
Use it on user-facing paths that have a live fallback and build in the background instead.

### Other `ensure_precomputed` options

| Kwarg                   | Use it to                                                                                                                                                                                                                                       |
| ----------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `sentinel_placeholders` | Keep a placeholder value out of the job hash. Name placeholders whose values change per request (for example a `now()` value). They hash as fixed sentinels and get their real values at INSERT time. Each name must also be in `placeholders`. |
| `modifiers`             | Set the HogQL modifiers used to print the INSERT. Modifiers are **not** part of the job hash.                                                                                                                                                   |
| `cache_key_context`     | Version result semantics that the substituted AST does not show, such as a result-changing modifier. It goes into the job hash, so a new value starts a new set of jobs. Omit it when empty so existing jobs keep matching.                     |
| `end_is_data_horizon`   | Clamp the last job's claim to `time_range_end` when the INSERT bakes that end into its own filters. Applies only to an end on a past UTC day. Leave it `False` when the INSERT fills whole days, or every distinct `end` creates a new job.     |
| `read_after_write`      | Set `False` when nothing reads the rows in the same request (background builders). It skips the replica-quorum wait. `result.freshly_built` then tells the caller not to read the new jobs in the same request.                                 |
| `spill_to_disk`         | Let a large GROUP BY spill to disk instead of failing with a memory error. Opt in for high-cardinality INSERTs.                                                                                                                                 |
| `insert_settings`       | Override ClickHouse settings on every INSERT. Applied last, over the defaults and `spill_to_disk`.                                                                                                                                              |
| `database`              | Pass a prebuilt HogQL `Database` so each INSERT does not rebuild the team's schema. Build it once per team, with the same `modifiers`.                                                                                                          |
| `wait_timeout_seconds`  | Set the wall-clock budget for the build-and-wait loop (default 180 seconds). The loop checks it before each INSERT and while waiting. Completed windows stay READY even when the call times out.                                                |
| `query_type`            | Tag each INSERT in `system.query_log` so its cost is attributable to a query family.                                                                                                                                                            |

### The result

`ensure_precomputed` returns a `LazyComputationResult`:

| Field             | Meaning                                                                                                                                               |
| ----------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| `ready`           | `True` when READY jobs cover the whole range. The executor never returns partial coverage.                                                            |
| `job_ids`         | The jobs to read, after overlap filtering keeps the newest job for each window. Always filter the read by time range too, because a job can be wider. |
| `stale`           | `True` when the jobs came from the stale-while-revalidate grace. Trigger a background rebuild.                                                        |
| `memory_exceeded` | `True` when an INSERT failed with a ClickHouse memory limit error. Callers use it to cap later INSERTs, for example with `max_window_days`.           |
| `freshly_built`   | `True` when some coverage landed during this call. A caller with `read_after_write=False` must not read these jobs in the same request.               |
| `computed_at`     | The oldest `computed_at` across the served jobs, for a "data as of" label. `None` when nothing was served.                                            |
| `errors`          | Error messages from failed attempts.                                                                                                                  |

### Non-retryable errors

Some ClickHouse errors fail the call at once instead of using the retry budget (`NON_RETRYABLE_CLICKHOUSE_ERROR_CODES`).
They include query errors (syntax, unknown identifiers, type mismatches), `TIMEOUT_EXCEEDED`, and `TOO_MANY_SIMULTANEOUS_QUERIES`.
Two of them matter most for sizing:

- **`MEMORY_LIMIT_EXCEEDED`**: a retry with the same window adds load to a cluster that is already out of memory. The result sets `memory_exceeded=True`.
- **`TOO_MANY_ROWS_OR_BYTES`** (the read-byte cap): the data does not shrink between attempts, so a retry fails the same way.

The caller falls back to its live path and can narrow later windows.

### Invalidating stored precompute

Staff can invalidate a team's stored precompute with `POST /api/projects/:id/precompute_debug/invalidate/` (`PrecomputeDebugViewSet.invalidate` in `products/analytics_platform/backend/api/precompute_debug.py`).

- It marks the team's READY jobs as STALE, so the next build pass for each window computes it again.
- Pass `query_hash` to limit it to one hash.
- PENDING jobs stay as they are. The response counts them as `pending_count`, because a job that started before a source resync can still finish with old data. Invalidate again once they finish.
- Use it after the underlying data changes, for example after a data warehouse resync.

`GET .../precompute_debug/state/` on the same viewset lists the stored hashes, their buckets, and their TTLs.

## Concurrency and race conditions

The executor handles concurrent queries that need the same lazy-computed data.

### Waiting for pending jobs

When query B requests data that query A is already computing, query B waits for A to finish rather than creating duplicate work. The executor subscribes to Redis pubsub channels for each pending job and wakes up instantly when a job completes (configurable timeout, default 3 minutes). This reduces PG polling — PG is queried on initial entry, after inserts, and on wake-up from notifications or pubsub timeouts.

### One INSERT per job ID

Each job ID is used for exactly one INSERT statement. This is critical because if a job fails partway through, we can't know what data was or wasn't inserted. Retrying with the same job ID could result in duplicate or inconsistent data.

### Race condition: multiple waiters, job fails

When a job fails, multiple waiters may all try to create a replacement job simultaneously. We use a partial unique index on `(team_id, query_hash, time_range_start, time_range_end) WHERE status = 'pending'` to ensure only one PENDING job can exist per range. The database atomically enforces this:

1. Job A fails
2. Waiters B and C both try to create a replacement
3. One succeeds (gets the new job); the other's `INSERT .. ON CONFLICT DO NOTHING` is a silent no-op (`create_lazy_computation_job` returns `None`)
4. The loser finds the winner's job and waits for it

### Replacement jobs use the same range

When creating a replacement for a failed job, we use the exact same time range as the failed job (not the original query's range). This ensures all waiters coordinate on the same replacement, even if they originally requested overlapping but different ranges.

### Attempt tracking

Each waiter tracks their own failure count locally. After a configurable number of retries (default 1, meaning 2 total attempts), the waiter stops retrying and reports the job as permanently failed. This means new queries get fresh attempt budgets, so newer queries may succeed where older ones gave up.

### Stale pending jobs

If an executor crashes while a job is PENDING, other waiters detect this via Redis-based ClickHouse liveness checks (no PG queries needed). The detection has two stages:

1. **CH INSERT not started**: Each executor sets a Redis key (`preagg:ch_started:{job_id}`) before running the INSERT. If this key doesn't exist and the job is older than the grace period (default 60s), it's considered stale — the executor likely crashed before reaching the INSERT.

2. **CH INSERT started but heartbeat expired**: `poll_query_performance` sets a heartbeat key with a 60s TTL for every active ClickHouse query. If the CH start marker exists but the heartbeat key has expired and the job is older than the stale threshold (default 60s), the query is no longer running and the job is stale.

Stale jobs are marked FAILED and the normal replacement flow kicks in. This means we can recover from crashes of the process we were waiting for.

## Observability

Each invocation of the executor emits both a structured log and Prometheus counters. The executor-level counter answers "is the caller getting served"; the job-level counters answer "are PG jobs flowing as fast as we're creating them".

### Prometheus

#### Executor-level

`lazy_computation_executions_total` is incremented once per `executor.execute()` call, with labels:

| label         | values                                                                                         |
| ------------- | ---------------------------------------------------------------------------------------------- |
| `outcome`     | `success`, `stale_hit`, `check_miss`, `timeout`, `non_retryable_error`, `max_retries_exceeded` |
| `cache_state` | `hit`, `partial_hit`, `miss` — see below                                                       |
| `table`       | the lazy table being populated (e.g. `preaggregation_results`)                                 |

#### Job-level

Jobs run synchronously inside `execute()` — there is no background queue, so PENDING just means "an INSERT is in flight in some pod". A periodic gauge of `status='pending'` rows misses jobs that started and finished between scrapes and tells you nothing about throughput. These two counters fire at the exact PG status transitions instead:

- `lazy_computation_jobs_created_total{cache_state, table}` — one increment every time a PENDING row is inserted (one per missing range per executor). The loser of a partial-unique-index race does **not** increment, so the count matches PG row inserts. `cache_state` mirrors the executor-level label so a job created during a fresh execute() call lands on `miss` and a top-up job filling a hole in pre-existing READY data lands on `partial_hit`. `hit` never appears because hits don't create anything.
- `lazy_computation_job_create_conflicts_total{table}` — one increment every time a create is skipped because a PENDING row already holds the `unique_pending_job_per_range` slot. A steady background rate is expected (the warmers and SWR revalidation race on the same windows by design); a sustained elevated rate means writers piling onto the same windows, or a PENDING row past its own `expires_at` blocking a window it no longer serves. Each conflict also emits a `lazy_computation.job_create_conflict` structured log with `team_id`, `query_hash`, and the window, which is the only place the colliding values appear now that the insert no longer raises a Postgres error.
- `lazy_computation_jobs_finished_total{outcome, table}` — one increment every time a job reaches a terminal status.

`outcome` values:

- `ready` — INSERT succeeded and wrote rows, PENDING → READY.
- `ready_empty` — INSERT succeeded but wrote no rows, PENDING → READY. Still a success; split out because an empty window is only provisionally computed (see `TtlSchedule.empty_result_ttl_seconds`), so a climbing share here points at a lagging source rather than a broken query.
- `failed` — INSERT raised (retryable or non-retryable), PENDING → FAILED.
- `stale` — a waiter detected the owning executor crashed (`_try_mark_stale_job_as_failed`) and the atomic update flipped the row to FAILED.
- `expired` — a create conflict found the blocking PENDING row past its own `expires_at` and flipped it to FAILED (`_try_fail_expired_pending_job`), unblocking the window. Like `stale`, each increment means an executor died earlier without cleanup.

Sum `ready` and `ready_empty` for total successes, and prefer `outcome=~"failed|stale|expired"` over `outcome!="ready"` when alerting — the latter counts empty-but-successful jobs as problems.

Net job throughput (positive = backlog growing, expected ~0 in steady state):

```promql
sum(rate(lazy_computation_jobs_created_total[5m]))
  -
sum(rate(lazy_computation_jobs_finished_total[5m]))
```

Failure share per table:

```promql
sum by (table) (rate(lazy_computation_jobs_finished_total{outcome=~"failed|stale|expired"}[5m]))
  /
sum by (table) (rate(lazy_computation_jobs_finished_total[5m]))
```

Average miss size (jobs per full-miss execution — answers "when we miss, how much do we end up computing?"):

```promql
sum(rate(lazy_computation_jobs_created_total{cache_state="miss"}[5m]))
  /
sum(rate(lazy_computation_executions_total{cache_state="miss"}[5m]))
```

Average partial-hit top-up size (jobs per partial-hit execution):

```promql
sum(rate(lazy_computation_jobs_created_total{cache_state="partial_hit"}[5m]))
  /
sum(rate(lazy_computation_executions_total{cache_state="partial_hit"}[5m]))
```

`cache_state` values:

- `hit` — the request did no new work (no jobs created, no waits).
- `partial_hit` — the request had to do work but found pre-existing READY data.
- `miss` — the request had to do work and found no pre-existing data.

Full hit ratio across a window:

```promql
sum(rate(lazy_computation_executions_total{cache_state="hit"}[5m]))
  /
sum(rate(lazy_computation_executions_total[5m]))
```

Any-coverage ratio (`hit` or `partial_hit`):

```promql
sum(rate(lazy_computation_executions_total{cache_state=~"hit|partial_hit"}[5m]))
  /
sum(rate(lazy_computation_executions_total[5m]))
```

Per-table breakdown of failures:

```promql
sum by (table, outcome) (
  rate(lazy_computation_executions_total{outcome!="success"}[5m])
)
```

### Structured log

The `lazy_computation.executed` log line carries the same `outcome`, `cache_state`, and `table` fields plus per-call detail (`query_hash`, `jobs_created`, `jobs_waited_for`, `total_duration_ms`, `time_range_days`). Useful when you need to follow a specific request rather than aggregate.

## Limitations

- Automatic transformation only supports very specific query patterns
- Person merges and late-arriving events can cause stale data
- Running the executor and then reading back the results takes about 30% longer than just reading results
- Storing intermediate results takes space, we can't just YOLO this

## TODOs

- While we are waiting, we block an entire django thread despite not doing any useful work. We should make it easier for people to use e.g. celery with this, this would involve using async queries though.
- Crashed PENDING jobs are marked FAILED, not STALE. Only the staff invalidate endpoint sets STALE.
- Add posthog logging for state transitions
