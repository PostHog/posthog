# HogQL isolation TODO

Created on 2026-06-19 on branch `hogql-isolation`.

This is the planning document for isolating `posthog/hogql/` from the rest of the PostHog codebase.

## Target rule

Files under `posthog/hogql/` must not import any first-party code outside `posthog.hogql`.

Allowed:

- Standard library imports.
- Third-party library imports, if they do not require Django/PostHog app setup as a side effect.
- Imports from `posthog.hogql.*`.

Forbidden:

- `posthog.*` imports outside `posthog.hogql.*`.
- `products.*` imports.
- `ee.*` imports.
- `common.*` imports, unless we explicitly move that dependency into `posthog.hogql` or make it a third-party-style package with its own dependency boundary.
- Lazy imports, `TYPE_CHECKING` imports, stringly model lookups, `apps.get_model`, `get_model`, callbacks that return Django models, or any other way of smuggling PostHog internals into HogQL.

The goal is not to satisfy an import regex while keeping the same coupling hidden behind a function.
The goal is a clean split: HogQL consumes explicit contracts and service protocols that carry primitive data and HogQL-owned types, while the rest of PostHog implements those protocols in an adapter layer outside `posthog/hogql/`.

## Current scan

Commands used for the first pass:

```bash
find posthog/hogql -type f | wc -l
rg -n '\b(from|import) (posthog|products|ee|common)\.' posthog/hogql -g '*.py' | rg -v 'from posthog\.hogql\b|import posthog\.hogql\b'
rg -n '\b(from|import) (posthog|products|ee|common)\.' posthog/hogql -g '*.py' -g '!**/test/**' -g '!**/test_*.py' | rg -v 'from posthog\.hogql\b|import posthog\.hogql\b'
rg -n '^(from|import) posthog\.hogql' posthog products ee common services -g '*.py' | rg -v '^posthog/hogql/'
```

Initial numbers:

- `posthog/hogql` has 318 files.
- 165 files under `posthog/hogql` currently contain first-party imports outside `posthog.hogql`.
- There are 630 first-party import statements under `posthog/hogql` that violate the target rule.
- 78 non-test files currently violate the target rule.
- There are 240 production violation lines before counting tests.
- 633 files outside `posthog/hogql` import `posthog.hogql` today, so the public API surface is broad and needs a compatibility plan.

Top production import roots currently pulled into `posthog/hogql`:

```text
56 posthog.models
33 posthog.clickhouse
29 posthog.schema
15 posthog.schema_enums
10 products.warehouse_sources
8  products.event_definitions
8  posthog.temporal
8  common.hogvm
7  products.cohorts
6  products.revenue_analytics
6  products.data_modeling
6  posthog.exceptions_capture
5  posthog.settings
4  posthog.utils
4  posthog.rbac
4  posthog.queries
4  posthog.hogql_queries
3  products.data_warehouse
2  products.web_analytics
2  products.product_analytics
2  products.data_tools
2  products.actions
2  posthog.scopes
2  posthog.cloud_utils
1  products.error_tracking
1  products.analytics_platform
1  products.access_control
1  posthog.udf_versioner
1  posthog.taxonomy
1  posthog.synthetic_user
1  posthog.person_db_router
1  posthog.event_usage
1  posthog.errors
1  posthog.constants
1  posthog.cache_utils
1  posthog.api
```

Highest-volume production files:

```text
24 posthog/hogql/database/database.py
16 posthog/hogql/property.py
13 posthog/hogql/direct_connection.py
12 posthog/hogql/query.py
9  posthog/hogql/context.py
9  posthog/hogql/autocomplete.py
7  posthog/hogql/functions/cohort.py
6  posthog/hogql/modifiers.py
6  posthog/hogql/database/schema/sessions_v2.py
5  posthog/hogql/transforms/property_types.py
5  posthog/hogql/property_planner.py
5  posthog/hogql/printer/utils.py
5  posthog/hogql/database/schema/sessions_v3.py
5  posthog/hogql/database/schema/sessions_v1.py
5  posthog/hogql/compiler/bytecode.py
4  posthog/hogql/transforms/geoip_dict_fallback.py
4  posthog/hogql/transforms/clickhouse_property_resolution.py
4  posthog/hogql/printer/base.py
4  posthog/hogql/metadata.py
4  posthog/hogql/database/schema/groups_revenue_analytics.py
4  posthog/hogql/database/postgres_utils.py
```

## Architectural shape

Use a two-layer split:

- `posthog.hogql`: pure HogQL core. It owns AST, parser, resolver, printer, type system, table models, query planning, contracts, protocol definitions, and pure transforms.
- An adapter layer outside `posthog/hogql`, likely `posthog/hogql_runtime/` or similar. It can import Django models, `posthog.schema`, query runners, ClickHouse clients, feature flags, products, access control, and settings. It converts PostHog objects into HogQL contracts, invokes the HogQL core, and converts results back to current API response types.

The adapter can depend on HogQL.
HogQL cannot depend on the adapter.

This means existing imports like `from posthog.hogql.query import execute_hogql_query` need a transition.
Do not keep Django-backed execution in `posthog/hogql/query.py`.
Either:

- Move the Django-backed function to `posthog.hogql_runtime.query.execute_hogql_query` and migrate callers.
- Keep `posthog.hogql.query` as a pure API that accepts HogQL contracts and service providers, while the compatibility wrapper outside `posthog/hogql` keeps the legacy `Team`/`User`/`posthog.schema` signature.

Prefer the second option for internal mechanics and the first option for legacy caller ergonomics:

- `posthog.hogql.query`: pure planner/executor interface with no PostHog imports.
- `posthog.hogql_runtime.query`: legacy-compatible PostHog integration wrapper.
- Callers that already have `Team`, `User`, `HogQLQueryResponse`, `HogQLMetadataResponse`, etc. migrate to `posthog.hogql_runtime`.
- New code that can work with pure contracts can call `posthog.hogql` directly.

## Non-negotiables

- No Django model instances in `HogQLContext`.
- No `Team`, `User`, `UserAccessControl`, `Organization`, `ExternalDataSource`, `DataWarehouseTable`, `DataWarehouseSavedQuery`, `Action`, `Cohort`, `PropertyDefinition`, or other ORM objects crossing into `posthog.hogql`.
- No provider method that returns an ORM object or accepts one.
- No `Any`-shaped "model" escape hatch.
- No `get_model("...")`, `apps.get_model`, import strings, or plugin registry that hands PostHog internals back to HogQL.
- No `posthog.schema` dependency in the core. If HogQL needs DTOs/enums, it owns them and the adapter maps to/from generated API schema types.
- No `posthog.schema_enums` dependency in the core. Move/copy the subset of enum definitions HogQL truly owns into `posthog.hogql.contracts` or `posthog.hogql.enums`; map at the adapter boundary.
- No ClickHouse client dependency in the core. HogQL may produce SQL and execution options; the adapter executes.
- No settings dependency in the core. Settings values become explicit configuration contracts.
- No product imports in table definitions. Product-owned table metadata must be supplied through contracts or registered from outside.

## Core contracts to introduce

Create HogQL-owned contracts. Use frozen dataclasses or pydantic dataclasses where runtime validation is valuable, but keep them framework-free.

