---
title: Writing ClickHouse queries for new products
sidebar: Handbook
showTitle: true
---

This guide covers best practices for writing ClickHouse queries when shipping new products at PostHog.

Related reading:

- [Writing HogQL queries in Python](./hogql-python.md)
- [Query performance optimization](./query-performance-optimization.md)
- [Materialized columns](./materialized-columns.md)
- [Query attribution](https://posthog.com/handbook/engineering/clickhouse/query-attribution)

## Use HogQL, not raw ClickHouse SQL

Always use [HogQL](./hogql-python.md) rather than writing raw ClickHouse SQL. HogQL is our AST-powered layer on top of ClickHouse SQL that provides critical safety and performance guarantees automatically.

### Why HogQL

HogQL gives you:

- **Automatic team ID guards**: Every query gets an automatic `team_id = <your_team_id>` filter injected on every table access (via [`team_id_guard_for_table()`](https://github.com/PostHog/posthog/blob/master/posthog/hogql/printer/clickhouse.py#L53-L63)), preventing cross-team data leaks.
- **Materialized property optimizations**: Property accesses like `properties.$browser` are automatically rewritten to use pre-extracted materialized columns where available – up to 25x faster than parsing JSON at query time.
- **Person join optimizations**: [Person-on-events (PoE) mode](https://github.com/PostHog/posthog/blob/master/posthog/hogql/database/database.py#L871-L895) is handled automatically – the right join or column strategy is selected based on team configuration, with no manual handling required.
- **Customer-specific query settings**: Per-query [settings](https://github.com/PostHog/posthog/blob/master/posthog/hogql/constants.py#L114-L139) and [modifiers](https://github.com/PostHog/posthog/blob/master/posthog/schema.py) (join algorithm, materialization mode, projection optimization, etc.) can be tuned per-team or per-query.

## Use backend query runners, not frontend-defined queries

Define your queries using backend Python query runners rather than constructing HogQL in the frontend. The base class is [`QueryRunner`](https://github.com/PostHog/posthog/blob/master/posthog/hogql_queries/query_runner.py#L974-L1029) in `query_runner.py`.

### Why query runners

The `QueryRunner` base class gives you:

- **Caching**: Built-in caching with configurable refresh intervals. Override [`_refresh_frequency()`](https://github.com/PostHog/posthog/blob/master/posthog/hogql_queries/insights/trends/trends_query_runner.py#L125-L142) to control how often results are refreshed. Cache keys are automatically derived from the query, team, modifiers, and timezone via `get_cache_key()`.

- **Observability**: Query execution is automatically instrumented with Prometheus metrics (`QUERY_EXECUTION_TOTAL`, `QUERY_EXECUTION_DURATION`) and PostHog analytics events, giving you latency histograms and error breakdowns for free.

- **Testability**: Query runners are straightforward to unit test – instantiate the runner with a team and a query schema, call `calculate()`, and assert on the response. No HTTP layer needed.

- **Async execution**: The base class handles async query execution, rate limiting, and query status tracking automatically.

### How to implement one

1. Define your query and response schema types in `frontend/src/queries/schema/schema-general.ts` (or `frontend/src/types.ts`). The Python `schema.py` is auto-generated from these – don't edit it directly.
2. Create a runner class extending `QueryRunner` (or `AnalyticsQueryRunner` for analytics-style queries)
3. Implement `_calculate()` to build and execute your HogQL query
4. Register your runner in [`get_query_runner()`](https://github.com/PostHog/posthog/blob/master/posthog/hogql_queries/query_runner.py)

For a clean example to follow, see [`EventsQueryRunner`](https://github.com/PostHog/posthog/blob/master/posthog/hogql_queries/events_query_runner.py).

## Use time-sortable IDs (UUIDv7)

If your product stores data in ClickHouse, prefer UUIDv7 for your row IDs. We have implementations in both Python (`uuid7()`) and TypeScript ([`UUID7` class](https://github.com/PostHog/posthog/blob/master/nodejs/src/utils/utils.ts#L260-L305)).

### Why this matters

ClickHouse tables have a primary index (roughly: the order rows are stored on disk) but no secondary index in the traditional RDBMS sense. You almost certainly need to support two access patterns:

1. **Lookup by ID** – fetching a specific row
2. **Aggregation over a time range** – analytics queries filtering by timestamp

Since ClickHouse can only efficiently filter on the primary key order, your ID must also encode the timestamp. [UUIDv7](https://www.rfc-editor.org/rfc/rfc9562#name-uuid-version-7) solves this: the first 48 bits are the Unix timestamp in milliseconds, so rows are naturally time-ordered.

### Canonical example: session IDs

The sessions v3 table is the canonical example of this pattern:

```sql
-- Both UInt128 and UUID are imperfect choices here
-- see https://michcioperz.com/wiki/clickhouse-uuid-ordering/
-- but also see https://github.com/ClickHouse/ClickHouse/issues/77226 and hope
session_id_v7 UInt128,
```

### ClickHouse UUID sorting is broken – use UInt128

ClickHouse does not sort UUIDs correctly as of today. The internal representation swaps the high and low 64-bit words, so `ORDER BY uuid_column` does not produce chronological order for UUIDv7s. This is a [known issue](https://michcioperz.com/wiki/clickhouse-uuid-ordering/) (see also [ClickHouse issue #77226](https://github.com/ClickHouse/ClickHouse/issues/77226)).

The workaround is to store your UUIDv7 as `UInt128` instead of `UUID`. You can convert with `reinterpretAsUInt128(toUUID(...))` or use a materialized column to do this at insert time. See the session ID materialization migration for an example of this conversion at the data layer.

### When not to use UUIDv7

You need a good reason to use a different format. The main exception is person IDs, which use UUIDv5 via `uuidFromDistinctId()`. Person IDs are deterministic based on `(team_id, distinct_id)` – this is critical because the same person must get the same UUID both before and after an identify call. This determinism requirement outweighs the benefits of time-sortability.

## Query performance

### Ensure relevant columns are materialized

If your product frequently filters or groups by a specific property, you should ensure that property has a materialized column. Materialized columns store JSON property values as separate columns on disk, making reads up to 25x faster.

Properties are automatically materialized by a cron job that analyzes slow queries (see `analyze.py`). But for new products, you may want to proactively create materialized columns for properties you know will be heavily queried. You can do this via a ClickHouse migration – see migration 0147 for an example that adds both a materialized column and a bloom filter index.

For more details, see the [materialized columns handbook page](./materialized-columns.md).

### Consider adding skip indexes

ClickHouse data skipping indexes allow the engine to skip granules (blocks of rows) that definitely don't match your query filter. Common types:

- **`minmax`** – tracks the min and max value per granule. Good for timestamp or numeric columns. Example: migration 0222 adds a `minmax` index on `$session_id_uuid`.
- **bloom_filter** – probabilistic index for equality and IN lookups on high-cardinality columns. Example: migration 0184 adds a bloom filter on `distinct_id`. Bloom filters also support Map columns – you can index `mapKeys(my_map)` and `mapValues(my_map)` separately to speed up lookups into map-typed columns. See the Logs table and spans table for examples, and `property_groups.py` for the reusable pattern.
- **ngrambf_v1** – n-gram bloom filter for `substring` and `ILIKE` searches on text columns. Good for things like log bodies, email addresses, URLs, or any column where users will do partial-match searches. Examples: the Logs table indexes `lower(body)` with `ngrambf_v1(3, 25000, 2, 0)`, and the spans table indexes span name. For materialized property columns, we have a reusable `NgramLowerIndex` helper that handles the ClickHouse limitations around case-insensitivity (must wrap in `lower()`) and `Nullable` columns (must wrap in `coalesce()`).

### Test that your skip indexes are actually used

If you add a skip index, write a test that asserts it is used. A skip index that isn't tested can silently stop working after schema changes, giving you a false sense of security.

We have a test helper `get_index_from_explain()` that runs `EXPLAIN PLAN indexes=1,json=1` on a compiled HogQL query and checks whether a specific named skip index appears in the plan. Here's the pattern from `test_printer.py`:

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

You can also use the `forceClickhouseDataSkippingIndexes` modifier to make ClickHouse error if a specified skip index can't be used – this acts as a safety net in production:

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
# ClickHouse will raise an error if the index can't be applied
```

See the full test examples in `test_printer.py` for both the success and failure cases.

There are also lower-level utilities in `explain.py` (`find_all_reads()`, `guestimate_index_use()`, `execute_explain_get_index_use()`) and corresponding tests in `test_explain.py` that analyze full EXPLAIN plans for index effectiveness across all table reads.

### Debugging query performance

Before shipping, you should verify that your queries perform well with realistic data volumes. Here's a workflow for doing this.

#### Step 1: Add your product to demo data generation

The `generate_demo_data` management command uses a Matrix simulation framework to generate realistic-looking data. Rather than creating a new Matrix subclass (which is significant overhead), add your product's events and properties to the existing `HedgeboxMatrix`. This is the default simulation and already generates a rich set of users, sessions, and behavioral patterns – you just need to add your product's events alongside the existing ones.

Run it with:

```bash
python manage.py generate_demo_data --n-clusters 10
```

Tweak the `--n-clusters` number as appropriate – higher values generate more data but take longer to run. This gives you a local dev environment with enough data to spot performance issues that wouldn't appear with a handful of rows.

#### Step 2: Get the compiled ClickHouse SQL

To debug performance, you need the actual ClickHouse SQL that HogQL compiles to. There are a few ways:

- **From a query runner**: Call `runner.to_query()` to get the compiled SQL without executing it
- **From `execute_hogql_query()`**: The returned `HogQLQueryResponse` includes a `.clickhouse` field with the compiled SQL
- **From the PostHog UI**: Open the query in the SQL editor and click "Show ClickHouse SQL"

#### Step 3: Run EXPLAIN to check index and partition usage

Once you have the compiled SQL, run it through ClickHouse's EXPLAIN to see how the query planner will execute it:

```sql
EXPLAIN PLAN indexes=1, json=1
SELECT ...your compiled query...
```

The key options:

- `indexes=1` – shows which indexes (primary key, partition key, skip indexes) are used and how many granules they filter
- `json=1` – outputs structured JSON so you can parse it programmatically

In the output, look for the `Indexes` array on each `ReadFromMergeTree` node. Each index entry shows:

- **Type** – `MinMax`, `Partition`, `PrimaryKey`, or a skip index name
- **Condition** – the filter condition applied (if `"true"`, the index wasn't useful)
- **Initial Granules** – granules before this index was applied
- **Selected Granules** – granules after (this should be significantly smaller than Initial Granules)

You can also run a pipeline analysis to see the execution plan including parallelism:

```sql
EXPLAIN PIPELINE
SELECT ...your compiled query...
```

This can reveal bottlenecks like single-threaded aggregation stages.

#### Step 4: Run the query with trace logging

To see what ClickHouse is actually doing during execution – including how much data it reads, which parts are slow, and where time is spent – run the query with trace-level logging via `clickhouse-client`:

```bash
clickhouse-client --send_logs_level=trace --query "SELECT ...your compiled query..."
```

This outputs detailed trace output showing:

- How many granules and rows were read from each part
- Which indexes were applied and how effective they were
- How much data was decompressed
- Time spent in each pipeline stage

#### Step 5: Check the query log for execution stats

After running a query, you can inspect its execution stats in `system.query_log`:

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

If `read_rows` is orders of magnitude larger than `result_rows`, your filters aren't being pushed down effectively and you likely need better indexing.

#### Step 6: Get a second opinion

At the very least, take your `EXPLAIN PLAN indexes=1, json=1` output and the compiled SQL, and paste them into an LLM to get a sanity check. Ask it to identify:

- Whether primary key / partition key indexes are being used effectively
- Whether any table scans are happening that shouldn't be
- Whether skip indexes are being applied
- Whether the query could benefit from different ordering or additional indexes

This is a quick way to catch obvious performance problems before they reach production.
