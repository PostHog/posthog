# Exposure preaggregation

This document explains how exposure preaggregation works to speed up experiment queries.

## The problem

Every time an experiment query runs, it scans the events table to find all users who were exposed to the experiment. This is the "exposures" CTE built by `_build_exposure_select_query()` in `experiment_query_builder.py`:

```sql
SELECT
    person_id AS entity_id,
    argMin(properties.$feature_flag_response, timestamp) AS variant,
    min(timestamp) AS first_exposure_time,
    max(timestamp) AS last_exposure_time,
    argMin(uuid, timestamp) AS exposure_event_uuid,
    argMin($session_id, timestamp) AS exposure_session_id
FROM events
WHERE event = '$feature_flag_called'
    AND properties.$feature_flag = 'my-experiment-flag'
    AND timestamp >= '2026-01-01'
    AND timestamp < '2026-01-15'
GROUP BY person_id
```

This query scans millions of events and groups by millions of users. If the experiment results page is viewed 10 times, this same expensive scan runs 10 times.

## The solution

Compute the exposures once and store them. Subsequent queries read from the stored results instead of scanning events.

---

## Data flow

### Step 1: Query runner starts

`ExperimentQueryRunner` is created with an experiment ID. It loads the experiment configuration:

```python
# From experiment_query_runner.py
self.experiment = Experiment.objects.get(id=self.query.experiment_id)
self.feature_flag = self.experiment.feature_flag
self.variants = [variant["key"] for variant in self.feature_flag.variants]
self.date_range = get_experiment_date_range(self.experiment, self.team, self.override_end_date)
```

---

### Step 2: Check for preaggregated exposures

Before building the exposures CTE, call `ensure_preaggregated()` with the exposures SELECT query:

```python
from products.analytics_platform.backend.lazy_preaggregation.lazy_preaggregation_executor import (
    ensure_preaggregated,
)

preagg_result = ensure_preaggregated(
    team=self.team,
    insert_query="""
        SELECT
            {entity_key} AS entity_id,
            {variant_expr} AS variant,
            min(timestamp) AS first_exposure_time,
            max(timestamp) AS last_exposure_time,
            argMin(uuid, timestamp) AS exposure_event_uuid,
            argMin(`$session_id`, timestamp) AS exposure_session_id,
            [] AS breakdown_value,
            now() + INTERVAL 6 HOUR AS expires_at
        FROM events
        WHERE event = '$feature_flag_called'
            AND properties.`$feature_flag` = {feature_flag_key}
            AND properties.`$feature_flag_response` IN {variants}
            AND timestamp >= {time_window_min}
            AND timestamp < {time_window_max}
        GROUP BY {entity_key}
    """,
    time_range_start=self.date_range.date_from,
    time_range_end=self.date_range.date_to,
    ttl_seconds=6 * 60 * 60,
    placeholders={
        "entity_key": ast.Constant(value="person_id"),
        "variant_expr": ...,  # Built from _build_variant_expr_for_mean()
        "feature_flag_key": ast.Constant(value=self.feature_flag.key),
        "variants": ast.Constant(value=self.variants),
    },
)
```

The `{time_window_min}` and `{time_window_max}` placeholders are required. They get filled in automatically by the preaggregation system for each time window.

---

### Step 3: Compute query hash

`ensure_preaggregated()` computes a hash from the query structure:

```python
# From lazy_preaggregation_executor.py
hash_input = {
    "query": repr(query_ast),
    "timezone": team.timezone,
    "breakdown_fields": [...],
}
query_hash = sha256(hash_input)  # e.g., "a1b2c3d4e5f6..."
```

Two queries with the same hash can share preaggregated data. Different feature flags, variants, or filters produce different hashes.

---

### Step 4: Find existing jobs in PostgreSQL

```python
# From lazy_preaggregation_executor.py
PreaggregationJob.objects.filter(
    team=team,
    query_hash=query_hash,
    time_range_start__lt=end,
    time_range_end__gt=start,
    status__in=[PreaggregationJob.Status.READY, PreaggregationJob.Status.PENDING],
).filter(
    expires_at__gte=now() + timedelta(hours=1)  # 1 hour buffer before expiry
)
```

Example result: Jobs covering Jan 1-10 exist, but Jan 11-15 is missing.

---

### Step 5: Create job for missing time range

```python
# From lazy_preaggregation_executor.py
PreaggregationJob.objects.create(
    team=team,
    query_hash=query_hash,
    time_range_start=datetime(2026, 1, 11),
    time_range_end=datetime(2026, 1, 15),
    status=PreaggregationJob.Status.PENDING,
    expires_at=now() + timedelta(hours=6),
)
```

---