Likely files:

- `posthog/hogql/contracts.py` for stable public DTOs.
- `posthog/hogql/enums.py` for HogQL-owned enum values.
- `posthog/hogql/services.py` for `Protocol` definitions.
- `posthog/hogql/runtime_context.py` or an expanded `context.py` for the pure context object.

Minimum contracts:

- `HogQLTeamContext`
  - `team_id`
  - `project_id`
  - `organization_id`
  - `uuid`
  - `timezone`
  - `week_start_day`
  - `modifiers`
  - `path_cleaning_filters`
  - anything else currently read from `Team`, but only as primitives or HogQL-owned value objects.
- `HogQLActorContext`
  - user id or synthetic id
  - distinct id
  - email if feature flag evaluation still needs it
  - system table scopes
  - organization admin/access snapshot
  - no `User` object.
- `HogQLAccessControlSnapshot`
  - denied system tables
  - restricted properties
  - source/object access decisions precomputed by the adapter.
- `HogQLQueryModifiers`
  - HogQL-owned replacement for the subset of `posthog.schema.HogQLQueryModifiers` used by the core.
- `HogQLGlobalSettings`
  - execution and printing settings now mixed between `posthog.hogql.constants`, `posthog.settings`, and query execution.
- `HogQLNotice`
  - replacement for `posthog.schema.HogQLNotice`.
- `HogQLQueryResponse`, `HogQLMetadata`, `HogQLMetadataResponse`, `HogQLColumn`, `HogQLQueryTiming`
  - core response types.
  - The adapter maps these to current `posthog.schema` response models.
- `HogQLPropertyFilter`, `HogQLPropertyGroup`, `HogQLFilters`, `HogQLVariable`
  - core filter contracts replacing `posthog.schema` and `posthog.models.property.Property`.
- `ActionDefinition` and `ActionStepDefinition`
  - pure action shape consumed by `action_to_expr`/`steps_to_expr`.
- `CohortDefinition`, `CohortCalculationSnapshot`, `CohortQueryDefinition`
  - pure cohort shape consumed by `functions/cohort.py`, `transforms/in_cohort.py`, and property filtering.
- `EventDefinitionContract`, `PropertyDefinitionContract`
  - metadata needed by taxonomy validation, property type transforms, restricted properties, and autocomplete.
- `GroupTypeMappingContract`
  - replacement for dicts returned by `get_group_types_for_project`.
- `WarehouseTableContract`
  - id/name/schema/source/credential/table columns/table type/sync status/etc.
- `WarehouseSavedQueryContract`
  - id/name/query/status/fields/table linkage/managed view metadata.
- `WarehouseJoinContract`
  - pure replacement for `DataWarehouseJoin`.
- `RevenueViewContract`
  - pure replacement for `RevenueAnalyticsBaseView`.
- `DirectConnectionContract`
  - id/source type/metadata/schema/connection config reference.
  - Do not include decrypted credentials in the core unless the core genuinely executes direct queries. Prefer adapter execution.
- `ObjectStorageConfig`
  - S3 endpoint/bucket/key options for `S3Table`, supplied by adapter.
- `PreaggregationTableNames`
  - distributed table names currently imported from `posthog.clickhouse.preaggregation.*`.
- `HogQLWorkload`
  - replacement for `posthog.clickhouse.workload.Workload`.

## Service protocols to introduce

Create a single explicit service bundle that the adapter implements:

```python
class HogQLServices(Protocol):
    def load_team_context(self, team_id: int) -> HogQLTeamContext: ...
    def load_database_sources(self, request: DatabaseSourcesRequest) -> HogQLDatabaseSources: ...
    def load_action(self, team_id: int, action_id: int) -> ActionDefinition | None: ...
    def load_cohort(self, team_id: int, cohort_id: int) -> CohortDefinition | None: ...
    def load_property_definitions(self, request: PropertyDefinitionRequest) -> list[PropertyDefinitionContract]: ...
    def resolve_materialized_property(self, request: MaterializedPropertyRequest) -> MaterializedPropertyResolution | None: ...
    def evaluate_feature_flag(self, request: FeatureFlagEvaluationRequest) -> bool: ...
    def report_exception(self, error: Exception) -> None: ...
    def execute_clickhouse(self, request: ClickHouseExecutionRequest) -> ClickHouseExecutionResult: ...
    def execute_direct_query(self, request: DirectQueryExecutionRequest) -> DirectQueryExecutionResult: ...
    def embed_text(self, request: EmbedTextRequest) -> list[float]: ...
```

This is intentionally a domain service API, not a generic callback bag.
Every method should have a name that describes the capability HogQL needs.
Every input and output should be a HogQL-owned contract.

Do not pass functions such as `get_model`, `get_team`, `get_source`, `execute_sql_anything`, or `queryset_factory`.
Those recreate the dependency in disguise.

## Migration phases

### Phase 0: lock down the definition

- Decide whether the strict boundary also bans `common.hogvm`.
  - If yes, move or duplicate the small needed HogVM interface under `posthog.hogql`, or invert the dependency so `common.hogvm` consumes HogQL-owned contracts.
  - If no, document it as an explicit exception and enforce that no other `common.*` imports are allowed.
- Decide whether Django imports themselves are allowed.
  - The stated rule only bans first-party imports outside `posthog.hogql`, but a clean split should also remove Django/DRF imports from core modules over time.
  - Current Django/DRF imports appear in `property.py`, `autocomplete.py`, `metadata.py`, `parser.py`, `ai.py`, `printer/base.py`, `printer/clickhouse.py`, `database/database.py`, `database/postgres_table.py`, `database/s3_table.py`, `functions/cohort.py`, `taxonomy_validation.py`, `transforms/geoip_dict_fallback.py`, and scripts/tests.
- Add a temporary CI check that reports violations but does not fail yet.
- Keep this file updated as the source of truth until enforcement lands.

### Phase 1: create core contracts and adapter shell

- Add `posthog.hogql.contracts` and `posthog.hogql.services`.
- Add `posthog.hogql_runtime` or equivalent outside `posthog/hogql`.
- In the adapter, implement conversions from:
  - `Team` to `HogQLTeamContext`.
  - `User`/`SyntheticUser`/`UserAccessControl` to `HogQLActorContext` and `HogQLAccessControlSnapshot`.
  - `posthog.schema.*` query DTOs to HogQL-owned query DTOs.
  - Product and warehouse ORM rows to HogQL-owned contracts.
  - HogQL-owned responses back to `posthog.schema.*` response DTOs.
- Add focused tests for adapter mapping.

### Phase 2: split context and modifiers

Current problems:

- `context.py` imports `Workload`, `posthog.schema`, `Team`, `User`, `UserAccessControl`.
- `HogQLContext.team` carries a `Team` model.
- `HogQLContext.project_id` queries `Team.objects`.
- `modifiers.py` imports `is_cloud`, `posthog.schema_enums`, `posthog.schema`, `Team`, `User`, and `posthoganalytics`.

Tasks:

- Replace `team` with `team_context`.
- Replace `user` with `actor_context`.
- Replace `user_access_control` with a pure access-control snapshot.
- Replace `project_id` cached property with a value already present on `HogQLTeamContext`.
- Replace `Workload` with `HogQLWorkload`.
- Replace schema notices/timings/modifiers with HogQL-owned contracts.
- Move feature flag defaulting for user/team modifiers into the adapter.
- Let the core set pure default modifier values based on explicit `environment` and team context fields.

