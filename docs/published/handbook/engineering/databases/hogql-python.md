---
title: Writing HogQL queries in Python
sidebar: Handbook
showTitle: true
---

> ❗️ This guide is intended only for development of PostHog itself.
> If you're looking for documentation on writing HogQL (or SQL) queries, go to the [SQL](https://posthog.com/docs/sql) docs.

HogQL is our layer on top of ClickHouse SQL which provides nice features such as:

- Automatic person/group/etc property joins depending on the team/context
- Customisable database schema per team
- Flexible AST-powered templating language for building queries.

## Query templates

HogQL queries are built up from AST (Abstract Syntax Tree) nodes.

You can build the nodes yourself, or use the helpers `parse_expr` and `parse_select` to convert HogQL strings into AST nodes:

```py
from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.parser import parse_expr, parse_select

num_last_days = 2

stmt = parse_select(
    "select event, timestamp from events where {where} limit 100",
    {
        'where': parse_expr(
            'timestamp > interval {days} days',
            { 'days': ast.Constant(value=num_last_days) }
        )
    }
)

query_result = execute_hogql_query(query=stmt, team=team, query_type="used in logs")
query_result.results == [...]
query_result.columns == ['event', 'timestamp']  # might be useful if you select '*'
```

Few things to note:

- `parse_select` parses full `SELECT` queries while `parse_expr` parses any expression (`1+1` or `event` or even a subquery `(select 1)`). It's not possible to parse parts of a select query, such as `limit 10`.
- Placeholders like `{where}` are just nodes of type `ast.Placeholder(field='where')`. You can leave them in, and call `stmt = replace_placeholders(stmt, { where: parse_expr('1') })` later.
- We wrote one AST node ourselves: `ast.Constant(value=num_last_days)`. We did it to sanitize the value by make sure it's treated as a constant. We might simplify constants further (e.g. `parse_const` or just `{days: 2}`), but we're not there yet.

Placeholder expansion allows at most 1,000 placeholders and shares a five-second deadline across the query.
All placeholders also share a 64 MiB budget in Hog VM memory units, charged using each expression's peak stack usage, including temporary values.
This accounting is not a limit on Python process memory.
The `range()` builtin checks its result size against the remaining VM allowance before allocating the list.
Queries that exceed these limits fail during expansion; reduce the number or size of the placeholder expressions to stay within them.

## Experimental count-query batching

`posthog.hogql.batch.CountBatchPlanner` builds an opt-in execution plan for a mapping of query IDs to HogQL strings.
It combines compatible `count()` and `count(column)` queries into conditional aggregates, then splits the output back into each query's rows, column names, and types.
Column counts accept unqualified columns and `properties.<key>` references and exclude null values.
Daily groups with no matching rows remain absent, but groups whose counted values are all null remain present with zero.
An empty ungrouped count remains one row containing zero.

Run it against the existing local PostHog database, from the repository root with the Python environment activated and the development services running:

```bash
set -a
source .env.services
set +a
DEBUG=1 PERSONHOG_ADDR=127.0.0.1:50052 python -m posthog.hogql.scripts.batch_demo --team-id 1
DEBUG=1 PERSONHOG_ADDR=127.0.0.1:50052 python -m posthog.hogql.scripts.batch_demo --team-id 1 --queries queries.json
DEBUG=1 python -m posthog.hogql.scripts.batch_demo --plan-only
```

Use your project's ID for `--team-id`; the runner never chooses a project implicitly.
Database execution combines queries only when the project-scoped backend feature flag `hogql-query-sharing` evaluates to `true`. Missing, disabled, or unavailable flag evaluation keeps queries separate. Local flag definitions must be available to the analytics SDK; this adapter does not fall back to remote flag evaluation.
Connections come from the normal Django settings, including `CLICKHOUSE_DATABASE` and `DATABASE_URL`.
The database runner uses the regular HogQL compiler with that project's schema and modifiers, then executes read-only ClickHouse queries.
It does not create tables or substitute event data. `SELECT *`, properties, joins, and other ClickHouse-backed HogQL queries execute separately when they cannot combine.
An event's time is `timestamp`; `properties.$timestamp` means a JSON property with that name, not the event's time. Browser properties normally use `properties.$browser`.
Query-level `SETTINGS` and direct warehouse connections are not supported by this adapter.

