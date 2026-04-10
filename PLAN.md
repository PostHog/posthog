# Error tracking isolation plan

## Goal

Bring `products/error_tracking` into practical compliance with the product facade architecture so it can participate in selective testing and keep cross-product coupling narrow and explicit.

## Why this matters

Per `products/README.md` and `products/architecture.md`, isolated products get the testing benefit only when they expose a stable public contract and keep implementation details private.

That means Error tracking needs:

- a small public facade in `backend/facade/`
- stable, framework-free contracts for cross-product data
- a real presentation boundary for HTTP wiring
- tach-enforced boundaries that discourage internal imports
- a meaningful `backend:contract-check`
- external consumers migrated off product internals

## Current status

Error tracking is no longer starting from zero. The core scaffolding now exists, but the boundary is still permissive and much of the migration work remains.

### Already implemented

- `products/error_tracking/backend/facade/` exists
  - `api.py`
  - `contracts.py`
  - `enums.py`
  - `__init__.py` re-exports the public facade surface
- `products/error_tracking/backend/presentation/` exists
  - `serializers.py`
  - `views.py`
  - `urls.py`
- `products/error_tracking/package.json` includes `backend:contract-check`
- `tach.toml` now treats `products.error_tracking` as a `products` layer module rather than `non_isolated`
- `tach.toml` already exposes explicit public interfaces, including:
  - `products.error_tracking.backend.facade`
  - `products.error_tracking.backend.presentation.views`
  - several temporary non-facade interfaces that still need cleanup
- there are already tests under `products/error_tracking/backend/test/facade/`

### Partially implemented

These pieces exist, but they are not yet in the final desired state.

#### Facade

The facade exists and already exposes useful entry points for:

- issue lookup and summaries
- assignment lookup
- remote config access
- weekly digest helpers
- counts used by reporting/usage paths

However, it is still only a partial architecture win:

- much of `backend/facade/api.py` is a thin wrapper around existing internal modules
- several facade methods still return plain `dict`/`list` payloads instead of dedicated frozen contract types
- the facade still imports product ORM models directly, which is acceptable internally but shows the implementation is still close to existing internals rather than a fully curated boundary
- query-runner access and tooling access are not yet consistently routed through the facade

#### Contracts

`backend/facade/contracts.py` exists and already defines frozen dataclasses, including:

- `IssueSummary`
- `ErrorTrackingIssueContract`
- `ErrorTrackingIssueAssignmentContract`
- `TeamCountContract`

But contracts are still incomplete:

- they cover only part of the currently exposed cross-product use cases
- digest, remote-config, search, and query-runner outputs still rely largely on legacy shapes
- some public facade methods still expose unstructured data that should become contract types if they remain public

#### Presentation

`backend/presentation/` exists, but today it is mostly a compatibility surface.

- `presentation/views.py` re-exports viewsets from `backend/api/*`
- `presentation/serializers.py` re-exports serializers from `backend/api/*`
- this gives callers a stable import path, but most HTTP/business logic structure still lives under `backend/api/`

So presentation has been introduced structurally, but true presentation separation has not happened yet.

#### Tach enforcement

Tach is better than before, but still intentionally loose.

- Error tracking is now product-layered
- there is an explicit facade interface
- there is an explicit presentation interface
- but many internal modules are still listed as public interfaces, including:
  - `backend.models`
  - `backend.remote_config`
  - `backend.weekly_digest`
  - `backend.tools.search_issues`
  - several `backend.hogql_queries.*` modules
  - `backend.sql`, `backend.embedding`, and `backend.indexed_embedding`

This means the repo recognizes the product boundary, but the allowed surface is still much broader than the intended steady state.

#### Contract-check

`backend:contract-check` exists, but it is currently a placeholder:

- script: `echo 'Contract files unchanged'`

That is enough for initial product recognition, but not enough to make contract discipline meaningful.

## What still imports Error tracking internals

A grep of Python imports still shows external consumers reaching into product internals.

### Still using `backend.models`

Representative external consumers include:

- `ee/hogai/context/error_tracking/context.py`
- `posthog/tasks/email.py`
- `posthog/tasks/usage_report.py`
- `posthog/test/test_permissions.py`
- `posthog/api/test/test_personal_api_keys.py`
- `posthog/hogql/database/schema/test/test_system_tables.py`
- `posthog/management/commands/*`
- `products/tasks/backend/repository_readiness.py` and similar reporting/usage paths

This remains the biggest isolation gap because ORM models are still acting as the public integration surface.

### Still using query-runner internals directly

Representative consumers include:

- `posthog/hogql_queries/query_runner.py`
- `products/signals/backend/temporal/backfill_error_tracking.py`
- `products/posthog_ai/scripts/hogql_example/__init__.py`

These consumers still depend on product-specific runner classes rather than a narrow public API.

### Still using other internal modules directly

Representative public-by-usage internal modules still include:

- `products.error_tracking.backend.remote_config`
- `products.error_tracking.backend.weekly_digest`
- `products.error_tracking.backend.tools.search_issues`
- `products.error_tracking.backend.sql`
- `products.error_tracking.backend.embedding`
- `products.error_tracking.backend.indexed_embedding`

Some of these are true business-boundary problems. Others are better treated as explicit infra/framework interfaces.

## Revised architecture assessment

### What is done

