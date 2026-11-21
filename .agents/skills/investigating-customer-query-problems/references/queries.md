# Query templates

Run these through querying-production-databases, or querying-production-databases-via-metabase as the fallback.
Replace `{org_id}`, `{team_id}`, `{since}` (a date), `{job_filter}` (a `LIKE` or `match` on `lc_query__query` that picks one job).
Write SQL and results to the session scratchpad so the handoff can cite them.

## 1. Census by path and outcome

```sql
SELECT
    team_id,
    lc_access_method AS access,
    lc_feature AS feature,
    lc_kind AS kind,
    user AS ch_user,
    lc_api_key_label AS key_label,
    lc_query__kind AS qkind,
    count() AS runs,
    countIf(exception_code = 0) AS ok,
    countIf(exception_code = 159) AS timeout_159,
    countIf(exception_code IN (202, 439)) AS capacity_rows,
    uniqExactIf(lc_client_query_id, exception_code IN (202, 439)) AS capacity_requests,
    countIf(exception_code = 241) AS memory_241,
    groupUniqArrayIf(exception_name, exception_code NOT IN (0, 159, 202, 241)) AS other_errors,
    round(sum(ProfileEvents_OSCPUVirtualTimeMicroseconds) / 3.6e9, 1) AS cpu_h,
    formatReadableSize(sum(read_bytes)) AS read,
    uniqExact(hogql_shape) AS shapes
FROM posthog.query_log_archive
WHERE event_date >= '{since}'
    AND lc_org_id = '{org_id}'
    AND is_initial_query
GROUP BY team_id, access, feature, kind, ch_user, key_label, qkind
ORDER BY runs DESC
```

To see the time cap a query actually ran with, add `extract(query, 'max_execution_time=(\\d+)') AS met` and group by it.

## 2. Jobs: shapes ranked by cost, with cadence

`hogql_shape` is the HogQL text with literals stripped, so one job with changing dates or IDs becomes one row. If the column is missing, use `cityHash64(replaceRegexpAll(replaceRegexpAll(h, '''[^'']*''', '?'), '\\b\\d+\\b', '?'))`.

```sql
WITH q AS (
    SELECT
        query_start_time AS t,
        lc_query__query AS h,
        exception_code AS code,
        read_bytes,
        ProfileEvents_OSCPUVirtualTimeMicroseconds AS cpu,
        hogql_shape AS shape
    FROM posthog.query_log_archive
    WHERE event_date >= '{since}'
        AND lc_org_id = '{org_id}'
        AND is_initial_query
        AND h != ''
)
SELECT
    shape,
    count() AS runs,
    uniqExact(h) AS texts,
    countIf(code != 0) AS failed,
    round(sum(cpu) / 3.6e9, 1) AS cpu_h,
    round(100 * sum(cpu) / sum(sum(cpu)) OVER (), 1) AS cpu_pct,
    formatReadableSize(sum(read_bytes)) AS read,
    round(arrayReduce('quantile(0.5)', arrayDifference(arraySort(groupArray(toUnixTimestamp(t))))) / 60, 1) AS p50_gap_min,
    replaceRegexpAll(substring(any(h), 1, 350), '\\s+', ' ') AS head
FROM q
GROUP BY shape
ORDER BY cpu_h DESC
LIMIT 25
```

`texts = 1` with many runs means a fixed query. `texts` close to `runs` means the literals change every run.

## 3. Hourly cadence of one job

```sql
SELECT
    toStartOfHour(query_start_time) AS hour,
    count() AS runs,
    countIf(exception_code = 0) AS ok,
    countIf(exception_code = 202) AS rejected,
    formatDateTime(min(query_start_time), '%H:%i') AS first_start,
    formatDateTime(max(query_start_time), '%H:%i') AS last_start
FROM posthog.query_log_archive
WHERE event_date >= '{since}'
    AND team_id = {team_id}
    AND is_initial_query
    AND {job_filter}
GROUP BY hour
ORDER BY hour
```

To check whether each hourly pass reached the newest data, extract the window end from the text with `parseDateTimeBestEffortOrNull(extract(lc_query__query, '<regex for the upper bound>'))` and count runs whose window end is after `query_start_time`.

## 4. Daily trend of one job (is it growing?)

```sql
SELECT
    event_date AS day,
    count() AS runs,
    countIf(exception_code != 0) AS failed,
    round(quantileIf(0.5)(query_duration_ms, exception_code = 0)) AS p50_ok_ms,
    formatReadableSize(avg(read_bytes)) AS avg_read,
    round(sum(ProfileEvents_OSCPUVirtualTimeMicroseconds) / 3.6e9, 1) AS cpu_h
FROM posthog.query_log_archive
WHERE event_date >= '{since}'
    AND lc_org_id = '{org_id}'
    AND is_initial_query
    AND {job_filter}
GROUP BY day
ORDER BY day
```

Read bytes per run that rise every day mean a window with a fixed start and no end. That job will cross any time cap eventually.

## 5. Fan-out per shape

