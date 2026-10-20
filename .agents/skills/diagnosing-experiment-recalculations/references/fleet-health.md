# Recalculation fleet health

Placeholders are in [queries.md](queries.md); `<max_age_days>` is `EXPERIMENT_RECALCULATION_MAX_AGE_DAYS`.

Recalculation queries run on the offline tier, as `default`,
or as `experiments` for organizations in the flag `experiment-recalculation-clickhouse-user`.
Each user has its own concurrency quota, so read shares per user.

## 1. Find the window

Compare the bad day with the days before, by UTC hour. In US, look back 2 to 3 days, not 7.

```sql
SELECT event_date AS day, toHour(event_time) AS hour_utc, user,
       countIf(recalc) AS recalc_202, countIf(NOT recalc) AS other_202
FROM (
  SELECT event_date, event_time, user,
         JSONExtractString(log_comment, 'temporal', 'workflow_type') = 'experiment-metrics-recalculation-workflow' AS recalc
  FROM clusterAllReplicas(posthog, system, query_log)
  WHERE event_date BETWEEN toDate('<from>') - 7 AND toDate('<to>')
    AND is_initial_query AND exception_code = 202
    AND user IN ('default', 'experiments') AND hostName() LIKE '%offline%'
)
GROUP BY day, hour_utc, user ORDER BY day, hour_utc, user
LIMIT 500
```

## 2. Cause or victim

202 counts show who was rejected, not who holds the slots. Query-seconds per source show the cause.

```sql
SELECT user, src, round(sum(query_duration_ms) / 1000) AS query_s,
       round(100 * sum(query_duration_ms) / sum(sum(query_duration_ms)) OVER (PARTITION BY user), 1) AS pct,
       countIf(exception_code = 202) AS received_202
FROM (
  SELECT user, query_duration_ms, exception_code,
         if(JSONExtractString(log_comment, 'kind') = 'temporal',
            concat('temporal:', JSONExtractString(log_comment, 'temporal', 'workflow_type')),
            concat(JSONExtractString(log_comment, 'kind'), ':', JSONExtractString(log_comment, 'product'),
                   if(JSONExtractString(log_comment, 'kind') = 'celery', concat(':', JSONExtractString(log_comment, 'query_type')), ''))) AS src
  FROM clusterAllReplicas(posthog, system, query_log)
  WHERE event_date BETWEEN toDate('<from>') AND toDate('<to>')
    AND event_time >= toDateTime('<from>', 'UTC') AND event_time < toDateTime('<to>', 'UTC')
    AND is_initial_query AND type != 'QueryStart'
    AND user IN ('default', 'experiments') AND hostName() LIKE '%offline%'
)
GROUP BY user, src ORDER BY user, query_s DESC
LIMIT 15 BY user
```

Classify `temporal:experiment-metrics-recalculation-workflow` on the saturated user:

| Recalc share of query-seconds | Verdict     | Next                                            |
| ----------------------------- | ----------- | ----------------------------------------------- |
| below 25%                     | victim      | Stop. Report the main holders and their owners. |
| 25% to 50%                    | contributor | Record it. No lever; point to durable fixes.    |
| 50% or more                   | cause       | Pick the scope (step 3).                        |

Report `experiment-saved-metrics-workflow` and `experiment-regular-metrics-workflow` separately: the recalculation levers do not touch them.

## 3. Scope

### Recalc load per team

Aggregate per team first, then rank. A window sum per row counts the top team many times.

```sql
SELECT team_id, round(sum(qs)) AS query_s,
       round(100 * sum(qs) / sum(sum(qs)) OVER (), 1) AS pct,
       uniqExact(experiment_id) AS experiments,
       max(win_days) AS max_window_days,
       round(100 * sumIf(qs, win_days > <max_age_days>) / sum(qs), 1) AS pct_window_past_max_age,
       round(100 * sumIf(qs, events_path = 'direct_scan') / sum(qs), 1) AS pct_direct_scan
FROM (
  SELECT JSONExtractInt(log_comment, 'team_id') AS team_id,
         JSONExtractInt(log_comment, 'experiment_id') AS experiment_id,
         dateDiff('day', parseDateTimeBestEffortOrNull(JSONExtractString(log_comment, 'experiment_scan_date_from')),
                         parseDateTimeBestEffortOrNull(JSONExtractString(log_comment, 'experiment_scan_date_to'))) AS win_days,
         JSONExtractString(log_comment, 'experiment_metric_events_path') AS events_path,
         query_duration_ms / 1000 AS qs
  FROM clusterAllReplicas(posthog, system, query_log)
  WHERE event_date BETWEEN toDate('<from>') AND toDate('<to>')
    AND event_time >= toDateTime('<from>', 'UTC') AND event_time < toDateTime('<to>', 'UTC')
    AND is_initial_query AND type != 'QueryStart'
    AND JSONExtractString(log_comment, 'temporal', 'workflow_type') = 'experiment-metrics-recalculation-workflow'
)
GROUP BY team_id ORDER BY query_s DESC
LIMIT 10
```

Then pick one scope:

- **A, one team** holds more than half of recalc query-seconds.
  Before any team lever, decide organic or runaway with the runs below, the gaps between runs and the UI-or-API match ([queries.md](queries.md)):
  - Organic: many creators, many experiments, mostly completed runs, frontend events that match, normal windows.
  - Runaway: one creator, a retry a few minutes after each failure, every hour including weekends, no matching frontend events, very long windows.

  A lever on an organic team hurts its users and leaves the load. Point to durable fixes instead.

- **B, scheduled burst**: `scheduled` runs dominate near `:30` of one hour. Read the busy schedule hours.
- **C, many teams**: no single team or trigger dominates.

### Runs by hour and trigger

