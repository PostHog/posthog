# HogQL access controls

HogQL enforces three kinds of access control:

1. **System tables** (`system.*`): resource-level and object-level access, used mostly by the MCP `execute_sql` tool.
2. **Warehouse objects**: data warehouse tables, views (saved queries), and materialized views.
3. **Property access control**: hiding sensitive event/person properties from query results.

All three share the same cross-cutting machinery: access rules are preloaded once per request into a `UserAccessControl` instance (`posthog/rbac/user_access_control.py`), resolved in memory, and folded into the query cache fingerprint so cached results are never shared between users with different access.

## Passing the user in

Enforcement only works if the query knows who is asking. Whenever a user is available (any user-initiated query), pass it into `Database.create_for()` or `HogQLContext` / `execute_hogql_query()`:

```python
from posthog.hogql.database.database import Database
from posthog.hogql.query import execute_hogql_query

# Building the schema directly (e.g. autocomplete, metadata):
database = Database.create_for(team=team, user=user)

# Executing a query:
execute_hogql_query(query="SELECT * FROM system.dashboards", team=team, user=user)
```

Query runners do this automatically: `QueryRunnerWithHogQLContext` builds the database with the runner's user (`posthog/hogql_queries/query_runner.py`), and `HogQLQueryExecutor` (`posthog/hogql/query.py`) threads `user` into both `HogQLContext` and `Database.create_for()`.

**If you forget, we fail closed.** With `user=None` the schema is built with every access-scoped system table denied and every warehouse table/view dropped (`_compute_system_table_access_decision` and the fail-closed branch in `Database._fetch_sources`, `posthog/hogql/database/database.py`). This is deliberate: it is much safer for a background job to error on a system table than for a code path to silently skip access control because nobody passed the user. See "When there is no user" below for the sanctioned userless paths.

## 1. System tables

System tables are Postgres-backed tables defined in `posthog/hogql/database/schema/system.py`. Access-controlled ones declare an `access_scope`:

```python
error_tracking_issues = PostgresTable(
    name="error_tracking_issues",
    postgres_table_name="posthog_errortrackingissue",
    access_scope="error_tracking",
    ...
)
```

Tables without an `access_scope` (e.g. `system.cohorts`) are visible to everyone on the team.

### Resource-level access

At schema build time, `_compute_system_table_access_decision()` (`posthog/hogql/database/database.py`) checks `UserAccessControl.access_level_for_resource()` for every scoped table and removes denied ones from the schema. A user without access to error tracking simply has no `system.error_tracking_issues` table; it also disappears from `system.information_schema`.

Removed table names are remembered in `Database._denied_tables`, so referencing one raises a distinct error instead of "unknown table" (`Database.get_table()`):

```text
QueryError: You don't have access to table `system.error_tracking_issues`.
```

### Object-level access

For resources with per-object access controls (dashboards, notebooks, insights, ...), denied objects are filtered out of results rather than erroring. The ClickHouse printer injects a guard into the generated SQL for every `system.*` table reference (`build_access_control_guard()` in `posthog/hogql/printer/access_control.py`, called from `BasePrinter.visit_join_expr`):

```sql
notIn(toString(system__dashboards.id), %(hogql_val_N_sensitive)s)
```

The blocked ID set comes from `UserAccessControl.blocked_resource_ids_by_scope` (preloaded, no extra queries). Child tables filter on the parent FK via `access_control_id_field` (e.g. `system.dashboard_tiles` filters on `dashboard_id`). When a guard is applied, the response carries an `AccessControlFilterWarning` ("Results may exclude dashboards you don't have access to").

### Edge case: object grant without resource access

The REST API lets an object-level grant override a resource-level "none" (you can still open a specific dashboard shared with you). HogQL is intentionally more restrictive: resource-level denial removes the table from the schema entirely, and object-level grants do not bring it back. If you have no access to the dashboards resource, `system.dashboards` errors even if specific dashboards are granted to you. This is a known limitation.

## 2. Warehouse tables, views, and materialized views

Gated by the `hogql-warehouse-access-control` feature flag (checked in `Database._fetch_sources`).

### Resource level: the `warehouse_objects` umbrella

`warehouse_objects` is an umbrella resource with two children, wired up in `RESOURCE_INHERITANCE_MAP` (`posthog/rbac/user_access_control.py`):

- `warehouse_table` (model `DataWarehouseTable`)
- `warehouse_view` (model `DataWarehouseSavedQuery`)

Resource-level access is only configurable on the umbrella; `access_level_for_resource("warehouse_table")` walks up to `warehouse_objects`. Restricting the umbrella filters **all** warehouse tables and views out of the user's HogQL schema at build time.

### Object level: per-table / per-view

