# Recalculation query templates

Every template is read-only and has a `LIMIT`.
Fill placeholders with `sed` from a hidden scratchpad file, or by hand, before you run the query.
`hogli metabase:query` does not fill `{name:Type}` parameters.

| Placeholder                    | Value                                                |
| ------------------------------ | ---------------------------------------------------- |
| `<team_id>`, `<experiment_id>` | ids in the region of the ticket                      |
| `<run_id>`                     | `posthog_experimentmetricsrecalculation.id` (a uuid) |
| `<run_id_list>`                | quoted, comma-separated run ids                      |
| `<from>`, `<to>`               | UTC, `YYYY-MM-DD HH:MM:SS`                           |
| `<region>`                     | `US` or `EU`                                         |

## ClickHouse sources

`clusterAllReplicas(posthog, system, query_log)` keeps about 2 weeks.
For older windows, use `posthog.query_log_archive` with its typed `lc_*` columns
(`lc_temporal__workflow_id`, `lc_experiment_query_surface` and others; see `generating-clickhouse-query-performance-reports`).

A recalculation query has:

- `log_comment.temporal.workflow_id` = `experiment-metrics-recalculation-<run_id>`, on metric reads and precompute builds;
- `query_id` = `<team_id>_experiment_metric_recalc_<run_id>_<metric_uuid>_attemptNN_<random>`, on metric reads;
- `log_comment.temporal.activity_type` = `calculate_experiment_metric_for_recalculation`.

## Postgres: one experiment

### Run history

```sql
-- Newest first. tombstone: FAILED without completed_at (stale force-fail or failed start).
SELECT id, trigger, status, created_at, started_at, completed_at, query_to,
       created_by_id IS NOT NULL AS has_creator,
       status = 'failed' AND completed_at IS NULL AS tombstone,
       CASE WHEN jsonb_typeof(metric_uuids) = 'array' THEN jsonb_array_length(metric_uuids) END AS metrics,
       CASE WHEN jsonb_typeof(metric_errors) = 'object' THEN (SELECT count(*) FROM jsonb_object_keys(metric_errors)) END AS failed_metrics
FROM posthog_experimentmetricsrecalculation
WHERE team_id = <team_id> AND experiment_id = <experiment_id>
  AND trigger <> 'timeseries_sync' AND created_at >= '<from>'
ORDER BY created_at DESC
LIMIT 50
```

### Metric errors across runs

Sorted by metric, so a repeat shows as consecutive rows with the same `error_type`.

```sql
SELECT e.key AS metric_uuid, r.created_at, r.trigger, r.status,
       e.value ->> 'error_type' AS error_type, e.value ->> 'step' AS step,
       e.value ->> 'retriable' AS retriable, left(e.value ->> 'message', 120) AS message
FROM posthog_experimentmetricsrecalculation r,
     jsonb_each(CASE WHEN jsonb_typeof(r.metric_errors) = 'object' THEN r.metric_errors ELSE '{}'::jsonb END) e
WHERE r.team_id = <team_id> AND r.experiment_id = <experiment_id>
  AND r.trigger <> 'timeseries_sync' AND r.created_at >= '<from>'
  AND jsonb_typeof(e.value) = 'object'
ORDER BY e.key, r.created_at DESC
LIMIT 200
```

### Gaps between runs

Per team. A short gap after a failed run, every hour, from one creator, is a client retry loop.

```sql
SELECT trigger, prev_status, count(*) AS runs, count(DISTINCT experiment_id) AS experiments,
       count(DISTINCT created_by_id) AS creators,
       round(percentile_cont(0.5) WITHIN GROUP (ORDER BY gap_s)) AS median_gap_s
FROM (
  SELECT experiment_id, trigger, created_by_id,
         lag(status) OVER w AS prev_status,
         extract(epoch FROM created_at - lag(coalesce(completed_at, started_at, created_at)) OVER w) AS gap_s
  FROM posthog_experimentmetricsrecalculation
  WHERE team_id = <team_id> AND trigger <> 'timeseries_sync' AND created_at >= '<from>'
  WINDOW w AS (PARTITION BY experiment_id ORDER BY created_at)
) x
WHERE prev_status IS NOT NULL
GROUP BY 1, 2 ORDER BY runs DESC
LIMIT 20
```

### Precompute jobs

Per team, for the "why direct_scan" branch. The error text is shortened to its shape.

```sql
SELECT created_at::date AS day, status,
       CASE WHEN time_range_end - time_range_start <= interval '1 day' THEN '<=1d'
            WHEN time_range_end - time_range_start <= interval '7 days' THEN '2-7d' ELSE '>7d' END AS width,
       left(regexp_replace(coalesce(error, ''), '[0-9a-f-]{20,}|[0-9]+', '#', 'g'), 60) AS error_shape,
       count(*) AS jobs
FROM analytics_platform_preaggregationjob
WHERE team_id = <team_id> AND created_at >= '<from>'
GROUP BY 1, 2, 3, 4 ORDER BY 1, 2, 3
LIMIT 80
```