### Phase 3: split query execution

Current problems:

- `query.py` imports `posthog.schema`, ClickHouse execution, query tagging, `Team`, `User`, access control, settings, direct connection validation, and product lazy computation.
- `HogQLQueryExecutor` accepts `Team` and `User`.
- Direct Postgres/MySQL execution is implemented in the core.
- ClickHouse SQL execution is implemented in the core.
- `_apply_optimizers` lazily imports product code.

Tasks:

- Move legacy PostHog execution entry points to `posthog.hogql_runtime.query`.
- Keep pure planning in `posthog.hogql.query`.
- Change `HogQLQueryExecutor` to accept:
  - query contract
  - `HogQLTeamContext`
  - `HogQLActorContext | None`
  - `HogQLServices`
  - pure modifiers/settings/context.
- Make the core return:
  - prepared HogQL string
  - prepared ClickHouse/direct SQL
  - values
  - engine selection
  - execution options
  - metadata/columns/types.
- Move actual ClickHouse execution into adapter service `execute_clickhouse`.
- Move direct Postgres/MySQL connection validation and execution into adapter service `execute_direct_query`.
- Move product lazy-computation optimizer into an externally registered optimizer hook that receives and returns pure AST/contracts.
- Keep read-only direct-query validation in core only if it is pure SQL parsing and does not need PostHog source config.

### Phase 4: split database source loading

Current problems:

- `database/database.py` imports Django query helpers, `Team`, `OrganizationMembership`, `UserAccessControl`, `SyntheticUser`, warehouse product models, data modeling models, revenue analytics views, external source models, sync status helpers, and `posthog.schema`.
- `_fetch_sources` does all ORM and feature flag I/O inside `posthog.hogql`.
- `_build_from_sources` still consumes ORM model instances.
- `serialize()` returns `posthog.schema` types.

Tasks:

- Move `_fetch_sources` to the adapter.
- Change `Database.create_for(...)` in the core to accept `HogQLDatabaseSources`, not `Team`.
- Keep `Database._build_from_sources(...)` in the core, but make `HogQLDatabaseSources` pure.
- Replace `HogQLDatabaseSources.team` with `team_context`.
- Replace saved query/table/join/revenue view ORM lists with contract lists.
- Replace model methods like `saved_query.hogql_definition(...)` and `table.hogql_definition(...)` with adapter-created table contracts or pure factory inputs.
- Replace `get_warehouse_sync_warnings(table)` with sync warning contracts computed by adapter.
- Replace `_compute_system_table_access_decision(...)` with adapter-provided access-control snapshot.
- Replace `serialize()` return types with HogQL-owned schema contracts and map them to `posthog.schema` in the adapter.
- Remove direct dependency on product-owned model methods. If a product owns a table type, it must supply a HogQL contract or register a pure table factory from outside.

### Phase 5: split property/action/cohort filtering

Current problems:

- `property.py` imports Django, DRF validation errors, `posthog.schema`, `posthog.models`, actions, cohorts, data tools joins, property definitions, and warehouse helpers.
- It parses schema filter DTOs, model `Property` objects, action ORM rows, cohort ORM rows, selectors, and team path-cleaning config in one module.
- `functions/cohort.py`, `functions/action.py`, and `transforms/in_cohort.py` lazily import cohorts/actions/query runners.

Tasks:

- Create pure property filter contracts.
- Move conversion from `posthog.schema` and model `Property` into adapter.
- Replace `Team` in `property_to_expr` with `HogQLTeamContext`.
- Replace path-cleaning reads with `team_context.path_cleaning_filters`.
- Replace action ORM access with `services.load_action(...) -> ActionDefinition`.
- Replace cohort ORM/query-runner access with explicit cohort service APIs returning AST fragments or pure query contracts.
- Move selector parsing/building into HogQL if it is pure, or have adapter precompute selector regex and element metadata.
- Replace DRF `ValidationError` with a HogQL-owned exception; adapter maps to DRF where needed.
- Replace `posthog.taxonomy` and property definition reads with metadata contracts.
- Keep generated AST logic in HogQL.

### Phase 6: split metadata, autocomplete, taxonomy validation

Current problems:

- `metadata.py` imports `posthog.schema`, query runner lookup, `Team`, and `User`.
- `autocomplete.py` imports `posthog.schema`, exception capture, query runner lookup, `Team`, `User`, property definitions, insight variables, and HogVM STL.
- `taxonomy_validation.py` imports schema notice types and model definitions.
- `variables.py` imports `HogQLVariable`, `Team`, and insight variables.

Tasks:

- Define HogQL-owned metadata/autocomplete response contracts.
- Move `posthog.schema` conversion to adapter.
- Move query runner lookup out of HogQL. If metadata needs query-runner-specific behavior, expose a pure metadata provider service.
- Move insight variable loading into adapter and pass pure variable definitions to HogQL.
- Move taxonomy property/event definition lookups into service methods.
- Decide the HogVM STL dependency. If strict, move the STL metadata needed by autocomplete into HogQL-owned constants/contracts or provide it through service initialization.

### Phase 7: split table schema modules

Current problems:

- Schema modules import ClickHouse table-name constants, exchange-rate constants, settings, scopes, organization models, raw session SQL helpers, revenue view classes, error tracking embedding table metadata, and event definition property types.
- Many table classes call product/model helpers while printing or building fields.

Tasks:

- Move static table names and SQL constants needed by HogQL into HogQL-owned constants where the ownership is genuinely HogQL.
- For product-owned tables, have the product/adapter register a pure table descriptor.
- Replace `APIScopeObject` with a HogQL-owned scope string enum.
- Replace `Organization`, `Team`, and model-specific constants with fields on `HogQLTeamContext` or service-provided table contracts.
- Replace raw sessions SQL imports with pure SQL strings owned by HogQL if they are HogQL table definitions; otherwise provide them through a table-definition contract.
- Replace revenue analytics view class checks with pure view kind/field contracts.
- Replace `EMBEDDING_TABLES` import with an adapter-provided table descriptor list.
- Replace `settings.object_storage` imports with `ObjectStorageConfig` passed in.

### Phase 8: split property materialization and transforms

Current problems:

- `property_planner.py`, `transforms/property_types.py`, and `transforms/clickhouse_property_resolution.py` import materialized column helpers, property group helpers, `Team`, schema enums, and property definition models.
- `transforms/geoip_dict_fallback.py` imports cache, ClickHouse execution, ClickHouse user, and settings.
- `transforms/preaggregated_table_transformation.py` imports web analytics product definitions.

Tasks:

- Replace materialized-column lookups with a service method that returns a pure materialization resolution.
- Replace property group optimizer state with a service-provided contract.
- Replace `Team` with team context.
- Move GeoIP dictionary probing/caching into adapter. HogQL should receive a boolean or strategy decision on context.
- Move product-specific preaggregated table transformation inputs into product/adapter registrations.

### Phase 9: split observability, errors, settings, and utilities

Current problems:

- `observability.py` and `feature_extractor.py` import query tagging constants/classes.
- `parser.py`, `database/utils.py`, and several modules call `capture_exception`.
- `ai.py` reports user action and reads instance region.
- `functions/embed_text.py` calls the embedding worker directly.
- `functions/udfs.py` reads cloud/CI and UDF versioner.
- `escape_sql.py`, printer modules, and resolver modules import `UUIDT`.

Tasks:

- Move query tagging into adapter. HogQL can emit a pure `HogQLFeatureSet`.
- Replace `capture_exception` with `services.report_exception(...)` where the core truly should report, or let exceptions bubble to adapter.
- Move product usage reporting to adapter.
- Replace embedding generation with `services.embed_text(...)`.
- Replace cloud/CI/UDF-version decisions with explicit config or service methods.
- Replace `UUIDT` with `uuid.UUID | str` aliases owned by HogQL.

### Phase 10: tests

Current problems:

- Most `posthog/hogql/**/test*` files import `posthog.test.base`, model factories, ClickHouse clients, product query runners, and product models.
- Tests under `posthog/hogql` will fail the same import rule if we enforce it uniformly.

Tasks:

- Keep pure unit tests under `posthog/hogql`.
- Move integration tests that need Django/PostHog models out of `posthog/hogql`, likely to `posthog/hogql_runtime/test/` or product-owned test folders.
- Build test adapters/fakes for service protocols so core tests remain pure.
- Snapshot tests that only need AST/parser/printer should stay with HogQL.
- Tests that exercise actual ClickHouse, warehouse models, Team/User setup, action/cohort models, or API schema conversion should live with the adapter or consuming product.

### Phase 11: enforcement

Add automated enforcement before the final migration ends.

Candidate checks:

```bash
rg -n '\b(from|import) (posthog|products|ee|common)\.' posthog/hogql -g '*.py' | rg -v 'from posthog\.hogql\b|import posthog\.hogql\b'
```

Better: add a small AST-based check so comments and strings do not produce false positives.
Wire it into lint or `hogli`.

Import-linter option:

- Extend `[tool.importlinter]` root packages beyond `products`.
- Add a forbidden contract where `source_modules = ["posthog.hogql"]`.
- Forbid `posthog`, `products`, `ee`, and `common`, while allowlisting `posthog.hogql`.
- Validate that import-linter handles same-root package exceptions correctly before relying on it.

Tach option:

- Investigate whether `tach.toml` can model `posthog.hogql` separately from the broad `posthog` module.
- If overlapping modules are not reliable, use import-linter or a custom AST check instead.

Final enforcement must fail on:

- Top-level imports.
- Lazy imports.
- `TYPE_CHECKING` imports.
- Relative imports that resolve outside `posthog.hogql`.
- `apps.get_model` or similar explicit string-based model access from inside `posthog/hogql`.

### Phase 12: caller migration

There are 633 files outside `posthog/hogql` importing it today.
Do not move every caller at once without a compatibility plan.

Tasks:

- Define the public modules external callers may use.
- Keep pure imports stable where possible: `ast`, `parser`, `errors`, `constants`, `base`, `visitor`, pure printer helpers.
- Move Django-backed APIs to `posthog.hogql_runtime`.
- Migrate callers in slices:
  - Query runners and insight code.
  - Product query runners.
  - API endpoints.
  - Temporal/data modeling tasks.
  - Tests.
  - EE/HogAI callers.
- Keep compatibility wrappers only outside `posthog/hogql`.
- Delete old wrappers after all callers move.

## Suggested public API after isolation

Pure core:

```text
posthog.hogql.ast
posthog.hogql.base
posthog.hogql.constants
posthog.hogql.contracts
posthog.hogql.context
posthog.hogql.errors
posthog.hogql.parser
posthog.hogql.printer
posthog.hogql.query
posthog.hogql.services
posthog.hogql.type_system
posthog.hogql.visitor
```

PostHog integration:

```text
posthog.hogql_runtime.context
posthog.hogql_runtime.database_sources
posthog.hogql_runtime.direct_connection
posthog.hogql_runtime.metadata
posthog.hogql_runtime.query
posthog.hogql_runtime.schema_adapters
posthog.hogql_runtime.services
```

Product-owned extension registrations should live with the owning product and be imported by `posthog.hogql_runtime`, not by `posthog.hogql`.

## File-specific first-pass notes

### `posthog/hogql/context.py`

- Remove `Team`, `User`, `UserAccessControl`, `Workload`, `posthog.schema`.
- Replace notice/warning/error list types with HogQL-owned notice contract.
- Replace `modifiers` default factory with a pure `HogQLQueryModifiers`.
- Replace `project_id` database lookup with `team_context.project_id`.
- Replace `restricted_properties` tuple using `PropertyDefinition.Type` with HogQL-owned property definition enum.

### `posthog/hogql/query.py`

- Move legacy execution to adapter.
- Keep SQL planning and direct SQL read-only validation pure.
- Adapter handles ClickHouse execution, direct Postgres/MySQL execution, query tagging, settings, and source validation.
- Replace `Team` and `User` with contracts.
- Replace `HogQLQueryResponse` and related schema DTOs with core contracts.
- Move product lazy-computation transformer behind a registered optimizer service.

### `posthog/hogql/database/database.py`

- Move all ORM fetches out.
- Make `HogQLDatabaseSources` pure.
- Make table-building consume pure contracts.
- Replace `serialize()` schema DTOs with HogQL contracts.
- Move access-control decisions out.
- Replace revenue/warehouse/model-specific method calls with contract mappers in adapter.

### `posthog/hogql/property.py`

- Split into:
  - pure AST property expression builder
  - adapter parser from PostHog model/schema filters to HogQL property contracts.
- Replace `Action`/`Cohort` model access with service APIs.
- Replace `Team` usage with `HogQLTeamContext`.
- Move selector helpers into HogQL only if they are truly pure; otherwise precompute selector regex in adapter.
- Replace DRF exceptions with HogQL exceptions.

### `posthog/hogql/direct_connection.py`

- This likely moves almost entirely to `posthog.hogql_runtime.direct_connection`.
- Core should only know direct query SQL dialect, selected connection id, and execution request/response contracts.

### `posthog/hogql/modifiers.py`

- Own the modifier enum/default logic in HogQL.
- Adapter supplies cloud/user/team feature flag values.
- No `posthoganalytics`, `is_cloud`, `posthog.schema`, or `Team` in core.

### `posthog/hogql/autocomplete.py` and `metadata.py`

- Move schema response conversion and query-runner lookup out.
- Use services for property definitions, insight variables, and any metadata loaded from products.

### `posthog/hogql/functions/cohort.py`, `functions/action.py`, `transforms/in_cohort.py`

- Replace inline ORM imports with `CohortDefinition`/`ActionDefinition` service calls.
- Any generated subquery should be produced by HogQL from pure cohort/action contracts or supplied as a pure AST by adapter.

### `posthog/hogql/database/schema/*`

- Separate static HogQL table definitions from product-owned table registrations.
- Any product-owned tables should be registered into a database source contract by the adapter.
- Scope/access constants must be HogQL-owned strings/enums, not imported from `posthog.scopes`.

### `posthog/hogql/compiler/*` and `common.hogvm`

