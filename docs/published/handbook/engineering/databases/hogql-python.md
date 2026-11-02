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

Saved views allow at most 100 nested views and 1,000 expansions per compilation, including repeated references to the same view.
Their cumulative expanded SQL source is limited to 4 MiB (UTF-8), charged before each parse; this is not a Python memory limit.
Circular dependencies fail with a query error. Soft saves skip column inference but still validate view dependencies.
Query preparation shares a 60-second cooperative deadline across parsing, resolution, transformations, and printing.
AST visitors check the deadline while walking; native parser calls are checked when they return, rather than interrupted mid-call.

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

Pass compiled ClickHouse SQL and `HogQLContext.values` together to the database client. The printer reserves `%(name)s` placeholders for values and rejects percent signs in identifiers. Do not apply brace formatting to compiled SQL: braces are valid identifier characters and must remain literal after authorization.

For trusted SQL templates passed to the Temporal `ClickHouseClient`, distinguish the layer that consumes each placeholder:

| Purpose              | Plain Python string | Python f-string source | Consumed by                                             |
| -------------------- | ------------------- | ---------------------- | ------------------------------------------------------- |
| Client-bound value   | `%(name)s`          | `%(name)s`             | `prepare_query`, after SQL value escaping               |
| Server-bound value   | `{name:Type}`       | `{{name:Type}}`        | ClickHouse, using the HTTP `param_name` parameter       |
| S3 partition marker  | `{_partition_id}`   | `{{_partition_id}}`    | ClickHouse                                              |
| Empty JSON object    | `'{}'`              | `'{{}}'`               | Neither; SQL string data                                |
| Literal percent sign | `%%`                | `%%`                   | `prepare_query`, when the parameter mapping is nonempty |

An f-string consumes one brace-escaping layer in its source. It does not reinterpret braces inside an interpolated string. `string.Template` substitutes `$name` and leaves braces unchanged. If a trusted template uses `.format()`, that call also needs its own brace escaping. Count these construction steps separately from database binding; do not halve braces across a query indiscriminately.

## Snowflake date formatting

For direct Snowflake queries, `formatDateTime` requires a literal format string and translates supported strftime specifiers into Snowflake format elements.
The printer binds the translated format as a query parameter, preserving literal quotes and backslashes in the parameter value.
Pass the printed SQL and `HogQLContext.values` together to the database driver.

## Database schema and features

Built-in tables also accept the `posthog` namespace, such as `SELECT id FROM posthog.persons` and `SELECT count() FROM posthog.groups`.
Explicit aliases work with these names, for example `SELECT p.id FROM posthog.persons AS p`.

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

On the native JSON events table, HogQL compares non-empty string constants directly with declared String paths and casts Dynamic paths to Nullable(String) for properties with String or unknown definition types.
This keeps equality and membership predicates visible to the JSON skip index without failing on mixed scalar types.
Numeric and Boolean properties on the native table compare as text when a string literal cannot be converted to the property's definition type.
Boolean literals keep ClickHouse's case-insensitive spellings, including yes/no, on/off and enable/disable.
DateTime property definitions keep their conversions when compared with strings, for both event and person properties.
Boolean conversion reads the native path directly because object and array text cannot match `true` or `false`; numeric conversions already read native paths directly.
Constants starting with `[` or `{` keep the full property read because arrays and objects serialize differently from scalars.
Single-property reads serialize sub-objects with ClickHouse's JSON formatter; whole-document reads still remove declared defaults.
Grouping keys and expressions evaluated after grouping use the general property reader so conversions reference the same expression as GROUP BY.
This includes window inputs, HAVING, ORDER BY and LIMIT BY; ordinary aggregate inputs and row-level predicates retain direct-path optimizations.
When a join constraint needs a lazy join of the joined events table, HogQL wraps that table in a subquery and the outer query reads the subquery's columns.
The subquery exports the columns, lazy-join fields and property keys the outer query reads, found by their resolved table binding rather than by alias text.
A property key is exported as its stored value and the outer read keeps its own conversion, so a Numeric definition and an explicit string parser read the same export.
The whole `properties` document is exported only where the outer query reads it whole, and each wrapped table decides this on its own.
Raw SQL property readers preserve backslashes before forward slashes whether ClickHouse's `output_format_json_escape_forward_slashes` setting is enabled or disabled.
Native queries disable forward-slash escaping so object and array text retains `/`.

Add new tables and fields as needed! Just make sure each table has a `team_id` column.

Internal marketing queries can read cached session dimensions from `posthog.web_sessions_dimensional_preaggregated`.
Rows include a precompute job ID and the person ID at computation time; readers must resolve current identities separately.
