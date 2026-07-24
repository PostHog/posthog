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

The `ttl_seconds` parameter accepts either an `int` (uniform TTL) or a `dict` mapping date strings to TTL values in seconds. Dict keys are parsed using `relative_date_parse` with the team's timezone:

- `"0d"` — cutoff at start of today: windows from today onward match
- `"1d"` — cutoff at start of yesterday: windows from yesterday onward match
- `"7d"` — cutoff 7 days ago: windows from last week onward match
- `"24h"` — cutoff 24 hours ago
- `"2w"` — cutoff 2 weeks ago
- `"2026-02-15"` — cutoff at a specific date
- `"default"` — fallback TTL for windows older than all cutoffs

Rules are matched most-specific first (shortest period wins). On the **read path**, existing jobs that are too stale for the requested TTL are skipped and recomputed. On the **write path**, each job is created with the TTL appropriate for its date range — ranges with different TTLs are never merged into a single job.

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
3. One succeeds (gets the new job), the other gets an IntegrityError
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

## Stale-while-revalidate

The executor's default behavior is "compute inline": a request that finds an expired window rebuilds it synchronously (Postgres bookkeeping, Redis coordination, a ClickHouse INSERT) before reading — which puts multi-second rebuilds on the user's request thread the moment a TTL lapses. Stale-while-revalidate (RFC 5861) trades that for freshness lag: serve the complete-but-stale rows that already exist, and refresh them in the background.

The mechanism is split into a framework half and a product half.

### The serve half (framework)

`LazyComputationExecutor(stale_while_revalidate_seconds=...)` — also exposed as the same kwarg on `ensure_precomputed` — is the grace window. When a request would otherwise compute inline or block on another executor's PENDING job, and READY jobs that expired **within the last N seconds** still fully cover the range, the executor returns them immediately with `stale=True` on the result. Nothing is recomputed; whoever refreshes next (the revalidation task, a warmer, or a request after the grace) replaces the data, and `filter_overlapping_jobs` always prefers the newer jobs.

Two invariants:

- The grace must stay **well under `EXPIRY_BUFFER_SECONDS` (48h)** — ClickHouse rows outlive their PG job by that buffer, so a larger grace would return job IDs whose rows were already TTL-deleted. The constructor enforces this.
- Coverage is checked on the overlap-filtered job set that would actually be returned, not the raw set — a newer narrow job can evict an older broad one and reopen a gap.

`run_inserts=False` (check-only mode) is the stricter sibling for user-facing reads: the request is either served from covering READY jobs (fresh, or stale within the grace) or told `ready=False` immediately. It never creates jobs, never runs INSERTs, and never waits on someone else's PENDING job — the caller falls back to its live query and leaves construction to background triggers.

### The revalidate half (products)

Serving stale is only safe when something actually refreshes the data afterwards, and that part is product-owned. Each product wires three things:

1. **Grace resolution** — `stale_policy.resolve_stale_while_revalidate_seconds(grace, own_triggers)` hands the grace to user-facing reads and `None` to anything that _is_ a refresh mechanism. This rule is deliberately centralized: a background refresher that gets served its own stale rows persists them as a fresh result and never recomputes — the data freezes rather than merely lagging. Refreshers are recognized by the `CACHE_WARMUP` feature tag (the product-agnostic gate) plus the product's own warming trigger names.
2. **Marking** — when an ensure returns `stale=True`, the read path calls `stale_policy.mark_served_stale()`. That tags the read's ClickHouse queries (`precompute_stale` in `system.query_log`) and feeds the response stamp below. A lazy read that fails _after_ marking (e.g. the compare period misses and the whole read falls back to live) must call `clear_served_stale()` so the fresh fallback isn't mislabeled.
3. **Revalidation** — a stale serve enqueues a debounced background re-run of the query (a Celery task tagged with the product's own revalidation trigger, so it never takes the grace itself), replacing both the precompute jobs and the query-result cache entry. The framework's PENDING-job unique index collapses concurrent recomputes to one INSERT.

Web analytics (`web_lazy_precompute_common.py`, trigger `webAnalyticsStaleRevalidation`) and marketing analytics (`marketing_lazy_precompute.py`, trigger `marketingAnalyticsStaleRevalidation`, gated by the `marketing-analytics-serve-stale` flag) are the two existing incarnations — read them before wiring a third.

### Telling the requester

A stale-served response is correct but old, and a fresh version is already being computed — the requester should be able to know that. Runners stamp `preComputeStale=True` on responses built from a stale-served read (`stale_policy.was_served_stale()`), alongside the existing `preComputeStrategy` field. Clients can treat it as "data is stale; a background revalidation is in flight; refetching shortly will return fresh data". Served-fresh responses omit the field entirely.

Two follow-ups to this surface are sketched in § TODOs below: a `preComputeAgeSeconds` field (how stale, not just whether) and an automatic frontend refetch when `preComputeStale` is set.

## Observability

Each invocation of the executor emits both a structured log and Prometheus counters. The executor-level counter answers "is the caller getting served"; the job-level counters answer "are PG jobs flowing as fast as we're creating them".

### Prometheus

#### Executor-level

`lazy_computation_executions_total` is incremented once per `executor.execute()` call, with labels:

| label         | values                                                                                         |
| ------------- | ---------------------------------------------------------------------------------------------- |
| `outcome`     | `success`, `timeout`, `non_retryable_error`, `max_retries_exceeded`, `stale_hit`, `check_miss` |
| `cache_state` | `hit`, `partial_hit`, `miss` — see below                                                       |
| `table`       | the lazy table being populated (e.g. `preaggregation_results`)                                 |

The serve-stale outcomes (see § Stale-while-revalidate):

- `stale_hit` — the request was served from expired-within-grace READY jobs instead of recomputing (`result.stale=True`). Always `cache_state="hit"` — serving existing rows is doing no new work.
- `check_miss` — check-only mode (`run_inserts=False`) found no servable coverage and told the caller to go live. `cache_state` records whether any fresh READY data existed (`partial_hit`) or none did (`miss`).

#### Job-level

Jobs run synchronously inside `execute()` — there is no background queue, so PENDING just means "an INSERT is in flight in some pod". A periodic gauge of `status='pending'` rows misses jobs that started and finished between scrapes and tells you nothing about throughput. These two counters fire at the exact PG status transitions instead:

- `lazy_computation_jobs_created_total{cache_state, table}` — one increment every time a PENDING row is inserted (one per missing range per executor). The loser of a partial-unique-index race (`IntegrityError`) does **not** increment, so the count matches PG row inserts. `cache_state` mirrors the executor-level label so a job created during a fresh execute() call lands on `miss` and a top-up job filling a hole in pre-existing READY data lands on `partial_hit`. `hit` never appears because hits don't create anything.
- `lazy_computation_jobs_finished_total{outcome, table}` — one increment every time a job reaches a terminal status.

`outcome` values:

- `ready` — INSERT succeeded, PENDING → READY.
- `failed` — INSERT raised (retryable or non-retryable), PENDING → FAILED.
- `stale` — a waiter detected the owning executor crashed (`_try_mark_stale_job_as_failed`) and the atomic update flipped the row to FAILED.

Net job throughput (positive = backlog growing, expected ~0 in steady state):

```promql
sum(rate(lazy_computation_jobs_created_total[5m]))
  -
sum(rate(lazy_computation_jobs_finished_total[5m]))
```

Failure share per table:

```promql
sum by (table) (rate(lazy_computation_jobs_finished_total{outcome=~"failed|stale"}[5m]))
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
- The stale enum value isn't used for anything, we just mark stale jobs as errored
- Add posthog logging for state transitions
- Surface `preComputeAgeSeconds` alongside `preComputeStale` — how stale, not just whether. Only a boolean crosses the response boundary today, but the executor already knows each served job's `computed_at`, so the serve-stale path could put the oldest one on `LazyComputationResult` and runners could stamp `preComputeAgeSeconds` next to the flag. That lets the UI say "data as of 25 minutes ago" instead of showing a bare indicator, and lets API clients pace refetches by actual staleness instead of a guessed delay. Wiring notes for whoever picks this up:
  - Extend `mark_served_stale()` to accept the age and keep the **max** across a request's ensures (current + compare period; marketing's touchpoints/conversions/costs) — the oldest served data wins.
  - A lazy read that fails after marking must drop the age together with the stale mark (`clear_served_stale()`), for the same don't-mislabel-the-fallback reason.
  - Deliberately parked until a concrete consumer wants it — don't add the field speculatively.
- Auto-refetch on `preComputeStale` in the frontend. The flag's contract makes this safe: by the time a client sees it, a debounced background revalidation is already enqueued (web gives it a ~20s head start) and will replace both the precompute jobs and the HogQL result cache entry, so a refetch shortly after usually lands on fresh data. The shape that fits:
  - In `dataNodeLogic`, when a response carries `preComputeStale`, schedule **one** silent `loadData` roughly 60–90s later, using a cache-respecting refresh mode (`blocking` / `async_except_on_cache_miss`) — not `force_*`, which skips the very cache entry the revalidation refreshes and recomputes instead.
  - If the refetch still comes back with `preComputeStale`, stop — the revalidation may have failed and the serve-stale grace (hours) is the ceiling; looping only adds load.
  - Debounce per query key, cancel on unmount or a user-initiated refresh, and consider gating behind a flag: this roughly doubles read volume for stale serves, which is a product call.