Each table and view is checked individually during schema build (`_is_warehouse_table_denied()` / `_is_warehouse_view_denied()` in `posthog/hogql/database/database.py`, requiring `viewer` via `UserAccessControl.check_access_level_for_object()`). Denied objects are dropped from the schema (not masked), recorded in `_denied_tables`, and referencing them raises the same ``You don't have access to table `x`.`` error.

There is UI for this: in the SQL editor sidebar, open the three-dot menu on a table or view and pick "Access control" (`frontend/src/scenes/data-warehouse/editor/sidebar/QueryDatabase.tsx`). The backend endpoints are the `access_controls` actions on `TableViewSet` and `DataWarehouseSavedQueryViewSet`.

### Views vs materialized views

The distinction matters when a user has access to a view but not its underlying table:

- **View (non-materialized saved query)**: at query time the resolver expands the view into its defining subquery (`Resolver.visit_join_expr` in `posthog/hogql/resolver.py` parses `SavedQuery.query` and re-resolves it). The expansion looks up the underlying tables in the user's schema, so a denied underlying table still errors. Having access to the view is not enough.
- **Materialized view**: resolves to its own physical backing table (`DataWarehouseSavedQuery.hogql_definition()` in `products/data_modeling/backend/models/datawarehouse_saved_query.py` returns the backing `Table` when `is_materialized` and `modifiers.useMaterializedViews`). The view's SQL is never re-resolved, so access to the materialized view alone is sufficient. The backing storage table is excluded from the schema so the view owns the name and the access control.

This makes materialized views the supported way to expose a subset of columns from a restricted table: grant access to the materialized view, deny the underlying table.

### When there is no user

Not every execution path has a request user. The sanctioned patterns, roughly in order of preference:

- **A creator is available**: use `created_by` as the principal. Alerts evaluate with `user=alert.created_by` (`products/alerts/backend/evaluation/hogql.py`); subscription/export rendering attributes the `ExportedAsset` to the subscription's `created_by` and exporters run with `user=exported_asset.created_by` (`ee/tasks/subscriptions/subscription_utils.py`, `products/exports/backend/tasks/`).
- **Shared/public dashboards, insights, notebooks**: the viewer is anonymous, represented by `SharedLinkUser` (`posthog/shared_link_user.py`). Warehouse access control is bypassed automatically for it (`SyntheticUser | SharedLinkUser` in `Database._fetch_sources`), because the share link itself is the authorization; publishing requires editor access on the resource (`check_can_edit_sharing_configuration` in `posthog/api/sharing.py`), so the publisher vouches for the queries. System tables stay fully hidden for shared viewers.
- **Project secret API keys (PSAK)**: `ProjectSecretAPIKeyUser` (a `SyntheticUser`, `posthog/auth.py`) also bypasses warehouse access control by design: PSAKs authorize via scopes, not RBAC. System tables are gated on the key's scopes via `readable_system_table_access_scopes()`.
- **True background jobs with no principal** (view materialization, cache warming, internal billing/data-modeling jobs): pass `bypass_warehouse_access_control=True` explicitly to `Database.create_for()` / `execute_hogql_query()` / `HogQLContext`. Be very skeptical before adding a new bypass call site; only do it when the job genuinely has no user to attribute and must see all tables. The bypass never relaxes system table access control, only warehouse objects.

## 3. Property access control

Rules live in the `PropertyAccessControl` model (`products/access_control/backend/models/property_access_control.py`, table `access_control_propertyaccesscontrol`), keyed to a `PropertyDefinition` (event or person property) with an access level per team default, role, or specific member. Gated by the `PROPERTY_ACCESS_CONTROL` available feature. This is how you hide sensitive properties (emails, PII) from a subset of users.

Unlike the table-level controls, enforcement happens at query compile time, not schema build time, and it **masks rather than errors**:

- An explicit read of a restricted property compiles to `NULL` (`ClickHousePropertyResolver._substitute_value_read()` in `posthog/hogql/transforms/clickhouse_property_resolution.py`). A restricted property in a `WHERE` clause compares against `NULL` and matches nothing.
- Selecting the whole `properties` / `person_properties` blob wraps it in `JSONDropKeys(...)` so restricted keys are stripped from the returned JSON (`ClickHousePrinter._maybe_apply_json_drop_keys()` in `posthog/hogql/printer/clickhouse.py`).
- Materialized columns backing restricted properties are never used, so comparisons can't probe them (`resolve_materialized_property_source()`).

One exception: the structured `EventsQuery` runner raises `ResolutionError: Access to property '{name}' is restricted` when a user-authored `select` explicitly names a restricted property (`EventsQueryRunner._raise_on_restricted_property_select()` in `posthog/hogql_queries/events_query_runner.py`), because silently returning `NULL` for a hand-typed column is confusing.

