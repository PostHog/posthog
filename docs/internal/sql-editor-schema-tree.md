# SQL editor schema tree

The SQL editor requests the database catalog with `DatabaseSchemaQuery.includeFields = false`.
The response contains table names and source metadata, with empty field dictionaries.
The sidebar does not mount source management or request the full external source list.
Connection labels and the default schema come from `external_data_sources/connections/`.
Saved query lists use `include_columns=false`; other API clients retain column definitions by default.
The list endpoint validates `include_columns` as a boolean and rejects invalid values.

Expanding a table or saved view requests its fields through `DatabaseSchemaQuery.tables`.
Filtered responses fetch serialization metadata only for the requested tables and views, including raw warehouse aliases.
Warehouse field requests first read a lightweight name catalog, then load column definitions only for the requested namespaces.
Keeping the namespace preserves inferred foreign keys, reverse joins, and the field names exposed on joined tables.
Requests with saved views in that namespace, explicit joins, saved expressions, revenue views, or event modifiers retain the complete construction path.
Direct connections and requests that include built-in tables also retain the complete construction path.
Serialization metadata reads do not reload warehouse credentials or decrypt source configuration.
Database construction still loads credentials for retained warehouse tables.
Saved views use the shared schema store for tree fields, joined fields, and the field overlay.
Expanded joins request the referenced table separately, including joins nested inside other joins.
Joins into saved views show loading or error children until the view's fields are available, including when the join is restored as expanded.
Field requests share the database store, deduplicate concurrent requests, and ignore responses from an older connection or schema refresh.
Restored expanded nodes load their fields when the table catalog arrives.
Failed field requests can be retried by collapsing and expanding the table.

Tables and nested joins expand on the first click, including after scrolling.
The virtualized tree keeps each rendered row under a parent keyed by the item ID.
Changing the visible range preserves the focused row so mouse-down and mouse-up reach the same element.

There is no timed background request for all fields.
Consumers that need fields across the catalog must request them explicitly with `ensureAllTableFields`.
Sidebar search uses this to retain column-name matching.
Warehouse series, warehouse property menus, and the data quality check editor explicitly request complete fields when needed.
After that request, catalog reloads also restore complete fields for consumers of the shared store.
Schema mutations refresh previously hydrated or pending tables, as well as expanded nodes.
Saved-query lists expose metadata only; refreshing them preserves the query and columns already fetched for an open editor tab.

## Saved-query writes

The saved-query API accepts `sync_frequency` on create and update.
Create applies the cadence after creating the DAG node, in the same transaction, so a refused cadence leaves no saved query behind.
An omitted cadence leaves the target unchanged on update; explicit `null` and `"never"` both clear it.
Invalid cadence values return 400.

`edited_history_id` protects query updates from concurrent edits and is ignored on create.
`soft_update` skips column inference and external table discovery on create and update, and skips the revision conflict check on update.
Query validation and revision updates still run.

`deleted` is read-only.
Use DELETE to remove a saved query so DAG cleanup, join cleanup, materialization cleanup, and name release run together.
Create does not upsert deleted rows.
A deleted row whose name was not released still reserves that name and needs separate cleanup.

`dag_id` must identify a non-managed DAG in the same project; invalid or foreign IDs return 400.
A DAG-only update moves the existing node and preserves its cadence and job history.
Moves are refused when the view has dependents, belongs to a managed DAG, has nodes in multiple DAGs, or has a materialization running.
Explicit `null` selects the default DAG.