Over long windows, `avg(execution_count)` per `hogql_shape` in the archive gives fan-out. Use the live query below when you need the peak on one node, which the archive doesn't keep.

Secondary queries per initial query show distributed nesting. A HogQL `WITH x AS (... FROM events) ... FROM events JOIN x` makes every shard re-run `x` on every shard.

```sql
WITH per_host AS (
    SELECT
        initial_query_id AS iq,
        hostName() AS host,
        countIf(NOT is_initial_query) AS sq,
        anyIf(JSONExtractString(log_comment, 'query', 'query'), is_initial_query) AS h,
        maxIf(query_duration_ms, is_initial_query) AS dur,
        maxIf(exception_code, is_initial_query) AS code
    FROM clusterAllReplicas(posthog, system, query_log)
    WHERE event_date >= today() - 2
        AND type != 'QueryStart'
        AND JSONExtractInt(log_comment, 'team_id') = {team_id}
    GROUP BY iq, host
),
per_q AS (
    SELECT iq, max(h) AS h, sum(sq) AS subq, max(sq) AS peak, max(dur) AS dur, max(code) AS code
    FROM per_host
    GROUP BY iq
)
SELECT
    cityHash64(replaceRegexpAll(h, '''[^'']*''|\\d+', '?')) AS shape,
    count() AS runs,
    countIf(code != 0) AS failed,
    round(avg(subq)) AS avg_subqueries,
    max(peak) AS max_on_one_node,
    round(quantile(0.5)(dur)) AS p50_ms,
    replaceRegexpAll(substring(any(h), 1, 400), '\\s+', ' ') AS head
FROM per_q
WHERE h != ''
GROUP BY shape
ORDER BY runs * avg_subqueries DESC
LIMIT 10
```

Compare with a plain events query from the same team as a baseline. A count several times that baseline means nested fan-out.

## 6. Blame replay for 202 rejections

Who held the ClickHouse user's slots on the node when each rejection happened. Take `{ch_user}` from the census `ch_user` column of the rejected rows. Scan the live table once, label every row by the cohort of its initial query, then take running sums per host.

```sql
WITH raw AS (
    SELECT
        hostname() AS host,
        if(is_initial_query, query_id, initial_query_id) AS iq,
        type,
        exception_code AS code,
        query_start_time_microseconds AS s,
        event_time_microseconds AS e,
        if(is_initial_query,
            multiIf(
                JSONExtractInt(log_comment, 'team_id') = {team_id} AND {job_filter_on_log_comment}, 3,
                JSONExtractInt(log_comment, 'team_id') = {team_id}, 2,
                1),
            0) AS init_label
    FROM clusterAllReplicas(posthog, system, query_log)
    WHERE event_date = '{day}'
        AND event_time >= '{start}' - INTERVAL 5 MINUTE AND event_time < '{end}' + INTERVAL 5 MINUTE
        AND user = '{ch_user}'
        AND type != 'QueryStart'
),
labeled AS (
    SELECT *, max(init_label) OVER (PARTITION BY iq) AS cohort FROM raw
),
points AS (
    SELECT host, iq, cohort,
        arrayJoin(if(type = 'ExceptionBeforeStart',
            if(code = 202 AND e >= '{start}' AND e < '{end}', [(e, 0)], []),
            [(s, 1), (e, -1)])) AS p
    FROM labeled
),
swept AS (
    SELECT host, iq, cohort, p.2 AS d,
        sum(d) OVER w AS total,
        sum(if(cohort = 3, d, 0)) OVER w AS job,
        sum(if(cohort = 2, d, 0)) OVER w AS customer_other,
        sum(if(cohort = 1, d, 0)) OVER w AS other_teams,
        sum(d) OVER (PARTITION BY host, iq ORDER BY p.1, p.2 ROWS UNBOUNDED PRECEDING) AS same_query
    FROM points
    WINDOW w AS (PARTITION BY host ORDER BY p.1, p.2 ROWS UNBOUNDED PRECEDING)
)
SELECT
    multiIf(cohort = 3, 'rejected: the job', cohort = 2, 'rejected: customer other', cohort = 1, 'rejected: other teams', 'rejected: unknown') AS victim,
    count() AS rejections,
    round(avg(total), 1) AS slots_held,
    round(avg(job - if(cohort = 3, same_query, 0)), 1) AS held_by_job,
    round(avg(customer_other - if(cohort = 2, same_query, 0)), 1) AS held_by_customer_other,
    round(avg(other_teams - if(cohort = 1, same_query, 0)), 1) AS held_by_other_teams
FROM swept
WHERE d = 0
GROUP BY victim
```

`{job_filter_on_log_comment}` is a condition on `JSONExtractString(log_comment, 'query', 'query')` that picks the suspect job. `slots_held` near the per-node limit at each rejection shows the replay is sound. Read that limit from the `exception` text of a 202 row. Timestamp granularity adds noise to "would have fit without the job", so measure the same share in a window without the job and compare. Use a window of 30 minutes or less.

