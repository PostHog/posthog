# HogQL schema definitions

This directory defines the tables and columns available in HogQL (events, persons, sessions,
system tables, etc.). Each table is a `Table`/`LazyTable` subclass whose `fields` map column names
to `DatabaseField` instances.

## Documenting tables and columns

Every `Table` and `DatabaseField` accepts an optional `description` (defined on `FieldOrTable` in
[`../models.py`](../models.py)). Set it to a short, factual sentence — what the value is, its units,
and how it relates to other tables. These descriptions are the canonical, human/agent-facing
documentation for the schema.

```python
class EventsTable(Table):
    description = "Every analytics event captured for the project."
    fields = {
        "timestamp": DateTimeDatabaseField(
            name="timestamp",
            nullable=False,
            description="When the event occurred (client timestamp, in UTC).",
        ),
        ...
    }
```

Descriptions are surfaced automatically through the queryable `system.information_schema` tables
(see [`information_schema.py`](information_schema.py)) — `tables`, `columns`, `relationships`, and
`data_types` — so agents can discover and disambiguate the schema with plain HogQL:

```sql
SELECT column_name, data_type, description
FROM system.information_schema.columns
WHERE table_name = 'events'
```

Prioritise descriptions for **ambiguous or easily-confused** columns (e.g. `timestamp` vs
`created_at`, `distinct_id` vs `person_id`). For data warehouse tables, descriptions come from the
`WarehouseColumnAnnotation` semantic layer and are merged in automatically — you don't set them here.

No regeneration step is required: descriptions are read live from the field objects at query time.

## Access control on system tables

A `PostgresTable` under the `system` namespace must declare `access_scope` — the same resource its REST viewset declares as `scope_object`.
That one field drives everything: the schema strip that hides the table from principals without the resource, the printer's `notIn` guard that drops rows for objects the caller is denied, and the query-cache partitioning that keeps a denied caller off an allowed caller's cached rows.
Leave it off and a user denied an object through its API can read the row — and whatever its `query`, `filters`, or `export_context` column holds — with plain HogQL.

When the rows belong to a parent object rather than being that object (a job run of a view, a recalculation of a cohort), also set `access_control_id_field` to the foreign key pointing at the parent, so denying the parent hides its child rows.
The deny set only ever holds parent IDs, so a child table left on its own primary key filters nothing.

`test_all_postgres_system_tables_declare_an_access_scope` fails on any new table without a scope.
A table that genuinely needs none goes in that test's `INTENTIONALLY_UNSCOPED_SYSTEM_TABLES` with the reason.