### Step 6: Run INSERT into ClickHouse

The preaggregation system wraps the SELECT query in an INSERT statement and executes it:

```sql
INSERT INTO experiment_exposures_preaggregated (
    team_id, job_id, entity_id, variant, first_exposure_time,
    last_exposure_time, exposure_event_uuid, exposure_session_id,
    breakdown_value, expires_at
)
SELECT
    123 AS team_id,                              -- added automatically
    'job-uuid-123' AS job_id,                    -- added automatically
    person_id AS entity_id,
    argMin(properties.$feature_flag_response, timestamp) AS variant,
    min(timestamp) AS first_exposure_time,
    max(timestamp) AS last_exposure_time,
    argMin(uuid, timestamp) AS exposure_event_uuid,
    argMin($session_id, timestamp) AS exposure_session_id,
    [] AS breakdown_value,
    now() + INTERVAL 6 HOUR AS expires_at
FROM events
WHERE event = '$feature_flag_called'
    AND properties.$feature_flag = 'my-experiment-flag'
    AND properties.$feature_flag_response IN ['control', 'test']
    AND timestamp >= '2026-01-11 00:00:00'       -- time_window_min
    AND timestamp < '2026-01-15 00:00:00'        -- time_window_max
GROUP BY person_id
```

---

### Step 7: Mark job as ready

```python
# From lazy_preaggregation_executor.py
job.status = PreaggregationJob.Status.READY
job.computed_at = now()
job.save()
```

---

### Step 8: Return job IDs

```python
# ensure_preaggregated() returns:
PreaggregationResult(
    ready=True,
    job_ids=['job-uuid-for-jan-1-10', 'job-uuid-for-jan-11-15']
)
```

---

### Step 9: Build experiment query using preaggregated data

Instead of scanning the events table, the exposures CTE reads from the preaggregated table:

```sql
-- Before (expensive):
WITH exposures AS (
    SELECT person_id, argMin(...), min(timestamp), ...
    FROM events
    WHERE event = '$feature_flag_called' AND ...
    GROUP BY person_id
)

-- After (fast):
WITH exposures AS (
    SELECT entity_id, variant, first_exposure_time, last_exposure_time, ...
    FROM experiment_exposures_preaggregated
    WHERE job_id IN ('job-uuid-for-jan-1-10', 'job-uuid-for-jan-11-15')
        AND first_exposure_time >= '2026-01-01 09:57:00'  -- exact experiment start
        AND first_exposure_time < '2026-01-15 14:30:00'   -- exact experiment end
)
```

The `job_id IN (...)` filter ensures we only read our preaggregated data. The time filters ensure we respect the exact experiment start/end times, even though preaggregation uses daily windows.

---

### Step 10: Rest of query runs normally

The rest of the experiment query (metric_events CTE, entity_metrics CTE, final aggregation) works exactly the same. Only the exposures CTE source changes.

```sql
WITH exposures AS (
    -- now reads from preaggregated table
    ...
),

metric_events AS (
    SELECT ...
    FROM events
    WHERE event = 'purchase_completed'
    ...
),

entity_metrics AS (
    SELECT
        exposures.entity_id,
        exposures.variant,
        sum(...) AS value
    FROM exposures
    LEFT JOIN metric_events
        ON exposures.entity_id = metric_events.person_id
        AND metric_events.timestamp >= exposures.first_exposure_time
    GROUP BY exposures.entity_id, exposures.variant
)

SELECT
    variant,
    count() AS num_users,
    sum(value) AS total_sum,
    ...
FROM entity_metrics
GROUP BY variant
```

---

## Key files

| File                              | Purpose                                                             |
| --------------------------------- | ------------------------------------------------------------------- |
| `experiment_query_runner.py`      | Orchestrates experiment query execution                             |
| `experiment_query_builder.py`     | Builds the SQL query, including `_build_exposure_select_query()`    |
| `lazy_preaggregation_executor.py` | Core preaggregation logic: `ensure_preaggregated()`, job management |
| `models/preaggregation_job.py`    | PostgreSQL model for tracking preaggregation jobs                   |

---

## Important notes

1. **Time precision**: Preaggregation uses daily windows for job management, but stores full timestamp precision. The final query filters to exact experiment start/end times.

2. **Query hash determines cache sharing**: Different feature flags, variants, or exposure criteria produce different hashes. Each experiment typically has its own preaggregated data.

3. **TTL and expiration**: Jobs have an `expires_at` field. The system ignores jobs expiring within 1 hour to avoid race conditions. ClickHouse TTL automatically deletes expired rows.

4. **Fallback**: If preaggregation fails or isn't ready, the query falls back to computing exposures from the events table directly.
