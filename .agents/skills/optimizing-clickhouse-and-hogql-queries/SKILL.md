---
name: optimizing-clickhouse-and-hogql-queries
description: Workflow for optimizing ClickHouse and HogQL queries. Use when a HogQL query, query runner, insight, or report is too slow; when a hand-written ClickHouse query (via `sync_execute` or in a migration) is too slow; when ClickHouse times out or hits memory limits; when investigating a slow `system.query_log` row; or when reviewing a proposed HogQL printer change for performance. Covers extracting the ClickHouse SQL (for HogQL queries), common smells (`FROM ... FINAL`, `JSONExtract` over properties, missing skip indexes, self-joins, CTE blow-up), measuring against a real cluster, and applying the fix at the right layer (printer, query runner, or ClickHouse migration). Does NOT cover Postgres / Django ORM / app-database queries; those need pganalyze and the Postgres section of `query-performance-optimization.md`, not this skill.
---

# Optimizing ClickHouse and HogQL queries

**Scope:** this skill optimizes **ClickHouse queries** and **HogQL queries** (which compile to ClickHouse). It does **not** optimize Postgres / Django ORM / app-database queries. If the slow query you're holding is a `Model.objects.filter(...)` or any other call against the app DB, stop and use pganalyze + the Postgres section of [`query-performance-optimization.md`](../../../docs/published/handbook/engineering/databases/query-performance-optimization.md) instead. Step 0 below has the full triage.

The best way to optimize a HogQL query is to **start with the ClickHouse SQL it produces, optimize that, then translate the change back into the HogQL query, the query runner, the HogQL printer, or a ClickHouse migration**. Skip ahead to the SQL; reasoning about HogQL alone hides what ClickHouse will actually execute.

This skill assumes you already know how to write HogQL. For writing new ClickHouse-backed queries from scratch, use `/writing-clickhouse-queries` first. For migration mechanics, use `/clickhouse-migrations`.

## Step 0: confirm you're at the right layer

Before walking through the workflow, check that the slow query in front of you actually goes to ClickHouse via HogQL. The fastest way is to look at how the query is built:

| What you see                                                                                              | Where it goes                     | What to use                                                                                                                                                                                                                                                                                                                             |
| --------------------------------------------------------------------------------------------------------- | --------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `execute_hogql_query(...)`, `HogQLQuery`, a `*QueryRunner` subclass, an insight, a HogQL `.ambr` snapshot | ClickHouse via the HogQL printer  | This skill                                                                                                                                                                                                                                                                                                                              |
| `sync_execute(...)`, `client.execute(...)`, hand-written `SELECT ... FROM events`, ClickHouse migration   | ClickHouse directly (no HogQL)    | This skill (steps 2-5; skip step 1)                                                                                                                                                                                                                                                                                                     |
| `Model.objects.filter(...)`, `Model.objects.raw(...)`, a Django queryset, a `RawSQL` over the app DB      | Postgres via Django ORM           | Not this skill. Read [`docs/published/handbook/engineering/databases/query-performance-optimization.md`](../../../docs/published/handbook/engineering/databases/query-performance-optimization.md) (`## PostgreSQL` section), and use [pganalyze](https://app.pganalyze.com/) / AWS RDS Performance Insights for production diagnostics |
| `personhog_client.*`, `get_personhog_client()`, `get_person_by_*` helpers                                 | personhog (gRPC, Postgres-backed) | Not this skill. See [`posthog/personhog_client/README.md`](../../../posthog/personhog_client/README.md)                                                                                                                                                                                                                                 |

If the file you were pointed at is a coordinator, orchestrator, Celery task, Temporal workflow, or management command, the actual ClickHouse-touching query is often **one layer further in**, in the activity / child workflow / inner function the coordinator dispatches. Follow the dispatch (e.g. the class passed to `start_child_workflow`, the activity decorated with `@temporalio.activity.defn`, the function called inside `apply_async`) until you find the layer that builds the HogQL query. Some files mix both (Postgres queries to pick work + HogQL queries to do it); treat them as two separate optimization tasks if both are slow.

## Background: read these once

Read the table schema files so you know what columns, sort keys, partition keys, and skip indexes already exist. Do not read them line-by-line; skim for `ORDER BY`, `PARTITION BY`, `INDEX`, and materialized column declarations.

- Events: [`posthog/models/event/sql.py`](../../../posthog/models/event/sql.py)
- Sessions (v3): [`posthog/models/raw_sessions/sessions_v3.py`](../../../posthog/models/raw_sessions/sessions_v3.py) (v2 still exists at [`sessions_v2.py`](../../../posthog/models/raw_sessions/sessions_v2.py))
- Persons: [`posthog/models/person/sql.py`](../../../posthog/models/person/sql.py)
- Person overrides: [`posthog/models/person_overrides/sql.py`](../../../posthog/models/person_overrides/sql.py)
- Cohorts (ClickHouse `cohortpeople`, the materialized membership table): [`posthog/models/cohort/sql.py`](../../../posthog/models/cohort/sql.py). The Postgres `Cohort` model that stores the cohort _definition_ lives at [`posthog/models/cohort/cohort.py`](../../../posthog/models/cohort/cohort.py); queries against that one are a Postgres concern, see step 0.

If the query you're optimizing hits a table not in this list (e.g. `precalculated_events`, `app_metrics2`, `session_replay_events`, `log_entries`, `heatmaps`, a product-specific table), find its schema under [`posthog/models/*/sql.py`](../../../posthog/models/) or in the [`posthog/clickhouse/migrations/`](../../../posthog/clickhouse/migrations/) that created it. Same drill: skim for `ORDER BY`, `PARTITION BY`, `INDEX`, and materialized columns.

And the HogQL side, so you know where to make a change:

- HogQL query entry point: [`posthog/hogql/query.py`](../../../posthog/hogql/query.py)
- ClickHouse printer: [`posthog/hogql/printer/clickhouse.py`](../../../posthog/hogql/printer/clickhouse.py)
- Base printer (shared visit methods): [`posthog/hogql/printer/base.py`](../../../posthog/hogql/printer/base.py)
- HogQL → SQL helpers: [`posthog/hogql/printer/utils.py`](../../../posthog/hogql/printer/utils.py)
- HogQL function registry: [`posthog/hogql/functions/`](../../../posthog/hogql/functions/) (aggregations are in [`aggregations.py`](../../../posthog/hogql/functions/aggregations.py))
- HogQL database schema mappings: [`posthog/hogql/database/schema/`](../../../posthog/hogql/database/schema/)

The materialization system (how property access gets rewritten away from `JSONExtract` automatically):

- Materialized columns registry: [`ee/clickhouse/materialized_columns/columns.py`](../../../ee/clickhouse/materialized_columns/columns.py). `get_materialized_columns(table)` / `get_enabled_materialized_columns(table)` return the `(property_name, table_column) → MaterializedColumn` map for a given table, cached for 15 minutes against the connected ClickHouse.
- Property groups (different column strategy, same registry shape): [`posthog/clickhouse/property_groups.py`](../../../posthog/clickhouse/property_groups.py).
- Printer swap point: `_get_materialized_property_source_for_property_type()` and `visit_property_type()` in [`posthog/hogql/printer/base.py`](../../../posthog/hogql/printer/base.py) (around lines 1260 and 1354). When the printer visits a property access, it asks the registry what's materialized for the current ClickHouse and emits the best form available (direct column read, property group lookup, or fall back to `JSONExtract`).
- ClickHouse-specific dispatch: [`posthog/hogql/printer/clickhouse.py`](../../../posthog/hogql/printer/clickhouse.py) `_get_materialized_property_source_for_property_type` override (around line 412).

This is the mechanism behind the test-vs-prod caveat in the JSON smell below: the printer's lookup runs against whatever ClickHouse it's connected to. The test fixture has a sparse set, prod has a dense set, and the same HogQL prints to different SQL in each. By default, assume property access in HogQL queries gets materialized. The exception is hand-written SQL strings in product code that never go through the printer (e.g. temporal activities, migrations, `sync_execute` callers) and have to do their own materialized-column lookup.

The cluster topology (shards, replicas, ingestion vs data nodes) is in [`posthog/clickhouse/migrations/CLAUDE.md`](../../../posthog/clickhouse/migrations/CLAUDE.md). Read that before proposing any migration that has to land safely across nodes.

## Step 1: get the ClickHouse SQL

**Already have the SQL?** If you're optimizing a hand-written ClickHouse query (a string passed to `sync_execute`, `client.execute`, `client.read_query`, or sitting inside a migration / activity), you already have the SQL in front of you. Skip to step 2.

For HogQL queries, three ways to get from HogQL to executable ClickHouse SQL; pick whichever is cheapest for the situation:

**From Python**, call `execute_hogql_query()` in [`posthog/hogql/query.py`](../../../posthog/hogql/query.py) and read `response.clickhouse`. If you only want the printed SQL without executing, call `prepare_and_print_ast(..., dialect="clickhouse")` from [`posthog/hogql/printer/utils.py`](../../../posthog/hogql/printer/utils.py). For an AST you've already prepared, `print_prepared_ast` is the lower-level entry point.

**From snapshot tests**, the `.ambr` files under `posthog/hogql_queries/test/__snapshots__/` (and equivalent test dirs in each product) contain the ClickHouse SQL generated for representative inputs. Search for a snapshot that resembles your shape and read the printed query directly.

**From production**, the slowest real example is usually more informative than anything you can synthesize. Use `/query-clickhouse-via-metabase` to hit `clusterAllReplicas(posthog, system, query_log)` (or `posthog.query_log_archive` for anything older than ~4 hours; the archive table holds ~22 days). Filter for `is_initial_query` to avoid the per-shard duplicates ClickHouse logs for every query, plus the usual `type = 'QueryFinish'` and `query_duration_ms > <threshold>` filters. `query_log_archive` has typed `lc_*` columns (lower-cardinality strings), so prefer it when you can.

## Step 2: scan for the common smells

Before reaching for tools, eyeball the SQL for the patterns that account for most slow ClickHouse queries.

### `FROM <table> FINAL`

`FROM person FINAL`, `FROM groups FINAL`, `FROM cohortpeople FINAL`, or any other `FINAL` on a ReplacingMergeTree / CollapsingMergeTree / AggregatingMergeTree table forces ClickHouse to run an on-the-fly merge across every part it reads, deduplicating to the latest version per sort-key row. It defeats parallel reads, blows up memory, and scales badly with part count. On large tables (`person`, anything sharded) it is rarely the right answer.

Common rewrites:

- **`argMax` per row.** Replace `SELECT properties FROM person FINAL WHERE team_id = X AND id IN (...)` with `SELECT argMax(properties, version) FROM person WHERE team_id = X AND id IN (...) GROUP BY id`. You get the latest properties without the merge.
- **`LIMIT 1 BY` with `ORDER BY version DESC`.** Useful when you want a row per group and the table has a monotonically increasing version column.
- **Filter before FINAL.** If you genuinely need FINAL (rare), make sure the WHERE clause is selective enough on the sort-key prefix that ClickHouse only has to FINAL a small slice of parts.

Worth a mention specific to PostHog: per [`CLAUDE.md`](../../../CLAUDE.md), new code that needs person/group data should go through personhog (`get_personhog_client`), not raw ClickHouse queries against `person` / `groups`. If you find yourself optimizing a raw `FROM person FINAL` in new code, the right fix is often to move to personhog rather than tune the query.

### JSON operations on properties

Any `JSONExtractString(properties, ...)`, `JSONExtractFloat(properties, ...)`, `JSONHas(properties, ...)`, or similar against the raw `properties` / `person_properties` / `group_properties` column is a huge smell. It means ClickHouse has to parse the JSON blob at query time for every row it reads.

We have three materialization strategies. Skim:

- Directly materialized columns: [`posthog/clickhouse/materialized_columns.py`](../../../posthog/clickhouse/materialized_columns.py)
- Property groups: [`posthog/clickhouse/property_groups.py`](../../../posthog/clickhouse/property_groups.py)
- Dynamic materialized columns (DMAT slots, recent): [`posthog/models/dmat_slot_assignments/`](../../../posthog/models/dmat_slot_assignments/) and `EVENTS_TABLE_DYNAMICALLY_MATERIALIZED_COLUMNS()` in [`posthog/models/event/sql.py`](../../../posthog/models/event/sql.py)

We are also experimenting with the new ClickHouse JSON data type. Check recent migrations under [`posthog/clickhouse/migrations/`](../../../posthog/clickhouse/migrations/) for the current state.

If a property is not materialized in the local fixtures, snapshot tests will fall back to `JSONExtract*`. In test code, wrap the block in the `materialized()` context manager from [`posthog/test/base.py`](../../../posthog/test/base.py) (search for `def materialized`) to materialize a property for the duration of the test. It supports `create_minmax_index`, `create_bloom_filter_index`, and the lower-case variants when you also want to assert the skip index is used.

**Important: `JSONExtract` in a test-extracted query is a noisy signal.** The HogQL printer's materialization lookup runs against whatever ClickHouse you're talking to. The test ClickHouse usually has a minimal materialized set (events `$browser`, `$os`, a few others), so the printer falls back to `JSONExtract(properties, ...)` and the `.ambr` snapshot bakes that in. Production has dozens of materialized properties per team and the printer emits direct column reads. Before chasing a JSON smell you saw in a snapshot, confirm it's actually `JSONExtract`-ing in production: pull the same query type from `system.query_log` (via `/query-clickhouse-via-metabase`) and see what the printer actually emitted. If prod is already on `pmat_X` and the snapshot just shows `JSONExtract`, the smell is a test-environment artifact, not a real performance problem.

### Primary key and skip indexes

Look at the `ORDER BY` of the table the query reads from, and check the `WHERE` clause covers a prefix. The `events` table sort key is `(team_id, toDate(timestamp), event, cityHash64(distinct_id), cityHash64(uuid))`, so any non-trivial events query should filter on both `timestamp` and `event` unless there is a documented reason not to (e.g. cohort calculation that legitimately needs all events).

For skip indexes, the test helpers `get_index_from_explain` and `get_indexes_from_explain` in [`posthog/test/base.py`](../../../posthog/test/base.py) run `EXPLAIN PLAN indexes=1, json=1` against the generated SQL and let you assert that a specific index is being considered. Add one of these to a test when you depend on a skip index for performance, otherwise a future change to the printer can silently undo your optimization.

When you find the index isn't being used, common causes are: a `nullIf` or similar wrapping the materialized column that hides it from the planner, a comparison being printed against a stringified `NULL`, or the materialized column not existing in the test fixtures (use `materialized(..., create_minmax_index=True)` etc.).

### Self-joins on events

Joining the `events` table to itself (or any large table to itself) is almost always wrong. Two passes over `events` is twice the work; with a join predicate you also lose the primary key ordering.

Rewrite to one pass plus conditional aggregation: `sumIf(amount, event = 'purchase')`, `uniqIf(distinct_id, event = 'pageview')`, `uniqMapIf(properties.utm, 1, event = 'session_start')`, etc. If you need correlated rows (e.g. "first event in session before a conversion"), `arrayFilter` / `arrayFirst` / window functions over an ordered `groupArray` are usually faster than a self-join.

If HogQL doesn't expose the conditional aggregation function you need, add it to [`posthog/hogql/functions/aggregations.py`](../../../posthog/hogql/functions/aggregations.py).

### CTEs

ClickHouse CTEs (the `WITH name AS (SELECT ...)` form, not the scalar `WITH x AS 1` form) are inlined into the query, **not** materialized. A CTE referenced twice is executed twice. A CTE referenced inside another CTE that is itself referenced N times multiplies out. This is the single most common cause of "the planner is doing something weird".

Until materialized CTEs ship in our ClickHouse version (check the latest CH release notes for `WITH ... AS MATERIALIZED`), the workaround is the same as the self-join case: rewrite to a single pass with conditional aggregation, or materialize the intermediate result yourself via a subquery in `FROM` that ClickHouse is more likely to execute once.

## Step 3: run EXPLAIN

ClickHouse `EXPLAIN` works on a dev instance even without representative data, because most of the planner output (indexes considered, query tree, pipeline) does not need rows to exist. Useful flavors:

- `EXPLAIN PLAN indexes=1, actions=1, json=1 SELECT ...` for primary key and skip index use
- `EXPLAIN QUERY TREE SELECT ...` for the post-analyzer logical tree
- `EXPLAIN PIPELINE SELECT ...` for the processor-level pipeline
- `EXPLAIN ESTIMATE SELECT ...` for per-part row/mark estimates
- `EXPLAIN SYNTAX SELECT ...` for the normalized SQL after parsing

See the [ClickHouse EXPLAIN docs](https://clickhouse.com/docs/sql-reference/statements/explain) for the full option matrix.

## Step 4: measure for real

`EXPLAIN` tells you what the planner intends. To know whether your rewrite is actually faster, you need to run both versions against representative data and compare.

### Local ClickHouse

`hogli dev:demo-data` (or `python manage.py generate_demo_data --help` for the underlying flags) seeds the dev ClickHouse with a synthetic dataset. `hogli db:ch` opens a `clickhouse-client` against it. Local data is small enough that wall-clock measurements are dominated by noise, so use it for correctness and for `EXPLAIN`; trust the Test Cluster for timing.

You **can** experiment locally with new skip indexes, materialized columns, or other schema changes, since local ClickHouse is a single node. Ask the user before adding anything, and remember production is multi-node, so any structural change has to round-trip through [`/clickhouse-migrations`](../clickhouse-migrations/SKILL.md) before it lands. After adding a skip index, `ALTER TABLE ... MATERIALIZE INDEX ...` to build it over existing data.

A useful local proxy for query work is the bytes-read figure (`SELECT ... FORMAT JSON` includes it, as does `system.query_log` locally), which is much less noisy than elapsed time.

### Test Cluster

The Test Cluster is a Metabase-fronted ClickHouse with a snapshot of team 2's data, read-only, with no noisy-neighbor interference from production. It is the right place for actual timing measurements. Go through [`/query-clickhouse-via-metabase`](../query-clickhouse-via-metabase/SKILL.md) to authenticate and submit queries.

Because it only has team 2 data, you will need to rewrite the production query before running it. At minimum, swap the `team_id` and pick a date range that overlaps the snapshot. If the original query depends on a custom property that team 2 doesn't use, or a PostHog feature that team 2 doesn't have configured, you may need to substitute or skip that branch; this is a judgement call.

**Apply the cluster's materialized columns before measuring.** If the query you're porting came from a `.ambr` snapshot or a local test, it almost certainly references `properties` via `JSONExtract` because the test fixture lacks the materialized columns prod has. The Test Cluster mirrors prod's schema, so `DESCRIBE <table>` will list real `pmat_*` (events) or `pmat_*` / `mat_*` (persons, groups) columns. Swap your `JSONExtract(properties, 'X', ...)` calls for the corresponding materialized column reference before timing the query. Skipping this step means you're measuring a query shape that the printer would never actually emit in production, and your numbers won't transfer.

For measurement, set `SETTINGS use_uncompressed_cache=0` (mirrors what [`ee/benchmarks/measure.sh`](../../../ee/benchmarks/measure.sh) does) and take the **median of 5 runs**. Pull the actual numbers from `system.query_log` on the Test Cluster, not from how long the Metabase request took, since the API path adds a fixed floor and per-request jitter that swamps the metric you care about. `query_log` also gives you `read_rows`, `read_bytes`, `memory_usage`, and the `ProfileEvents` map, all of which are more diagnostic than wall time when you're comparing two versions.

**Before suggesting an optimization, measure it on the Test Cluster.** If you're proposing a rewrite (dropping `FINAL`, swapping a CTE for conditional aggregation, materializing a column, restructuring a join), run both the original and your candidate against the same team-2-adapted query and report the before/after `query_duration_ms`, `read_bytes`, and `memory_usage` from `system.query_log`. A suggestion without numbers is a guess. If you couldn't measure (Test Cluster unavailable, query doesn't adapt cleanly to team 2's data, the change is a schema-only optimization the read-only cluster can't host), say so explicitly when you make the suggestion rather than implying the change will be faster in production.

The Test Cluster is read-only, so you cannot try schema changes there. For those, prototype locally, then write the migration and have it reviewed.

### Query performance autoresearch (the powertool)

For hard cases, [`products/query_performance_ai/`](../../../products/query_performance_ai/) wraps [pi-autoresearch](https://github.com/davebcn87/pi-autoresearch) in a coordinator that hands the LLM a query and asks it to optimize against the Test Cluster in a loop. Setup is non-trivial (Docker sandbox per query, ANTHROPIC_API_KEY, Metabase database IDs), so ask the user to run the setup themselves:

- Coordinator and setup: [`products/query_performance_ai/README.md`](../../../products/query_performance_ai/README.md)
- Coordinator entry point: [`products/query_performance_ai/orchestrator/coordinator.py`](../../../products/query_performance_ai/orchestrator/coordinator.py)
- The campaign skill the sandboxed agent runs: [`products/query_performance_ai/sandboxed_autoresearch_agent/pi_plugin/skills/clickhouse-autoresearch-campaign/SKILL.md`](../../../products/query_performance_ai/sandboxed_autoresearch_agent/pi_plugin/skills/clickhouse-autoresearch-campaign/SKILL.md)
- Orchestration contract: [`products/query_performance_ai/sandboxed_autoresearch_agent/pi_plugin/skills/clickhouse-autoresearch-campaign/orchestration.md`](../../../products/query_performance_ai/sandboxed_autoresearch_agent/pi_plugin/skills/clickhouse-autoresearch-campaign/orchestration.md)

I am not entirely sure of the exact commands needed beyond the snippets in the README. Ask the user; the setup also takes effort on their side.

## Step 5: apply the optimization

Once you have a faster ClickHouse SQL, you need to make HogQL emit it. Pick the lowest-blast-radius layer that gets the job done:

**HogQL query / query runner change** is the cheapest. If the rewrite can be expressed as a different HogQL query (different aggregation, different join order, swapping a CTE for conditional aggregation), change the query runner under `posthog/hogql_queries/` or `products/*/backend/`. Snapshot the new ClickHouse output via the relevant `.ambr` test.

**New HogQL function** if the rewrite needs a conditional aggregation or other ClickHouse function HogQL doesn't expose yet. Add it to [`posthog/hogql/functions/aggregations.py`](../../../posthog/hogql/functions/aggregations.py) (or the appropriate file under [`posthog/hogql/functions/`](../../../posthog/hogql/functions/)) with `HogQLFunctionMeta(name, min_args, max_args, aggregate=True)` and the query runner can use it like any other function.

**HogQL printer change** when the optimization is a SQL-level rewrite the printer should apply automatically. The ClickHouse printer at [`posthog/hogql/printer/clickhouse.py`](../../../posthog/hogql/printer/clickhouse.py) already does several of these; `_get_optimized_materialized_column_equals_operation` (around line 574) is a good template for a comparison-rewrite optimization. Add a snapshot test and a `get_index_from_explain` assertion so the optimization can't silently regress.

**ClickHouse migration** for schema changes (new skip index, new materialized column, projection, table engine change). Use [`/clickhouse-migrations`](../clickhouse-migrations/SKILL.md) for the patterns. Remember production is multi-shard, multi-replica with separate data and ingestion node roles, so `node_roles=[...]`, `sharded=True`, and `is_alter_on_replicated_table=True` matter; never use `ON CLUSTER`.

[`posthog/clickhouse/migrations/0250_property_values_lowercase_text_index.py`](../../../posthog/clickhouse/migrations/0250_property_values_lowercase_text_index.py) is a clean example of adding a skip index on a replicated table and materializing it.

## A note on team-specific heuristics

Some rewrites help one team and hurt another. A funnels optimization we tried was great when there was a large drop-off between the first and second step (small intermediate set, cheap to enumerate), but slower when the first step matched almost every event (huge set, expensive to enumerate).

When you notice this kind of asymmetry, suggest a heuristic to the user rather than implementing it yourself: count the events for each step in the relevant time window, and only apply the optimization when the ratio is favorable. The shape of the heuristic depends on the rewrite and the team, so this is a design decision for the user, not something to commit speculatively.

## Test discipline

Whenever you change a printer rule, a query runner, or add a HogQL function, snapshot the generated ClickHouse SQL in `.ambr` and add an `EXPLAIN`-based assertion if the optimization depends on a specific index or rewrite. A passing-after-fix test isn't proof the test would have failed before; flip the change off briefly to confirm the test was actually exercising your code path.

## Learnings log

[`references/learnings.md`](references/learnings.md) collects case studies and surprising findings from past optimization sessions, especially ones where the rule-of-thumb in this skill turned out to be wrong or needed nuance. Read it before relying heavily on one of the smell descriptions, and append a new entry when you measure something worth remembering.

**Do not paste customer data into entries.** This file is checked into the public OSS repo. No raw person / group / distinct_id values, no custom property names or values, no team or org names, no row samples, no precise operational scale (exact row counts, customer-specific durations). Use placeholders (`<bound_uuid>`, `<custom_property>`, `<team_id>`) or describe the shape (`a 1M-person slice`, `tens of millions of rows`). PostHog's own team 2 is fine to name as the canonical Test Cluster target; redact other team IDs.
