# Root-causing an individual slow query

This is the deep-dive behind the main skill's [Step 2 (smells)](../SKILL.md) and
[Step 3 (EXPLAIN)](../SKILL.md): once you have a specific slow query in front of you, this is how to
explain _why_ it is slow before you reach for a fix. Where Step 2 scans the SQL for known-bad shapes,
this reference works the other way round, from the runtime cost back to the cause.

It is written for a query you pulled from production (via `/query-clickhouse-via-metabase` against
`posthog.query_log_archive`, since the slowest real example beats a synthesized one), but the reasoning
applies to any slow query. You do not need certainty: a concrete, falsifiable hypothesis ("the sort key
is function-wrapped, so the date filter can't prune granules") is what drives the next step. Always state
one, then test it.

## Pull the full query, never a substring

When drilling into a specific query, select the **complete** `query` text plus the `exception` message,
not a `substring`. The smoking gun is almost always at the tail: the `ORDER BY`, the `WHERE` time
bound, the `LIMIT`, and the `SETTINGS` clause (`max_threads`, `max_execution_time`, `max_memory_usage`).
A scan-list preview that truncates at 160 chars will hide all of it.

```sql
SELECT query, exception, query_duration_ms,
       formatReadableSize(memory_usage) AS mem, formatReadableSize(read_bytes) AS read, read_rows
FROM posthog.query_log_archive
WHERE query_id = '<id>' AND event_date = '<YYYY-MM-DD>' AND is_initial_query
```

The `exception` message for an OOM (code 241) states the configured ceiling and the column that blew
it, e.g. `Query memory limit exceeded: would use 42.01 GiB, maximum: 42.00 GiB (while reading column
elements_chain)`. That column name is a direct pointer to what to look at.

## Read bytes, CPU time, and duration together

Three signals matter, and all three are worth pulling: **bytes read**, **CPU time**, and **duration**.
None of them on its own tells the whole story.

- **Bytes read** is the most stable measure of work done. Sort candidates by `read_bytes DESC`. Compare
  bytes against rows across queries in the same batch: if two queries read similar row counts but one
  reads ~100x more bytes, the heavy one is decompressing a wide column (almost always a `properties` JSON
  blob).

  ```text
  Query A: 210M rows,  19 GiB   -- materialized columns only
  Query B: 210M rows, 2.65 TiB  -- JSONExtractRaw(events.properties, '$some_prop')
  ```

- **CPU time** (`ProfileEvents['OSCPUVirtualTimeMicroseconds']`, or `query_duration_ms` vs CPU to gauge
  parallelism) catches work that bytes read misses: expensive expressions, high-cardinality
  aggregation, and grouping that burns CPU without reading much more data.

- **Duration** still matters, but with a hard rule: **never rely on the duration of the API request.**
  That number includes queueing, serialization, network, and app overhead, and does not reflect the
  ClickHouse query itself. When you report duration, it must come from `query_duration_ms` in
  `query_log` / `query_log_archive`, never from the API timing. Read against bytes and CPU, duration is
  most telling when it is _high but bytes and CPU are not_: that gap usually means the query spent its
  time **waiting** (on locks, on concurrency limits, on other queries), which is itself worth flagging.

## Common causes, most frequent first

These are the causes that come up most often, but they are only a subset: frequently the real problem is
something else entirely. Treat this list as a starting set of hypotheses to check, not an exhaustive
diagnosis, and stay open to a cause that is not listed here.

1. **Unmaterialized property access (JSONExtract).** The number-one cause of extreme byte reads.
   `JSONExtract*(events.properties, …)` or `JSONExtract*(person_properties, …)` forces a read of the
   full JSON blob per matching row. Confirm by searching the query text for `JSONExtract` / `JSONHas`.
   The fix depends on where the `JSONExtract` came from. If it's **hand-written in a printer-path query**
   (HogQL source that literally says `JSONExtractString(properties, 'X')`), the fix is to replace it with
   property access `properties.X` for every such property and let the printer materialize; the column may
   already be materialized in prod, so no migration is needed (see the JSON-operations smell in
   [`SKILL.md`](../SKILL.md)). If the **source already uses `properties.X`** (or it's raw SQL that bypasses
   the printer) and prod still emits `JSONExtract`, the property genuinely isn't materialized, so the
   fix is to materialize it (the migration layer in `SKILL.md` Step 5) or drop the property filter. This
   applies to both event and person property blobs: reading either as raw JSON can be up to ~100x slower
   than reading a directly materialized (`mat_*` / `dmat_*`) column, and ~10x slower than a property group
   read.
2. **Session joins.** Joining `raw_sessions` / `sharded_sessions` (for `$session_duration` etc.) adds a
   full sessions scan. Look for `raw_sessions` in the text.
3. **High-cardinality breakdowns.** A `breakdown_value` on something like a URL or an ID explodes the
   grouping. This is the dominant OOM driver for user-facing `TrendsQuery`.
4. **High-volume event as a funnel/first step.** `$pageview` as a step scans all pageviews; index
   pruning helps but the raw volume is large.
5. **Ratio / multi-series metrics with double scans.** Numerator and denominator each run their own
   scan and person-overrides join; doubles the work when both use high-volume events.
6. **All-time or multi-month date ranges.** Scans proportionally more data; check the range.
7. **Function-wrapped sort/filter keys defeating index pruning.** When the `WHERE` time bound or
   `ORDER BY` wraps the sort column in a function (e.g. `coalesce(toTimeZone(timestamp, …))` instead of
   raw `timestamp`), ClickHouse can't match it to the primary key, so the filter drops to a Prewhere
   row filter (no granule pruning) and the read scans far more than the requested window, often the
   team's full history. On a wide table (events), reading `properties` / `elements_chain` for that
   inflated row set under a high `max_threads` is a classic OOM, and where it does not OOM it hits the
   `max_execution_time` cap as a timeout. Watch for no-op wrappers like a single-argument `coalesce()`
   on a non-nullable column. Confirm with EXPLAIN by diffing granule counts (below).

## Tracing a query back to its origin

The `lc_*` columns exist **only on `query_log_archive`**: they are the pre-parsed `log_comment` tags.
`system.query_log` carries the exact same information, but unparsed, inside its `log_comment` JSON blob,
so on `query_log` you read the field out of that JSON (e.g. `JSONExtractString(log_comment, 'query_type')`)
instead of selecting an `lc_*` column. The table below uses the `query_log_archive` column names.

These tags tell you what triggered the query without reverse-engineering the SQL:

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

## EXPLAIN to test the hypothesis

Per the [ClickHouse EXPLAIN docs](https://clickhouse.com/docs/sql-reference/statements/explain), no
EXPLAIN variant executes the query or scans table data, so EXPLAIN is safe to run against prod at any
size. Two variants are not entirely free, though: `EXPLAIN ESTIMATE` and `EXPLAIN indexes=1` read primary
index marks / part metadata to do their analysis. That is a small metadata read, not a data scan, but it
is not zero, so prefer the lighter plan-only variants (`actions=1`, `PIPELINE`) when you do not
specifically need index pruning numbers, and avoid hammering `indexes=1` in a tight loop. If in doubt,
re-check the current docs before running a variant at scale. Pull the query text, strip the leading
`/* … */` tag comment, and prepend the EXPLAIN modifier that answers your question:

- `EXPLAIN actions=1`: the full plan, showing the `Sorting` step, `ReadType` (`InOrder` vs `Default`),
  and whether a filter is a primary-key condition or only a `Prewhere` row filter.
- `EXPLAIN indexes=1`: per-index granule pruning (`Granules: X/Y`, which skip indexes fired).
- `EXPLAIN PIPELINE`: the executor pipeline (thread fan-out, merge stages).
- `EXPLAIN json=1`: machine-readable, handy for diffing two plans programmatically.

The strongest technique is to **EXPLAIN the suspect query and a fixed variant side by side, then diff**.
For the function-wrapped-key case, compare the generated `ORDER BY coalesce(toTimeZone(timestamp, …))`
against raw `ORDER BY timestamp`: a large drop in `Granules` (full history shrinks to just the date
window) and the time bound moving from Prewhere into the primary-key condition confirms the wrapper is
the cause.

Signals to read off the plan:

- **`Granules: X`**: how many 8192-row blocks survive index pruning. A wrapped/opaque filter shows a
  much larger granule count than the equivalent raw-column filter; that delta is the wasted scan.
- **`ReadType: InOrder` vs `Default`**: whether `optimize_read_in_order` applies. Note the events
  table is ordered by `toDate(timestamp)`, not sub-day, so ordering by full `timestamp` still sorts;
  do not infer read-in-order from a date sort alone.
- **`Prewhere filter` vs primary-key condition**: a time bound in Prewhere is evaluated row-by-row and
  does not prune granules; in the primary-key condition it does.
- **Skip-index effectiveness** (e.g. `minmax_mat_*`): how many granules each eliminates.
- **Bytes vs rows**: similar granule counts but wildly different bytes means a column-width problem
  (the JSON blob again).

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