The CLI prints the plan, compares separate and combined results, and reports executions, rows read, and summed server time (including compiler lookups).
It displays up to ten result rows but compares the complete results. It does not inject the SQL editor's preview limit.
`--show-sql` prints compiled ClickHouse SQL. Execution errors include the failing query IDs and the underlying error.
Queries fail rather than return partial results at the configured limits: `--timeout` (15 seconds), `--max-result-rows` (1,000,000), 128 MiB result size, and 512 MiB query memory.
Concurrent ingestion, volatile expressions such as `now()` or `rand()`, and `LIMIT` without deterministic ordering can cause mismatches between successive executions; there is no shared snapshot.
These measurements are not whole-dashboard latency benchmarks.

To change the batch, pass `--queries <file.json>` with an object mapping query IDs to SQL:

```json
{
  "all": "SELECT count() AS n FROM events WHERE event = 'purchase' AND timestamp >= '2026-01-01' AND timestamp < '2026-01-08'",
  "chrome": "SELECT count() AS n FROM events WHERE event = 'purchase' AND timestamp >= '2026-01-01' AND timestamp < '2026-01-08' AND properties.$browser = 'Chrome'"
}
```

Choose bounds and events that exist in your project. The default database batch uses a broad fixed date range and includes a recent-events query that executes separately.

For an isolated fixture without application services, use `--synthetic` (and optionally `--rows 0` or `--container <name>`).
This mode substitutes a `system.numbers` fixture exposing `timestamp`, `event` (`purchase` or `signup`), `distinct_id`, and `properties.browser` (`Chrome` or `Firefox`), across January 1–7, 2026.
Its measurements demonstrate repeated work on generated data, not savings on application tables.

The combining rule accepts a single unaliased `events` source and either a total or `GROUP BY toDate(timestamp)` with the day selected.
Grouping and day ordering must match. Timestamp bounds may be absent, one-sided, overlapping, or disjoint; literal bounds retain their exact operators and timezone arguments inside each aggregate.
Each aggregate applies its own full filter. The shared scan reads the union of the original filters, with common conditions factored out for pruning.
Without a restricting filter, the scan can read the entire project; this is allowed, not a promise of a speedup.
Simple comparisons on event fields and properties are supported. Joins, other aggregates, arbitrary count expressions, relative time, CTEs, limits, settings, and unsupported expressions remain separate, with a reason in the plan.
Equivalent supported count queries share an aggregate even when their output aliases differ. Deduplication is structural, not a general SQL-equivalence proof; unsupported or volatile queries are not deduplicated.
When a batch group contains only duplicates, it retains the original `count` expression rather than rewriting to `countIf`, preserving ClickHouse's count optimizations.
`--max-group-size` bounds the distinct count/filter combinations in each group (default 8); duplicate outputs do not consume additional slots.

This is an experimental library and local playground, not a dashboard endpoint.
`BatchPlan.execute()` takes an execution callback; a future application adapter must preserve one team/access context and return complete, untruncated results.
Execution is sequential and errors propagate without automatic retries. Dashboard caching, deadlines, cancellation, and per-chart error handling are not implemented.
The optional synthetic SQL adapter is not the production HogQL compiler and must not be used to execute against application tables.

### Experimental aggregation sharing

`posthog.hogql.multi_query.MultiQueryPlanner` accepts an ordered registry of sharing rules and returns independent execution groups, per-consumer result routers, and rejection reasons. Rules operate on cloned ASTs and do not execute queries or manage caches. The existing count planner is available through `CountFusionRule`.

`SameAggregationTopNRule` combines pairs with identical input, projection, grouping, and `HAVING`, but different output rankings and limits. It computes the aggregation once, ranks each consumer in ClickHouse, and returns only the requested rows with routing metadata. Each limit must be a positive literal no greater than 1,000. Output aliases must match; ordering must reference selected outputs. It supports a conservative function allowlist over `events`, including expanded deterministic projection/filter subqueries. Opaque views, joins, relative time, windowed inputs, nested limits, offsets, `WITH TIES`, settings, and unknown functions remain separate.

Try the standalone comparison against local ClickHouse:

```bash
DEBUG=1 python -m posthog.hogql.scripts.batch_demo --sharing --synthetic --rows 1000000
DEBUG=1 python -m posthog.hogql.scripts.batch_demo --sharing --synthetic --rows 0
```

