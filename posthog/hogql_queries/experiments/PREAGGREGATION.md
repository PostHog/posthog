# Exposure preaggregation

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

This scans millions of events. If the experiment results page is viewed 10 times, this same scan runs 10 times. Preaggregation computes the exposures once, stores them, and subsequent queries read from the stored results.

---

## Data flow

### Step 1: Query runner starts

`ExperimentQueryRunner` is created with an experiment ID. It loads the experiment configuration:

```python
self.experiment = Experiment.objects.get(id=self.query.experiment_id)
self.feature_flag = self.experiment.feature_flag
self.variants = [variant["key"] for variant in self.feature_flag.variants]
self.date_range = get_experiment_date_range(self.experiment, self.team, self.override_end_date)
```

---

### Step 2: Ensure exposures are preaggregated

The runner calls `_ensure_exposures_preaggregated()` which gets the exposure query template from the builder and passes it to the preaggregation system:

```python
def _ensure_exposures_preaggregated(self, builder: ExperimentQueryBuilder) -> PreaggregationResult:
    query_string, placeholders = builder.get_exposure_query_for_preaggregation()

    date_from = self.experiment.start_date
    date_to = self.override_end_date or self.experiment.end_date or datetime.now(UTC)

    return ensure_preaggregated(
        team=self.team,
        insert_query=query_string,
        time_range_start=date_from,
        time_range_end=date_to,
        ttl_seconds=DEFAULT_EXPOSURE_TTL_SECONDS,
        table=PreaggregationTable.EXPERIMENT_EXPOSURES_PREAGGREGATED,
        placeholders=placeholders,
    )
```

The query template uses `{time_window_min}` and `{time_window_max}` placeholders that the preaggregation system fills in for each time window. Other placeholders (entity_key, variant_expr, etc.) are returned in a dict and passed through.

---

### Step 3: Compute query hash

`ensure_preaggregated()` computes a stable hash from the query structure:

```python
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
query_hash = sha256(hash_input)
```

Time placeholders are replaced with fixed sentinels before hashing, so the hash doesn't change when the time range changes. This allows reuse of previously computed windows. Different feature flags, variants, or filters produce different hashes.

---

### Step 4: Find existing jobs

```python
PreaggregationJob.objects.filter(
    team=team,
    query_hash=query_hash,
    time_range_start__lt=end,
    time_range_end__gt=start,
    status__in=[PreaggregationJob.Status.READY, PreaggregationJob.Status.PENDING],
).filter(
    expires_at__gte=now() + timedelta(hours=1)
)
```

Example: jobs covering Jan 1-10 exist, but Jan 11-15 is missing.

---

### Step 5: Create job for missing time range

```python
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

The preaggregation system wraps the SELECT query in an INSERT and executes it:

```sql
INSERT INTO experiment_exposures_preaggregated (
    team_id, job_id, entity_id, variant, first_exposure_time,
    last_exposure_time, exposure_event_uuid, exposure_session_id,
    breakdown_value, expires_at
)
SELECT
    123 AS team_id,
    'job-uuid-123' AS job_id,
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
    AND timestamp >= '2026-01-11 00:00:00'
    AND timestamp < '2026-01-15 00:00:00'
GROUP BY person_id
```

`team_id` and `job_id` are prepended automatically. The time range comes from the job's window.

---

### Step 7: Mark job as ready

```python
job.status = PreaggregationJob.Status.READY
job.computed_at = now()
job.save()
```

---

### Step 8: Return job IDs

```python
PreaggregationResult(
    ready=True,
    job_ids=['job-uuid-for-jan-1-10', 'job-uuid-for-jan-11-15']
)
```

---

### Step 9: Build experiment query using preaggregated data

`_build_exposure_from_preaggregated(job_ids)` in the builder reads from the preaggregated table instead of scanning events:

```sql
SELECT
    t.entity_id AS entity_id,
    argMin(t.variant, t.first_exposure_time) AS variant,
    min(t.first_exposure_time) AS first_exposure_time,
    max(t.last_exposure_time) AS last_exposure_time,
    argMin(t.exposure_event_uuid, t.first_exposure_time) AS exposure_event_uuid,
    argMin(t.exposure_session_id, t.first_exposure_time) AS exposure_session_id
FROM experiment_exposures_preaggregated AS t
WHERE t.job_id IN ('job-uuid-for-jan-1-10', 'job-uuid-for-jan-11-15')
    AND t.team_id = 123
GROUP BY t.entity_id
```

The `GROUP BY` with `argMin`/`min`/`max` is needed because a user can appear in multiple jobs. For example, if exposures were preaggregated in two phases (Jan 1-10, then Jan 11-15), a user with events in both windows has a row in each job. The re-aggregation merges them into one row per user. This is cheap — the preaggregated table has one row per user per job, so even with multiple jobs the data volume is small.

This method returns the same columns as `_build_exposure_select_query()`, so the rest of the experiment query works unchanged regardless of which path produced the exposures.

---

### Step 10: Rest of query runs normally

Only the exposures CTE source changes. The metric_events CTE, entity_metrics CTE, and final aggregation are identical:

```sql
WITH exposures AS (
    -- reads from preaggregated table (step 9)
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

| File                                                          | Purpose                                                                                                                                                                                       |
| ------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `experiment_query_runner.py`                                  | Orchestrates experiment query execution, including `_ensure_exposures_preaggregated()`                                                                                                        |
| `experiment_query_builder.py`                                 | Builds the SQL query: `_build_exposure_select_query()` (events scan), `_build_exposure_from_preaggregated()` (preaggregated read), `get_exposure_query_for_preaggregation()` (write template) |
| `lazy_preaggregation_executor.py`                             | Core preaggregation logic: `ensure_preaggregated()`, job management                                                                                                                           |
| `models/preaggregation_job.py`                                | PostgreSQL model for tracking preaggregation jobs                                                                                                                                             |
| `hogql/database/schema/experiment_exposures_preaggregated.py` | HogQL schema for the preaggregated ClickHouse table                                                                                                                                           |

---

## Notes

1. **Time precision**: Preaggregation uses daily windows for job management, but stores full timestamp precision. The final query filters to exact experiment start/end times.

2. **Query hash determines cache sharing**: Different feature flags, variants, or exposure criteria produce different hashes. Each experiment typically has its own preaggregated data.

3. **TTL and expiration**: Jobs have an `expires_at` field. The system ignores jobs expiring within 1 hour to avoid race conditions. ClickHouse TTL automatically deletes expired rows.

4. **Fallback**: If preaggregation fails or isn't ready, the query falls back to scanning the events table directly.

5. **Future: GROUP BY (entity_id, variant)**: Currently the query groups by entity_id only and resolves the variant during preaggregation (e.g., argMin for first-seen). This bakes the variant handling strategy into the stored data, so switching between "first seen" and "exclude multiple" requires recomputation. A better approach is to GROUP BY (entity_id, variant) so we store one row per user-variant pair, then resolve multiple variants at query time.
