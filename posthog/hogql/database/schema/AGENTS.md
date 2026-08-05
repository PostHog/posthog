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
