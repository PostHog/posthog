# Slow-query report: ready-to-run patterns

All queries run against `posthog.query_log_archive` via `hogli metabase:query --region <us|eu>
--database-id <id>` (discover the id with `hogli metabase:databases`). Save wide results with
`--save <path>`. `now() - INTERVAL 14 DAY` = "last two weeks"; adjust the interval per request.

The health-poll exclusion below removes the cluster's own liveness probe so it does not show up as a
"slow query"; keep it in every aggregate.

```sql
AND normalized_query_hash != normalizedQueryHash('SELECT hostname(), query_id FROM clusterAllReplicas(posthog, system.processes) WHERE query_id LIKE ? SETTINGS max_execution_time = 2')
```

## 0. Confirm retention covers the window

Run this first. If the earliest day is later than your window start, the archive does not go back far
enough and the report must say so.

```sql
SELECT toDate(event_time) AS day, count() AS rows
FROM posthog.query_log_archive
WHERE event_time > now() - INTERVAL 21 DAY
GROUP BY day ORDER BY day
```

## 1. Headline summary

Do not wrap the slow predicate in a CTE that projects only some columns: ClickHouse's analyzer prunes
columns and then cannot resolve a column used only in `WHERE`. Filter in the main query.

```sql
SELECT
    count() AS total_slow,
    round(sum(query_duration_ms)/3600000, 0) AS total_hours,
    round(avg(query_duration_ms)/1000) AS avg_s,
    round(max(query_duration_ms)/1000) AS max_s,
    countIf(exception_code = 0)   AS ok_slow,
    countIf(exception_code = 159) AS timeouts,
    countIf(exception_code = 241) AS ooms,
    countIf(exception_code NOT IN (0,159,160,241)) AS other_exc,
    countIf(lc_access_method = 'personal_api_key') AS via_api_key,
    uniqExact(team_id) AS teams,
    formatReadableSize(sum(read_bytes)) AS total_read
FROM posthog.query_log_archive
WHERE event_time > now() - INTERVAL 14 DAY
    AND is_initial_query
    AND (query_duration_ms > 30000 OR exception_code IN (159,160,241))
    AND normalized_query_hash != normalizedQueryHash('SELECT hostname(), query_id FROM clusterAllReplicas(posthog, system.processes) WHERE query_id LIKE ? SETTINGS max_execution_time = 2')
```

Quantiles (p90/p99) over the full set are expensive and can hit the Metabase ~60s cutoff. If the query
is cancelled, drop the quantiles or shorten the window.

## 2. Daily distribution

```sql
SELECT
    toDate(event_time) AS day,
    count() AS slow,
    countIf(exception_code = 159) AS timeouts,
    countIf(exception_code = 241) AS ooms,
    round(sum(query_duration_ms)/3600000, 1) AS total_hours
FROM posthog.query_log_archive
WHERE event_time > now() - INTERVAL 14 DAY
    AND is_initial_query
    AND (query_duration_ms > 30000 OR exception_code IN (159,160,241))
    AND normalized_query_hash != normalizedQueryHash('SELECT hostname(), query_id FROM clusterAllReplicas(posthog, system.processes) WHERE query_id LIKE ? SETTINGS max_execution_time = 2')
GROUP BY day ORDER BY day
```

## 3. Category breakdown

The backbone of the report: it separates background work from synchronous user-facing queries.

```sql
SELECT
    lc_kind, lc_product, lc_access_method,
    count() AS slow,
    uniqExact(team_id) AS teams,
    countIf(exception_code = 0)   AS ok_slow,
    countIf(exception_code = 159) AS timeouts,
    countIf(exception_code = 241) AS ooms,
    countIf(exception_code NOT IN (0,159,160,241)) AS other_exc,
    round(sum(query_duration_ms)/3600000, 1) AS total_hours,
    round(avg(query_duration_ms)/1000) AS avg_s,
    round(quantile(0.95)(query_duration_ms)/1000) AS p95_s,
    formatReadableSize(sum(read_bytes)) AS total_read
FROM posthog.query_log_archive
WHERE event_time > now() - INTERVAL 14 DAY
    AND is_initial_query
    AND (query_duration_ms > 30000 OR exception_code IN (159,160,241))
    AND normalized_query_hash != normalizedQueryHash('SELECT hostname(), query_id FROM clusterAllReplicas(posthog, system.processes) WHERE query_id LIKE ? SETTINGS max_execution_time = 2')
GROUP BY lc_kind, lc_product, lc_access_method
ORDER BY slow DESC LIMIT 40
```

