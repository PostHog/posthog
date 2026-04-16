# Funnel metric events precomputation

## Problem

An experiment funnel query has three CTEs: `exposures`, `metric_events`, and `entity_metrics`. The `exposures` CTE is already precomputed (see `LAZY_COMPUTATION.md`). The `metric_events` CTE still scans the events table on every query:

```sql
metric_events AS (
    SELECT
        person_id AS entity_id,
        properties.$feature_flag_response AS variant,
        timestamp,
        uuid,
        properties.$session_id AS session_id,
        step_0,  -- 1 if this is an exposure event, else 0
        step_1,  -- 1 if this matches funnel step 1, else 0
        step_2   -- 1 if this matches funnel step 2, else 0
    FROM events
    WHERE (exposure_predicate OR funnel_steps_filter)
)
```

This scans every event that matches the exposure criteria OR any funnel step (e.g. `pageview`, `purchase`). For high-traffic experiments, this is millions of rows — and it runs on every query.

## Solution

Scan the events table once, store matching events in `experiment_metric_events_preaggregated`, and read from there on subsequent queries.

## What gets stored

One row per matching event. The step indicators are packed into an `Array(UInt8)`:

```text
┌──────────┬──────────┬───────────┬─────────────────────┬───────────┬────────────┬───────────┐
│ team_id  │ job_id   │ entity_id │ timestamp           │ event_uuid│ session_id │ steps     │
├──────────┼──────────┼───────────┼─────────────────────┼───────────┼────────────┼───────────┤
│ 123      │ job-A    │ user-1    │ 2026-01-02 10:00:00 │ evt-111   │ sess-1     │ [1, 0, 0] │  ← exposure
│ 123      │ job-A    │ user-1    │ 2026-01-02 11:00:00 │ evt-222   │ sess-1     │ [0, 1, 0] │  ← pageview
│ 123      │ job-A    │ user-1    │ 2026-01-02 12:00:00 │ evt-333   │ sess-1     │ [0, 0, 1] │  ← purchase
│ 123      │ job-A    │ user-2    │ 2026-01-02 14:00:00 │ evt-444   │ sess-2     │ [1, 0, 0] │  ← exposure
│ 123      │ job-A    │ user-2    │ 2026-01-02 15:00:00 │ evt-555   │ sess-2     │ [0, 1, 0] │  ← pageview
│ ...      │          │           │                     │           │            │           │
└──────────┴──────────┴───────────┴─────────────────────┴───────────┴────────────┴───────────┘
```

`steps = [1, 0, 0]` means: this event matches step_0 (exposure) but not step_1 or step_2.

## Data flow

### Without precomputation

```text
┌────────────────────────────────┐
│         events table           │
│       (millions of rows)       │
└───────┬───────────────┬────────┘
        │               │
        │ scan for      │ scan for pageview,
        │ exposures     │ purchase, etc.
        │               │
        ▼               ▼
  exposures CTE   metric_events CTE ◄── THIS IS THE EXPENSIVE PART
        │               │
        └───────┬───────┘
                │ LEFT JOIN
                ▼
        entity_metrics CTE
        (aggregate_funnel_array UDF)
                │
                ▼
          Final result
```

### With precomputation

```text
  FIRST QUERY (precomputes):

  events table ──scan──▶ experiment_metric_events_preaggregated
                         (stores matching events with step indicators)


  SUBSEQUENT QUERIES (reads from cache):

  ┌─────────────────────────┐    ┌───────────────────────────────────┐
  │ experiment_exposures    │    │ experiment_metric_events          │
  │ _preaggregated          │    │ _preaggregated                   │
  │ (already cached)        │    │ (newly cached)                   │
  └──────────┬──────────────┘    └────────────────┬──────────────────┘
             │                                    │
             ▼                                    ▼
       exposures CTE                      metric_events CTE
             │                                    │
             └──────────┬─────────────────────────┘
                        │ LEFT JOIN
                        ▼
                entity_metrics CTE        ← same UDF, same logic
                        │
                        ▼
                  Final result            ← identical output
```

## How it works

### Write path: `get_funnel_metric_events_query_for_precomputation()`

The builder produces a query template with `{time_window_min}` and `{time_window_max}` placeholders:

