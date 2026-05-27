# Root-causing an individual slow query

Once a finding points at a specific query or pattern, this is how to explain _why_ it is slow. Run
everything via the `query-clickhouse-via-metabase` skill against `posthog.query_log_archive`.

## Start from bytes read, not duration

Duration drifts with cluster load and cache warmth; **bytes read is the stable measure of work done**.
Sort candidates by `read_bytes DESC`. Compare bytes against rows across queries in the same batch: if
two queries read similar row counts but one reads ~100x more bytes, the heavy one is decompressing a
wide column (almost always a `properties` JSON blob).

```text
Query A: 210M rows,  19 GiB   -- materialized columns only
Query B: 210M rows, 2.65 TiB  -- JSONExtractRaw(events.properties, '$some_prop')
```

## Common causes, most frequent first

1. **Unmaterialized property access (JSONExtract).** The number-one cause of extreme byte reads.
   `JSONExtract*(events.properties, …)` or `JSONExtract*(person_properties, …)` forces a read of the
   full JSON blob per matching row. Confirm by searching the query text for `JSONExtract` / `JSONHas`;
   then check whether the property has a `mat_<property>` column. Fix: materialize it (see
   `materialization-analysis.md`) or drop the property filter. Person properties are the worst because
   the blobs are large.
2. **Session joins.** Joining `raw_sessions` / `sharded_sessions` (for `$session_duration` etc.) adds a
   full sessions scan. Look for `raw_sessions` in the text.
3. **High-cardinality breakdowns.** A `breakdown_value` on something like a URL or an ID explodes the
   grouping. This is the dominant OOM driver for user-facing `TrendsQuery`.
4. **High-volume event as a funnel/first step.** `$pageview` as a step scans all pageviews; index
   pruning helps but the raw volume is large.
5. **Ratio / multi-series metrics with double scans.** Numerator and denominator each run their own
   scan and person-overrides join; doubles the work when both use high-volume events.
6. **All-time or multi-month date ranges.** Scans proportionally more data; check the range.

## Tracing a query back to its origin

The `lc_*` columns tell you what triggered the query without reverse-engineering the SQL:

| Column                                                                    | Tells you                                                  |
| ------------------------------------------------------------------------- | ---------------------------------------------------------- |
| `lc_query__kind`                                                          | Product query type (`TrendsQuery`, `ExperimentQuery`, ...) |
| `lc_route_id`                                                             | API route that handled the request                         |
| `lc_dashboard_id` / `lc_insight_id` / `lc_experiment_id` / `lc_cohort_id` | The object that fired it                                   |
| `lc_feature`, `lc_temporal__workflow_type`, `lc_dagster__job_name`        | Background-job origin                                      |
| `lc_access_method`, `lc_api_key_label`                                    | Whether it came from the web, OAuth, or a named API key    |
| `lc_user_id`                                                              | Who triggered it                                           |

The full `log_comment` (raw, on `system.query_log`) additionally carries `http_referer`, `scene`, and
`source_file`/`source_line`. These tags are defined in `posthog/clickhouse/query_tagging.py`
(`QueryTags`).

To reverse-engineer SQL, grep the PostHog codebase for the `lc_query__kind` value (e.g. `TrendsQuery`)
to find the query runner that generates it.

## EXPLAIN the worst queries

Pull the query text, strip the leading `/* … */` tag comment, and prepend `EXPLAIN indexes=1`:

```sql
EXPLAIN indexes=1 WITH … SELECT …
```

Look for:

- **`ReadFromMergeTree` granule counts** (`Granules: X/Y`): how many survive each index stage. Lower is better.
- **PrimaryKey condition**: confirm event-name filters reach the primary key (`event = A OR event = B` is fine).
- **Skip-index effectiveness** (e.g. `minmax_mat_*`): how many granules each eliminates.
- **Bytes vs rows**: similar granule counts but wildly different bytes means a column-width problem (the blob again).

## Concurrency and timing notes

- In `query_log`, `event_time` is the **completion** time for `QueryFinish` rows. Use
  `query_start_time_microseconds` when reconstructing concurrency, or short queries that finish first
  will look like they ran first.
- A single experiment page load fires **one query per metric**, dispatched via celery with limited
  parallelism. Wall-clock ≈ dispatch overhead + the longest single query; total data scanned is the
  **sum** across metric queries. Same query length does not mean same query; distinguish by
  `client_query_id`.
- `person_distinct_id_overrides` joins are expected and mandatory for correct person resolution. Do not
  flag them on their own; they are the cost of correctness. A query joining **both**
  `person_distinct_id_overrides` and `person_distinct_id2` is the pattern worth a closer look.

## Codebase map (in `../posthog` or the public repo)

| Path                                            | What it explains                                                                                             |
| ----------------------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| `posthog/hogql/printer/base.py`                 | HogQL → SQL; the materialization decision tree (`mat_*` → `dmat_*` → property groups → JSONExtract fallback) |
| `posthog/hogql/transforms/property_types.py`    | Whether a property access uses a materialized column or JSON extraction                                      |
| `posthog/hogql/property.py`                     | How property filters become AST (person properties → `["person","properties"]` chain)                        |
| `posthog/hogql/database/schema/events.py`       | Events table schema; lazy joins to person, pdi, sessions, groups                                             |
| `posthog/hogql/database/database.py`            | Person-on-events mode: how `person_id` resolves via overrides vs pdi2                                        |
| `posthog/hogql_queries/experiments/`            | How experiment queries build exposure CTEs and resolve persons                                               |
| `ee/clickhouse/materialized_columns/analyze.py` | Auto-materialization logic (properties in 10+ slow queries reading >20GB or >5M rows)                        |
| `posthog/clickhouse/query_tagging.py`           | The `QueryTags` model behind the `lc_*` columns                                                              |
