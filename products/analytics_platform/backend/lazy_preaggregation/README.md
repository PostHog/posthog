# Lazy preaggregation

Lazy preaggregation speeds up queries by saving and reusing intermediate aggregated results. Instead of scanning the raw events table on every query, we compute aggregated data once and reuse it for subsequent queries with the same shape.

This is intended to be used for our most important queries by our biggest customers. It runs against our ClickHouse and Postgres databases — some of the largest in the world — and the design takes that into account.

## How it works

There are two ways that this can work:

- Automatically transforming HogQL queries
- Manual API for query runners to consume

### Automatic HogQL transformation

1. **Pattern detection**: Traverse the AST, check if any SELECT clause matches a supported pattern (e.g., daily unique persons for pageviews)
2. **Hash the query**: Compute a stable hash from the query structure, timezone, and other settings (excluding the time range for the query)
3. **Find existing jobs**: Look up which time ranges already have preaggregated data in Postgres
4. **Compute missing ranges**: For any missing date ranges, run INSERT queries to populate the preaggregation table in ClickHouse
5. **Transform the query**: Rewrite the original query to read from the preaggregation table using aggregate merge functions

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

If you are writing a query runner (e.g., for web analytics) and want to preaggregate a specific set of data which is too complex to automatically transform, you can provide the query string to the executor and have it run the necessary INSERTs to cover the time range.

The query must use `{time_window_min}` and `{time_window_max}` placeholders - these are automatically substituted with the correct time range for each job.

```python
from datetime import datetime
from products.analytics_platform.backend.lazy_preaggregation.lazy_preaggregation_executor import ensure_preaggregated, PreaggregationTable
from posthog.hogql import ast

# Ensure that the given query is preaggregated
preagg_result = ensure_preaggregated(
    team=self.team,
    insert_query="""
        SELECT
            toStartOfHour(timestamp) as time_window_start,
            now() + INTERVAL 1 DAY as expires_at,
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
    ttl_seconds=24 * 60 * 60,
    table=PreaggregationTable.PREAGGREGATION_RESULTS,
    # Custom placeholders can be passed too
    placeholders={"some_filter": ast.Constant(value="filter_value")},
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
        "job_ids": ast.Tuple(exprs=[ast.Constant(value=str(jid)) for jid in preagg_result.job_ids]),
        "time_start": ast.Constant(value=datetime(2025, 12, 18)),
        "time_end": ast.Constant(value=datetime(2025, 12, 25)),
    },
)
# note that this is using HogQL, which automatically adds a team_id condition
```

## Concurrency and race conditions

The executor handles concurrent queries that need the same preaggregated data.

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

Each waiter tracks their own attempt count locally. After a configurable number of failures (default 2), the waiter stops retrying and reports the job as permanently failed. This means new queries get fresh attempt budgets, so newer queries may succeed where older ones gave up.

### Stale pending jobs

If an executor crashes while a job is PENDING, other waiters detect this via Redis-based ClickHouse liveness checks (no PG queries needed). The detection has two stages:

1. **CH INSERT not started**: Each executor sets a Redis key (`preagg:ch_started:{job_id}`) before running the INSERT. If this key doesn't exist and the job is older than the grace period (default 60s), it's considered stale — the executor likely crashed before reaching the INSERT.

2. **CH INSERT started but heartbeat expired**: `poll_query_performance` sets a heartbeat key with a 10s TTL for every active ClickHouse query. If the CH start marker exists but the heartbeat key has expired and the job is older than the stale threshold (default 60s), the query is no longer running and the job is stale.

Stale jobs are marked FAILED and the normal replacement flow kicks in. This means we can recover from crashes of the process we were waiting for.

## Limitations

- Automatic transformation only supports very specific query patterns
- Person merges and late-arriving events can cause stale data
- Running the executor and then reading back the results takes about 30% longer than just reading results
- Storing intermediate results takes space, we can't just YOLO this

## TODOs

- While we are waiting, we block an entire django thread despite not doing any useful work. We should make it easier for people to use e.g. celery with this, this would involve using async queries though.
- The TTL of an inserted job should be conditional on how recent the data is. Data from the same day might want a very short (e.g. 15 mins!) TTL, or to be skipped entirely and UNION'ed with real data, which we could make a bit easier.
- The stale enum value isn't used for anything, we just mark stale jobs as errored
- Add posthog logging for state transitions