- Decide ownership.
- If strict, move the needed HogVM bytecode execution interface or constants into a package HogQL may import.
- If keeping `common.hogvm` as shared infrastructure, record that explicit exception in the boundary checker.

## Enforcement done criteria

The isolation work is complete only when all are true:

- `rg -n '\b(from|import) (posthog|products|ee|common)\.' posthog/hogql -g '*.py' | rg -v 'from posthog\.hogql\b|import posthog\.hogql\b'` returns no violations, except documented exceptions if any.
- No `TYPE_CHECKING` imports from outside `posthog.hogql`.
- No lazy imports from outside `posthog.hogql`.
- No `apps.get_model`, `get_model`, string import, or callback escape hatch that hands PostHog internals to HogQL.
- `HogQLContext` contains no Django model or PostHog service object.
- HogQL contracts contain only primitives, stdlib types, and HogQL-owned types.
- Adapter tests prove conversion between current PostHog objects/schema DTOs and HogQL contracts.
- Core tests under `posthog/hogql` run without Django app setup unless a pure parser/compiler test needs a third-party dependency.
- Integration tests that require Django models live outside `posthog/hogql`.
- CI has a failing guard for the import rule.

## Appendix A: current production first-party violations

This list excludes tests and excludes valid `posthog.hogql` imports.
Regenerate it after each phase because this branch is expected to drift.