```sql
SELECT
    person_id AS entity_id,
    timestamp AS timestamp,
    uuid AS event_uuid,
    `$session_id` AS session_id,
    [toUInt8(if(exposure_pred, 1, 0)),
     toUInt8(if(step_1_pred, 1, 0)),
     toUInt8(if(step_2_pred, 1, 0))] AS steps
FROM events
WHERE timestamp >= {time_window_min}
    AND timestamp < {time_window_max}
    AND (exposure_predicate OR funnel_steps_filter)
```

The lazy computation system (`ensure_precomputed()`) splits the experiment date range into daily windows, fills in the time placeholders, and wraps the SELECT in an INSERT:

```sql
INSERT INTO experiment_metric_events_preaggregated
    (team_id, job_id, entity_id, timestamp, event_uuid, session_id, steps, expires_at)
SELECT
    123 AS team_id,
    'job-uuid' AS job_id,
    ... -- the SELECT from above
```

Each daily window becomes a separate job. Already-computed windows are skipped.

### Read path: `_build_funnel_query_legacy()`

When `metric_events_preaggregation_job_ids` is set, the metric_events CTE reads from the precomputed table instead of scanning events:

```sql
metric_events AS (
    SELECT
        toUUID(t.entity_id) AS entity_id,
        t.timestamp AS timestamp,
        t.event_uuid AS uuid,
        t.session_id AS session_id,
        arrayElement(t.steps, 1) AS step_0,
        arrayElement(t.steps, 2) AS step_1,
        arrayElement(t.steps, 3) AS step_2
    FROM experiment_metric_events_preaggregated AS t
    WHERE t.job_id IN ('job-A', 'job-B')
        AND t.team_id = 123
)
```

`arrayElement(t.steps, N)` extracts individual step indicators from the packed array. The rest of the query (entity_metrics CTE, `aggregate_funnel_array` UDF, final aggregation) is unchanged.

### Wiring: `_get_experiment_query()`

The runner orchestrates both precomputations:

```python
if should_precompute and not is_data_warehouse_query:
    # 1. Precompute exposures (already existed)
    result = self._ensure_exposures_precomputed(builder)
    if result.ready:
        builder.preaggregation_job_ids = result.job_ids

    # 2. Precompute metric events (new — ordered funnels only)
    if is_ordered_funnel:
        result = self._ensure_metric_events_precomputed(builder)
        if result.ready:
            builder.metric_events_preaggregation_job_ids = result.job_ids
```

Both use the same lazy computation system (daily windows, job management, TTL).

## Conversion window

Funnel steps can occur after the experiment end date (within the conversion window). Example: experiment ends Jan 15, conversion window is 7 days, a purchase on Jan 20 still counts.

The runner extends `time_range_end` by the conversion window when precomputing metric events:

```python
date_to = experiment.end_date + timedelta(seconds=conversion_window_seconds)
```

The exposure precomputation does NOT need this extension — exposures only occur within the experiment date range.

## Key differences from exposure precomputation

|                            | Exposures                              | Metric events                              |
| -------------------------- | -------------------------------------- | ------------------------------------------ |
| **Granularity**            | 1 row per user per job                 | 1 row per event per job                    |
| **Re-aggregation on read** | Yes — `argMin`/`min`/`max` across jobs | No — events are unique per daily window    |
| **Table**                  | `experiment_exposures_preaggregated`   | `experiment_metric_events_preaggregated`   |
| **Time range**             | Experiment start → end                 | Experiment start → end + conversion window |
| **Stores variant**         | Yes                                    | No — variant comes from exposures CTE      |

## Scope

Currently implemented for **ordered funnels only**. Unordered funnels, mean, ratio, and retention metrics are not yet precomputed.

## Key files

| File                                        | Purpose                                                                                                                 |
| ------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| `experiment_query_builder.py`               | `get_funnel_metric_events_query_for_precomputation()` (write), precomputed CTE in `_build_funnel_query_legacy()` (read) |
| `experiment_query_runner.py`                | `_ensure_metric_events_precomputed()`, wiring in `_get_experiment_query()`                                              |
| `lazy_computation_executor.py`              | Core lazy computation: `ensure_precomputed()`, job management                                                           |
| `experiment_metric_events_sql.py`           | ClickHouse table definition                                                                                             |
| `experiment_metric_events_preaggregated.py` | HogQL schema for the table                                                                                              |
