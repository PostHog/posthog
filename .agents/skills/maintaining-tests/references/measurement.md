# Measuring test cost

Use the same measurement before and after a change. State the command, scope, and time type.

## Local measurements

Start with the repository test runner:

```bash
hogli test path/to/test.py::TestClass::test_name
```

Use pytest directly when you need pytest timing output:

```bash
uv run pytest -q path/to/test.py::TestClass::test_name --durations=20
```

Measure full wall time separately:

```bash
/usr/bin/time -f 'wall=%e user=%U system=%S max_rss_kb=%M' \
  uv run pytest -q path/to/test.py -k 'target_family' --durations=20
```

For a parameterized family, record all cases. Do not compare one case before the change with the full family after it.

Run a cold baseline when the optimization targets startup. Run a warm baseline when the optimization targets repeated work within one process. Label the result.

## Interpreting pytest time

Pytest can report separate phases:

- **setup:** fixture setup before the test call.
- **call:** the test function body.
- **teardown:** fixture cleanup after the test call.
- **wall:** the complete command, including collection and process startup.

A module-scoped fixture can move cost from repeated call phases into one setup phase. The call sum can decrease while wall time stays flat. Report both.

## Profiling

Use cProfile for in-process Python CPU work:

```bash
uv run python -m cProfile -o /tmp/test.prof -m pytest -q <nodeid>
uv run python - <<'PY'
import pstats
pstats.Stats('/tmp/test.prof').strip_dirs().sort_stats('cumulative').print_stats(40)
PY
```

Use py-spy or a system profiler when subprocesses, native code, or I/O dominate. Use service logs when the test starts a worker or container.

Do not profile a broad file first. Profile the smallest target that still reproduces the cost.

## CI timing data

The Backend CI timing reporter writes pytest spans to `posthog.trace_spans`.

Useful fields include:

```text
service_name = 'ci-backend'
resource_attributes['ci.branch']
resource_attributes['ci.run_id']
attributes['test.runner']
attributes['test.outcome']
attributes['test.owner_team']
attributes['test.file']
attributes['test.file_source']
attributes['shard.segment']
is_root_span
duration_nano
```

Read timing data with `posthog:execute-sql`. Use `master` for post-merge impact. Use explicit UTC windows.

### Rank individual pytest tests

```sql
SELECT
    name,
    coalesce(attributes['test.owner_team'], 'unowned') AS owner_team,
    count() AS executions,
    round(quantile(0.5)(duration_nano / 1000000000), 3) AS p50_seconds,
    round(quantile(0.95)(duration_nano / 1000000000), 3) AS p95_seconds,
    round(sum(duration_nano) / 1000000000 / 3600, 2) AS observed_hours
FROM posthog.trace_spans
WHERE timestamp >= toDateTime('2026-01-01 00:00:00', 'UTC')
  AND service_name = 'ci-backend'
  AND resource_attributes['ci.branch'] = 'master'
  AND attributes['test.runner'] = 'pytest'
  AND attributes['test.outcome'] = 'passed'
  AND duration_nano > 0
GROUP BY name, owner_team
HAVING executions >= 10
ORDER BY observed_hours DESC
LIMIT 50
```

Replace the example date with a recent complete window.

### Compare a test before and after a merge

Use two windows with the same length. Leave a gap around the merge so old jobs cannot enter the after group.

```sql
WITH samples AS (
    SELECT
        multiIf(
            timestamp >= toDateTime('2026-01-01 00:00:00', 'UTC')
                AND timestamp < toDateTime('2026-01-02 00:00:00', 'UTC'), 'before',
            timestamp >= toDateTime('2026-01-03 00:00:00', 'UTC')
                AND timestamp < toDateTime('2026-01-04 00:00:00', 'UTC'), 'after',
            'excluded'
        ) AS period,
        duration_nano / 1000000000 AS seconds
    FROM posthog.trace_spans
    WHERE service_name = 'ci-backend'
      AND resource_attributes['ci.branch'] = 'master'
      AND attributes['test.outcome'] = 'passed'
      AND name = '<exact test span name>'
)
SELECT
    period,
    count() AS executions,
    round(quantile(0.5)(seconds), 3) AS p50_seconds,
    round(quantile(0.95)(seconds), 3) AS p95_seconds,
    round(avg(seconds), 3) AS mean_seconds
FROM samples
WHERE period != 'excluded'
GROUP BY period
ORDER BY period
```