Add `AND team_id = <team_id>` for one team. Read it after the per-team load: trigger counts can stay flat while runs get heavier.

```sql
SELECT date_trunc('hour', created_at) AS hour_utc, trigger, count(*) AS runs,
       count(*) FILTER (WHERE status = 'failed') AS failed,
       count(DISTINCT experiment_id) AS experiments, count(DISTINCT created_by_id) AS creators
FROM posthog_experimentmetricsrecalculation
WHERE trigger <> 'timeseries_sync' AND created_at >= '<from>' AND created_at < '<to>'
GROUP BY 1, 2 ORDER BY 1, 2
LIMIT 300
```

### Busy schedule hours

Burst hours come from each team's `experiment_recalculation_times`; find them, do not assume them.
Null means the default hour in `TeamExperimentsConfig`. The team flag is not visible here.

```sql
SELECT coalesce(t.hhmm, 'default') AS hour_utc, count(DISTINCT e.team_id) AS teams, count(*) AS experiments
FROM posthog_experiment e
LEFT JOIN experiments_teamexperimentsconfig c ON c.team_id = e.team_id
LEFT JOIN LATERAL jsonb_array_elements_text(
  CASE WHEN jsonb_typeof(c.experiment_recalculation_times) = 'array' THEN c.experiment_recalculation_times END
) AS t(hhmm) ON true
WHERE NOT e.deleted AND e.status = 'running'
  AND e.start_date >= now() - make_interval(days => <max_age_days>)
GROUP BY 1 ORDER BY experiments DESC
LIMIT 30
```

## 4. Retry depth

202s above `CAPACITY_MAX_METRIC_ATTEMPTS` mean earlier attempts failed another way (usually timeouts), so the capacity cap did not apply.

```sql
SELECT toHour(event_time) AS hour_utc, JSONExtractInt(log_comment, 'temporal', 'attempt') AS attempt,
       count() AS queries, countIf(exception_code = 202) AS rejected,
       countIf(exception_code IN (159, 394)) AS timed_out
FROM clusterAllReplicas(posthog, system, query_log)
WHERE event_date BETWEEN toDate('<from>') AND toDate('<to>')
  AND event_time >= toDateTime('<from>', 'UTC') AND event_time < toDateTime('<to>', 'UTC')
  AND is_initial_query AND type != 'QueryStart'
  AND JSONExtractString(log_comment, 'temporal', 'activity_type') = 'calculate_experiment_metric_for_recalculation'
GROUP BY hour_utc, attempt ORDER BY hour_utc, attempt
LIMIT 300
```

## 5. Worker metrics (Grafana)

Both queues report the same metrics with a `task_queue` label:
`experiments-recalculation-task-queue` and `experiments-recalculation-activity-task-queue`.

| Question                                                    | PromQL                                                                                                                                                |
| ----------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| Recalc queries in flight (one calc activity runs one query) | `sum by (task_queue) (temporal_worker_task_slots_used{task_queue=~"experiments-recalculation(-activity)?-task-queue", worker_type="ActivityWorker"})` |
| Queue wait, p95                                             | `histogram_quantile(0.95, sum by (le, task_queue) (rate(experiment_metrics_recalculation_activity_schedule_to_start_latency_bucket[5m])))`            |
| Failures by class                                           | `sum by (error_type) (increase(experiment_metrics_recalculation_activity_failures[1h]))`                                                              |
| Run outcomes                                                | `sum by (status) (increase(experiment_metrics_recalculation_workflow_finished[1h]))`                                                                  |
| Pods                                                        | `kube_deployment_status_replicas{deployment=~"temporal-worker-experiments-recalculation.*"}`                                                          |
| Pollers                                                     | `sum by (task_queue) (temporal_num_pollers{task_queue=~"experiments-recalculation(-activity)?-task-queue"})`                                          |
| API side                                                    | `experiment_metrics_recalculation_rate_limited_total`, `_existing_run_reused_total`, `_stale_rows_cleaned_total`                                      |

On `temporal_*` metrics, `namespace` is the Temporal namespace, not a Kubernetes one.
Convert epoch times to UTC with a script, not by hand.
A rising queue wait with flat failures is the cap doing its job, not a fault.

## 6. Act

If recalculation is the cause, follow the staff-only runbook
[Experiment recalculation saturates ClickHouse](https://github.com/PostHog/runbooks/blob/main/content/services/experiments/runbooks/recalculation-clickhouse-saturation.mdx)
(private repository `PostHog/runbooks`).
It holds the levers per scope, their order, the roll back and who can run them.
Propose one lever with the evidence, effect, side effects and roll back; a named person runs it.
Record what, who and when (UTC) in the incident or ticket, never in the repository.
If the person lacks the access a lever needs, name the role that has it, and stop.

## Drift checks

A value missing from this skill means the skill is stale.

```sql
-- Postgres: error classes in metric_errors.
SELECT e.value ->> 'error_type' AS error_type, count(*) AS n
FROM posthog_experimentmetricsrecalculation r,
     jsonb_each(CASE WHEN jsonb_typeof(r.metric_errors) = 'object' THEN r.metric_errors ELSE '{}'::jsonb END) e
WHERE r.created_at >= now() - interval '2 days' AND jsonb_typeof(e.value) = 'object'
GROUP BY 1 ORDER BY n DESC
LIMIT 20
```

```sql
-- HogQL, internal project: scheduled skip reasons.
SELECT properties.reason AS reason, count() AS n
FROM events
WHERE event = 'experiment scheduled recalculation skipped' AND timestamp >= now() - INTERVAL 2 DAY
GROUP BY reason ORDER BY n DESC
LIMIT 20
```

In Grafana, list the label values of `error_type` on `experiment_metrics_recalculation_activity_failures`
and of `task_queue` on `temporal_worker_task_slots_used`.
