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

## 1b. Cluster-wide totals (all queries, the honest denominator)

The headline above is the slow set only, which is a biased subset (~0.2% of queries but a large share of
bytes and query-time). Capture the totals across **all** `is_initial_query` queries too, so the report
records the real denominator and a baseline future reports can diff against. Record total query-seconds,
total CPU-seconds, total bytes read, and total OOMs.

Use the **typed flattened** `ProfileEvents_OSCPUVirtualTimeMicroseconds` column for CPU time. Do **not**
use `ProfileEvents['OSCPUVirtualTimeMicroseconds']` (the `Map` form): a map lookup over the full
~180M-row window times out even at a 300s client timeout, while the typed Int64 column sums in seconds.

```sql
SELECT
    count() AS all_queries,
    round(sum(query_duration_ms)/1000, 0)                          AS total_query_seconds,
    round(sum(ProfileEvents_OSCPUVirtualTimeMicroseconds)/1e6, 0)  AS total_cpu_seconds,
    formatReadableSize(sum(read_bytes))                            AS total_read_all,
    countIf(exception_code = 241)                                  AS total_ooms
FROM posthog.query_log_archive
WHERE event_time > now() - INTERVAL 14 DAY AND is_initial_query
```

CPU-seconds exceed wall query-seconds because queries run multi-threaded; the ratio is rough average
parallelism. `total_ooms` here equals the slow-set OOM count (every OOM is in the slow set by
definition), so it is directly comparable across reports even when the all-query totals are not yet
available historically. These all-query totals cannot be backfilled for an old report once its window
ages past the archive's ~3-week retention.

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

## 4c. Top consumers by resource (all queries, not just slow)

Attribute total cluster resource use across **all** `is_initial_query` queries, not just the slow set:
this catches consumers that cost the cluster through many cheap queries without ever crossing the slow
threshold (and so are invisible to 4a/4b). Report top teams, top API keys, and top tools by **all three of
bytes / CPU / wall-time** (the leader differs by metric). Use the typed
`ProfileEvents_OSCPUVirtualTimeMicroseconds` column, not the `Map` lookup (§1b). Re-run each block with a
different `ORDER BY` (`cpu_hours`, `sum(read_bytes)`, `query_hours`) to get the per-metric leaders. The
CPU:wall ratio per row separates compute-bound (ratio >> 1, highly parallel) from wait/IO-bound (ratio
~1 or below) consumers.

```sql
-- top teams (swap ORDER BY for the bytes / wall-time rankings)
SELECT team_id,
    round(sum(query_duration_ms)/3600000, 0)                       AS query_hours,
    round(sum(ProfileEvents_OSCPUVirtualTimeMicroseconds)/3.6e9, 0) AS cpu_hours,
    formatReadableSize(sum(read_bytes))                            AS bytes_read,
    countIf(exception_code = 241)                                  AS ooms,
    count()                                                        AS queries
FROM posthog.query_log_archive
WHERE event_time > now() - INTERVAL 14 DAY AND is_initial_query AND team_id != 0
GROUP BY team_id ORDER BY cpu_hours DESC LIMIT 15
```

```sql
-- top named API keys / integrations (lc_api_key_label); swap ORDER BY as above
SELECT lc_api_key_label,
    round(sum(query_duration_ms)/3600000, 0)                       AS query_hours,
    round(sum(ProfileEvents_OSCPUVirtualTimeMicroseconds)/3.6e9, 0) AS cpu_hours,
    formatReadableSize(sum(read_bytes))                            AS bytes_read,
    countIf(exception_code = 241) AS ooms, uniqExact(team_id) AS teams, count() AS queries
FROM posthog.query_log_archive
WHERE event_time > now() - INTERVAL 14 DAY AND is_initial_query AND lc_api_key_label != ''
GROUP BY lc_api_key_label ORDER BY cpu_hours DESC LIMIT 15
```

```sql
-- top tools (lc_product), cluster-wide (this is the all-query counterpart to the §3 slow-set categories)
SELECT lc_product,
    round(sum(query_duration_ms)/3600000, 0)                       AS query_hours,
    round(sum(ProfileEvents_OSCPUVirtualTimeMicroseconds)/3.6e9, 0) AS cpu_hours,
    formatReadableSize(sum(read_bytes))                            AS bytes_read,
    countIf(exception_code = 241) AS ooms, uniqExact(team_id) AS teams, count() AS queries
FROM posthog.query_log_archive
WHERE event_time > now() - INTERVAL 14 DAY AND is_initial_query
GROUP BY lc_product ORDER BY cpu_hours DESC LIMIT 15
```