```text
posthog/hogql/property.py:13:from posthog.schema import (
posthog/hogql/property.py:51:from posthog.clickhouse.query_tagging import tag_contains_user_hogql
posthog/hogql/property.py:52:from posthog.constants import AUTOCAPTURE_EVENT, TREND_FILTER_TYPE_ACTIONS, PropertyOperatorType
posthog/hogql/property.py:53:from posthog.models import Property, PropertyDefinition, Team
posthog/hogql/property.py:54:from posthog.models.element import Element
posthog/hogql/property.py:55:from posthog.models.event import Selector
posthog/hogql/property.py:56:from posthog.models.property import PropertyGroup, ValueT
posthog/hogql/property.py:57:from posthog.models.property.util import build_selector_regex
posthog/hogql/property.py:58:from posthog.utils import get_from_dict_or_attr
posthog/hogql/property.py:60:from products.actions.backend.models.action import Action, ActionStepJSON
posthog/hogql/property.py:61:from products.cohorts.backend.models.cohort import Cohort
posthog/hogql/property.py:62:from products.data_tools.backend.models.join import DataWarehouseJoin
posthog/hogql/property.py:63:from products.event_definitions.backend.models.property_definition import PropertyType
posthog/hogql/property.py:64:from products.warehouse_sources.backend.models.util import get_view_or_table_by_name
posthog/hogql/property.py:282:        from posthog.taxonomy.taxonomy import CORE_FILTER_DEFINITIONS_BY_GROUP
posthog/hogql/property.py:391:        from posthog.utils import relative_date_parse
posthog/hogql/placeholders.py:44:        from common.hogvm.python.execute import execute_bytecode
posthog/hogql/variables.py:4:from posthog.schema import HogQLVariable
posthog/hogql/variables.py:10:from posthog.models.team.team import Team
posthog/hogql/variables.py:12:from products.product_analytics.backend.models.insight_variable import InsightVariable
posthog/hogql/timings.py:8:    from posthog.schema import QueryTiming
posthog/hogql/timings.py:61:        from posthog.schema import QueryTiming  # noqa: PLC0415
posthog/hogql/observability.py:27:from posthog.clickhouse.query_tagging import Product, get_query_tags
posthog/hogql/cli.py:7:from common.hogvm.python.execute import execute_bytecode
posthog/hogql/resolver.py:65:from posthog.models.utils import UUIDT
posthog/hogql/metadata.py:7:from posthog.schema import HogLanguage, HogQLMetadata, HogQLMetadataResponse, HogQLNotice, HogQLQuery
posthog/hogql/metadata.py:26:from posthog.hogql_queries.query_runner import get_query_runner
posthog/hogql/metadata.py:27:from posthog.models import Team
posthog/hogql/metadata.py:28:from posthog.models.user import User
posthog/hogql/modifiers.py:5:from posthog.cloud_utils import is_cloud
posthog/hogql/modifiers.py:6:from posthog.schema_enums import (
posthog/hogql/modifiers.py:20:    from posthog.schema import HogQLQueryModifiers
posthog/hogql/modifiers.py:22:    from posthog.models import Team, User
posthog/hogql/modifiers.py:28:    from posthog.schema import HogQLQueryModifiers  # noqa: PLC0415
posthog/hogql/modifiers.py:53:    from posthog.schema import CustomChannelRule, HogQLQueryModifiers  # noqa: PLC0415
posthog/hogql/property_planner.py:26:from posthog.clickhouse.materialized_columns import (
posthog/hogql/property_planner.py:32:from posthog.clickhouse.property_groups import property_groups
posthog/hogql/property_planner.py:33:from posthog.models.property import PropertyName, TableColumn
posthog/hogql/property_planner.py:34:from posthog.schema_enums import PropertyGroupsMode
posthog/hogql/property_planner.py:36:from products.event_definitions.backend.models.property_definition import PropertyType
posthog/hogql/compiler/bytecode.py:14:from common.hogvm.python.execute import BytecodeResult, execute_bytecode
posthog/hogql/compiler/bytecode.py:15:from common.hogvm.python.operation import HOGQL_BYTECODE_IDENTIFIER, HOGQL_BYTECODE_VERSION, Operation
posthog/hogql/compiler/bytecode.py:16:from common.hogvm.python.stl import STL
posthog/hogql/compiler/bytecode.py:17:from common.hogvm.python.stl.bytecode import BYTECODE_STL
posthog/hogql/compiler/bytecode.py:20:    from posthog.models import Team
posthog/hogql/functions/traffic_type.py:19:from products.web_analytics.backend.hogql_queries.bot_definitions import BOT_DEFINITIONS
posthog/hogql/user_query_validator.py:18:from posthog.models.team import Team
posthog/hogql/warehouse_warnings.py:25:    from posthog.schema import DataWarehouseSyncWarning
posthog/hogql/database/s3_table.py:13:from posthog.clickhouse.client.escape import substitute_params
posthog/hogql/escape_sql.py:10:from posthog.models.utils import UUIDT
posthog/hogql/hogql.py:10:from posthog.queries.util import alias_poe_mode_for_legacy
posthog/hogql/feature_extractor.py:12:from posthog.clickhouse.query_tagging import EVENT_TAG_MATCHERS, HogQLFeatures
posthog/hogql/database/utils.py:6:from posthog.exceptions_capture import capture_exception
posthog/hogql/database/models.py:16:from posthog.clickhouse.workload import Workload
posthog/hogql/database/models.py:508:        from products.data_modeling.backend.models.datawarehouse_saved_query import validate_saved_query_name
posthog/hogql/database/models.py:514:        from products.data_modeling.backend.models.datawarehouse_saved_query import validate_saved_query_name
posthog/hogql/context.py:8:from posthog.clickhouse.workload import Workload
posthog/hogql/context.py:11:    from posthog.schema import DataWarehouseSyncWarning, HogQLNotice, HogQLQueryModifiers
posthog/hogql/context.py:17:    from posthog.models import Team, User
posthog/hogql/context.py:18:    from posthog.rbac.user_access_control import UserAccessControl
posthog/hogql/context.py:24:    from posthog.schema import HogQLQueryModifiers  # noqa: PLC0415
posthog/hogql/context.py:134:            from posthog.schema import HogQLNotice  # noqa: PLC0415
posthog/hogql/context.py:146:            from posthog.schema import HogQLNotice  # noqa: PLC0415
posthog/hogql/context.py:158:            from posthog.schema import HogQLNotice  # noqa: PLC0415
posthog/hogql/context.py:167:        from posthog.models import Team
posthog/hogql/database/schema/web_stats_preaggregated.py:13:from posthog.clickhouse.preaggregation.web_stats_preaggregated_sql import DISTRIBUTED_WEB_STATS_PREAGGREGATED_TABLE
posthog/hogql/taxonomy_validation.py:9:from posthog.schema import HogQLNotice
posthog/hogql/taxonomy_validation.py:15:from posthog.models import EventDefinition, PropertyDefinition, Team
posthog/hogql/database/postgres_table.py:10:from posthog.person_db_router import PERSONS_DB_MODELS
posthog/hogql/database/postgres_table.py:11:from posthog.scopes import APIScopeObject
posthog/hogql/database/schema/preaggregation_results.py:14:from posthog.clickhouse.preaggregation.sql import DISTRIBUTED_PREAGGREGATION_RESULTS_TABLE
posthog/hogql/functions/udfs.py:1:from posthog.cloud_utils import is_ci, is_cloud
posthog/hogql/functions/udfs.py:37:    from posthog.udf_versioner import augment_function_name
posthog/hogql/database/postgres_utils.py:11:from posthog.exceptions_capture import capture_exception
posthog/hogql/database/postgres_utils.py:13:from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
posthog/hogql/database/postgres_utils.py:14:from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
posthog/hogql/database/postgres_utils.py:15:from products.warehouse_sources.backend.models.table import DataWarehouseTable
posthog/hogql/parser.py:40:from posthog.exceptions_capture import capture_exception
posthog/hogql/parser.py:41:from posthog.schema_enums import ParserMode
posthog/hogql/database/schema/persons_revenue_analytics.py:17:from posthog.models.exchange_rate.sql import EXCHANGE_RATE_DECIMAL_PRECISION
posthog/hogql/database/schema/persons_revenue_analytics.py:18:from posthog.schema_enums import DatabaseSchemaManagedViewTableKind
posthog/hogql/database/schema/persons_revenue_analytics.py:33:    from products.revenue_analytics.backend.views import RevenueAnalyticsCustomerView, RevenueAnalyticsRevenueItemView
posthog/hogql/query.py:14:from posthog.schema import (
posthog/hogql/query.py:63:from posthog.clickhouse.client import sync_execute
posthog/hogql/query.py:64:from posthog.clickhouse.client.connection import Workload
posthog/hogql/query.py:65:from posthog.clickhouse.query_tagging import tag_queries
posthog/hogql/query.py:66:from posthog.errors import ExposedCHQueryError
posthog/hogql/query.py:67:from posthog.exceptions_capture import capture_exception
posthog/hogql/query.py:68:from posthog.models.team import Team
posthog/hogql/query.py:69:from posthog.models.user import User
posthog/hogql/query.py:70:from posthog.rbac.user_access_control import UserAccessControl
posthog/hogql/query.py:71:from posthog.settings import HOGQL_INCREASED_MAX_EXECUTION_TIME
posthog/hogql/query.py:489:                from products.analytics_platform.backend.lazy_computation.lazy_computation_transformer import (
posthog/hogql/query.py:707:        from posthog.temporal.data_imports.sources.postgres.postgres import _get_sslmode, source_requires_ssl
posthog/hogql/filters.py:6:from posthog.schema import HogQLFilters, SessionPropertyFilter
posthog/hogql/filters.py:23:from posthog.models import Team
posthog/hogql/filters.py:24:from posthog.utils import relative_date_parse
posthog/hogql/database/database.py:141:from posthog.exceptions_capture import capture_exception
posthog/hogql/database/database.py:142:from posthog.models.group_type_mapping import get_group_types_for_project
posthog/hogql/database/database.py:143:from posthog.models.organization import OrganizationMembership
posthog/hogql/database/database.py:144:from posthog.models.team.team import Team, WeekStartDay
posthog/hogql/database/database.py:145:from posthog.rbac.user_access_control import NO_ACCESS_LEVEL, UserAccessControl
posthog/hogql/database/database.py:146:from posthog.schema_enums import DatabaseSerializedFieldType, PersonsOnEventsMode, SessionTableVersion
posthog/hogql/database/database.py:147:from posthog.synthetic_user import SyntheticUser
posthog/hogql/database/database.py:149:from products.data_tools.backend.models.join import DataWarehouseJoin
posthog/hogql/database/database.py:150:from products.data_warehouse.backend.sync_status import get_warehouse_sync_warnings
posthog/hogql/database/database.py:151:from products.revenue_analytics.backend.views import RevenueAnalyticsBaseView
posthog/hogql/database/database.py:152:from products.warehouse_sources.backend.models.credential import DataWarehouseCredential
posthog/hogql/database/database.py:153:from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
posthog/hogql/database/database.py:154:from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
posthog/hogql/database/database.py:155:from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
posthog/hogql/database/database.py:156:from products.warehouse_sources.backend.models.table import DataWarehouseTable, DataWarehouseTableColumns
posthog/hogql/database/database.py:161:    from posthog.schema import (
posthog/hogql/database/database.py:173:    from posthog.models import User
posthog/hogql/database/database.py:175:    from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
posthog/hogql/database/database.py:738:        from posthog.schema import (  # noqa: PLC0415
posthog/hogql/database/database.py:750:        from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
posthog/hogql/database/database.py:1021:        from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
posthog/hogql/database/database.py:1128:                        from products.revenue_analytics.backend.views.orchestrator import (  # noqa: PLC0415
posthog/hogql/database/database.py:1230:        from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
posthog/hogql/database/database.py:2103:    from posthog.schema import DatabaseSchemaField  # noqa: PLC0415
posthog/hogql/database/schema/web_analytics_s3.py:9:from posthog.settings.base_variables import DEBUG
posthog/hogql/database/schema/web_analytics_s3.py:10:from posthog.settings.object_storage import (
posthog/hogql/workload.py:6:from posthog.clickhouse.workload import Workload
posthog/hogql/metadata_heuristics.py:4:from posthog.schema import HogQLNotice
posthog/hogql/transforms/in_cohort.py:100:        from products.cohorts.backend.models.cohort import Cohort
posthog/hogql/transforms/in_cohort.py:313:            from products.cohorts.backend.models.cohort import Cohort
posthog/hogql/autocomplete.py:9:from posthog.schema import (
posthog/hogql/autocomplete.py:47:from posthog.exceptions_capture import capture_exception
posthog/hogql/autocomplete.py:48:from posthog.hogql_queries.query_runner import get_query_runner
posthog/hogql/autocomplete.py:49:from posthog.models.team.team import Team
posthog/hogql/autocomplete.py:50:from posthog.models.user import User
posthog/hogql/autocomplete.py:52:from products.event_definitions.backend.models.property_definition import PropertyDefinition
posthog/hogql/autocomplete.py:53:from products.product_analytics.backend.models.insight_variable import InsightVariable
posthog/hogql/autocomplete.py:55:from common.hogvm.python.stl import STL
posthog/hogql/autocomplete.py:56:from common.hogvm.python.stl.bytecode import BYTECODE_STL
posthog/hogql/transforms/events_predicate_pushdown.py:50:from posthog.settings import TEST
posthog/hogql/transforms/events_predicate_pushdown.py:53:    from posthog.schema import HogQLQueryModifiers
posthog/hogql/transforms/clickhouse_property_resolution.py:46:from posthog.clickhouse.materialized_columns import TablesWithMaterializedColumns, get_materialized_column_for_property
posthog/hogql/transforms/clickhouse_property_resolution.py:47:from posthog.clickhouse.property_groups import property_groups
posthog/hogql/transforms/clickhouse_property_resolution.py:48:from posthog.models.property import PropertyName, TableColumn
posthog/hogql/transforms/clickhouse_property_resolution.py:49:from posthog.schema_enums import MaterializationMode, PropertyGroupsMode
posthog/hogql/database/schema/web_goals_preaggregated.py:13:from posthog.clickhouse.preaggregation.web_goals_preaggregated_sql import DISTRIBUTED_WEB_GOALS_PREAGGREGATED_TABLE
posthog/hogql/restricted_properties.py:26:    from products.event_definitions.backend.models.property_definition import PropertyDefinition  # noqa: PLC0415
posthog/hogql/database/schema/conversion_goal_attributed_preaggregated.py:14:from posthog.clickhouse.preaggregation.conversion_goal_attributed_sql import (
posthog/hogql/functions/cohort.py:14:from posthog.schema_enums import InlineCohortCalculation
posthog/hogql/functions/cohort.py:20:    from posthog.models import Team
posthog/hogql/functions/cohort.py:44:    from products.cohorts.backend.models.calculation_history import CohortCalculationHistory
posthog/hogql/functions/cohort.py:74:    from posthog.hogql_queries.hogql_cohort_query import HogQLCohortQuery
posthog/hogql/functions/cohort.py:76:    from products.cohorts.backend.models.cohort import Cohort
posthog/hogql/functions/cohort.py:94:        from posthog.models import Team
posthog/hogql/functions/cohort.py:118:    from products.cohorts.backend.models.cohort import Cohort
posthog/hogql/transforms/geoip_dict_fallback.py:59:from posthog.cache_utils import cache_for
posthog/hogql/transforms/geoip_dict_fallback.py:60:from posthog.clickhouse.client import sync_execute
posthog/hogql/transforms/geoip_dict_fallback.py:61:from posthog.clickhouse.client.connection import ClickHouseUser
posthog/hogql/transforms/geoip_dict_fallback.py:62:from posthog.settings import CLICKHOUSE_CLUSTER
posthog/hogql/database/schema/sessions_v1.py:24:from posthog.models.sessions.sql import (
posthog/hogql/database/schema/sessions_v1.py:28:from posthog.queries.insight import insight_sync_execute
posthog/hogql/database/schema/sessions_v1.py:29:from posthog.schema_enums import BounceRatePageViewMode
posthog/hogql/database/schema/sessions_v1.py:31:from products.event_definitions.backend.models.property_definition import PropertyType
posthog/hogql/database/schema/sessions_v1.py:34:    from posthog.models.team import Team
posthog/hogql/database/schema/persons_pdi.py:17:from posthog.models.organization import Organization
posthog/hogql/functions/action.py:16:    from products.actions.backend.models.action import Action
posthog/hogql/database/schema/cohort_people.py:27:    from products.cohorts.backend.models.cohort import Cohort
posthog/hogql/ai.py:16:from posthog.event_usage import report_user_action
posthog/hogql/ai.py:17:from posthog.utils import get_instance_region
posthog/hogql/ai.py:23:    from posthog.models import Team, User
posthog/hogql/transforms/property_types.py:24:from posthog.clickhouse.materialized_columns import (
posthog/hogql/transforms/property_types.py:31:from posthog.models import Team
posthog/hogql/transforms/property_types.py:32:from posthog.models.property import PropertyName, TableColumn
posthog/hogql/transforms/property_types.py:36:    from posthog.models import PropertyDefinition
posthog/hogql/transforms/property_types.py:37:    from posthog.models.materialized_column_slots import MaterializedColumnSlot, MaterializedColumnSlotState
posthog/hogql/functions/embed_text.py:3:from posthog.api.embedding_worker import generate_embedding
posthog/hogql/functions/embed_text.py:4:from posthog.models.team.team import Team
posthog/hogql/database/schema/experiment_metric_events_preaggregated.py:13:from posthog.clickhouse.preaggregation.experiment_metric_events_sql import DISTRIBUTED_EXPERIMENT_METRIC_EVENTS_TABLE
posthog/hogql/database/schema/web_vitals_paths_preaggregated.py:13:from posthog.clickhouse.preaggregation.web_vitals_paths_preaggregated_sql import (
posthog/hogql/resolver_utils.py:243:    from posthog.hogql_queries.query_runner import get_query_runner
posthog/hogql/resolver_utils.py:244:    from posthog.models import Team
posthog/hogql/database/schema/metrics.py:13:from posthog.clickhouse.workload import Workload
posthog/hogql/database/schema/spans.py:11:from posthog.clickhouse.workload import Workload
posthog/hogql/database/schema/web_overview_preaggregated.py:13:from posthog.clickhouse.preaggregation.web_overview_preaggregated_sql import (
posthog/hogql/database/schema/web_stats_frustration_preaggregated.py:13:from posthog.clickhouse.preaggregation.web_stats_frustration_preaggregated_sql import (
posthog/hogql/database/schema/experiment_exposures_preaggregated.py:13:from posthog.clickhouse.preaggregation.experiment_exposures_sql import DISTRIBUTED_EXPERIMENT_EXPOSURES_TABLE
posthog/hogql/database/schema/web_stats_paths_preaggregated.py:13:from posthog.clickhouse.preaggregation.web_stats_paths_preaggregated_sql import (
posthog/hogql/database/schema/groups_revenue_analytics.py:17:from posthog.models.exchange_rate.sql import EXCHANGE_RATE_DECIMAL_PRECISION
posthog/hogql/database/schema/groups_revenue_analytics.py:18:from posthog.schema_enums import DatabaseSchemaManagedViewTableKind
posthog/hogql/database/schema/groups_revenue_analytics.py:120:    from products.revenue_analytics.backend.views import RevenueAnalyticsRevenueItemView
posthog/hogql/database/schema/groups_revenue_analytics.py:280:    from products.revenue_analytics.backend.views import RevenueAnalyticsCustomerView, RevenueAnalyticsRevenueItemView
posthog/hogql/database/schema/sessions_v3.py:27:from posthog.models.raw_sessions.sessions_v3 import (
posthog/hogql/database/schema/sessions_v3.py:32:from posthog.queries.insight import insight_sync_execute
posthog/hogql/database/schema/sessions_v3.py:34:from products.event_definitions.backend.models.property_definition import PropertyType
posthog/hogql/database/schema/sessions_v3.py:37:    from posthog.schema import CustomChannelRule
posthog/hogql/database/schema/sessions_v3.py:39:    from posthog.models.team import Team
posthog/hogql/transforms/preaggregated_table_transformation.py:39:from products.web_analytics.backend.hogql_queries.pre_aggregated.properties import (
posthog/hogql/database/schema/document_embeddings.py:18:from products.error_tracking.backend.indexed_embedding import EMBEDDING_TABLES
posthog/hogql/database/schema/sessions_v2.py:30:from posthog.models.raw_sessions.sessions_v2 import (
posthog/hogql/database/schema/sessions_v2.py:34:from posthog.queries.insight import insight_sync_execute
posthog/hogql/database/schema/sessions_v2.py:35:from posthog.schema_enums import BounceRatePageViewMode, SessionsV2JoinMode
posthog/hogql/database/schema/sessions_v2.py:37:from products.event_definitions.backend.models.property_definition import PropertyType
posthog/hogql/database/schema/sessions_v2.py:40:    from posthog.schema import CustomChannelRule
posthog/hogql/database/schema/sessions_v2.py:42:    from posthog.models.team import Team
posthog/hogql/direct_connection.py:5:from posthog.schema import HogQLQueryModifiers
posthog/hogql/direct_connection.py:11:from posthog.rbac.user_access_control import UserAccessControl
posthog/hogql/direct_connection.py:13:from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
posthog/hogql/direct_connection.py:16:    from posthog.models import Team, User
posthog/hogql/direct_connection.py:17:    from posthog.temporal.data_imports.sources.generated_configs import MySQLSourceConfig, PostgresSourceConfig
posthog/hogql/direct_connection.py:18:    from posthog.temporal.data_imports.sources.mysql.mysql import MySQLImplementation
posthog/hogql/direct_connection.py:19:    from posthog.temporal.data_imports.sources.postgres.source import PostgresSource
posthog/hogql/direct_connection.py:95:    from posthog.temporal.data_imports.sources import SourceRegistry
posthog/hogql/direct_connection.py:96:    from posthog.temporal.data_imports.sources.postgres.source import PostgresSource
posthog/hogql/direct_connection.py:98:    from products.data_warehouse.backend.types import ExternalDataSourceType
posthog/hogql/direct_connection.py:122:    from posthog.temporal.data_imports.sources import SourceRegistry
posthog/hogql/direct_connection.py:123:    from posthog.temporal.data_imports.sources.mysql.source import MySQLSource
posthog/hogql/direct_connection.py:125:    from products.data_warehouse.backend.types import ExternalDataSourceType
posthog/hogql/database/schema/persons.py:32:from posthog.models.organization import Organization
posthog/hogql/database/schema/persons.py:33:from posthog.schema_enums import PersonsArgMaxVersion
posthog/hogql/database/schema/logs.py:11:from posthog.clickhouse.workload import Workload
posthog/hogql/database/schema/exchange_rate.py:12:from posthog.models.exchange_rate.sql import EXCHANGE_RATE_DECIMAL_PRECISION
posthog/hogql/database/schema/exchange_rate.py:13:from posthog.models.team.team import Team
posthog/hogql/database/schema/exchange_rate.py:16:    from posthog.schema import RevenueAnalyticsEventItem
posthog/hogql/database/schema/channel_type.py:5:from posthog.schema_enums import CustomChannelField, CustomChannelOperator, DefaultChannelTypes
posthog/hogql/database/schema/channel_type.py:8:    from posthog.schema import CustomChannelRule
posthog/hogql/database/schema/marketing_touchpoints_preaggregated.py:13:from posthog.clickhouse.preaggregation.marketing_touchpoints_sql import (
posthog/hogql/database/schema/system.py:28:from posthog.scopes import APIScopeObject
posthog/hogql/printer/utils.py:3:from posthog.schema_enums import InCohortVia
posthog/hogql/printer/utils.py:6:    from posthog.schema import HogQLQueryModifiers
posthog/hogql/printer/utils.py:43:from posthog.clickhouse.workload import Workload
posthog/hogql/printer/utils.py:44:from posthog.models.team import Team
posthog/hogql/printer/utils.py:46:from products.access_control.backend.property_access_control import get_restricted_properties_for_team
posthog/hogql/printer/postgres.py:23:from posthog.models.utils import UUIDT
posthog/hogql/printer/base.py:36:from posthog.clickhouse.kafka_engine import json_extract_trim_quotes
posthog/hogql/printer/base.py:37:from posthog.models.team.team import WeekStartDay
posthog/hogql/printer/base.py:38:from posthog.models.utils import UUIDT
posthog/hogql/printer/base.py:39:from posthog.schema_enums import PersonsOnEventsMode
posthog/hogql/printer/clickhouse.py:30:from posthog.models.exchange_rate.sql import EXCHANGE_RATE_DECIMAL_PRECISION, EXCHANGE_RATE_DICTIONARY_NAME
posthog/hogql/printer/clickhouse.py:31:from posthog.models.team.team import WeekStartDay
posthog/hogql/printer/clickhouse.py:32:from posthog.models.utils import UUIDT
posthog/hogql/database/schema/util/revenue_analytics.py:3:from posthog.schema_enums import DatabaseSchemaManagedViewTableKind
posthog/hogql/database/schema/util/revenue_analytics.py:5:from products.revenue_analytics.backend.views.schemas import SCHEMAS as VIEW_SCHEMAS
posthog/hogql/database/schema/util/where_clause_extractor.py:293:            from products.event_definitions.backend.models.event_definition import EventDefinition
```

