---
name: optimizing-postgres-queries
description: Diagnose and fix slow Postgres queries against the app database (Django ORM, `.raw()`, `RawSQL`, psycopg). Use when an Aurora CPU / connection / replication alert fires, when pganalyze or RDS Performance Insights names an expensive query, when a Django queryset is slow, or when a query "should be cheap" but shows high total time. Covers tracing a pganalyze fingerprint back to the ORM call site, reading the plan with EXPLAIN against a seeded local database, the house anti-patterns (the `COALESCE(project_id, team_id)` OR form, non-strict quals that stop Postgres demoting an outer join, raw SQL built from an unordered set, unbounded `IN` lists, per-row queries in a loop, count over a whole table), and choosing between a query rewrite, a new index, caching, and the reader instance. Also covers a plan that flips after an auto-ANALYZE, and a query that hides from query statistics by fingerprinting differently per worker. Does NOT cover ClickHouse or HogQL — use `/optimizing-clickhouse-and-hogql-queries` for those.
---

# Optimizing Postgres queries

Covers the **app database** (`posthog_*`, `ee_*`, `products_*` tables) reached through Django. Analytics queries live in ClickHouse and belong to [`/optimizing-clickhouse-and-hogql-queries`](../optimizing-clickhouse-and-hogql-queries/SKILL.md); person and group reads go through [personhog](../../../posthog/personhog_client/README.md), not the ORM.

The background reading is [`query-performance-optimization.md`](../../../docs/published/handbook/engineering/databases/query-performance-optimization.md). This skill is the workflow on top of it.

## The trap this skill exists for

A query with a small call count and a large share of database time is the interesting one, not the noisy one. Chasing the top row by call count finds a cheap query called often, which is usually fine. A query called a few thousand times an hour that still lands near the top of total time is doing per-call work it should not be doing — almost always a scan where a seek was available.

So sort by total time, then ask of each candidate: **is the per-call cost plausible for what it asks for?** A lookup of 300 names by primary scope should read a few pages. If it reads thousands, the plan is wrong, not the traffic.

## Step 1: get from the alert to the call site

The alert says a database is hot. It does not say which query. Both sources give you SQL, neither gives you Python.

- **pganalyze** — `app.pganalyze.com`, per-query fingerprints with total time, calls, mean time, and history. The `pganalyze` MCP server, when configured, queries this directly.
- **RDS Performance Insights** — AWS console, top SQL by average active sessions. Groups by normalized statement, so one ORM call site can appear as several rows (one per `IN`-list length). Add those rows up before judging a call site as small.

To map SQL back to Python, grep for the shape rather than the text. The table name plus the distinctive predicate is usually enough:

```sh
rg -t py 'EnterpriseEventDefinition.objects' products/ posthog/ ee/
rg -t py 'project_id__isnull=True'
```

When the SQL has no distinctive predicate, print candidate querysets and compare: `print(Model.objects.filter(...).query)`.

**Name the caller, not just the query.** A query that is cheap per call and runs once per HTTP request is a different problem from the same query running once per scanned session inside a Temporal activity. The fix follows the caller: a hot loop wants a cache or a batch; a request path wants an index.

## Step 2: reproduce the plan locally

Do not reason about the plan from the SQL. Get `EXPLAIN` output from a real Postgres with the real indexes, because expression-index matching turns on details that are not visible in the query text.

**Seed a scratch database, never the dev one.** Measuring needs bulk inserts, and it is easier to skip foreign keys than to satisfy them, so the work has to land somewhere disposable. `posthog` is your working dev database and [`/querying-local-postgres`](../querying-local-postgres/SKILL.md) forbids writing to it. Copy the schema into a scratch database instead, and drop it when you are done.

```sh
docker compose -f docker-compose.dev.yml up -d db
docker exec posthog-db-1 psql -U posthog -d postgres -c 'CREATE DATABASE plan_scratch TEMPLATE posthog'
docker exec posthog-db-1 psql -U posthog -d plan_scratch -c '\d posthog_eventdefinition'
# ... seed, ANALYZE, EXPLAIN ...
docker exec posthog-db-1 psql -U posthog -d postgres -c 'DROP DATABASE plan_scratch'
```

