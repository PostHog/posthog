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