The generated fixture has a frequently called tool with few distinct users, so the two top-five rankings differ. Original queries execute concurrently, as do independent optimized groups. The comparison reports row/type equality, rows and bytes read for the synthetic source, summed server time, and client wall time. Local timings and generated-source byte counts are not production savings estimates. Add deterministic tie-breakers when comparing exact ordered results.

For existing local data, supply `--sharing --team-id <id> --queries <file.json>` using the same environment setup as above. This path calls `HogQLQueryExecutor.prepare_for_sharing()` before matching, resolving views, placeholders and output names without running the analytics. It returns a cloned logical AST so the shared query can be compiled with fresh parameter bindings. `--plan-only` does not connect to the database and therefore matches only the supplied syntax, without expanding saved views.

Every `SharingQuery` carries a caller-validated context key. Compiler preparation includes the request scope, principal/access context identity, team, effective settings/modifiers, workload and timezone. The key is a compatibility partition, not authorization or a persistent cache key. The caller must still validate permissions, use one consistent schema/time context, execute under that context, and reject truncated results. Inputs are limited to 32 queries by default.

`SharingQuery.sharing_enabled` defaults to `False`. Compiler preparation populates it from `hogql-query-sharing`; the planner excludes disabled inputs from every sharing rule. Synthetic fixtures and syntax-only planning explicitly opt in without consulting a project flag. They do not execute against application tables.

The standalone comparison propagates shared execution failures. It does not exercise dashboard caching, cancellation, or retries.

### Experimental dashboard integration

Authenticated dashboard refreshes can opt into shared execution behind `hogql-query-sharing`, checked by both the browser and backend. The flag is off by default. Public/shared dashboards, embedded placements, and refreshes outside 2–32 insight tiles keep the existing loading path.

The dashboard sends one streaming request with its effective filters and variable overrides. Up to four workers use the existing insight serializer and query runner, preserving per-insight permissions, cache keys, refresh modes, and rate limits. Cached tiles return without entering the planner. Eligible SQL queries wait up to 50 ms for a compatible partner; unsupported queries execute immediately. Matching is opportunistic within that window, not a global optimization across every tile.

The adapter supports the planner's same-aggregation top-N pairs and scalar `count()` / `count(column)` pairs. It removes positive pagination limits only from supported scalar counts, which always return one row. Paginated daily counts remain separate. Other insight types continue through their normal query runners.

Each tile streams as soon as it completes. A failed or incomplete shared query falls back to the original queries independently, and one tile's query error does not fail its siblings. A broken stream retries only undelivered tiles through the existing refresh path. Disconnecting or starting another refresh cancels queued work and requests ClickHouse cancellation for that batch.

Monitor `posthog_dashboard_sharing_executions_total` for separate executions, shared groups, and fallback groups. Sharing reduces duplicate work only when compatible, uncached queries meet during the matching window; it does not guarantee lower dashboard latency.

## Pattern matching during query preparation

Expressions inside HogQL placeholders execute in the Python HogVM.
Its regex and LIKE functions and operators accept patterns up to 16,384 characters.
Larger patterns raise a `HogVMException`; shorten the pattern before matching.
Subject strings have no separate matching limit and use the VM's existing 64 MiB stack memory budget, so matching can process multi-megabyte response bodies.
These limits also apply to `extractRegex`, which still returns an empty string for invalid regex syntax.
Regex matching uses RE2 syntax, so backreferences and lookaround are unsupported.

SQL LIKE and ILIKE patterns sent to ClickHouse are not subject to these VM limits.
For non-nullable materialized columns, patterns above 16,384 characters skip the optional sentinel-based rewrite and use the normal property read.

## ClickHouse query errors

`posthog/errors.py` maps ClickHouse error codes to exceptions. Query APIs expose `ExposedCHQueryError` messages and hide `InternalCHQueryError` messages.
For additional user-correctable errors, set `ErrorCodeMeta.user_safe` to a fixed explanation with a next step.
Parsing, array, regular expression, scalar subquery, JOIN, and LIMIT errors use these explanations where raw details cannot be exposed safely.
Unrecognized error codes stay internal.

