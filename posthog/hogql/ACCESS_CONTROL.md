# HogQL access controls

HogQL enforces access control in three layers:

| Layer | What it protects | Where it's enforced | Effect when denied |
|---|---|---|---|
| [System tables](#1-system-tables) | `system.*` tables (dashboards, notebooks, error tracking issues, ...) | Schema build time + print time | Table removed from schema, query errors; denied objects filtered via `WHERE` |
| [Warehouse tables and views](#2-warehouse-tables-and-views) | `DataWarehouseTable`, `DataWarehouseSavedQuery` (views and materialized views) | Schema build time | Table/view removed from schema, query errors |
| [Property access control](#3-property-access-control) | Sensitive event/person properties (PII like email) | Compile time (AST transform + printing) | Values masked to `NULL` / stripped from JSON, no error |

All three layers share one preloaded `UserAccessControl` instance and partition the query cache so a restricted user can never be served an unrestricted user's cached rows.
See [cache partitioning](#query-cache-partitioning).

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

**Fail closed:** if you forget to pass the user, the schema is built as if for an anonymous principal.
All access-controlled system tables are removed (`_compute_system_table_access_decision` in `posthog/hogql/database/database.py` returns every scoped table as denied for `user=None`), and all warehouse tables/views are denied (`_is_warehouse_table_denied` / `_is_warehouse_view_denied` fail closed when `user_access_control is None`).
This is deliberate: a forgotten user degrades to "no access" instead of "default access".
In practice the user is available anywhere system tables are queried; for user-initiated background work, see [contexts without a request user](#contexts-without-a-request-user).

## 1. System tables

System tables are Postgres-backed tables under the `system.` namespace, defined in `SystemTables` (`posthog/hogql/database/schema/system.py`).
They're primarily used by the MCP `execute-sql` tool and the SQL editor.

### Resource-level access

Each access-controlled system table declares an `access_scope` (e.g. `system.dashboards` → `"dashboard"`, `system.error_tracking_issues` → `"error_tracking"`).
At schema build time, `_compute_system_table_access_decision()` checks `UserAccessControl.access_level_for_resource(access_scope)` for each scoped table and removes denied ones from the schema (`Database._apply_system_table_access()`).

Removed tables are tracked in `Database._denied_tables`, so referencing one raises a clear error instead of pretending the table doesn't exist (`Database.get_table()`):

```text
You don't have access to table `system.error_tracking_issues`.
```

This is a `QueryError` (`posthog/hogql/errors.py`), so it's exposed to the user.

### Object-level access

For resources with per-object access controls (dashboards, notebooks, ...), denied objects are filtered out of results rather than erroring.
At print time, `ClickHousePrinter._ensure_access_control_where_clause()` (`posthog/hogql/printer/clickhouse.py`) injects a `WHERE` guard built by `build_access_control_guard()` (`posthog/hogql/printer/access_control.py`) from `UserAccessControl.blocked_resource_ids_by_scope`.
Child tables filter on the parent's FK (e.g. `system.dashboard_tiles` uses `access_control_id_field="dashboard_id"`).
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
A denied table/view is dropped from the schema entirely (`_is_warehouse_table_denied` / `_is_warehouse_view_denied` in `posthog/hogql/database/database.py`), and its name lands in `_denied_tables` so queries get "You don't have access to table" instead of "Unknown table".

The creator always has access: `UserAccessControl.access_level_for_object()` grants the object's `created_by` user the highest level regardless of explicit denies.
`Database._fetch_sources()` preloads `created_by` on warehouse tables and saved queries so this check is query-free.

### Views vs materialized views

The two behave differently when the user has access to the view but not the underlying table:

- **View (non-materialized):** the view's HogQL is inlined and re-resolved at query resolution time (`Resolver.visit_join_expr` in `posthog/hogql/resolver.py` parses `database_table.query` and walks it like user SQL). The nested lookup of the underlying table hits the denied schema and raises `You don't have access to table ...`. So a view cannot be used to grant indirect access to a restricted table.
- **Materialized view:** `DataWarehouseSavedQuery.hogql_definition()` (`products/data_modeling/backend/models/datawarehouse_saved_query.py`) returns the backing `DataWarehouseTable` directly; it's a real table, no re-resolution of the source query happens. Access is checked on the view object only, so this works even when the underlying table is denied. **This is the supported way to expose a subset of columns from a restricted table.**

### Contexts without a request user

Warehouse access control fails closed without a user, so every caller needs one of these:

1. **User is on the request:** pass it through, as shown in [passing the user into HogQL](#passing-the-user-into-hogql).
2. **Background job acting for a user:** use the resource's `created_by`. Alerts evaluate as `alert.created_by` (`products/alerts/backend/evaluation/hogql.py`), exports render as `exported_asset.created_by` (`products/exports/backend/tasks/csv_exporter.py`).
3. **Trusted internal job with no user at all:** pass `bypass_warehouse_access_control=True` explicitly. Used by materialization workflows (`posthog/temporal/data_modeling/`), insight cache warming, and ducklake compilation (`posthog/ducklake/client.py`). **Be very skeptical before adding a new bypass** — only do it when the job genuinely has no acting user and the output isn't served to a specific user with narrower access. The bypass never relaxes system-table access control (`_compute_system_table_access_decision` runs regardless).

```python
# Background materialization job — no user exists, bypass explicitly
execute_hogql_query(query=..., team=team, bypass_warehouse_access_control=True)
```

4. **Public dashboards / notebooks / shared insights:** the viewer is anonymous, and queries run as `SharedLinkUser` (`posthog/shared_link_user.py`, built in `SharingViewerPageViewSet`). `SharedLinkUser` is a `SyntheticUser`, which auto-sets the warehouse bypass in `Database.create_for` — shared queries execute regardless of warehouse ACLs. That's by design: the gate is at publish time instead. Enabling sharing requires editor-level access to the resource (`SharingResourceEditCheck` in `posthog/api/sharing.py`), so only someone with access can publish it. System tables stay fully denied for shared links (`readable_system_table_access_scopes()` returns an empty set).
5. **Project secret API keys:** `ProjectSecretAPIKeyUser` (a `SyntheticUser`, `posthog/auth.py`) also bypasses warehouse access control. That's intentional: PSAKs are authorized by their scopes, not by role-based access control. System tables are gated by the key's scopes via `readable_system_table_access_scopes()`.

## 3. Property access control

Hides sensitive event and person properties (e.g. `email`) from query results.
Rules live in the `PropertyAccessControl` model (`products/access_control/backend/models/property_access_control.py`), one row per property definition per target (team default, organization member, or role).
Resolution (`products/access_control/backend/property_access_control.py`): org admins bypass, then user-specific rule → role rules (most permissive wins) → team default rule → allow.
Requires the `PROPERTY_ACCESS_CONTROL` feature; without it everything short-circuits to no restrictions.

### Enforcement: masking, not errors

Unlike the table layers, restricted properties do not error.
They're masked at compile time, so a restricted read is indistinguishable from a nonexistent property (anti-enumeration):

- **Explicit reads** (`properties.email`): `ClickHousePropertyResolver` (`posthog/hogql/transforms/clickhouse_property_resolution.py`) replaces the property access with `NULL`, and refuses to resolve it to a materialized column.
- **Whole-blob reads** (`SELECT properties` or `SELECT *`): `ClickHousePrinter._maybe_apply_json_drop_keys()` (`posthog/hogql/printer/clickhouse.py`) wraps the column in `JSONDropKeys(...)` so restricted keys are stripped from the returned JSON.

(The REST events API behaves differently: filtering on a restricted property there raises a `ValidationError`, see `posthog/api/event.py`.)

Restrictions are batch-loaded once per query in `prepare_ast_for_printing()` (`posthog/hogql/printer/utils.py`) via `get_restricted_properties_for_team()` onto `HogQLContext.restricted_properties`, memoized per `(team_id, user_id)` for the request lifetime.
`restricted_property_keys_for_table_type()` (`posthog/hogql/restricted_properties.py`) maps table types to event vs person restrictions.

### No user: default rules apply

When no user is present (including `SharedLinkUser` and `SyntheticUser`, which are treated as userless here), only the team **default** rules apply — see `get_restricted_properties_for_team()`.
So public dashboards mask exactly what the team default masks, instead of failing every query closed.
Note the asymmetry with the warehouse layer, which bypasses entirely for shared links rather than applying a default; that may be aligned later.

## Query cache partitioning

**The critical invariant:** if a query reads access-controlled tables, its cache key must include the user's restrictions.
Otherwise a cache hit short-circuits the schema strip, and a denied user gets served an allowed user's cached rows.

The cache key is derived from `get_cache_payload()`:

- `QueryRunner.get_cache_payload()` (`posthog/hogql_queries/query_runner.py`) adds `restricted_properties` (sorted `(name, type)` pairs) when the user has property restrictions.
- `AnalyticsQueryRunner.get_cache_payload()` adds `restricted_resources` (denied scopes) and `restricted_objects` (denied object IDs per scope) for the table layers.

Two things keep cache hit rates high:

1. **Feature gate:** if the organization doesn't have `AvailableFeature.ACCESS_CONTROL`, no resource/object restrictions exist, so nothing is added and the cache isn't partitioned by user at all.
2. **Scoped to queried tables:** `queried_access_controlled_resources()` (`posthog/hogql_queries/access_controlled_resources.py`) parses the query and returns only the access-controlled scopes it actually reads. A plain events query returns an empty set and skips access-control payload entirely, so it shares one cache entry across all users (including userless cache warming). Warehouse scopes are only included when the query actually references warehouse tables or views. When a non-materialized view is referenced, `warehouse_table` is folded in too, because the view re-resolves its underlying tables at execution and a cache hit would skip that check.

Userless runs fail closed in the fingerprint too (`restricted_resources: ["*"]`), and synthetic principals partition on their readable scopes so a narrow token can't reuse a broader token's cache.

## One preloaded `UserAccessControl` everywhere

`UserAccessControl` (`posthog/rbac/user_access_control.py`) bulk-fetches every access control row relevant to the user on the team in a single query (`_cached_access_controls`, covering team defaults, the user's membership, and the user's roles), then answers all checks in memory (`access_level_for_resource`, `check_access_level_for_object`, `blocked_resource_ids_by_scope`, ...).

The same instance is reused across:

- **Schema filtering:** passed into `Database.create_for()`, warmed by `_compute_system_table_access_decision()`, stored as `database.user_access_control`.
- **Cache fingerprint:** `QueryRunnerWithHogQLContext.user_access_control` returns `self.database.user_access_control`, so the fingerprint and the schema strip resolve access from the same preloaded rows.
- **Print-time row guards:** `build_access_control_guard()` reads `blocked_resource_ids_by_scope` off the same instance.
- **API-level (viewset) access control:** `TeamAndOrgViewSetMixin.user_access_control` (`posthog/api/routing.py`) creates one instance per request, and dashboard rendering passes it down into each tile's query runner (`products/product_analytics/backend/api/insight.py`), so N insights share one access-control fetch.

Net cost when both access-control types are active: one bulk `AccessControl` fetch plus one `PropertyAccessControl` fetch per query run.

## Tests

- Table layers: `posthog/hogql/printer/test/test_hogql_access_control.py` (full matrix: resource/object denies, views vs materialized views, bypass, shared links, cache keys)
- Property layer: `posthog/hogql/printer/test/test_property_access_control.py`
- Cache partitioning: `posthog/hogql_queries/test/test_query_runner.py`