- facade scaffolding: **done**
- initial contract scaffolding: **done**
- presentation scaffolding: **done**
- package-level contract-check hook: **done, but placeholder**
- product-layer tach classification: **done**

### What is only partial

- migrating external consumers to the facade: **partial**
- replacing ORM/model-based integrations with contract-based reads: **partial**
- replacing direct query-runner imports with a public surface: **partial at best**
- separating presentation from legacy `backend/api/`: **partial**
- tightening tach to the intended long-term public surface: **partial**
- defining contracts for all durable public outputs: **partial**

### What remains genuinely unfinished

- move remaining external consumers off `backend.models`
- decide which non-facade interfaces are legitimate infra/framework surfaces versus migration debt
- shrink the tach interface list accordingly
- replace the placeholder contract-check with a real contract-focused check
- make `backend/presentation` the real home of public HTTP wiring rather than a re-export layer
- complete facade coverage for query/search/digest/remote-config use cases that remain public

## Remaining work

The rest of the work should focus on three areas, in this order.

### 1. Consumer migration

This is the highest-value remaining work.

#### Migrate model-based consumers first

Replace external imports of `products.error_tracking.backend.models` with facade methods wherever the use case is business-facing, especially in:

- email/digest orchestration
- usage reporting
- permissions and API checks
- AI/context assembly
- product-to-product reads

Target outcome:

- external callers depend on `products.error_tracking.backend.facade`
- external callers receive contract dataclasses or deliberately stable plain values
- ORM model classes stop being the default cross-product API

#### Migrate direct helper-module consumers

Move external callers off these business-facing modules:

- `backend.remote_config`
- `backend.weekly_digest`
- `backend.tools.search_issues`

Target outcome:

- these capabilities are reachable through facade methods or another explicitly public module with a narrow purpose

#### Revisit query-runner consumers

For consumers outside Error tracking, stop importing product runner classes directly unless a framework dispatch point truly requires it.

Target outcome:

- consumer code calls facade query functions or a clearly designated framework adapter
- if central HogQL dispatch must still import a runner temporarily, document that as an explicit framework exception rather than treating it like normal product API

### 2. Tach tightening

Once consumer migration lands, tighten `tach.toml` aggressively.

#### Desired steady-state business surface

The preferred public business surface is:

- `products.error_tracking.backend.facade`
- `products.error_tracking.backend.presentation.views`

#### Interfaces that may remain public, but should be classified explicitly

These likely belong as explicit infra/framework interfaces rather than facade surface:

- `products.error_tracking.backend.apps`
- `products.error_tracking.dags`
- `products.error_tracking.backend.sql`
- `products.error_tracking.backend.embedding`
- `products.error_tracking.backend.indexed_embedding`
- possibly a small amount of query-dispatch glue if it truly cannot move yet

#### Interfaces to remove from the public list when migration is complete

These should stop being public interfaces once callers are migrated:

- `products.error_tracking.backend.models`
- `products.error_tracking.backend.remote_config`
- `products.error_tracking.backend.weekly_digest`
- `products.error_tracking.backend.tools.search_issues`
- direct `products.error_tracking.backend.hogql_queries.*` runners used as de facto product API

### 3. True presentation separation

Right now `backend/presentation` mainly re-exports legacy API modules. The final step is to make it a real architectural layer.

#### Move public HTTP entry points behind presentation-owned modules

Over time:

- route registration should import from `backend.presentation.views`
- presentation modules should own DRF-facing serializers/viewsets
- business logic should stop accumulating in `backend/api/*`

#### Reduce `backend/api/` to legacy/internal transition code

Possible end states:

- migrate `backend/api/*` code into `backend/presentation/*` and retire the old package, or
- keep `backend/api/*` internal-only and ensure external imports use `backend.presentation.*`

The important part is not the directory name; it is that public HTTP wiring is clearly separated from internal business logic and no longer doubles as the product's public Python API.

## Suggested next slices

A good incremental order is:

1. migrate `posthog/tasks/email.py` to the facade where possible
2. migrate AI/context consumers such as `ee/hogai/context/error_tracking/context.py`
3. migrate usage/permissions/reporting consumers off `backend.models`
4. introduce facade/query entry points for remaining external query-runner consumers
5. shrink tach interfaces after each migration wave
6. replace the placeholder `backend:contract-check` with a real contract-sensitive implementation
7. progressively move DRF modules from `backend/api/` into true `backend/presentation/` ownership

For the concrete caller-by-caller backlog and PR sequencing, see `products/error_tracking/MIGRATION_MATRIX.md`.

## Definition of done

Error tracking is in the desired end state when all of the following are true:

- external business consumers import only `products.error_tracking.backend.facade`
- public HTTP wiring imports only `products.error_tracking.backend.presentation.views`
- stable cross-product data is represented by durable contract types
- `backend.models`, `backend.weekly_digest`, `backend.remote_config`, and search/query internals are no longer used as accidental public APIs
- tach exposes only the intentionally public interfaces
- `backend:contract-check` is meaningful rather than a placeholder
- implementation-only changes inside Error tracking avoid unnecessary downstream retesting

## Risks and caveats

- some remaining imports are infrastructure or framework concerns and should not be forced through the business facade
- query-runner dispatch may need a staged migration rather than a one-step rewrite
- moving to true presentation separation will likely be incremental because existing DRF modules mix concerns
- the right goal is a narrow, explicit public surface — not forcing every technical dependency through one facade module
