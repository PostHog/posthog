# HogQL access controls

HogQL enforces access control in three layers:

1. **[System tables](#1-system-tables)** — the `system.*` tables (dashboards, notebooks, error tracking issues, ...).
   - Enforced at schema build time and print time.
   - When denied: the whole table is removed from the schema and the query errors; individual denied objects are filtered out with a `WHERE` guard.
2. **[Warehouse tables and views](#2-warehouse-tables-and-views)** — `DataWarehouseTable` and `DataWarehouseSavedQuery` (views and materialized views).
   - Enforced at schema build time.
   - When denied: the table or view is removed from the schema and the query errors.
3. **[Property access control](#3-property-access-control)** — sensitive event and person properties (PII like email).
   - Enforced when the query is printed to ClickHouse SQL (AST transform, then printing).
   - When denied: values are masked to `NULL` or stripped from the JSON blob, with no error.

All three layers share one preloaded `UserAccessControl` instance and partition the query cache so a restricted user can never be served an unrestricted user's cached rows.

## Passing the user into HogQL

Access control needs to know who is querying.
The user is threaded through `Database.create_for()` and `HogQLContext` (`posthog/hogql/context.py`):

```python
from posthog.hogql.query import execute_hogql_query

# The standard path: query runners pass the request user through
execute_hogql_query(query="SELECT * FROM system.dashboards", team=team, user=request.user)
```

```python
from posthog.hogql.database.database import Database

# Building the schema directly
database = Database.create_for(team=team, user=user, user_access_control=user_access_control)
```

`HogQLQueryRunner` and `QueryRunnerWithHogQLContext` (`posthog/hogql_queries/query_runner.py`) do this automatically when constructed with a user.
The MCP `execute-sql` tool goes through the same path (`posthog/api/query.py` runs queries as `request.user`).

**Fail closed:** if you forget to pass the user, all access-controlled system tables are removed (`_compute_system_table_access_decision` in `posthog/hogql/database/database.py` returns every scoped table as denied for `user=None`), and all warehouse tables/views are denied (`_is_warehouse_table_denied` / `_is_warehouse_view_denied` fail closed when `user_access_control is None`).
This is deliberate: if someone forgets to pass the user, the query fails outright and makes the mistake obvious, instead of silently falling back to a permissive "default access" that would leak data.
In practice the user is available anywhere system tables are queried; for user-initiated background work, see [contexts without a request user](#contexts-without-a-request-user).

## 1. System tables

System tables are Postgres-backed tables under the `system.` namespace, defined in `SystemTables` (`posthog/hogql/database/schema/system.py`).
They're primarily used by the MCP `execute-sql` tool for retrieval.

### Resource-level access

Each access-controlled system table declares an `access_scope` (e.g. `system.dashboards` → `"dashboard"`, `system.error_tracking_issues` → `"error_tracking"`).

At schema build time, `_compute_system_table_access_decision()` checks `UserAccessControl.access_level_for_resource(access_scope)` for each scoped table and removes denied ones from the schema (`Database._apply_system_table_access()`).

Removed tables are tracked in `Database._denied_tables`, so referencing one raises a clear error instead of pretending the table doesn't exist — that way the user knows the table is there and can request access from an admin if they need it:

```text
You don't have access to table `system.error_tracking_issues`.
```

This is a `QueryError` (`posthog/hogql/errors.py`), so it's exposed to the user.

### Object-level access

Some resources support per-object access controls - dashboards, insights, notebooks, feature flags, experiments, surveys, error tracking issues, session recordings, etc.
For these, denied objects are filtered out of the results.

At print time the printer appends a guard that excludes the user's denied object IDs by primary key — effectively `WHERE <id> NOT IN (<denied ids>)`.
Child tables filter on the parent's FK — e.g. `system.dashboard_tiles` uses `access_control_id_field="dashboard_id"`.

When rows are filtered, the response carries a warning: "Results may exclude {resources} you don't have access to".

**Edge case:** object-level access does not override a resource-level deny in HogQL.
In the app UI you can open a specific dashboard you were granted access to even if the dashboard resource is denied for you; in HogQL the resource-level deny removes `system.dashboards` entirely, so the object grant doesn't help.
HogQL is intentionally more restrictive here, and it's a known limitation.

## 2. Warehouse tables and views

Gated by the `hogql-warehouse-access-control` feature flag (checked in `Database._fetch_sources`).

### Resource-level: the `warehouse_objects` umbrella

`warehouse_table` and `warehouse_view` both inherit from the umbrella resource `warehouse_objects` (`RESOURCE_INHERITANCE_MAP` in `posthog/rbac/user_access_control.py`).
Denying `warehouse_objects` for a user filters every warehouse table and view out of their schema at build time.

### Object-level: per-table and per-view

Specific tables and views can be restricted individually.
There's UI for this in the SQL editor: open a table's "More" menu → "Access controls".
A denied table or view is dropped from the schema entirely, and its name lands in `_denied_tables` so queries get "You don't have access to table" instead of "Unknown table".
The deny checks are `_is_warehouse_table_denied` and `_is_warehouse_view_denied` in `posthog/hogql/database/database.py`.

The creator always keeps access: `UserAccessControl.access_level_for_object()` grants the object's `created_by` user the highest level regardless of explicit denies.
"Creator" here is the `created_by` on the object — for a view, whoever authored it; for a warehouse table, whoever created the row (for an externally synced source, the user who connected the source).

### Views vs materialized views

The two behave differently when the user has access to the view but not the underlying table:

- **View (non-materialized):** the view's HogQL is inlined and re-resolved at query resolution time — `Resolver.visit_join_expr` (`posthog/hogql/resolver.py`) parses `database_table.query` and walks it like user SQL.
  That nested lookup of the underlying table hits the denied schema and raises `You don't have access to table ...`.
  So if you can't query the table directly, you can't reach it through the view either.
- **Materialized view:** the view resolves straight to its backing `DataWarehouseTable` — a real table, so no re-resolution of the source query happens.
  Access is checked on the view object only, so this works even when access to the table used in the materialized view is denied.
  **This is the supported way to expose a subset of columns from a restricted table.**

### Contexts without a request user

Without a user, warehouse access control denies every warehouse table and view, so every caller needs one of these:

1. **User is on the request:** pass it through, as shown in [passing the user into HogQL](#passing-the-user-into-hogql).
2. **Background job acting for a user:** use the resource's `created_by`. Alerts evaluate as `alert.created_by` (`products/alerts/backend/evaluation/hogql.py`), exports render as `exported_asset.created_by` (`products/exports/backend/tasks/csv_exporter.py`).
3. **Trusted internal job with no user at all:** pass `bypass_warehouse_access_control=True` explicitly. Used by materialization workflows (`posthog/temporal/data_modeling/`), insight cache warming, and ducklake compilation (`posthog/ducklake/client.py`). **Be very skeptical before adding a new bypass** — only do it when the job genuinely has no acting user and the output isn't served to a specific user with narrower access.

```python
# Background materialization job — no user exists, bypass explicitly
execute_hogql_query(query=..., team=team, bypass_warehouse_access_control=True)
```

4. **Public dashboards / notebooks / shared insights:** the viewer is anonymous, so queries run as `SharedLinkUser` (`posthog/shared_link_user.py`, built in `SharingViewerPageViewSet`).
   `Database.create_for` doesn't restrict any warehouse tables or views for a shared-link viewer; the access gate is at publish time instead.
   Enabling sharing requires editor-level access to the resource, so only someone who already has access can publish it.
   System tables stay fully denied for shared links — `readable_system_table_access_scopes()` returns an empty set.
5. **Project secret API keys:** these run as a `SyntheticUser` — `ProjectSecretAPIKeyUser` (`posthog/auth.py`) — which also isn't restricted on warehouse tables or views.
   That's intentional: a project secret API key is authorized by the scopes granted to the key, not by role-based access control.
   System tables are gated by the key's scopes via `readable_system_table_access_scopes()`.

## 3. Property access control

Hides sensitive event and person properties (e.g. `email`) from query results.
Rules live in the `PropertyAccessControl` model (`products/access_control/backend/models/property_access_control.py`).

Property access control is a paid feature, available on the Scale and Enterprise plans: it needs the `PROPERTY_ACCESS_CONTROL` entitlement, and without it resolution short-circuits to no restrictions.

### Enforcement: masking, not errors

Unlike the table layers, restricted properties do not error.
They're masked when the query is printed to ClickHouse SQL, so a restricted read is indistinguishable from a property that was never set (anti-enumeration):

- **Explicit reads** (`properties.email`) are replaced with `NULL`, and the resolver refuses to back them with a materialized column — `ClickHousePropertyResolver` in `posthog/hogql/transforms/clickhouse_property_resolution.py`.
- **Whole-blob reads** (`SELECT properties` or `SELECT *`) have the restricted keys stripped from the returned JSON via `JSONDropKeys(...)` — `ClickHousePrinter._maybe_apply_json_drop_keys()` in `posthog/hogql/printer/clickhouse.py`.

The restriction set is loaded once per query in `prepare_ast_for_printing()` and cached per `(team_id, user_id)` for the request lifetime.

### No user: default rules apply

When no user is present, only the team **default** rules apply instead of failing every query — see `get_restricted_properties_for_team()`.
There is the asymmetry with the warehouse access control, which bypasses entirely for shared links rather than applying a default; that may be aligned later.

## Query cache partitioning

**The critical invariant:** if a query reads access-controlled tables, its cache key must include the user's restrictions.
Otherwise a denied user gets served an allowed user's cached rows.

The cache key is derived from `get_cache_payload()`:

- `QueryRunner.get_cache_payload()` adds `restricted_properties` (sorted `(name, type)` pairs) when the user has property restrictions.
- `AnalyticsQueryRunner.get_cache_payload()` adds `restricted_resources` (denied scopes) and `restricted_objects` (denied object IDs per scope) for the table layers.

Two things keep cache hit rates high:

1. **Feature gate:** if the organization doesn't have `AvailableFeature.ACCESS_CONTROL`, no resource/object restrictions exist, so nothing is added and the cache isn't partitioned by user at all.
2. **Scoped to queried tables:** `queried_access_controlled_resources()` (`posthog/hogql_queries/access_controlled_resources.py`) parses the query and returns only the access-controlled scopes it actually reads, so warehouse scopes are added to the payload only when the query references warehouse tables or views — a plain **events or persons query shares one cache entry across all users**

When a run has no user but does read access-controlled resources, the fingerprint uses `restricted_resources: ["*"]` so it can never collide with a real user's cache, and synthetic principals partition on their readable scopes so a narrow token can't reuse a broader token's cached rows.

## One preloaded `UserAccessControl` everywhere

`UserAccessControl` (`posthog/rbac/user_access_control.py`) bulk-fetches every access control row relevant to the user on the team in a single query (`_cached_access_controls`, covering team defaults, the user's membership, and the user's roles), then resolves all checks in memory (`access_level_for_resource`, `check_access_level_for_object`, `blocked_resource_ids_by_scope`, ...).

The same instance is reused across:

- **Schema filtering:** passed into `Database.create_for()`, warmed by `_compute_system_table_access_decision()`, stored as `database.user_access_control`.
- **Cache fingerprint:** `QueryRunnerWithHogQLContext.user_access_control` returns `self.database.user_access_control`, so the fingerprint and the schema strip resolve access from the same preloaded rows.
- **Print-time row guards:** `build_access_control_guard()` reads `blocked_resource_ids_by_scope` off the same instance.
- **API-level (viewset) access control:** `TeamAndOrgViewSetMixin.user_access_control` (`posthog/api/routing.py`) creates one instance per request, and dashboard rendering passes it down into each tile's query runner (`products/product_analytics/backend/api/insight.py`), so N insights share one access-control fetch.

When both access-control types are active, a query run makes just one query to `AccessControl` and one to `PropertyAccessControl`.
