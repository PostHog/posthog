---
name: writing-clickhouse-queries
description: Guide for writing performant ClickHouse queries in PostHog product code. Use when implementing a query runner extending QueryRunner, writing HogQL in backend Python under posthog/hogql_queries/ or posthog/hogql/, designing ClickHouse tables for a new product, choosing row ID formats (UUIDv7 vs UUID), adding materialized columns or skip indexes (minmax, bloom_filter, ngrambf_v1), testing that skip indexes are used, or debugging slow ClickHouse queries (EXPLAIN PLAN, trace logging, system.query_log). Covers HogQL vs raw SQL, QueryRunner patterns, UUID storage as UInt128, demo data generation, and the performance debugging workflow.
---

# Writing ClickHouse queries for new products

Canonical source: [handbook guide](https://posthog.com/handbook/engineering/databases/clickhouse-queries-new-products).
This skill mirrors the handbook for agents editing product code — prefer the handbook link when it is updated.

Related in-repo docs:

- [docs/published/handbook/engineering/databases/hogql-python.md](docs/published/handbook/engineering/databases/hogql-python.md)
- [docs/published/handbook/engineering/databases/materialized-columns.md](docs/published/handbook/engineering/databases/materialized-columns.md)
- [docs/published/handbook/engineering/databases/query-performance-optimization.md](docs/published/handbook/engineering/databases/query-performance-optimization.md)

## When to use

- Writing or reviewing a `QueryRunner` subclass in `posthog/hogql_queries/` or `products/*/backend/`
- Adding a new ClickHouse table or ALTER for a product (`posthog/clickhouse/migrations/`)
- Choosing a row ID format for a new table
- Adding or removing materialized columns, skip indexes, or projections
- Investigating a slow ClickHouse query in dev or prod

Not the right skill for: customer-facing ad-hoc HogQL via Max / `posthog:execute-sql` — use `query-examples` for that.

## Core rules

### 1. Use HogQL, not raw ClickHouse SQL

Always go through HogQL. The AST layer gives you, for free:

- **Team-ID guards** — `team_id = <team>` injected on every table access by [`team_id_guard_for_table()`](posthog/hogql/printer/clickhouse.py). Writing raw SQL risks cross-team data leaks.
- **Materialized property rewrites** — `properties.$browser` transparently resolves to the materialized column where it exists (up to 25× faster than JSON parsing).
- **Person-on-events mode** — the right join / column strategy is picked per team config. Don't branch on it yourself.
- **Per-query settings and modifiers** — join algorithm, materialization mode, projection optimization, etc.

Reach for raw SQL only when HogQL cannot express what you need, and document why.

### 2. Use backend query runners, not frontend HogQL

Define queries in Python subclasses of [`QueryRunner`](posthog/hogql_queries/query_runner.py) (or `AnalyticsQueryRunner` for analytics shapes). Constructing HogQL strings in the frontend skips caching, observability, and testability.

`QueryRunner` gives you:

- **Caching** — cache key derived from query, team, modifiers, timezone. Override `_refresh_frequency()` to tune.
- **Observability** — Prometheus metrics (`QUERY_EXECUTION_TOTAL`, `QUERY_EXECUTION_DURATION`) and PostHog analytics events.
- **Testability** — instantiate with a team + query schema, call `calculate()`, assert on the response. No HTTP.
- **Async execution, rate limiting, status tracking** — handled by the base class.

**Implementation checklist**

1. Define query and response schema in `frontend/src/queries/schema/schema-general.ts`. Python `schema.py` is auto-generated — do not edit it directly.
2. Subclass `QueryRunner` (or `AnalyticsQueryRunner`).
3. Implement `_calculate()` to build and execute your HogQL.
4. Register the runner in `get_query_runner()` in `posthog/hogql_queries/query_runner.py`.

Clean reference to copy from: [`EventsQueryRunner`](posthog/hogql_queries/events_query_runner.py).

### 3. Prefer UUIDv7 for row IDs, stored as UInt128

ClickHouse has a primary index (on-disk sort order) but no traditional secondary index. Most product tables need two access patterns:

1. Lookup by ID
2. Aggregation over a time range

The primary key can only satisfy one of those efficiently — so make your ID encode the timestamp. UUIDv7 does exactly that: the first 48 bits are the Unix timestamp in milliseconds. Helpers:

- Python: `uuid7()`
- TypeScript: `UUID7` class in `nodejs/src/utils/utils.ts`

**Store as `UInt128`, not `UUID`.** ClickHouse sorts `UUID` columns incorrectly — the internal representation swaps the high and low 64-bit words, so `ORDER BY uuid_col` is not chronological for UUIDv7. Convert with `reinterpretAsUInt128(toUUID(...))` or a materialized column at insert time. The sessions v3 table is the canonical example.

**Exception — person IDs.** Person IDs use UUIDv5 via `uuidFromDistinctId()` because they must be deterministic from `(team_id, distinct_id)` so the same person gets the same UUID before and after identify. Determinism outweighs time-sortability there.

## Query performance

### Materialize frequently filtered or grouped properties

If your query filters or groups by a specific property often, that property needs a materialized column. The auto-materialization cron (`analyze.py`) catches slow queries after the fact — for new products, materialize known hot properties up front via a ClickHouse migration. Migration `0147` is a good reference (materialized column + bloom filter index together).

### Pick the right skip index

ClickHouse data skipping indexes let the engine skip granules (blocks of rows) that cannot match. Pick the type to fit the column and the query:

| Index | Good for | Example migration |
| --- | --- | --- |
| `minmax` | Timestamp / numeric columns | `0222` on `$session_id_uuid` |
| `bloom_filter` | Equality / `IN` on high-cardinality columns; `Map` columns via `mapKeys`/`mapValues` | `0184` on `distinct_id` |
| `ngrambf_v1` | Substring / `ILIKE` on text (log bodies, emails, URLs, span names) | Logs table on `lower(body)` |

For `Map` columns, see `posthog/clickhouse/property_groups.py` for the reusable pattern (index `mapKeys` and `mapValues` separately).

For materialized property columns, use the `NgramLowerIndex` helper in `ee/clickhouse/materialized_columns/columns.py` — it handles the two ClickHouse quirks: case-insensitive text must be wrapped in `lower()`, and `Nullable` columns must be wrapped in `coalesce()`.

### Test that skip indexes are actually used

A skip index that is not covered by a test can silently stop working after any schema or printer change and give you a false sense of security.

Use `get_index_from_explain()` from `posthog.test.base` — it runs `EXPLAIN PLAN indexes=1, json=1` on a compiled HogQL query and checks whether a named skip index appears in the plan. Pattern (from `posthog/hogql/printer/test/test_printer.py`):

```python
from posthog.test.base import get_index_from_explain, materialized
from ee.clickhouse.materialized_columns.columns import get_minmax_index_name

def test_skip_index_is_used(self):
    with materialized("events", "test_prop", create_minmax_index=True) as mat_col:
        result = execute_hogql_query(
            team=self.team,
            query="SELECT distinct_id FROM events WHERE properties.test_prop = 'target_value'",
        )
        index_name = get_minmax_index_name(mat_col.name)
        assert get_index_from_explain(result.clickhouse, index_name), (
            f"Expected skip index {index_name} to be used"
        )
```

For a production safety net, set `forceClickhouseDataSkippingIndexes` on the query modifiers — ClickHouse will error if the index cannot be applied:

```python
from posthog.schema import HogQLQueryModifiers, MaterializationMode

result = execute_hogql_query(
    team=self.team,
    query="SELECT distinct_id FROM events WHERE properties.test_prop = 'foo'",
    modifiers=HogQLQueryModifiers(
        materializationMode=MaterializationMode.AUTO,
        forceClickhouseDataSkippingIndexes=[index_name],
    ),
)
```

Lower-level utilities for full-plan analysis: `find_all_reads()`, `guestimate_index_use()`, `execute_explain_get_index_use()` in `posthog/clickhouse/explain.py`, tested in `test_explain.py`.

## Performance debugging workflow

Before shipping a new query, verify it performs well at realistic data volumes.

### Step 1 — Generate demo data

Add your product's events and properties to the existing `HedgeboxMatrix` (do not subclass — too much overhead for most products). Then:

```bash
python manage.py generate_demo_data --n-clusters 10
```

Tune `--n-clusters` for volume vs runtime. Enough rows to expose the performance issues you will see in prod.

### Step 2 — Get the compiled ClickHouse SQL

- From a runner: `runner.to_query()` (compiles without executing)
- From `execute_hogql_query()`: `HogQLQueryResponse.clickhouse`
- From the UI: SQL editor → "Show ClickHouse SQL"

### Step 3 — EXPLAIN to check index usage

```sql
EXPLAIN PLAN indexes=1, json=1
SELECT ...your compiled query...
```

In the JSON output, inspect the `Indexes` array on each `ReadFromMergeTree` node:

- **Type** — `MinMax`, `Partition`, `PrimaryKey`, or a skip index name
- **Condition** — the filter the index is applying (`"true"` means it was not useful)
- **Initial Granules** vs **Selected Granules** — the latter should be much smaller

For pipeline / parallelism bottlenecks:

```sql
EXPLAIN PIPELINE
SELECT ...your compiled query...
```

### Step 4 — Trace logs

```bash
clickhouse-client --send_logs_level=trace --query "SELECT ...your compiled query..."
```

Shows granules and rows read per part, which indexes were applied and how effective they were, decompression volume, and per-stage time.

### Step 5 — Check `system.query_log`

```sql
SELECT
    query_duration_ms,
    read_rows,
    read_bytes,
    result_rows,
    memory_usage,
    ProfileEvents['SelectedMarks'] AS selected_marks,
    ProfileEvents['SelectedRanges'] AS selected_ranges
FROM system.query_log
WHERE type = 'QueryFinish'
ORDER BY event_time DESC
LIMIT 1
```

If `read_rows` is orders of magnitude larger than `result_rows`, filters are not pushing down — you need better indexing.

### Step 6 — Second opinion

Paste the compiled SQL and `EXPLAIN PLAN indexes=1, json=1` output into an LLM and ask whether primary key, partition key, and skip indexes are pulling their weight, whether any unintended scans are happening, and whether a different ordering or extra index would help.

## Related

- **Migrations:** use `clickhouse-migrations` skill for the migration file structure, node roles, and engine choices
- **HogQL internals:** `posthog/hogql/` (printer, database, modifiers)
- **Query runner base:** `posthog/hogql_queries/query_runner.py`
- **Materialized column helpers:** `ee/clickhouse/materialized_columns/columns.py`
- **EXPLAIN utilities:** `posthog/clickhouse/explain.py`