A grouped aggregation over the full ~180M-row window is heavier than the slow-set queries; if Metabase
returns a 502 or times out, retry (transient) or raise `--timeout`. `any(lc_product)` per team is
non-deterministic (a team spans products), so annotate notable teams by hand rather than trusting it.

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
outlier that would otherwise top the list. The `substring(query, 1, 160)` here is only for skimming the
list; when you drill into one query, pull the **full** `query` text (see the
[`optimizing-clickhouse-and-hogql-queries`](../../optimizing-clickhouse-and-hogql-queries/references/investigation-playbook.md)
investigation playbook — the `ORDER BY` / `WHERE` / `SETTINGS` tail is where the cause usually is).

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

### Shareable link to a single query

For each example in a report, link to a self-contained Metabase URL that carries the SQL in its hash
fragment, so a reader clicks straight through to the query in `query_log_archive`. This survives the
short `system.query_log` retention (unlike the old `795-look-up-query-by-query-id` card). Build it by
base64-encoding the native-query payload:

```python
import base64, json

BASE = {"us": "https://metabase.prod-us.posthog.dev", "eu": "https://metabase.prod-eu.posthog.dev"}

def _ch_literal(value: str) -> str:
    # query_id derives from the caller-supplied client_query_id, so it can contain a single quote.
    # Escape for a ClickHouse single-quoted literal by doubling quotes. Treat this as required, not
    # cosmetic: Metabase may execute the embedded native query on load, so an unescaped quote is a real
    # injection vector, not just malformed SQL in an editor.
    return str(value).replace("'", "''")

def query_link(query_id, event_date, region="us", database_id=43):
    # database_id is a ClickHouse connection on the cluster (US 43). IDs can change when Metabase's
    # metadata is rebuilt: rediscover with `hogli metabase:databases` and any ClickHouse id works,
    # since query_log_archive is a Distributed table. EU needs its own id.
    sql = (f"  SELECT lc_query__query FROM posthog.query_log_archive\n"
           f"  WHERE query_id = '{_ch_literal(query_id)}'\n"
           f"    AND event_date = '{_ch_literal(event_date)}' AND is_initial_query")
    payload = {
        "dataset_query": {"type": "native", "native": {"query": sql, "template-tags": {}}, "database": database_id},
        "display": "table", "parameters": [], "visualization_settings": {},
    }
    blob = base64.b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode()
    return f"{BASE[region]}/question#{blob}"
```

`SELECT lc_query__query` shows the originating product query; widen the SELECT (e.g. `*`, or `query`
for the executed ClickHouse SQL) if you want more detail in the linked view. Example output:

```text
https://metabase.prod-us.posthog.dev/question#eyJkYXRhc2V0X3F1ZXJ5Ijp7InR5cGUiOiJuYXRpdmUiLCJ...
```

## 7. JSON-extracted properties: which names, which teams

A core report output and the input to materialization. Pulls the property names that slow queries
`JSONExtract` out of a JSON blob, split by which blob (`properties` = event, `person_properties` =
person, `group_properties` = group), with the teams driving each. `extractAllGroupsVertical` returns
one `[alias, column, name]` triple per match; `ARRAY JOIN` explodes them.

```sql
SELECT
    column,                                 -- properties (event) | person_properties | group_properties
    property,
    sum(c) AS slow_queries,
    uniqExact(team_id) AS teams,
    sum(failures) AS failures,              -- OOM + timeout among them
    arraySlice(arrayReverseSort(x -> x.2, groupArray((team_id, c))), 1, 5) AS top_teams_by_count
FROM (
    SELECT g[2] AS column, g[3] AS property, team_id,
        count() AS c,
        countIf(exception_code IN (159,160,241)) AS failures
    FROM posthog.query_log_archive
    ARRAY JOIN extractAllGroupsVertical(query, 'JSONExtract\\w*\\((\\w+)\\.(\\w*properties),\\s*''([^'']+)''') AS g
    WHERE event_time > now() - INTERVAL 14 DAY
        AND is_initial_query
        AND (query_duration_ms > 30000 OR exception_code IN (159,160,241))
        AND query LIKE '%JSONExtract%'
    GROUP BY column, property, team_id
)
GROUP BY column, property
ORDER BY slow_queries DESC LIMIT 30
```

`top_teams_by_count` reads as `[[team_id, query_count], ...]`. Caveat: a query that extracts N
properties contributes one row per property after the `ARRAY JOIN`, so `slow_queries` counts
property-occurrences, not distinct queries (which is what you want for ranking materialization
candidates). The regex captures the first key only, so a nested path `JSONExtract(properties, 'a', 'b')`
shows as `a`.

To drill one property and list every team using it:

```sql
SELECT team_id, count() AS slow_queries,
    countIf(exception_code IN (159,160,241)) AS failures,
    formatReadableSize(avg(read_bytes)) AS avg_read
FROM posthog.query_log_archive
WHERE event_time > now() - INTERVAL 14 DAY AND is_initial_query
    AND (query_duration_ms > 30000 OR exception_code IN (159,160,241))
    AND match(query, 'JSONExtract\\w*\\(\\w+\\.\\w*properties,\\s*''<PROPERTY>''')
GROUP BY team_id ORDER BY slow_queries DESC LIMIT 30
```