`TEMPLATE posthog` needs no other session connected to `posthog`, so stop the dev stack's app processes first. Inside the scratch database you can disable triggers to skip foreign keys, which is exactly why it must not be the database you keep.

An empty table always sequential-scans, so seed enough rows for the planner to have a choice, then `ANALYZE`. Seed the shape that matters, not just the volume: if the anti-pattern depends on a large `project_id IS NULL` population, or on one project holding far more rows than the median, reproduce that skew.

Then run **both** forms — the current one and the proposed one — under `EXPLAIN (ANALYZE, BUFFERS, COSTS OFF, TIMING OFF)`, and compare `Buffers: shared` and `Rows Removed by Filter`. Buffers are the honest number; wall time on a warm local cache understates a cold production one.

Read the plan for these, in order:

| In the plan                              | Means                                                  |
| ---------------------------------------- | ------------------------------------------------------ |
| `Seq Scan` on a large table              | No usable index, or the predicate is not sargable      |
| `BitmapOr`                               | An `OR` no single index can serve; each branch scanned |
| `Rows Removed by Filter` ≫ rows returned | The index found the rows but could not exclude them    |
| `Index Cond` missing your second column  | The index is being used, but only its leading column   |
| `Hash Full Join` / `Merge Full Join`     | A full join Postgres could not demote; see below       |

`loops=N` on an inner node means that node ran N times inside this one statement, which is how a nested loop works and is not by itself a problem. It is not evidence of an application N+1, and an application N+1 does not show up here at all: it is many separate statements, so you find it in a request trace or in the call count for one fingerprint, not in one plan.

## Step 3: pick the fix

Try these in order. The earlier ones are cheaper to ship and cheaper to keep correct.

1. **Rewrite the predicate to match an index that already exists.** Free at runtime, no migration, no new write cost. Almost always the answer when the table is already indexed for this access path. The next section is the house case.
2. **Add an index.** A real cost: it slows every write to the table and takes disk. Justify it with the plan, and add it with `SafeAddIndexConcurrently` from `posthog.migration_helpers` — CI blocks Django's `AddIndexConcurrently`. See [`/django-migrations`](../django-migrations/SKILL.md) for the helper set and the safety rules.
3. **Stop making the call.** A per-team lookup inside a per-item loop should be hoisted or cached. This beats any index, because the fastest query is the one that does not run.
4. **Move the read to the reader instance.** Helps cluster-wide load, but it is not a fix for a bad plan — the reader executes the same plan. Do it for genuinely read-only, replication-lag-tolerant work, and do it in addition to the rewrite, never instead of it.

A slow query is often several of these. Fix the plan first, then decide whether the call still deserves to happen.

## The `COALESCE(project_id, team_id)` pattern

The taxonomy tables are project-scoped with a team-scoped legacy fallback: `project_id` is the scope, and rows written before projects existed have `project_id IS NULL` and belong to the primary team, whose id equals the project id.

Two ways to express that scope. They select exactly the same rows, and only one of them can use an index.

```python
# Never. No index covers this.
Model.objects.filter(
    Q(project_id=project_id) | Q(project_id__isnull=True, team_id=project_id),
    name__in=names,
)

# Always.
from products.event_definitions.backend.models import effective_project_id_expr

Model.objects.alias(effective_project_id=effective_project_id_expr()).filter(
    effective_project_id=project_id, name__in=names
)
```

Every taxonomy table leads its scope index with that expression: `event_definition_proj_uniq` on `posthog_eventdefinition`, `posthog_propdef_proj_uniq` and `index_property_def_query_proj` on `posthog_propertydefinition`. Each of those is composite, so it can satisfy the scope and the `name` together.

Postgres cannot serve an `OR` from one index, so the `COALESCE` index is off the table and it bitmap-ORs two narrower scans instead. Neither branch applies both predicates the way the composite index would, so each reads more than it needs and the recheck discards the surplus. In one measured plan the `project_id = X` branch matched on the project alone, returned all 20,000 of that project's definitions, and the filter then dropped 19,850 of them.

Which branch wastes the work depends on what other indexes exist and on the data, so read the plan rather than assuming. What is constant is the composite index going unused, and the surplus growing with the tenant rather than with the request.

The `COALESCE` form seeks that index and uses `name` as a second scan key, so a 300-name lookup becomes 300 index descents instead of a scan and a discard.

