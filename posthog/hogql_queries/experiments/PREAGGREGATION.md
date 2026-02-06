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
from posthog.hogql_queries.experiments.experiment_exposures_preaggregation import (
    ensure_experiment_exposures_preaggregated,
)

preagg_result = ensure_experiment_exposures_preaggregated(
    team=self.team,
    feature_flag_key=self.feature_flag.key,
    variants=self.variants,
    entity_math="persons",
    multiple_variant_handling=MultipleVariantHandling.FIRST_SEEN,
    filter_test_accounts=False,
    date_from=self.date_range.date_from,
    date_to=self.date_range.date_to,
)
```

Under the hood, this builds a HogQL query with `{time_window_min}` and `{time_window_max}` placeholders that get filled in automatically by the preaggregation system for each time window.

See `experiment_exposures_preaggregation.py` for the full query template and placeholder details.

---

### Step 3: Compute query hash

`ensure_preaggregated()` computes a hash from the query structure:

```python
# From lazy_preaggregation_executor.py
# Before hashing, time placeholders are replaced with fixed sentinel values
# so the hash is stable regardless of the time range being queried.
hash_placeholders = {
    **base_placeholders,
    "time_window_min": ast.Constant(value="__TIME_WINDOW_MIN__"),
    "time_window_max": ast.Constant(value="__TIME_WINDOW_MAX__"),
}
parsed_for_hash = parse_select(insert_query, placeholders=hash_placeholders)

hash_input = {
    "query": repr(parsed_for_hash),
    "timezone": team.timezone,
    "breakdown_fields": [...],
}
query_hash = sha256(hash_input)  # e.g., "a1b2c3d4e5f6..."
```

Two queries with the same hash can share preaggregated data. Different feature flags, variants, or filters produce different hashes. Changing the time range does **not** change the hash — this is what allows reuse of previously computed daily windows.

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
    today() + INTERVAL 1 DAY AS expires_at
FROM events
WHERE event = '$feature_flag_called'
    AND properties.$feature_flag = 'my-experiment-flag'
    AND properties.$feature_flag_response IN ('control', 'test')
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
    -- job_id already scopes data to the right time range
    -- additional time filters may be added depending on the final implementation
)
```

The `job_id IN (...)` filter ensures we only read our preaggregated data.

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

5. **Future: GROUP BY (entity_id, variant)**: Currently the query groups by entity_id only and resolves the variant during preaggregation (e.g., argMin for first-seen). This bakes the variant handling strategy into the stored data, so switching between "first seen" and "exclude multiple" requires recomputation. A better approach is to GROUP BY (entity_id, variant) so we store one row per user-variant pair, then resolve multiple variants at query time. This makes the preaggregated data reusable regardless of which variant handling the user picks.