Use the exact merge timestamp from GitHub to choose the windows. Confirm that the after window contains runs with the merged code.

### Measure a parameter family per workflow run

```sql
WITH per_run AS (
    SELECT
        resource_attributes['ci.run_id'] AS run_id,
        sum(duration_nano) / 1000000000 AS call_seconds,
        uniq(name) AS cases
    FROM posthog.trace_spans
    WHERE timestamp >= toDateTime('2026-01-01 00:00:00', 'UTC')
      AND service_name = 'ci-backend'
      AND resource_attributes['ci.branch'] = 'master'
      AND attributes['test.outcome'] = 'passed'
      AND name LIKE '%::test_target_family[%]'
    GROUP BY run_id
)
SELECT
    count() AS runs,
    round(quantile(0.5)(call_seconds), 2) AS p50_call_seconds_per_run,
    round(quantile(0.95)(call_seconds), 2) AS p95_call_seconds_per_run,
    round(avg(cases), 1) AS mean_cases_per_run
FROM per_run
```

Check the mean case count. A lower duration is not a valid improvement if fewer cases ran.

### Measure the affected shard

```sql
WITH per_run AS (
    SELECT
        resource_attributes['ci.run_id'] AS run_id,
        max(duration_nano) / 1000000000 AS slowest_job_seconds,
        sum(duration_nano) / 1000000000 AS total_job_seconds,
        count() AS jobs
    FROM posthog.trace_spans
    WHERE timestamp >= toDateTime('2026-01-01 00:00:00', 'UTC')
      AND service_name = 'ci-backend'
      AND resource_attributes['ci.branch'] = 'master'
      AND is_root_span
      AND attributes['shard.segment'] = '<segment>'
    GROUP BY run_id
)
SELECT
    count() AS runs,
    round(quantile(0.5)(slowest_job_seconds), 2) AS p50_slowest_job_seconds,
    round(quantile(0.95)(slowest_job_seconds), 2) AS p95_slowest_job_seconds,
    round(quantile(0.5)(total_job_seconds), 2) AS p50_total_job_seconds,
    round(avg(jobs), 1) AS jobs_per_run
FROM per_run
```

The slowest job approximates the segment's critical path. The total job seconds approximate runner work.

### Measure total pytest work and the critical job

```sql
WITH per_run AS (
    SELECT
        resource_attributes['ci.run_id'] AS run_id,
        sumIf(duration_nano, NOT is_root_span AND attributes['test.runner'] = 'pytest') / 1000000000 AS test_call_seconds,
        maxIf(duration_nano, is_root_span) / 1000000000 AS critical_job_seconds,
        uniqIf(trace_id, is_root_span) AS jobs
    FROM posthog.trace_spans
    WHERE timestamp >= toDateTime('2026-01-01 00:00:00', 'UTC')
      AND service_name = 'ci-backend'
      AND resource_attributes['ci.branch'] = 'master'
    GROUP BY run_id
    HAVING jobs > 0
)
SELECT
    count() AS runs,
    round(quantile(0.5)(test_call_seconds), 1) AS p50_test_call_seconds,
    round(quantile(0.95)(test_call_seconds), 1) AS p95_test_call_seconds,
    round(quantile(0.5)(critical_job_seconds), 1) AS p50_critical_job_seconds,
    round(quantile(0.95)(critical_job_seconds), 1) AS p95_critical_job_seconds
FROM per_run
```

A lower test-call sum means less compute. A lower critical-job duration means less waiting for that workflow.

### Measure ownership

```sql
SELECT
    toDate(timestamp) AS day,
    count() AS test_spans,
    countIf(attributes['test.owner_team'] IS NULL) AS unowned_spans,
    round(100 * unowned_spans / test_spans, 2) AS unowned_percent
FROM posthog.trace_spans
WHERE timestamp >= toDateTime('2026-01-01 00:00:00', 'UTC')
  AND service_name = 'ci-backend'
  AND attributes['test.runner'] = 'pytest'
GROUP BY day
ORDER BY day
```

Treat ownership as a routing result. It does not prove that test cost decreased.

## Reporting limits

Before you state an improvement, confirm these conditions:

- Both samples use the same branch.
- Both samples use the same test name or family rule.
- Both samples contain the same cases.
- Both samples use the same time type.
- The after sample contains the merged code.
- The sample sizes are large enough to resist one unusual run.

State when unrelated changes landed in the same window. Use the exact-test result for causal claims. Use the whole-run result as directional evidence.
