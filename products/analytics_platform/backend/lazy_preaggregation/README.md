
# Lazy preaggregation

Lazy preaggregation speeds up queries by saving and reusing intermediate aggregated results. Instead of scanning the raw events table on every query, we compute aggregated data once and reuse it for subsequent queries with the same shape.

## How it works

There's 2 ways that this can work

* Automatically transforming HogQL queries
* Manual API for query runners to consume

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

Let's say that you are writing a query runner for e.g. web analytics, and you want to preaggregate a specific set of data which is too complex
to automatically transform, you can provide the transformed query to the executor and have it run the necessary INSERTs to cover the time range.

```python

# ensure that the given query is preaggregated 
preagg_result = executor.ensure_preaggregated(parse_select("""
SELECT
    toStartOfHour(session_start) as time_window_start,
    count() as num_sessions,
    sum(pageview_count) as pageview_count,
    uniqState(person_id) as num_persons,
    avgState(session_duration) as avg_duration,
    avgState(is_bounce) as bounce_rate
    FROM (
        SELECT 
        any(session.$start_timestamp) as session_start,
        any(person_id) as person_id,
        any(duration) as session_duration,
        any(session.$is_bounce) as is_bounce
        FROM events
        WHERE and(
            timestamp >= {time_window_min},
            timestamp <= dateAdd({time_window_max}, toIntervalDay(1)),
            session.$start_timestamp >= {time_window_min},
            session.$start_timestamp <= {time_window_max},
            {internal_test_user_filters}
        )
    )
    GROUP BY time_window_start
    HAVING and(time_window_start >= {time_window_min}, time_window_start <={time_window_max})
"""),
    time_window_min="2025-12-18",
    time_window_max="2025-12-25",
    ttl_seconds = 24 * 60 * 60,
    preagg_table = "web_preagg", # different teams might want to add their own table design
    placeholders = {"internal_test_user_filters": _get_filters(self.team)} # time_window_min and time_window_max are added automatically
)

# then you can query from this table directly
query = parse_select('''
select
    avgMerge(bounce_rate),
    toStartOfDay(time_window_start) as day
FROM web_preagg
WHERE and(
    time_window_start >= {time_window_min},
    time_window_start <= {time_window_max},
    in(job_id, {job_ids})
)
GROUP BY day
''',
    placeholders = {
        "job_ids": preagg_result.job_ids,
        "time_window_min": "2025-12-18",
        "time_window_max": "2025-12-25"
    }
)

```

## Limitations

* Automatic transformation only supports very specific query patterns
* Person merges and late-arriving events can cause stale data
* Running the executor and then reading back the results takes about 30% longer than just reading results
* Storing intermediate results take space, we can't just YOLO this
