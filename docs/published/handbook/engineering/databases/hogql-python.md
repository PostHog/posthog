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

## Pattern matching during query preparation

Expressions inside HogQL placeholders execute in the Python HogVM.
Its regex and LIKE functions and operators accept patterns up to 16,384 characters.
Larger patterns raise a `HogVMException`; shorten the pattern before matching.
Subject strings have no separate matching limit and use the VM's existing 64 MiB stack memory budget, so matching can process multi-megabyte response bodies.
These limits also apply to `extractRegex`, which still returns an empty string for invalid regex syntax.
Regex matching uses RE2 syntax, so backreferences and lookaround are unsupported.

SQL LIKE and ILIKE patterns sent to ClickHouse are not subject to these VM limits.
For non-nullable materialized columns, patterns above 16,384 characters skip the optional sentinel-based rewrite and use the normal property read.

## Scan estimate accuracy

ClickHouse execution records `estimated_rows` alongside `plan_fingerprint` in the query's `log_comment` when at least one table in the query has a measured estimate.
This uses the same estimator as the SQL editor, independently of the editor's display flag.
Missing statistics, unsupported queries, and estimator failures leave the estimate tag absent and do not prevent execution.
The `scan_estimate` timing measures the added planning work.

The estimate has one entry per table in the FROM tree, each labeled with its source and precision.
An `events` scan is `measured`: it has a model of what the query reads and is scored by the accuracy query.
A warehouse table is `size_only`: its rows and bytes are known from the last sync, the query's read of it is not.
`persons` and `groups` are `size_only` too, from a count of the team's rows that is cached for a day.
A table on a customer's own database (a direct Postgres, MySQL or Snowflake source) is `size_only` from the row estimate its catalog reported at the last schema refresh, and is never scored, because nothing returns `read_rows` for a query that ran there.
`sessions` is `measured` like events: a daily rate, cached for a day, scaled to the range the query puts on the session start time.
Any other table is `unknown` until its source gets a statistic.
The headline `rows` sums the entries that have a number, and `upper_bound` says whether that sum is a ceiling.
`cost_plan` renders the same facts as one plan (`posthog/hogql/cost/explain.py`): each scan in FROM order, the property filters that apply to it with how much each skips, then one join line.
It is what the SQL editor shows when the bar is expanded, and what an agent reads to decide whether to narrow a query before running it.

The estimate counts rows read, not rows returned, so a property filter lowers it only when a skip index can drop granules.
An equality or `IN` filter on an event property with a bloom filter index is scaled by the share of granules expected to hold a match.
That share comes from the number of distinct values recorded for the property in the `property_values` table.
A filter with no usable index does not change the estimate, because the query reads every row either way.
Any other indexed filter sets `upper_bound`, and the SQL editor then shows "Reads up to" instead of "Reads about".

Use `posthog.hogql.cost.accuracy.cost_estimate_accuracy_hogql(days=7)` to generate a HogQL query over the team's archived `query_log`.
It compares estimated rows with actual `read_rows` for successful initial queries, grouped by plan fingerprint.
Both row counts must be positive.
The report includes row-only estimates; byte accuracy uses only entries with positive byte estimates and reads, and returns `NULL` when none exist.
Q-error measures the larger of estimate / actual and actual / estimate: 1 is exact, and 3 means a factor of three off.

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