## Appendix B: useful follow-up scans

Full violations including tests:

```bash
rg -n '\b(from|import) (posthog|products|ee|common)\.' posthog/hogql -g '*.py' | rg -v 'from posthog\.hogql\b|import posthog\.hogql\b'
```

Production violations only:

```bash
rg -n '\b(from|import) (posthog|products|ee|common)\.' posthog/hogql -g '*.py' -g '!**/test/**' -g '!**/test_*.py' | rg -v 'from posthog\.hogql\b|import posthog\.hogql\b'
```

External callers of HogQL:

```bash
rg -n '^(from|import) posthog\.hogql' posthog products ee common services -g '*.py' | rg -v '^posthog/hogql/'
```

Imports from Django/DRF inside HogQL:

```bash
rg -n 'from django|import django|rest_framework' posthog/hogql -g '*.py'
```

Potential model escape hatches:

```bash
rg -n 'apps\.get_model|get_model\(|import_string|ContentType|objects\.|\.objects' posthog/hogql -g '*.py'
```

## Open decisions

- Is `common.hogvm` allowed as shared infrastructure, or must HogQL be isolated from `common.*` too?
- Is the target only "no PostHog first-party imports", or should core HogQL also be free of Django/DRF imports?
- What is the adapter package name?
- Which external modules remain public HogQL APIs, and which move to runtime integration APIs?
- Should response/query contracts be dataclasses, pydantic dataclasses, or pydantic models?
- Should product-owned table registrations be explicit adapter code, plugin registry calls, or static contract lists?
- How much compatibility should `posthog.hogql.query` preserve, given it cannot import runtime wrappers?
