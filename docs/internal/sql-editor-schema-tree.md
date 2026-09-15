# SQL editor schema tree

The SQL editor requests the database catalog with `DatabaseSchemaQuery.includeFields = false`.
The response contains table names and source metadata, with empty field dictionaries.
The sidebar does not mount source management or request the full external source list.
Connection labels and the default schema come from `external_data_sources/connections/`.
Saved query lists use `include_columns=false`; other API clients retain column definitions by default.
The list endpoint validates `include_columns` as a boolean and rejects invalid values.

Expanding a table or saved view requests its fields through `DatabaseSchemaQuery.tables`.
Saved views use the shared schema store for tree fields, joined fields, and the field overlay.
Expanded joins request the referenced table separately, including joins nested inside other joins.
Field requests share the database store, deduplicate concurrent requests, and ignore responses from an older connection or schema refresh.
Restored expanded nodes load their fields when the table catalog arrives.
Failed field requests can be retried by collapsing and expanding the table.

There is no timed background request for all fields.
Consumers that need fields across the catalog must request them explicitly with `ensureAllTableFields`.
Sidebar search uses this to retain column-name matching.
Schema mutations invalidate and refresh the catalog; field hydration follows the expanded nodes.
