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
3. **Find existing jobs**: Look up which time ranges already have precomputed data in Postgres
4. **Compute missing ranges**: For any missing date ranges, run INSERT queries to populate the precomputed table in ClickHouse
5. **Transform the query**: Rewrite the original query to read from the precomputed table using aggregate merge functions

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
from products.analytics_platform.backend.lazy_computation.lazy_computation_executor import ensure_precomputed, ComputationTable
from posthog.hogql import ast

# Ensure that the given query is precomputed with variable TTLs
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
        "0d": 15 * 60,           # current day: 15 min
        "1d": 60 * 60,            # previous day: 1 hour
        "7d": 24 * 60 * 60,       # last week: 1 day
        "default": 7 * 24 * 60 * 60,  # older: 7 days
    },
    table=ComputationTable.PREAGGREGATION_RESULTS,
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

The executor handles concurrent queries that need the same precomputed data.

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

## Limitations

- Automatic transformation only supports very specific query patterns
- Person merges and late-arriving events can cause stale data
- Running the executor and then reading back the results takes about 30% longer than just reading results
- Storing intermediate results takes space, we can't just YOLO this

## TODOs

- While we are waiting, we block an entire django thread despite not doing any useful work. We should make it easier for people to use e.g. celery with this, this would involve using async queries though.
- The stale enum value isn't used for anything, we just mark stale jobs as errored
- Add posthog logging for state transitions