Do not assume an error code makes its raw message safe. ClickHouse can append expressions and query context after the initial exception.
Those messages can contain storage credentials, signed URLs, settings, or source data values, including values that a shared insight does not otherwise reveal.
Check both the throw sites and the exception enrichment paths before allowing raw text.
Keep importable exception classes when adding a fixed explanation, and test the wrapped message as well as its string representation.

## AST nodes

If you want more control, you can build the AST nodes directly. The same query above can be written as:

```py
from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.parser import parse_expr

num_last_days = 2

stmt = ast.SelectQuery(
    select=[ast.Field(chain="event"), ast.Field(chain="timestamp")],
    select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
    where=parse_expr(
        "timestamp > interval {days} day",
        { 'days': ast.Constant(value=num_last_days) }
    ),
    limit=ast.Constant(value=100),
)

query_result = execute_hogql_query(query=stmt, team=team, query_type="used in logs")
query_result.results == [...]
query_result.columns == ['event', 'timestamp']  # might be useful if you select '*'
```

You can mix and match `parse_expr` and `ast` nodes as you please. The example above _still_ took a shortcut for the where clause because it was easier to write.

## Snowflake date formatting

For direct Snowflake queries, `formatDateTime` requires a literal format string and translates supported strftime specifiers into Snowflake format elements.
The printer binds the translated format as a query parameter, preserving literal quotes and backslashes in the parameter value.
Pass the printed SQL and `HogQLContext.values` together to the database driver.

## Database schema and features

The HogQL database schema is in flux. You will soon be able to explore it in the [PostHog app itself](https://github.com/PostHog/posthog/pull/14591).

The most up to date resource is [hogql/database.py](https://github.com/PostHog/posthog/blob/master/posthog/hogql/database.py) on Github. At the time of writing, these tables were available:

```python
class Database(BaseModel):
    # Users can query from the tables below
    events: EventsTable = EventsTable()
    persons: PersonsTable = PersonsTable()
    person_distinct_ids: PersonDistinctIdTable = PersonDistinctIdTable()
    session_recording_events: SessionRecordingEvents = SessionRecordingEvents()
    cohort_people: CohortPeople = CohortPeople()
    static_cohort_people: StaticCohortPeople = StaticCohortPeople()
```

Some tables have some fields that are actually "lazy tables". When accessed they will add a join to the table. The events table is such an example:

```python
class EventsTable(Table):
    uuid: StringDatabaseField = StringDatabaseField(name="uuid")
    event: StringDatabaseField = StringDatabaseField(name="event")
    properties: StringJSONDatabaseField = StringJSONDatabaseField(name="properties")
    timestamp: DateTimeDatabaseField = DateTimeDatabaseField(name="timestamp")
    team_id: IntegerDatabaseField = IntegerDatabaseField(name="team_id")
    distinct_id: StringDatabaseField = StringDatabaseField(name="distinct_id")
    elements_chain: StringDatabaseField = StringDatabaseField(name="elements_chain")
    created_at: DateTimeDatabaseField = DateTimeDatabaseField(name="created_at")

    # lazy join that joins in the person_distinct_ids table when accessed. The join is described
    # as plain data: a resolver tag naming a join recipe in `lazy_join_registry.RESOLVERS`.
    pdi: LazyJoin = LazyJoin(
        from_field=["distinct_id"], join_table=PersonDistinctIdsTable(), resolver=PERSON_DISTINCT_IDS
    )
    # person fields on the event itself
    poe: EventsPersonSubTable = EventsPersonSubTable()

    # These are swapped out if the user has PoE enabled
    person: FieldTraverser = FieldTraverser(chain=["pdi", "person"])
    person_id: FieldTraverser = FieldTraverser(chain=["pdi", "person_id"])
```

If you access `pdi.person.properties.$browser`, we make a join via `persons` (this is a HogQL table name, not ClickHouse name). We do a bunch of `argmax` magic in the join, and inline all accessed properties within the subquery for performance. For the user, it looks just like simple property access.

If you access `poe.properties.$browser`, we will actually access the field `person_properties` on the events table.

In practice, you should avoid both and access `person.properties.$browser`, which will choose the right approach for you.

Add new tables and fields as needed! Just make sure each table has a `team_id` column.

Internal marketing queries can read cached session dimensions from `posthog.web_sessions_dimensional_preaggregated`.
Rows include a precompute job ID and the person ID at computation time; readers must resolve current identities separately.