Two details worth knowing:

- **The expression must match the index exactly**, including argument order. `COALESCE(team_id, project_id)` is a different expression and matches nothing. That is why `effective_project_id_expr()` is a shared function that lives next to the index definitions rather than something callers hand-write.
- **The integer/bigint mismatch is fine.** `team_id` is `integer` and `project_id` is `bigint`, so the index reads as `COALESCE(project_id, (team_id)::bigint)`. Postgres inserts the same implicit cast when parsing the query, so the trees still match. Confirm it in the `Index Cond` anyway.

A semgrep rule, `project-scope-filter-uses-coalesce`, blocks the `OR` form in CI.

### The catch: `COALESCE` is not strict

Fixing the index match can arm a second problem, in a query that also has an outer join.

Postgres demotes an outer join to a cheaper one when the `WHERE` clause proves the nullable side cannot be null — `reduce_outer_joins`. It proves that from **strict** quals, ones that return null for null input. `project_id = X` is strict. `COALESCE(project_id, team_id) = X` is not, because `COALESCE` returns a value even when its first argument is null.

So a `FULL OUTER JOIN` that Postgres used to demote stays a full join once the scope filter becomes `COALESCE`. A full join can be neither a nested loop nor a filter pushed into the scan, which leaves a sequential scan of the whole table as a plan the planner may pick. It usually will not, until an auto-`ANALYZE` shifts the estimates.

That failure is intermittent and parameter-dependent, which is what makes it hard to recognize. The same query is fine whenever the request happens to add another strict qual on the same table — a `name NOT LIKE`, a search term — because that restores the demotion.

Check for an outer join whenever you rewrite a scope filter into `COALESCE` form. Where the join is over a multi-table-inheritance child, `FULL OUTER JOIN` is almost always wrong anyway: the child's pointer column is its primary key and a NOT NULL foreign key, so a full join adds no rows and only removes plans.

**Swapping `FULL OUTER` for `LEFT` is only safe with the parent table on the left.** Check which side the query names first, because these are hand-written SQL strings and some put the child first. `posthog/taxonomy/property_definition_api.py` builds its `table` as `ee_enterprisepropertydefinition FULL OUTER JOIN posthog_propertydefinition`. Changing only the join word there drops every property definition that has no enterprise row, which is most of them. Reorder to `parent LEFT JOIN child` and prove it with a test that asserts a definition with no child row still comes back.

## Other house anti-patterns

- **Unbounded `IN` lists.** Cap the list at the call site. Even an index-backed lookup does one descent per element, and an uncapped list from customer data has no ceiling.
- **A query inside a loop.** A queryset built per item, or one fingerprint with a call count that tracks rows rather than requests. Batch it into one `__in` query, or hoist it out and cache per team.
- **`.count()` on an unfiltered queryset.** Postgres counts by walking rows. Use an estimate, or filter first.
- **A missing `select_related` / `prefetch_related`** turns one query into one-per-row when the template or serializer touches a relation.
- **Writing a row that is already correct.** An `UPDATE` that sets a column to the value it already holds still takes a lock and leaves a dead tuple. Guard it in the `WHERE`.
- **A raw-SQL statement built from an unordered collection.** Iterating a Python `set` to render a column list gives a different order per process, because the hash seed is per process. Surfaces that group by the statement text then split one query across hundreds of entries, and none of them looks expensive while the query burns the cluster. RDS Performance Insights groups this way. Sort anything you interpolate into SQL. Grouping is not the same on every surface, so when a query is heavy but nothing in one tool shows it, check another before concluding the query is fine.

## Before you call it done

- Show the two plans, before and after, with buffer counts. A claim that a query "now uses the index" is worth nothing without the `Index Cond`.
- Check whether the same shape exists elsewhere. These patterns get copied — the fix is usually three call sites, not one.
- Consider whether a lint rule can hold the line. See the ladder in `CLAUDE.md` under "Agent automation"; `.semgrep/rules/devex/` is where a Python pattern rule goes.
- Keep production numbers out of the PR. The repository is public — describe the effect qualitatively and leave exact row counts, customer names, and internal dashboards in the thread. See "Public open source repo guidance" in `CLAUDE.md`.
