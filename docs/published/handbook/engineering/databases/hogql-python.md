---
title: Writing HogQL queries in Python
sidebar: Handbook
showTitle: true
---

> ❗️ This guide is intended only for development of PostHog itself.
> If you're looking for documentation on writing HogQL (or SQL) queries, go to the [SQL](/docs/sql) docs.

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
- We wrote one AST node ourselves: `ast.Constant(value=num_last_days)`. We did it to santise the value by make sure it's treated as a constant. We might simplify constants further (e.g. `parse_const` or just `{days: 2}`), but we're not there yet.

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

    # lazy table that adds a join to the persons table
    pdi: LazyTable = LazyTable(
        from_field="distinct_id", table=PersonDistinctIdTable(), join_function=join_with_max_person_distinct_id_table
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
