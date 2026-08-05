---
name: optimizing-clickhouse-and-hogql-queries
description: Workflow for optimizing ClickHouse and HogQL queries. Use when a HogQL query, query runner, insight, or report is too slow; when a hand-written ClickHouse query (via `sync_execute` or in a migration) is too slow; when ClickHouse times out or hits memory limits; when investigating a slow `system.query_log` row; or when reviewing a proposed HogQL printer change for performance. Covers extracting the ClickHouse SQL, common smells (`FROM ... FINAL`, `JSONExtract` over properties, missing skip indexes, self-joins, CTE blow-up), measuring against a real cluster, and applying the fix at the right layer (printer, query runner, or migration). Does NOT cover Postgres / Django ORM / app-database queries; those need pganalyze and the Postgres section of `query-performance-optimization.md`.
---

# Optimizing ClickHouse and HogQL queries

Optimizes **ClickHouse and HogQL queries** (HogQL compiles to ClickHouse), not Postgres / Django ORM. For an app-DB query (`Model.objects.filter(...)`), stop and use pganalyze plus the Postgres section of [`query-performance-optimization.md`](../../../docs/published/handbook/engineering/databases/query-performance-optimization.md); Step 0 has the full triage.

**Work from the ClickHouse SQL, not the HogQL.** Get the ClickHouse SQL the query produces, optimize that, then translate the change back into the HogQL query, query runner, printer, or a migration. Reasoning about HogQL alone hides what ClickHouse executes.

Assumes you can write HogQL. For new queries from scratch use `/writing-clickhouse-queries`; for migration mechanics, `/clickhouse-migrations`.

## Optimizing every query a team owns

When the job is "optimize all of team X's queries," build the full inventory first or you'll miss some.

1. **Resolve the team to its owned paths** with [`/establishing-code-ownership`](../establishing-code-ownership/SKILL.md). Owned paths span backend Python _and_ `frontend/src/...`, often across several products; don't silently narrow to one product or to the backend.
2. **Find queries across every path.** Most are Python (`*QueryRunner`, `execute_hogql_query`, raw `sync_execute`), but plenty are built client-side and POSTed to `/query`. Grep `frontend/` for:
   - `api.queryHogQL(...)`, `HogQLQueryString`, the `` hogql`...` `` template
   - `NodeKind.HogQLQuery` / `kind: 'HogQLQuery'` with a `query:` string
   - nodes that compile to ClickHouse: `DataTableNode`, `EventsQuery`, `TrendsQuery`/`InsightVizNode`, `PropertyFilterType.HogQL`
   - literals with `SELECT ... FROM events`, or product markers (`'survey sent'`, `$survey_id`)

The same query is sometimes implemented **twice** (backend runner plus frontend HogQL, often a stalled migration). Both are in-scope; a backend printer/function fix won't reach a hand-built frontend string.

## Step 0: confirm you're at the right layer

Check how the query is built:

| What you see                                                                                   | Where it goes                    | What to use                                                                                                                                                                                                 |
| ---------------------------------------------------------------------------------------------- | -------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `execute_hogql_query(...)`, `HogQLQuery`, a `*QueryRunner`, an insight, a HogQL `.ambr`        | ClickHouse via the HogQL printer | This skill                                                                                                                                                                                                  |
| `sync_execute(...)`, `client.execute(...)`, hand-written `SELECT ... FROM events`, a migration | ClickHouse directly (no HogQL)   | This skill (steps 2-5; skip step 1)                                                                                                                                                                         |
| `Model.objects.filter(...)`, `.raw(...)`, a queryset, `RawSQL` over the app DB                 | Postgres via Django ORM          | Not this skill. [`query-performance-optimization.md`](../../../docs/published/handbook/engineering/databases/query-performance-optimization.md) (`## PostgreSQL`) + [pganalyze](https://app.pganalyze.com/) |
| `personhog_client.*`, `get_personhog_client()`, `get_person_by_*`                              | personhog (gRPC, Postgres)       | Not this skill. [`posthog/personhog_client/README.md`](../../../posthog/personhog_client/README.md)                                                                                                         |

If you were pointed at a coordinator / orchestrator / Celery task / Temporal workflow / management command, the ClickHouse query is usually **one layer in** (the dispatched activity, child workflow, or `apply_async` target). Follow the dispatch to the layer that builds the HogQL. A file may mix Postgres (pick work) and HogQL (do work); treat them as separate tasks.

**If the slow query is raw ClickHouse SQL in production code** (f-strings / strings to `sync_execute`, `client.execute`, `client.read_query`, not printer output), flag it, then continue. The printer gives HogQL materialized-column substitution, property-group dispatch, lazy joins, and team-id guards for free; raw SQL reimplements or loses each. The structural fix is to express it in HogQL, but that's larger; offer both options (local fix now, HogQL move later).

**Single-team vs multi-team decides whether raw SQL is excusable.** `execute_hogql_query` is team-scoped (one team, injects the `team_id` guard).

- **One team should almost always be HogQL.** A single-team `team_id = X` query that's hand-written leaks materialization, lazy joins, and the team-id guard. Treat raw single-team `sync_execute` as a smell. Clearest tell: a hand-rolled materialized-column lookup (e.g. `get_materialized_column_for_property(...)` with a `JSONExtract` fallback), which is the printer's job done by hand.
- **Many teams are exempt.** Cross-team / global jobs (enrichment, billing rollups, "find every team where X" with no `team_id` or a `team_id IN (...)`) can't use `execute_hogql_query`; keep them raw and optimize in place. A hand-rolled materialized-column lookup is expected here, not a smell.

So: one team, recommend HogQL; many teams, optimize the raw SQL directly.

**`INSERT` doesn't exempt the read half.** HogQL has no `INSERT`, so build the `SELECT` in HogQL, print it, and concatenate into `INSERT INTO <table> <printed_select>` (only the wrapper is raw). A single-team `INSERT ... SELECT` with a hand-written `SELECT` (raw columns, `JSONExtract` over `properties`, manual `team_id`) is the same smell: move the `SELECT` to HogQL, keep the `INSERT INTO` wrapper raw. Genuinely raw-fine: `INSERT ... VALUES` of Python rows, multi-team `INSERT ... SELECT`, migrations, one-shot scripts.

## Background: read these once

Handbook (conceptual model): [`query-performance-optimization.md`](../../../docs/published/handbook/engineering/databases/query-performance-optimization.md) (finding/fixing slow queries), [`hogql-python.md`](../../../docs/published/handbook/engineering/databases/hogql-python.md) (printer pipeline, driving HogQL), [`clickhouse-queries-new-products.md`](../../../docs/published/handbook/engineering/databases/clickhouse-queries-new-products.md) (table/runner design).

Table schemas, skim for `ORDER BY` / `PARTITION BY` / `INDEX` / materialized columns (don't read line-by-line):

- Events: [`posthog/models/event/sql.py`](../../../posthog/models/event/sql.py)
- Sessions v3: [`sessions_v3.py`](../../../posthog/models/raw_sessions/sessions_v3.py) (v2: [`sessions_v2.py`](../../../posthog/models/raw_sessions/sessions_v2.py))
- Persons: [`posthog/models/person/sql.py`](../../../posthog/models/person/sql.py); overrides: [`person_overrides/sql.py`](../../../posthog/models/person_overrides/sql.py)
- Cohorts (`cohortpeople` membership): [`products/cohorts/backend/models/sql.py`](../../../products/cohorts/backend/models/sql.py). The Postgres `Cohort` definition ([`cohort.py`](../../../products/cohorts/backend/models/cohort.py)) is a Postgres concern (Step 0).
- Other tables (`app_metrics2`, `session_replay_events`, `log_entries`, `heatmaps`, product tables): find under [`posthog/models/*/sql.py`](../../../posthog/models/) or the [migration](../../../posthog/clickhouse/migrations/) that created them.

HogQL side: query entry [`query.py`](../../../posthog/hogql/query.py); printers [`clickhouse.py`](../../../posthog/hogql/printer/clickhouse.py) / [`base.py`](../../../posthog/hogql/printer/base.py); helpers [`utils.py`](../../../posthog/hogql/printer/utils.py); functions [`posthog/hogql/functions/`](../../../posthog/hogql/functions/) (aggregations in [`aggregations.py`](../../../posthog/hogql/functions/aggregations.py)); schema [`posthog/hogql/database/schema/`](../../../posthog/hogql/database/schema/).

Materialization (auto-rewrites property access away from `JSONExtract`):

- Registry: [`ee/clickhouse/materialized_columns/columns.py`](../../../ee/clickhouse/materialized_columns/columns.py), `get_materialized_columns(table)` / `get_enabled_materialized_columns(table)`, cached 15 min against the connected ClickHouse.
- Property groups: [`posthog/clickhouse/property_groups.py`](../../../posthog/clickhouse/property_groups.py).
- Printer swap: `_get_materialized_property_source_for_property_type()` / `visit_property_type()` in [`base.py`](../../../posthog/hogql/printer/base.py) (~1260, ~1354), ClickHouse override in [`clickhouse.py`](../../../posthog/hogql/printer/clickhouse.py) (~412). On each property access the printer emits the best form available (direct column, property group, or `JSONExtract` fallback) for the connected ClickHouse.

This is why the same HogQL prints differently in test (sparse materialization) vs prod (dense): the lookup runs against the connected ClickHouse. Assume printer-path property access gets materialized; only hand-written SQL that bypasses the printer must do its own lookup.

Cluster topology (shards, replicas, ingestion vs data nodes): [`posthog/clickhouse/migrations/CLAUDE.md`](../../../posthog/clickhouse/migrations/CLAUDE.md), read before proposing any migration.

## Step 1: get the ClickHouse SQL

**Raw ClickHouse query?** You already have the SQL; skip to Step 2. For HogQL, three ways:

- **Python:** `execute_hogql_query()` ([`query.py`](../../../posthog/hogql/query.py)) gives `response.clickhouse`. SQL only, no execute: `prepare_and_print_ast(..., dialect="clickhouse")` ([`utils.py`](../../../posthog/hogql/printer/utils.py)); for a prepared AST, `print_prepared_ast`.
- **Snapshots:** `.ambr` files under `posthog/hogql_queries/test/__snapshots__/` (and per-product test dirs) hold generated ClickHouse SQL for representative inputs.
- **Production** (most informative): `/query-clickhouse-via-metabase` against `clusterAllReplicas(posthog, system, query_log)` (or `posthog.query_log_archive` for rows older than ~4h; ~22 day retention, typed `lc_*` columns, so prefer it). Filter `is_initial_query`, `type = 'QueryFinish'`, `query_duration_ms > <threshold>`.

## Step 2: scan for the common smells

Eyeball the ClickHouse SQL for these before reaching for tools. To instead work backwards from a specific slow query's runtime cost (bytes vs CPU vs duration, high-cardinality breakdowns, function-wrapped sort keys, ratio-metric double scans, tracing to source code, EXPLAIN), see [`references/investigation-playbook.md`](references/investigation-playbook.md).

### `FROM <table> FINAL`

`FINAL` on a ReplacingMergeTree / CollapsingMergeTree / AggregatingMergeTree (`person`, `groups`, `cohortpeople`, …) forces an on-the-fly merge across every part read, deduplicating to the latest version per sort-key row. It defeats parallel reads, blows up memory, scales badly with part count; rarely right on large/sharded tables. Rewrites:

- **`argMax` per row:** `SELECT properties FROM person FINAL WHERE ... id IN (...)` becomes `SELECT argMax(properties, version) FROM person WHERE ... id IN (...) GROUP BY id`.
- **`LIMIT 1 BY` with `ORDER BY version DESC`** for one row per group with a monotonic version column.
- **Filter before FINAL** (if truly needed): make the WHERE selective on the sort-key prefix so few parts are merged.

PostHog-specific: per [`CLAUDE.md`](../../../CLAUDE.md), new person/group access should go through personhog (`get_personhog_client`), not raw `person` / `groups`. A raw `FROM person FINAL` in new code usually wants the personhog move, not tuning.

### JSON operations on properties

`JSONExtractString/Float(...)`, `JSONHas(...)`, etc. against raw `properties` / `person_properties` / `group_properties` parse the JSON blob per row: up to ~100x slower than a directly materialized (`mat_*` / `dmat_*`) column, ~10x slower than a property group read.

**Printer-path queries (backend `parse_select` / `execute_hogql_query` / `*QueryRunner`, frontend `api.queryHogQL` / `` hogql`...` ``): replace every `JSONExtract*(properties, 'X')` with `properties.X` (wrap in `toFloat(...)` / `toInt(...)` for non-strings). Convert _all_ of them; don't work out what's materialized.** The printer does the lookup at print time and emits the best form (materialized column, property group, DMAT slot, or `JSONExtract` fallback). `properties.X` is **never worse** than the hand-written form, and improves automatically when a column is later materialized.

**Don't cherry-pick by reading migrations / the registry / `DESCRIBE`**, which reimplements the printer and gets it wrong: materialization often isn't from a migration, property groups have no dedicated column, and the set varies per environment and over time. Partial conversion leaves the query inconsistent for zero benefit. Convert all; let the printer decide.

**Exception, raw SQL that bypasses the printer** (multi-team `sync_execute`, migrations, hand-built temporal activity strings): no printer and no `properties.X` syntax, so reference the materialized column directly. Correct there, and only there. Strategies (for that case and background; not needed for printer-path): directly materialized [`materialized_columns.py`](../../../posthog/clickhouse/materialized_columns.py); property groups [`property_groups.py`](../../../posthog/clickhouse/property_groups.py); DMAT slots [`posthog/models/dmat_slot_assignments/`](../../../posthog/models/dmat_slot_assignments/) plus `EVENTS_TABLE_DYNAMICALLY_MATERIALIZED_COLUMNS()` in [`event/sql.py`](../../../posthog/models/event/sql.py). The new ClickHouse JSON type is being trialed; check recent [migrations](../../../posthog/clickhouse/migrations/).

In tests, materialize a property for the block with the `materialized()` context manager in [`posthog/test/base.py`](../../../posthog/test/base.py) (`create_minmax_index`, `create_bloom_filter_index`, lower-case variants).

A `JSONExtract` in a `.ambr` snapshot whose source uses `properties.X` is just the test fixture's fallback (prod may emit a materialized read). Not a bug; don't "fix" it.

### Primary key and skip indexes

Check the `WHERE` covers an `ORDER BY` prefix. The `events` sort key is `(team_id, toDate(timestamp), event, cityHash64(distinct_id), cityHash64(uuid))`, so non-trivial events queries should filter `timestamp` and `event` unless there's a documented reason (e.g. cohort calc needing all events).

Assert skip-index use with `get_index_from_explain` / `get_indexes_from_explain` ([`posthog/test/base.py`](../../../posthog/test/base.py), run `EXPLAIN PLAN indexes=1, json=1`) so a printer change can't silently undo it. Common reasons an index isn't used: a `nullIf`/wrapper hiding the materialized column, a comparison against stringified `NULL`, or the column missing from fixtures (use `materialized(..., create_minmax_index=True)`).

### Self-joins on events

Joining `events` (or any large table) to itself doubles the work and loses primary-key ordering. Rewrite to one pass plus conditional aggregation: `sumIf(amount, event='purchase')`, `uniqIf(distinct_id, event='pageview')`, `uniqMapIf(...)`. For correlated rows ("first event before a conversion"), `arrayFilter` / `arrayFirst` / window functions over an ordered `groupArray` beat a self-join. Missing aggregation function? Add it to [`aggregations.py`](../../../posthog/hogql/functions/aggregations.py).

### CTEs

ClickHouse `WITH name AS (SELECT ...)` CTEs are **inlined, not materialized**: referenced twice means executed twice, and nesting multiplies out. Most common cause of "the planner is doing something weird." Until `WITH ... AS MATERIALIZED` ships (check CH release notes), rewrite to a single pass with conditional aggregation, or force one execution via a `FROM` subquery.

## Step 3: run EXPLAIN

`EXPLAIN` works on dev ClickHouse without representative data (planner output doesn't need rows):

- `EXPLAIN PLAN indexes=1, actions=1, json=1 SELECT ...` for primary key + skip index use
- `EXPLAIN QUERY TREE SELECT ...` for the post-analyzer logical tree
- `EXPLAIN PIPELINE SELECT ...` for the processor pipeline
- `EXPLAIN ESTIMATE SELECT ...` for per-part row/mark estimates
- `EXPLAIN SYNTAX SELECT ...` for the normalized SQL

[ClickHouse EXPLAIN docs](https://clickhouse.com/docs/sql-reference/statements/explain). For the side-by-side diff technique (suspect vs fixed variant, diffing `Granules` / `ReadType` / Prewhere-vs-primary-key), see [`references/investigation-playbook.md`](references/investigation-playbook.md).

## Step 4: measure for real

`EXPLAIN` shows intent; to know if a rewrite is faster, run both versions against representative data.

**Local ClickHouse** (correctness and EXPLAIN, not timing, which is too noisy): `hogli dev:demo-data` seeds synthetic data; `hogli db:ch` opens a client. You _can_ try skip indexes / materialized columns / schema changes locally (single node), but ask the user first, and remember prod is multi-node so structural changes must round-trip through [`/clickhouse-migrations`](../clickhouse-migrations/SKILL.md); `ALTER TABLE ... MATERIALIZE INDEX ...` builds a new index over existing data. Bytes-read (`FORMAT JSON`, or local `system.query_log`) is a less-noisy proxy than wall time.

**Test Cluster** (timing): Metabase-fronted, read-only snapshot of team 2's data, no noisy neighbors. Use [`/query-clickhouse-via-metabase`](../query-clickhouse-via-metabase/SKILL.md). Adapt the prod query first: swap `team_id`, pick an overlapping date range, substitute/skip branches that depend on properties/features team 2 lacks (judgement call). **Apply prod materialized columns before timing**: `DESCRIBE <table>` lists real `pmat_*` (events) / `pmat_*` / `mat_*` (persons, groups); swap `JSONExtract(...)` for them or you're timing a shape the printer never emits. Set `SETTINGS use_uncompressed_cache=0`, take the **median of 5**, and read `query_duration_ms` / `read_rows` / `read_bytes` / `memory_usage` / `ProfileEvents` from `system.query_log`, not the Metabase request time.

**Measure before suggesting.** For any rewrite, run original vs candidate on the same team-2-adapted query and report before/after `query_duration_ms`, `read_bytes`, `memory_usage`. A suggestion without numbers is a guess; if you couldn't measure (cluster unavailable, doesn't adapt, schema-only change), say so. The cluster is read-only, so prototype schema changes locally.

**Autoresearch (powertool)** for hard cases: [`tools/query-performance-ai/`](../../../tools/query-performance-ai/) wraps [pi-autoresearch](https://github.com/davebcn87/pi-autoresearch) to optimize against the Test Cluster in a loop. Setup is non-trivial (Docker sandbox, `ANTHROPIC_API_KEY`, Metabase DB IDs); have the user run it. See its [README](../../../tools/query-performance-ai/README.md) and [coordinator](../../../tools/query-performance-ai/query_performance_ai/orchestrator/coordinator.py).

## Step 5: apply the optimization

Make HogQL emit the faster ClickHouse SQL at the lowest-blast-radius layer:

- **Query runner** (cheapest): if the rewrite is a different HogQL query (aggregation, join order, CTE to conditional aggregation), edit the runner under `posthog/hogql_queries/` or `products/*/backend/`; snapshot via `.ambr`.
- **New HogQL function**: add to [`aggregations.py`](../../../posthog/hogql/functions/aggregations.py) (or the right file in [`functions/`](../../../posthog/hogql/functions/)) with `HogQLFunctionMeta(name, min_args, max_args, aggregate=True)`.
- **Printer change**: for a SQL-level rewrite the printer should apply automatically. `_get_optimized_materialized_column_equals_operation` (~line 574, [`clickhouse.py`](../../../posthog/hogql/printer/clickhouse.py)) is a template. Add a snapshot test plus a `get_index_from_explain` assertion.
- **Migration**: for schema changes (skip index, materialized column, projection, engine). Use [`/clickhouse-migrations`](../clickhouse-migrations/SKILL.md); prod is multi-shard/replica with data vs ingestion roles, so `node_roles=[...]`, `sharded=True`, `is_alter_on_replicated_table=True` matter; never `ON CLUSTER`. Clean example: [`0250_property_values_lowercase_text_index.py`](../../../posthog/clickhouse/migrations/0250_property_values_lowercase_text_index.py).

## Team-specific heuristics

Some rewrites help one team and hurt another (a funnels rewrite was great with a big step-1-to-2 drop-off but slower when step 1 matched almost every event). For such asymmetries, suggest a runtime heuristic (count events per step, apply only when the ratio is favorable) rather than committing it speculatively; the shape is the user's call.

## Test discipline

When you change a printer rule / query runner / add a function, snapshot the generated ClickHouse SQL in `.ambr` and add an `EXPLAIN`-based assertion if the win depends on a specific index or rewrite. Green-after-fix isn't proof; flip the change off to confirm the test exercises your path.

## Learnings log

[`references/learnings.md`](references/learnings.md) has case studies where a smell here needed nuance; read before leaning hard on one, and append what you measure. **No customer data** (public repo): no raw person/group/distinct_id values, custom property names/values, team/org names, row samples, or precise scale. Use placeholders (`<custom_property>`, `<team_id>`) or shapes (`tens of millions of rows`). Team 2 is fine to name; redact other team IDs.
