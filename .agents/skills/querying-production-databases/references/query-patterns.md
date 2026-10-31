# Query patterns for the direct-query connections

Run the ClickHouse queries with `sendRawQuery: true` on the `Production` connection (or its EU match).
Run the Postgres queries in HogQL mode on the Postgres connection.
Replace each `<placeholder>` before you run a query.

## ClickHouse: the query log

`posthog.query_log_archive` holds the query log of every node, with about three weeks of retention.
Prefer it over `system.query_log`, which on the ops connection covers one node only.
The archive has typed columns in place of `log_comment`: `team_id`, `lc_workload`, `lc_kind`, `lc_access_method`, `lc_query_type`, `lc_product`, and more.
Read the full list with `SELECT name, type FROM system.columns WHERE database = 'posthog' AND table = 'query_log_archive'`.
Filter `event_date` as well as `event_time`, because the table is partitioned by date.
For a full slow-query report, use the patterns in [`generating-clickhouse-query-performance-reports`](../../generating-clickhouse-query-performance-reports/references/query-patterns.md). They run here unchanged.

A slow query is `query_duration_ms > 30000`, or one of these exception codes:

| Code | Meaning               |
| ---- | --------------------- |
| 159  | TIMEOUT_EXCEEDED      |
| 160  | TOO_SLOW              |
| 241  | MEMORY_LIMIT_EXCEEDED |

### Slowest user queries in the last day

```sql
SELECT
    query_id,
    team_id,
    query_duration_ms,
    formatReadableSize(memory_usage) AS memory,
    formatReadableSize(read_bytes) AS read_bytes,
    exception_code,
    lc_query_type,
    substring(query, 1, 200) AS query_preview
FROM posthog.query_log_archive
WHERE event_date >= yesterday()
    AND event_time > now() - INTERVAL 1 DAY
    AND is_initial_query
    AND (query_duration_ms > 30000 OR exception_code IN (159, 160, 241))
    AND lc_workload NOT IN ('Workload.OFFLINE', 'OFFLINE')
    AND lc_kind != 'temporal'
    AND team_id != 0
ORDER BY query_duration_ms DESC
LIMIT 50
```

### Query cost per team over one day

```sql
SELECT
    team_id,
    count() AS queries,
    countIf(query_duration_ms > 30000) AS slow_queries,
    formatReadableSize(sum(read_bytes)) AS total_read,
    quantile(0.95)(query_duration_ms) AS p95_duration_ms
FROM posthog.query_log_archive
WHERE event_date >= yesterday()
    AND event_time > now() - INTERVAL 1 DAY
    AND is_initial_query
    AND team_id != 0
GROUP BY team_id
ORDER BY sum(read_bytes) DESC
LIMIT 20
```

Widen the window one step at a time. A week of the whole archive is a heavy scan.

### One query by id

```sql
SELECT event_time, query_duration_ms, read_rows, read_bytes, memory_usage, exception, query
FROM posthog.query_log_archive
WHERE event_date = '<YYYY-MM-DD>'
    AND query_id = '<query id>'
```

## ClickHouse: cluster state on the ops connection

These read `system.*` on the node that the ops connection reaches.
Use them for a node-level view, not for fleet totals.

```sql
-- Running mutations
SELECT database, table, mutation_id, command, create_time, parts_to_do, latest_fail_reason
FROM system.mutations
WHERE NOT is_done
ORDER BY create_time
LIMIT 50
```

```sql
-- Active parts per table on this node
SELECT database, table, count() AS parts, formatReadableSize(sum(bytes_on_disk)) AS size
FROM system.parts
WHERE active
GROUP BY database, table
ORDER BY sum(bytes_on_disk) DESC
LIMIT 20
```

## ClickHouse: event data for one team

Event tables are huge. Filter `team_id` and a short `timestamp` window in every query.

```sql
SELECT toDate(timestamp) AS day, count() AS events
FROM posthog.events
WHERE team_id = <team id>
    AND timestamp >= now() - INTERVAL 14 DAY
    AND timestamp < now() + INTERVAL 1 DAY
GROUP BY day
ORDER BY day
```

## Postgres: the app database

The Postgres connection takes HogQL, so use HogQL functions and schema-qualified names.

```sql
-- New warehouse sources per source type in the last day
SELECT source_type, count() AS n
FROM public.posthog_externaldatasource
WHERE created_at >= now() - INTERVAL 1 DAY
GROUP BY source_type
ORDER BY n DESC
LIMIT 20
```

```sql
-- A team and its organization
SELECT t.id, t.name, t.organization_id, o.name AS organization_name
FROM public.posthog_team AS t
JOIN public.posthog_organization AS o ON o.id = t.organization_id
WHERE t.id = <team id>
```

A count grouped by tenant can scan a whole table, even with a `LIMIT` on the result.
Filter to one tenant, or bound the inner scan with a `LIMIT`.
For a query plan, use the Metabase skill, because this connection does not accept `EXPLAIN`.