## 4a. Per-team offenders by total cluster-time

```sql
SELECT
    team_id, lc_product, lc_kind,
    count() AS slow,
    countIf(exception_code = 241) AS ooms,
    countIf(exception_code = 159) AS timeouts,
    round(sum(query_duration_ms)/3600000, 1) AS total_hours,
    round(avg(query_duration_ms)/1000) AS avg_s,
    round(max(query_duration_ms)/1000) AS max_s,
    formatReadableSize(sum(read_bytes)) AS total_read
FROM posthog.query_log_archive
WHERE event_time > now() - INTERVAL 14 DAY
    AND is_initial_query
    AND (query_duration_ms > 30000 OR exception_code IN (159,160,241))
    AND team_id != 0
    AND normalized_query_hash != normalizedQueryHash('SELECT hostname(), query_id FROM clusterAllReplicas(posthog, system.processes) WHERE query_id LIKE ? SETTINGS max_execution_time = 2')
GROUP BY team_id, lc_product, lc_kind
ORDER BY total_hours DESC LIMIT 30
```

## 4b. OOM attribution

Rank OOMs by team + product + API key. If one row dominates, the cluster OOM "spike" is one tenant.

```sql
SELECT
    team_id, lc_product, lc_access_method, lc_kind, lc_api_key_label,
    countIf(exception_code = 241) AS ooms,
    round(avg(query_duration_ms)/1000) AS avg_s,
    formatReadableSize(avg(memory_usage)) AS avg_mem,
    formatReadableSize(sum(read_bytes)) AS total_read
FROM posthog.query_log_archive
WHERE event_time > now() - INTERVAL 14 DAY
    AND is_initial_query
    AND exception_code = 241
GROUP BY team_id, lc_product, lc_access_method, lc_kind, lc_api_key_label
ORDER BY ooms DESC LIMIT 25
```

To confirm an incident's timing and source, pin to the suspect team and watch it per day:

```sql
SELECT toDate(event_time) AS day, countIf(exception_code = 241) AS ooms, count() AS total,
    any(lc_query__kind) AS qkind, any(lc_route_id) AS route, any(lc_api_key_label) AS key_label
FROM posthog.query_log_archive
WHERE event_time > now() - INTERVAL 14 DAY AND is_initial_query AND team_id = <TEAM_ID>
GROUP BY day ORDER BY day
```

## 5. User-facing insight characterization

Synchronous web product-analytics queries (the ones a logged-in user waits on), by query kind, with
the two most common slowness signals.

```sql
SELECT
    lc_query__kind AS qkind,
    count() AS slow,
    uniqExact(team_id) AS teams,
    countIf(exception_code = 241) AS ooms,
    countIf(exception_code = 159) AS timeouts,
    round(avg(query_duration_ms)/1000) AS avg_s,
    countIf(query LIKE '%person_properties%' AND query LIKE '%JSONExtract%') AS json_person_props,
    countIf(query LIKE '%breakdown_value%') AS breakdowns,
    formatReadableSize(sum(read_bytes)) AS total_read
FROM posthog.query_log_archive
WHERE event_time > now() - INTERVAL 14 DAY AND is_initial_query
    AND lc_kind = 'request' AND lc_product = 'product_analytics' AND lc_access_method = ''
    AND (query_duration_ms > 30000 OR exception_code IN (159,160,241))
GROUP BY qkind ORDER BY slow DESC LIMIT 15
```

## 6. Example queries for the write-up

Use `--format json` and pull `query_id` + `event_date`. Bound the duration to skip a single stuck
outlier that would otherwise top the list.

```sql
SELECT query_id, event_date, team_id, lc_product, lc_kind, lc_query__kind,
    lc_temporal__workflow_type AS wf, lc_dashboard_id AS dash, lc_insight_id AS insight,
    query_duration_ms, exception_code,
    formatReadableSize(read_bytes) AS read, formatReadableSize(memory_usage) AS mem,
    substring(query, 1, 160) AS q
FROM posthog.query_log_archive
WHERE event_time > now() - INTERVAL 14 DAY AND is_initial_query
    AND (query_duration_ms > 30000 OR exception_code IN (159,160,241))
    AND query_duration_ms BETWEEN 60000 AND 5000000
ORDER BY query_duration_ms DESC LIMIT 20
```

Resolve any example later from the archive (the short-retention `system.query_log` lookup card will
miss anything older than a few hours):

```sql
SELECT * FROM posthog.query_log_archive
WHERE query_id = '<id>' AND event_date = '<YYYY-MM-DD>' AND is_initial_query
```