Restrictions are loaded once per compilation via `get_restricted_properties_for_team()` (`products/access_control/backend/property_access_control.py`), memoized per request per `(team, user)`.

### No-user behavior differs from warehouse

When no user is present (public dashboards, background jobs), property access control falls back to the team's **default rules** rather than failing closed: `get_restricted_properties_for_team(user=None, ...)` applies only rules with no member/role target. So a public dashboard still hides properties the team restricts by default, but doesn't break every query. This is intentionally different from warehouse objects, where shared links bypass access control entirely instead of applying defaults. Aligning the two is a possible future cleanup.

## 4. Rule preloading and cache partitioning

### One preload, used everywhere

`UserAccessControl` fetches every access control row relevant to the user for the team in a single query (`_cached_access_controls` in `posthog/rbac/user_access_control.py`, covering team defaults, the user's membership, and their roles) and answers all subsequent checks in memory: `access_level_for_resource()`, `check_access_level_for_object()`, `blocked_resource_ids_by_scope`, `blocked_resources`.

The same instance is reused across the whole request:

- API viewsets expose it as `TeamAndOrgViewSetMixin.user_access_control` (`posthog/api/routing.py`), used by serializers and API-level permission checks.
- It can be handed into query runners (`get_query_runner_or_none(..., user_access_control=...)`) and into `Database.create_for(..., user_access_control=...)`, so schema filtering, the printer's object-level guard, and the cache fingerprint all resolve against the same preloaded rows without extra queries. A guardrail test (`test_run_issues_bounded_access_control_queries`) pins this to one `ee_accesscontrol` query per run.

### The cache fingerprint (`get_cache_payload`)

Query results are cached by a key derived from `QueryRunner.get_cache_payload()` (`posthog/hogql_queries/query_runner.py`). **If a query reads access-controlled tables, the cache must be partitioned by the user's effective access; otherwise a cached result computed for an unrestricted user would be served verbatim to a restricted one, bypassing every mechanism above.** A cache hit returns before schema build, resolution, and printing, so none of the enforcement layers run on it.

The payload gets three access control components:

- `restricted_properties`: sorted `(property_name, type)` pairs from property access control (base `QueryRunner.get_cache_payload()`). Omitted when there are no restrictions or the feature is unavailable.
- `restricted_objects`: per-resource denied object IDs from `blocked_resource_ids_by_scope`, and
- `restricted_resources`: resource scopes the user can't access, both added in `AnalyticsQueryRunner.get_cache_payload()`.

Two important behaviors:

- **Feature gate**: if the organization doesn't have `AvailableFeature.ACCESS_CONTROL`, resource/object restrictions are skipped entirely, so unentitled orgs keep one shared cache entry with zero access control queries.
- **Partition only by what the query reads**: `queried_access_controlled_resources()` (`posthog/hogql_queries/access_controlled_resources.py`) parses the query and returns the scopes it actually touches. A query over `events` or `persons` returns an empty set and shares one cache entry across all users (including userless cache warming). Warehouse scopes are only added when the query references a warehouse table or view by name (or a `DataWarehouseNode` in a structured insight query), so plain event queries never pay warehouse partitioning. One subtlety: referencing a non-materialized view adds `warehouse_table` too, because a cache hit skips the resolver expansion that would otherwise enforce underlying-table denials.

Userless runs that do touch access-controlled tables get `restricted_resources: ["*"]`, keeping them on their own fail-closed cache partition.

## Key files

| Concern | Where |
| --- | --- |
| Schema build, fail-closed, warehouse filtering, denied-table error | `posthog/hogql/database/database.py` |
| System table definitions (`access_scope`) | `posthog/hogql/database/schema/system.py` |
| Object-level SQL guard for system tables | `posthog/hogql/printer/access_control.py` |
| Rule preload + in-memory resolution | `posthog/rbac/user_access_control.py` |
| Property masking | `posthog/hogql/transforms/clickhouse_property_resolution.py`, `posthog/hogql/printer/clickhouse.py`, `posthog/hogql/restricted_properties.py` |
| Property rules model + loading | `products/access_control/backend/` |
| Cache fingerprint | `posthog/hogql_queries/query_runner.py` (`get_cache_payload`), `posthog/hogql_queries/access_controlled_resources.py` |
| Shared link / synthetic principals | `posthog/shared_link_user.py`, `posthog/auth.py` |
| Tests | `posthog/hogql/printer/test/test_hogql_access_control.py`, `posthog/hogql/printer/test/test_property_access_control.py`, `posthog/hogql_queries/test/test_query_runner.py` |