## 7. API concurrency against the `api_per_team` limit

```sql
WITH q AS (
    SELECT
        query_start_time_microseconds AS s,
        query_start_time_microseconds + toIntervalMillisecond(query_duration_ms) AS e
    FROM posthog.query_log_archive
    WHERE event_date >= '{since}'
        AND team_id = {team_id}
        AND lc_access_method = 'personal_api_key'
        AND is_initial_query
),
ev AS (
    SELECT t, d, sum(d) OVER (ORDER BY t, d ROWS UNBOUNDED PRECEDING) AS running
    FROM (SELECT arrayJoin([(s, 1), (e, -1)]) AS x, x.1 AS t, x.2 AS d FROM q)
)
SELECT
    countIf(d = 1) AS starts,
    countIf(d = 1 AND running > {api_per_team_limit}) AS starts_above_limit,
    max(running) AS max_running
FROM ev
```

## 8. Exact repeats and the gap since the previous identical run

Use for one team or, without the team filter and with a 6-hour window, for the fleet.

```sql
WITH q AS (
    SELECT
        team_id,
        query_start_time AS t,
        cityHash64(lc_query__query) AS h,
        result_rows,
        ProfileEvents_OSCPUVirtualTimeMicroseconds AS cpu
    FROM posthog.query_log_archive
    WHERE event_date = '{day}'
        AND query_start_time >= '{start}' AND query_start_time < '{end}'
        AND lc_access_method = 'personal_api_key'
        AND is_initial_query
        AND exception_code = 0
        AND lc_query__query != ''
),
w AS (
    SELECT *,
        lagInFrame(toNullable(t)) OVER (PARTITION BY team_id, h ORDER BY t ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING) AS prev_t
    FROM q
)
SELECT
    multiIf(prev_t IS NULL, '0 first', dateDiff('second', prev_t, t) <= 300, '1 <=5m', dateDiff('second', prev_t, t) <= 1800, '2 5-30m', dateDiff('second', prev_t, t) <= 3600, '3 30-60m', '4 >1h') AS gap,
    count() AS queries,
    round(sum(cpu) / 3.6e9) AS cpu_h,
    round(100 * sum(cpu) / (SELECT sum(cpu) FROM w), 1) AS cpu_pct
FROM w
GROUP BY gap
ORDER BY gap
```

Set the bucket edges from the SQL cache freshness you confirmed (limits.md). Repeats inside it should be cache hits. If they reach ClickHouse, check `execution_mode` in live `query_log` for a forced refresh.

## 9. Proving a rewrite on prod

1. Compile check. Run the HogQL through PostHog MCP `execute-sql` on project 2 with a marker comment and a 1-hour window, for example `call execute-sql {"query": "/* mycase:rw */ SELECT ... AND timestamp >= now() - INTERVAL 1 HOUR ... LIMIT 5"}`. This also catches HogQL syntax errors.
2. Get the compiled SQL. Find the marker in live `query_log` (`JSONExtractInt(log_comment, 'team_id') = 2`, `log_comment LIKE '%mycase%'`). To run it as the customer's team, replace project 2's timezone in the SQL with theirs (their timezone is in the `toTimeZone(...)` calls of their own compiled SQL in `query_log`) and only the `equals(<alias>.team_id, 2)` references with their team ID. A blanket `, 2)` replace also hits `tupleElement(s, 2)`. Check the swap first: the customer's original query swapped the same way must be byte-identical to their own prod compile from `query_log`. This only works when both teams use the same person-on-events mode.
3. Compare results without pulling rows:

   ```sql
   /* mycase:orig */ SELECT count() AS rows, sum(cityHash64(toString(tuple(<cols>)))) AS fingerprint
   FROM (<compiled sql>) SETTINGS <original settings minus readonly>, max_execution_time=60
   ```

   `toString(tuple(...))` keeps NULLs in the hash. Equal rows and fingerprint for the original and the rewrite means the same result.

4. Measure cost and fan-out by marker. The query you use to search `query_log` is logged too, so match with a regex that doesn't match its own text, for example `match(query, 'mycase[:]rw')`:

   ```sql
   SELECT
       anyIf(extract(query, 'mycase[:]([a-z0-9]+)'), is_initial_query) AS marker,
       maxIf(query_duration_ms, is_initial_query) AS ms,
       round(maxIf(ProfileEvents['OSCPUVirtualTimeMicroseconds'], is_initial_query) / 1e6, 1) AS cpu_s,
       formatReadableSize(maxIf(read_bytes, is_initial_query)) AS read,
       countIf(NOT is_initial_query) AS secondaries,
       uniqIf(hostName(), NOT is_initial_query) AS nodes
   FROM clusterAllReplicas(posthog, system, query_log)
   WHERE event_time > now() - INTERVAL 15 MINUTE AND type != 'QueryStart'
   GROUP BY initial_query_id
   HAVING marker != ''
   ```

Use a small team for anything that joins persons. A large team can hit the memory limit.