## ClickHouse: one run

### Attempts and codes

Every query of the run, in order: metric, attempt, surface (`metric` or `precompute_build`), code, time, size, window and paths.

```sql
SELECT event_time,
       JSONExtractString(log_comment, 'experiment_metric_uuid') AS metric_uuid,
       JSONExtractInt(log_comment, 'temporal', 'attempt') AS attempt,
       JSONExtractString(log_comment, 'experiment_query_surface') AS surface,
       exception_code, round(query_duration_ms / 1000) AS seconds, formatReadableSize(read_bytes) AS read,
       JSONExtractString(log_comment, 'experiment_scan_date_from') AS scan_from,
       JSONExtractString(log_comment, 'experiment_exposures_path') AS exposures_path,
       JSONExtractString(log_comment, 'experiment_metric_events_path') AS events_path,
       JSONExtractString(log_comment, 'experiment_metric_events_skip_reason') AS events_skip_reason,
       JSONExtractString(log_comment, 'experiment_precompute_skip_reason') AS precompute_skip_reason
FROM clusterAllReplicas(posthog, system, query_log)
WHERE event_date BETWEEN toDate('<from>') AND toDate('<to>')
  AND is_initial_query AND type != 'QueryStart'
  AND JSONExtractString(log_comment, 'temporal', 'workflow_id') = 'experiment-metrics-recalculation-<run_id>'
ORDER BY event_time
LIMIT 200
```

Codes 43, 386 and 754 are deterministic: every attempt fails the same way.
A 394 with a matching kill below is our own attempt timeout or a cancel.

### Kills

```sql
SELECT event_time, type, user
FROM clusterAllReplicas(posthog, system, query_log)
WHERE event_date BETWEEN toDate('<from>') AND toDate('<to>')
  AND query_kind = 'KillQuery' AND query LIKE '%experiment_metric_recalc_<run_id>%'
ORDER BY event_time
LIMIT 50
```

## Events (internal PostHog project, HogQL)

The project is in US/Pacific time. Keep `toTimeZone(timestamp, 'UTC')` and the UTC bounds.
Compare id properties with `toInt(...)`: a plain `properties.team_id = 123` fails with a type error.

### Scheduled starts and skips

```sql
SELECT toTimeZone(timestamp, 'UTC') AS ts_utc, event,
       properties.hour AS hour, properties.reason AS reason, properties.recalculation_id AS run_id
FROM events
WHERE event IN ('experiment scheduled recalculation started', 'experiment scheduled recalculation skipped')
  AND properties.region = '<region>'
  AND toInt(properties.team_id) = <team_id> AND toInt(properties.experiment_id) = <experiment_id>
  AND timestamp >= toDateTime('<from>', 'UTC') AND timestamp < toDateTime('<to>', 'UTC')
ORDER BY timestamp DESC
LIMIT 100
```

`properties.hour` is the team's UTC schedule hour. A skip event also carries the detail of its reason (for example the exposure count).

### Queue time and what the user saw

```sql
SELECT toTimeZone(timestamp, 'UTC') AS ts_utc, event, properties.status AS status,
       properties.trigger AS trigger, properties.reason AS reason, properties.is_existing AS is_existing,
       properties.queue_duration_ms AS queue_ms, properties.total_duration_ms AS total_ms
FROM events
WHERE event IN ('experiment results refresh completed', 'experiment metric recalculation')
  AND toInt(properties.experiment_id) = <experiment_id>
  AND timestamp >= toDateTime('<from>', 'UTC') AND timestamp < toDateTime('<to>', 'UTC')
ORDER BY timestamp DESC
LIMIT 100
```

`experiment metric recalculation` comes from the frontend: `triggered`, `completed`, `failed`, or `abandoned` with a `reason` (`poll_timeout` and others).
The same `experiment_id` can exist in US and EU. Match on the run id when you have it.

### UI or API

A click in the UI sends `experiment metric recalculation` with `status = 'triggered'` and the run id.
Count the matches for the runs in question, and the fleet baseline without the id filter.
Zero matches with a normal baseline means the runs did not come from the button.

```sql
SELECT countIf(properties.recalculation_id IN (<run_id_list>)) AS matched,
       count() AS fleet_baseline
FROM events
WHERE event = 'experiment metric recalculation' AND properties.status = 'triggered'
  AND timestamp >= toDateTime('<from>', 'UTC') AND timestamp < toDateTime('<to>', 'UTC')
LIMIT 1
```

The run-id list lands in the transcript. Never save it to a file.

## Loki: silent scheduled no-starts

The scheduled workflow runs on the general-purpose worker.
These log keys have no event: `scheduled_recalculation_request_failed`, `scheduled_recalculation_dispatch_failed`,
`scheduled_recalculation_skip_check_failed`, `scheduled_recalculation_exposure_query_failed`.

```logql
{service_name="temporal-worker-general-purpose"} |= "scheduled_recalculation_" |= "<experiment_id>"
```

Use a window of a few minutes after `:30` of the expected hour.
