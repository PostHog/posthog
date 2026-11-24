# Modular Architecture & Isolated Testing

## Purpose

This document defines the future architectural direction for our Django monolith, focusing on:

- Establishing a clear, Django-friendly **folder structure** for product boundaries
- Using **frozen dataclasses** as the stable interface between products
- Introducing **facades** as the only public interface for products
- Enforcing **isolation** between products to avoid accidental cross-product coupling
- Enabling **selective testing** via Turbo (task caching) and hoglint (boundary enforcement)

This is a forward-looking design document, not a migration guide.

### Terminology

Different tools use different names for the same concept:

- **Product** — a self-contained feature area under `products/<name>/`. This is the unit of isolation, ownership, and selective testing.
- **Django app** — the backend implementation of a product (`products/<name>/backend/`). Registered in `INSTALLED_APPS` via `AppConfig`.
- **Turbo package** — the build/test unit defined by `package.json`. One product = one Turbo package.
- **hoglint package** — the boundary unit in hoglint's PostHog preset (`tools/hoglint/presets/posthog.toml`). Maps 1:1 to a product. Most code under `posthog/`, `ee/` and `common/` is the `core` package.

This document uses **"product"** when talking about boundaries and architecture, and **"Django app"** only for Django-specific mechanics (models, migrations, `apps.py`).

# 1. Why Modularization?

As the codebase grows, running all tests for every change becomes expensive, and startup time of the dev server grows. Our goal:

- **Reduce CI time** via selective testing
- **Make product boundaries explicit**
- **Prevent accidental cross-product imports**
- **Preserve developer velocity as the system grows**

Turbo provides task-level caching so that:

- Only tests affected by a change run
- Contract files (frozen dataclasses, enums) determine whether downstream products need retesting

hoglint enforces the Python boundaries between products with the rules of its PostHog preset (`tools/hoglint/presets/posthog.toml`).
Existing violations are debt in the generated `hoglint.ledger`, and a change must not add new ones.

To benefit from selective testing, we must introduce architectural boundaries inside the Django monolith.

# 2. Turbo + hoglint (Initial Scope: Single Product)

We will begin by wiring up **one product** to:

- Validate the folder structure
- Test contract-based selective testing with Turbo
- Verify boundary enforcement with hoglint
- Build the foundation for incremental test selection

Focus:

- One product = one Turbo package with `backend:test`; isolated products also declare `backend:contract-check`
- Non-isolated products must **not** declare `backend:contract-check` — `turbo-discover` uses this key to identify isolated products, and its presence causes selective testing to skip the full Django test suite
- Facade (`facade/api.py`) will define the **public interface**
- Internal files will be private implementation details
- Presentation layer (DRF) sits above the facade, outside the contract surface — but a product is only soundly skippable once that presentation is thin and reaches internals exclusively through the facade (see [What makes the skip sound](#what-makes-the-skip-sound)); an unsealed presentation that still holds business logic is not

Eventually this grows into:

- A dependency graph across products via contract inputs
- True selective test execution

But this document is about foundational structure, not full rollout.

### What makes the skip sound

Skipping the full suite for an isolated product is a claim that _a change inside the product can only break the product's own tests._
hoglint proves the import half of that claim.
Its Isolated level fails when code outside the product reaches a product file that the `backend:contract-check` inputs do not watch (`reached-watched`).
It cannot prove the other half.
A product's HTTP API is exercised **in-process** by tests (the Django test client dispatches into the view stack in the same process, not over a real socket), and cross-cutting tests — permissions, schema, activity-log, "every viewset does X" — reach a product's endpoints by URL.
That couples them to the product's live behavior with **zero imports**, so it is invisible to hoglint and to any import-graph audit.
"No importers" is necessary, not sufficient.

Because this channel can't be enumerated, it is closed by construction rather than inspection:

1. Keep the presentation layer thin and reaching internals only through the facade, so every observable behavior lives either in the facade (tested in-product, inside the boundary) or in the serializer shape (the OpenAPI schema, whose changes already force the full suite).
2. Keep behavior tests in-product.
3. Keep the model surface — `backend/models/` (or `backend/models.py`) and `backend/migrations/` — in the `backend:contract-check` inputs.
   A model is reachable with no import: `apps.get_model("label", "Class")`, migrations, admin, fixtures.
   An import graph cannot see that, so a model or migration change always re-runs the full suite.
   hoglint's `wiring-watched` rule fails the Isolated level when a narrowing leaves the surface out.
4. Keep in the inputs every module that outside suites run without an import:
   - a module with a signal receiver on a sender of core or another product;
   - a module that a test outside the product names by dotted path, as a patch target does;
   - a module that core loads by name through `load_product_modules`;
   - `backend/apps.py` and every product module it imports, because Django runs the AppConfig in every process;
   - `backend/admin.py` and every product module it imports, because Django's admin autodiscovery imports it;
   - a module that registers into a `register_*` hook of core or another product, and the module that defines what it registers;
   - a module that core settings name by dotted path, such as a middleware;
   - a module that core's request pipeline imports (see below).

   hoglint's `wiring-watched` rule finds each of them, and the Isolated level fails until each module is in the inputs.
   It watches the entry module, not everything that module calls: code behind it is tested in the product, like code behind the facade.

A product whose views still hold business logic is not soundly skippable even if nothing imports it.
This is also why "no in-process callers, so we don't need a facade" is the wrong test: a product whose only consumers are over HTTP (node services, the generated TS/MCP types) is _not_ facade-optional — there the facade's whole job is sealing its own presentation.
The genuine exception is a product with essentially no Django-side logic (a thin shim over an external service): it has nothing to seal, but it is then simply not isolated — no `backend:contract-check`, still paying the full suite — which is an accept-the-cost choice, not "isolated without a facade".

A product with a thin presentation can still be unsafe to skip when its facade returns decisions that core enforces on every request, such as access checks, and the tests for those decisions live outside the product.
A change behind its facade changes what core does, and only the full suite tests that.
hoglint's `request-path` rule lists every product module that core's request pipeline imports: the modules that settings name for the per-request pipeline, the view base class, and the product code they import.
`wiring-watched` asks for each of those modules in the `backend:contract-check` inputs, so a product that does not watch them fails the Isolated level.

### Wiring couplings

Core sometimes needs behavior from a product, not data: query runners it dispatches on, Temporal workflows it registers, Max tools it offers.
These cross the boundary as classes — allowed only under all three rules:

1. **Approved interface.**
   The class implements a core-owned base from the approved list — today `QueryRunner` (`posthog/hogql_queries/query_runner.py`), `MaxTool` (`ee/hogai/tool.py`), Temporal's `@workflow.defn`/`@activity.defn` and `Interceptor` (the worker in `posthog/temporal/common/worker.py` registers each one), and Celery's `@shared_task`.
   Core code may rely only on the base's interface, never on product-specific members.
   Extending the list is a core PR: define the base and validate at the registration point.
   DRF viewsets are not part of this channel: they live in `presentation/`, register through `routes.py`, and never pass through the facade (a facade must not import DRF, and not its own `presentation/`; hoglint's `facade-no-drf` rule enforces both, and `hoglint.ledger` holds the existing violations) — their soundness is governed by the presentation rules above.
2. **Designated location.**
   The implementation lives in the product's wiring location — `backend/hogql_queries/`, `backend/max_tools.py`, `backend/temporal/`, `backend/tasks/` (a flat `backend/tasks.py` also qualifies).
   An isolated product keeps a wiring location in its `backend:contract-check` inputs while a test outside the product can execute what lives there, so such a change still re-runs the full suite.
   The full suite matters only while such a test exists.
   For `backend/hogql_queries/` that is measured.
   Core dispatches runners by query kind, so hoglint's `drives` rule reads the dispatch and records every outside test that runs one of the product's kinds.
   `wiring-watched` then asks for every file such a test drives, and for the location's entry, in the inputs.
   Nothing is declared. Move the driving tests into the product, and the inputs may let those files go.
   A location with several subtrees may be watched one subtree at a time.
   `product_analytics` watches the whole `backend/hogql_queries/trends/` subtree, because trends is the only subtree an outside test still drives.
   Of its funnels, retention, lifecycle, paths and stickiness subtrees it watches only the runner modules its facade hands out (`reached-watched`), so the rest of that code changes without re-running the suite.
   Core runs the other locations by name (Celery task names, Temporal workflow names, Max tool names), and no rule reads those names yet.
   For each of them, `wiring-watched` asks for at least one watched file in the location.
3. **Validated registration.**
   A registration point accepts only implementations of its base and rejects anything else.
   A static check such as hoglint reads only the source; _what an object is_ can only be checked at runtime, at the door.
   `MaxTool` is the reference implementation: a class registers itself by subclassing (`__init_subclass__` in `ee/hogai/tool.py`), so only a `MaxTool` enters the registry, and the hook rejects an unknown tool name.
   Celery task discovery and `get_query_runner` do not validate yet: they accept whatever the wiring location holds.
   The Temporal worker validates every product's declaration (see [Temporal](#temporal)), and refuses to start when a `facade/temporal.py` has none.

Django models never cross, with or without an approved base.
A model cannot be narrowed: whatever interface it presents, the object still carries managers, `save()`/`delete()`, FK descriptors that query other tables on attribute access, and reverse relations added by other apps.
Two core registries are keyed by model class identity and are explicit, sanctioned exceptions: the team-extension registry and the file-system unfiled registry (`FileSystemSyncMixin`).
There the class crosses for registration only, core drives only the registry's mixin methods, and the model's module must stay in the product's contract-check inputs.

**The watched-models allowance** is the one further, deliberately temporary exception, for products whose models are load-bearing substrate that core and sibling products consume and cannot yet stop consuming.
Four products hold entries.
`warehouse_sources`: core HogQL reads its warehouse table/schema/source models to build queryable tables.
`ExternalDataDestination`, `ExternalDataSourceDestination` and `ExternalDataSchemaDestination` cross for the same reason as the rest of the product's models — the destination CRUD `ModelViewSet` and the source-/schema-level link-table editors need the classes themselves for `Meta.model`, querysets, and edits to the link rows, not a read-only shape.
`data_modeling`: `DataWarehouseSavedQuery`, `DataWarehouseSavedQueryDraft`, `DataWarehouseSavedQueryColumnAnnotation`, `DataWarehouseManagedViewSet`, `DataModelingJob`, `DAG`, `Node` and `Edge`.
Core HogQL reads saved queries to build the views a query can name, the same reason the `warehouse_sources` table models cross.
The saved-query, draft and column-annotation `ModelViewSet`s live in `data_warehouse` `presentation/` and need the classes for `Meta.model`, querysets and writes.
`endpoints` holds a ForeignKey into `DataWarehouseSavedQuery`.
Retiring the entries means moving those viewsets into the product, so that consumers keep only ids and contracts.
`product_analytics`: `Insight` and `InsightVariable`.
Core and seven products (alerts, dashboards, surveys, annotations, exports, customer_analytics, pulse) hold ForeignKeys or M2Ms into `Insight` — dashboard tiles, subscriptions and exported assets, sharing configurations, tagged items — and rely on cascade deletes, relation traversal, reverse relations, and queryset-typed access-control filtering that a frozen contract cannot express.
`InsightVariable` has no consumer left outside the product; its entry survives only because the SQL-variables `ModelViewSet` in `presentation/` needs the class and presentation may reach internals only through the facade, so retiring the entry means converting that viewset off `ModelSerializer` first.
The dashboards→product_analytics `DashboardTile.insight` FK and `Dashboard.insights` M2M-through cross into the product against §8's direction rule; that coupling is accepted under this entry until dashboards pursues its own isolation.
`workflows`: `HogFlow`.
`HogFlowViewSet` in `presentation/` reads and writes workflows through facade functions, but the log, metrics and access-control mixins it inherits read the row through `get_object()`, and `UserAccessControl` resolves the resource and the object-level rules from the model instance.
Retiring the entry means teaching those core mixins and `UserAccessControl` to accept a resource type and id in place of a model instance.

An allowance product's facade may hand out model classes defined under `backend/models/`.
The model surface is watched by every narrowed product anyway (see [What makes the skip sound](#what-makes-the-skip-sound)); the allowance adds only the permission to hand out the class.
That is the same soundness contract wiring locations have; what it does not buy is isolation — the coupling to core remains, `hoglint.ledger` keeps it on record as debt, and the direction of travel is still facade functions returning contracts.
The ledger records each hand-out of these classes (`export-shape`, `facade-signature`), and `hoglint compare` blocks a change that adds one.
The debt only shrinks.
Only a person can accept a new hand-out, with a reviewed exception in `hoglint.exceptions.toml`, and the change must amend this section to name the class and why it cannot yet be a contract.
Each use of these classes outside the product is a `model-crossings` row, which only reports (see the next paragraphs).

**The consumer side is default-deny.**
A product model may appear in code outside its product only in a shape that hoglint's `model-crossings` rule identifies as instance-free.
These shapes are allowed:

- an annotation, on an argument, a return, or a variable;
- `X.DoesNotExist`;
- a nested class attribute, such as `X.Status` or `X.PrivilegeLevel`;
- `X._meta`;
- a manager chain that ends in `values()`, `values_list()`, `count()`, `exists()`, or `aggregate()`;
- a manager chain that `Exists(...)` or `Subquery(...)` embeds;
- a signal sender;
- the class passed to `cast(...)` or to `get_or_create_team_extension(...)`.

Every other use is disallowed.
The check does not ask what the consumer intended.
If the check does not identify a use as instance-free, change the caller.
`model-crossings` reports a disallowed use and does not block it, because the fix often needs facade work from the team that owns the model.
CI lists each new use for that team.

**Move the code, do not permit it.**
Code that queries, serializes, or writes a model belongs in that model's product.
A consumer that holds such code is misplaced code, not a coupling to document.
Move the code into the owning product.
The facade function is what the move leaves behind.
The consumer keeps the orchestration and the ids.

**`apps.get_model` is ratcheted for every product model.**
`apps.get_model('label', 'Class')` reaches a model through the Django app registry.
It leaves no import edge, so an import-graph check cannot see it.
hoglint's `get-model` rule therefore counts every reference from outside the owning product to any product's model, not only the allowance classes.
Test modules stay out of scope, which is a blind spot, not permission.
A core test fixture that reaches a model this way is not counted here and, with no import edge, not selected by snob when the model changes.
Seed product rows through a facade write function, or through a `facade/testing.py` helper for fixture-only needs, instead; a test that reaches any other module past the facade is a `public-surface` finding.
Migrations stay out of scope too: a migration reaches a model through the historical registry, and that is the only way a migration can.
Production code must not add one; the rule reports each one, like `model-crossings`.

**The ratchet.**
`hoglint.ledger` records the existing debt of the rules that block.
The crossing rules (`public-surface`, `model-crossings`, `get-model`) keep no ledger lines: they only report.
`drives` lines record the tests outside a product that execute its wiring, read from test modules only.
A new `drives` line is a new outside test that drives product code, and that test belongs in the product.
`facade-signature` and `export-shape` lines record what a facade hands out, read from the facade itself rather than from a caller.
The pre-commit hook and CI hold the ledger equal to a fresh scan.
A count can go down.
A count must not go up: `hoglint compare` blocks new debt in CI.
A use that goes away must leave the ledger in the same change: `hoglint ledger shrink` removes the stale lines and lowers the counts.
Run `hoglint check --all --rule model-crossings` to see the uses, and `hoglint explain <rule>` for the page of a rule.

**The ledger only shrinks.**
The ledger is generated, so a hand edit cannot add a line.
New lines come only with a change that a person reviews: a new rule that records the findings that exist when it lands, or a reviewed exception in `hoglint.exceptions.toml` (DevEx owns it).
A coupling that must stand needs such a change, not a line.
A change that only moves or splits a consumer module carries its lines along.

**What the check cannot see.**
The check reads uses of the class name, plus `get_model` string references.
It does not read three things:

- attribute access on an instance the consumer already holds, inside a function body;
- traversal of a foreign key that the consumer's own model declares;
- a `get_model` call whose app label or model name is a variable.

All three are a declared residual, not permission to add more.

A behavioral class that fits no approved interface must not cross at all.
Wrap it in a facade function returning contracts, or register a plain function (see the managed-view provider registry in `products/data_modeling/backend/facade/managed_viewset_hooks.py`).
A product whose facade hands out unapproved behavior is not soundly isolated: it loses `backend:contract-check` and pays the full suite until fixed.
The one exception is a rule that DevEx introduces: findings that already exist at that moment are recorded in `hoglint.ledger` instead, and those lines may only go away.

**Inbound webhook consumers are a designated location of the same kind.**
A product declares its handlers in `backend/webhook_consumers.py`, in a `WEBHOOK_CONSUMERS` sequence.
`posthog/ingress/` discovers that module through `load_product_modules("webhook_consumers")` on the first delivery, and its registry validates each consumer at build: an unknown provider app, a name already taken for that provider, or an event type the provider does not declare raises.
No class crosses, because a consumer is a plain function behind a frozen contract, and hoglint's `webhook-consumers-use-facade` rule lets the module reach product backend code only through a facade.
See [posthog/ingress/README.md](/posthog/ingress/README.md).

Why shape rules rather than location rules: publicness-by-location without a constrained API shape rots.
Shopify's Packwerk `app/public` folders became a "catch-all drawer" of models, controllers, and jobs for exactly this reason.
The facade stays honest only if what crosses is a frozen dataclass or an implementation of a core-owned interface — nothing else.

### Temporal

A product hosts its Temporal code on core's worker through one declaration, and offers its workflows to other code only through named functions.

**Home.**
A workflow or an activity that one product owns lives in `backend/temporal/`.
`posthog/temporal/` holds the platform only: the worker, the client, the codec, core's interceptors and metrics, shared test infrastructure, and workflows whose domain is core.
Do not add a product-owned subtree to `posthog/temporal/`.

**The declaration.**
`backend/facade/temporal.py` holds one value, `TEMPORAL`, of the core type `TemporalRegistration` (`posthog/temporal/common/registration.py`).
It binds workflows and activities to task queues, and lists the product's interceptor classes, histogram specs, schedule reconcilers and log-source resolvers.
A binding names its queue by the name of a `*_TASK_QUEUE` setting in `posthog/settings/temporal.py`, for example `QueueBinding(queue_setting="VIDEO_EXPORT_TASK_QUEUE", ...)`.
Every queue setting resolves to one development queue under `DEBUG`, so tools such as the workflow catalog need the name, not the value.
Core finds the declaration with `load_product_modules("facade.temporal")` and never imports a product's Temporal code by name.
The module holds nothing else: no list, no workflow class, no activity, no helper.
Only core's Temporal loaders and the product's own tests read it.
`products/review_hog/backend/facade/temporal.py` is the reference.
A `facade/temporal.py` without `TEMPORAL` stops every worker at startup, and CI fails on it first.

**Validation.**
Core validates every declaration before a worker starts and before schedules apply.
It rejects a workflow without `@workflow.defn`, an activity without `@activity.defn`, a member that another product owns, two different implementations with one name on one queue, an unknown queue setting, and an interceptor that is not an `Interceptor` class.
A product test calls the same validator (`validate_registration`), so a broken declaration fails in the product's own `backend:test`.

**Using another product's workflow.**
The product that owns a workflow offers named functions for it:

- `backend/facade/temporal_client.py`: start, signal and query from ordinary code.
- `backend/facade/temporal_workflow.py`: helpers that are safe to call from inside a workflow, for example to start a child workflow.

Create each module only when another boundary needs it.
Their inputs and outputs are contracts in `facade/contracts.py`: frozen dataclasses or pydantic models, with no model, no queryset and no bare `Any`.
Do not start, signal or query another boundary's workflow by a literal name.
A literal name is correct in one case: a deleted workflow or activity that an open execution must still replay.

**Tests.**
A product's Temporal tests live in the product and run in its `backend:test`.
Core's Temporal tests use their own fixture workflows, not product workflows.
A helper that other products' tests need goes in `facade/testing.py`.

**Watching.**
An Isolated product keeps `backend/temporal/` in its `backend:contract-check` inputs.
A file that another boundary executes through a facade hand-out stays in the inputs.

# 3. Folder Structure

Each product adopts the following structure:

```text
myproduct/
  backend/
    __init__.py
    apps.py
    models.py          # Django ORM only
    logic.py           # Business logic
    logic/             # ...or a package, once logic.py outgrows one file

    tasks/
      __init__.py
      tasks.py         # Celery entrypoints (call facade)
      schedules.py     # Celery beat / periodic config (optional)

    management/
      commands/
        <command>.py   # CLI entrypoints (parse args, call facade)

    facade/
      __init__.py
      api.py           # Facade (the only thing other products may import)
      contracts.py     # Frozen dataclasses (+ enums if small enough)
      enums.py         # Optional: exported enums/shared types when contracts.py grows

    presentation/
      __init__.py
      serializers.py   # DRF serializers (frozen dataclasses <-> JSON)
      views.py         # DRF views (HTTP endpoints)
      urls.py          # HTTP routing

    routes.py          # register_routes(routers): the one module core reads to mount the views

    tests/
      test_models.py
      test_logic.py
      test_api.py            # Facade tests
      test_presentation.py   # DRF integration tests
      test_tasks.py
```

### Why this layout?

- Matches Django conventions — low friction
- Keeps business logic separate from HTTP concerns
- Keeps the product root clean
- Provides an explicit, enforced boundary (`facade/`)
- Scales naturally with contract-based selective testing

### Which locations are fixed, and which are yours

Only the paths the tooling is pointed at have fixed names: `facade/`, `presentation/`, `tasks/`, `routes.py`, `webhook_consumers.py`, and the wiring locations (`hogql_queries/`, `max_tools.py`, `temporal/`) — see [Wiring couplings](#wiring-couplings).
They are the narrowed `backend:contract-check` inputs, and hoglint's `presentation-uses-facade` rule holds the HTTP surface inside them by shape: `routes.py` and `presentation/` reach product code only through `facade/` or their own product's `presentation/`.
Core reaches a product's views only through `routes.py`, so the chain core → routes → presentation → facade is three import edges, and a view anywhere else simply cannot be routed.

Everything else under `backend/` is internal implementation.
`logic/` is the default home and the scaffold creates it as a package, but as a domain grows into `services/`, `queries/`, `reviewer/`, or whatever it is called in that product, no lint polices the name.
Nothing outside the product can import those packages, and their changes are exactly what the isolation skip is meant to skip.
The boundary is the shape of what crosses the facade, not the location of what stays behind it.

For the broader monorepo structure (products, services, platform), see [monorepo-layout.md](/docs/internal/monorepo-layout.md).

# 4. Contracts (`contracts.py`)

Each product defines its public interface as **frozen dataclasses** in `backend/facade/contracts.py`. These are the only data structures that cross product boundaries — facades accept and return them, and other products import them.

### Rules:

- No Django imports, in `contracts.py` and in `enums.py`. An enum that backs model or serializer choices is a `LabeledStrEnum` or `LabeledIntEnum` from `posthog/enums.py`, not a `models.TextChoices`
- Immutable (`frozen=True`)
- Small, hashable, stable
- Facades accept them as inputs and return them as outputs

### Choosing a dataclass flavor

Stdlib `dataclasses.dataclass` is the baseline.
`pydantic.dataclasses.dataclass` is the preferred upgrade when construction-time validation is useful:
it keeps full dataclass semantics (passes `is_dataclass()`, works with `DataclassSerializer`, identical kwargs construction, `frozen=True`, `field(default_factory=...)`)
and adds Pydantic's runtime type validation as a 1-line import swap.

Use `pydantic.BaseModel` only when a contract genuinely needs features that dataclasses don't have — field aliases (e.g., camelCase wire / snake_case Python), computed fields exposed in the schema, custom validators, discriminated unions.
Stay with one of the dataclass flavors otherwise;
switching to `BaseModel` loses `is_dataclass()`-based tooling.

DTO validation is **best-effort, not HTTP validation**.
DRF serializers (or Pydantic schemas at the HTTP boundary) own the contract for untrusted input.
Pydantic dataclass validation catches construction-site mistakes inside the backend — structural mismatches from mappers, malformed data from internal callers — close to the bug rather than at the wire.

Note that Pydantic v2 dataclasses coerce inputs where the conversion is unambiguous (string → UUID/datetime, int → str) rather than reject them.
Structural mistakes (None for a required int, dict where a list is expected, unparseable UUID) still raise `ValidationError`.
If a contract genuinely needs strict typing — e.g., to catch a string sneaking into a UUID field — opt in per-contract via `@dataclass(frozen=True, config=ConfigDict(strict=True))`.

### Example

```python
from pydantic.dataclasses import dataclass


@dataclass(frozen=True)
class Artifact:
    id: UUID
    project_id: int
    content_hash: str
    storage_path: str
    width: int
    height: int
    size_bytes: int
    created_at: datetime
```

Contracts **should not depend on**:

- Django models
- DRF serializers
- Request objects

If input and output shapes are identical, reuse the same dataclass.

# 5. Facades: The Public Interface

Each product exposes a facade via the `backend/facade/` package — the only place core and other products may import from (hoglint's `public-surface` rule reports any other import).
`api.py` holds the data capabilities: functions that accept and return contracts.
Capability submodules (`queries.py`, `max_tools.py`, `tasks.py`, …) exist only to re-export wiring implementations — see [Wiring couplings](#wiring-couplings) — and contain no logic of their own.
`temporal.py` holds the product's Temporal declaration, and `temporal_client.py` and `temporal_workflow.py` hold named functions that start, signal or call its workflows — see [Temporal](#temporal).

### Responsibilities

- Accept frozen dataclasses as input parameters
- Call business logic (`logic.py`)
- Convert Django models → frozen dataclasses before returning
- Remain thin and stable

### Do NOT:

- Implement business logic (use `logic.py`)
- Change state: no writes, row locks or transactions, and no reads that leave the team scope. The whole operation goes into `logic.py`, and the facade calls it (hoglint's `facade-no-state` rule)
- Import DRF, HTTP, or serializers
- Expose Django models or return ORM instances

### Example

```python
class ArtifactAPI:
    @staticmethod
    def create(params: CreateArtifact) -> Artifact:
        instance = logic.create_artifact(params)
        return _to_artifact(instance)
```

### Contracts inside the product

A product's own `logic.py` may take its contracts as arguments, as `logic.create_artifact(params)` above does; internals importing `facade.contracts` and `facade.enums` is expected, not a layering violation.
Keep the wire in mind: a contract that also backs a `DataclassSerializer` request body is the HTTP shape shipped clients send.
Pass it through while its fields are one-to-one with what logic needs, and split off an internal parameter object at the first real divergence — dead or deprecated wire fields, values logic needs that the wire must not accept, invariants the wire can't promise.
That split lives in the facade, the only in-process caller.
Never widen a type on the way in: if logic needs a `str`, don't accept a contract with `str | None` and add a runtime guard.
See `/writing-dataclasses` for the general rule.

### Why explicit mappers?

Facades convert ORM models to frozen dataclasses via mapper functions. These look repetitive when fields align 1:1:

```python
def _to_artifact(instance) -> contracts.Artifact:
    return contracts.Artifact(
        id=instance.id,
        content_hash=instance.content_hash,
        # ... more fields
    )
```

The value isn't the copying — it's having **one place** where "internal" becomes "external":

1. **Explicit boundary** — the frozen dataclass defines exactly what callers receive. Internal fields don't accidentally leak.
2. **Transformation point** — add computed fields, flatten relations, rename for consistency.
3. **Drift absorption** — when models and the exposed dataclass diverge, the mapper absorbs it instead of changes leaking everywhere.

The alternative — returning ORM objects — works until it doesn't, then you're retrofitting isolation under pressure.

# 6. Business Logic (backend/logic/)

Business logic lives here: validation, calculations, business rules, ORM queries.
Further internal packages beside it are fine (see [Which locations are fixed](#which-locations-are-fixed-and-which-are-yours)).

Start as a single `logic.py`.
Once it outgrows one file, split it into a `logic/` package with one module per concern and mirror that split in `tests/logic/` — `products/visual_review/backend/logic/` is the reference, and `/splitting-oversized-modules` does the move.
Import the submodule you need (`from .logic import runs`) rather than re-exporting through `__init__.py`: one binding per symbol keeps it obvious where behavior lives and keeps test patch targets on the real definition.

Examples:

- Deduplication rules
- Business invariants
- Cross-field validations
- Idempotency checks

### Why separate from the facade?

- Facades must stay thin and stable
- Presentation should not contain business rules
- Frozen dataclasses remain pure data
- Logic is internal implementation — changes here don't affect other products' tests

# 7. Presentation Layer (DRF)

Located in `backend/presentation/`.

Responsibilities:

- Validate incoming JSON (via DRF serializers)
- Convert incoming JSON → frozen dataclasses
- Call facade methods
- Convert frozen dataclasses → JSON responses
- No business logic

Presentation may only import `facade` and other `presentation` modules within the same product. It must not import `models`, `logic`, or any other internal module directly — even utility modules like `cache.py` or `permissions.py`. hoglint's `presentation-uses-facade` rule enforces this in CI.

`backend/routes.py` exists to hand the views to core's router (`register_routes(routers)`), nothing else. hoglint counts it as presentation, so the same rule holds it. A product whose routes still register views from `backend/api/` carries that import as debt in `hoglint.ledger` until `hogli product:isolate:move` relocates them.

### Where do cross-cutting utilities go?

If both presentation and logic need the same utility (caching, permissions, etc.), putting it at `backend/cache.py` and importing from both layers creates an "accidental shared kernel" — a hidden coupling that bypasses the facade. Instead:

- **Presentation concern** (response caching, rate limiting, user RBAC — see below) → `presentation/`
- **Business concern** (domain-level caching, tenant scoping, domain invariants) → `logic/`, exposed through the facade
- **Both layers need it** → that's a signal the boundary is drawn wrong; refactor

### Who owns RBAC?

User RBAC stays on the **viewset** — it depends on the authenticated `request`/`user`, which the facade doesn't have (facades also run from Celery, CLIs, and other products). Declare it the standard way: `scope_object` plus `scope_object_read_actions`/`scope_object_write_actions`, and let the shared permission classes (`APIScopePermission`, `AccessControlPermission`) on `TeamAndOrgViewSetMixin` enforce API-scope and resource access. See `products/visual_review/backend/presentation/views.py`.

A view that fetches a contract from the facade has no model instance for DRF's `get_object()` to check.
It still checks object access through the same permission stack:

- Override `read_object()` to fetch the contract through the facade, filtered by team. Return `None` for a missing object, which becomes a 404. `TeamAndOrgViewSetMixin` forbids overriding `get_object()` itself.
- The mixin's `get_object()` calls `check_object_permissions` on the contract and returns the contract. Actions, `LogEntryMixin`, `AppMetricsMixin` and DRF's detail `OPTIONS` metadata get the contract from `get_object()`.
- `AccessControlPermission` needs an `ObjectAccessRef` (`products/access_control/backend/facade/contracts.py`) to resolve the object's access. Override `object_access_ref(record)` to build it from the contract. Set `fallback_parent` when the resource inherits access from a parent object (`RESOURCE_FALLBACK_MAP`).
- When no access rule can name one record, for example when `scope_object` is not an access-control resource, set `records_have_object_access_rules = False` instead.
- A view that does neither fails closed: the object check raises.

Do not call `AccessControlPermission` methods by hand, and do not pass `UserAccessControl` or a required level into the facade.
`UserAccessControl` object methods take a model instance only. They raise on a contract.

The facade owns **tenant scoping** (`team_id` enforced via `for_team(team_id)` / a `ProductTeamModel` fail-closed manager) and **domain invariants** (state machines, idempotency) — these must hold for every caller, so they live below the HTTP boundary; user RBAC must not. Keeping RBAC in the shared DRF stack also lets cross-cutting permission tests enforce it consistently across products.

### Path ids

A view that reads through the facade has no `queryset`, so nothing can read the type of a URL kwarg from a model.
Declare the types on the view: `path_parameters = {"pk": UUID}`.
`TeamAndOrgViewSetMixin` parses each declared kwarg before the handler runs, and answers 404 for a malformed value, the same as a queryset view.
The handler gets `pk: UUID`, and the OpenAPI schema shows `format: uuid`.
A named capture in an action's `url_path` goes in the same mapping.
A nested parent lookup goes in by its bare name: `"pipeline_id": UUID` types the `parent_lookup_pipeline_id` kwarg.
`team_id`, `project_id` and `organization_id` do not, because `parents_query_dict` resolves them.
To describe an id in the API docs, declare `PathParameter(type=UUID, description="...")` instead of the bare type.
Do not parse path ids by hand. See `products/visual_review/backend/presentation/views.py`.

### How do lists page?

A facade returns contracts, not a queryset, so a view cannot hand its rows to a DRF paginator.
The facade pages in SQL instead, and the view builds the standard response from that page.
`posthog/paging.py` holds the page types, `posthog/queryset_paging.py` pages a queryset into them, and `posthog/api/pagination.py` holds the view helpers.

- A facade list function takes a `PageRequest` (or a `CursorPageRequest`) and returns `Page[Contract]`.
  Page the queryset with `select_page` (or `select_cursor_page`), then convert the rows with `page.map(...)`.
  Both helpers count the whole list and add the primary key as the last sort term, so the page order is deterministic.
  An offset page can still shift when rows are added or deleted between requests.
  A cursor page does not skip or repeat a row, unless the ordering values of a row change between requests.
  The queryset must hold one row per item, so a join that duplicates rows breaks both forms.
- The view sets `pagination_class = FacadeLimitOffsetPagination` and returns `facade_page_response(self, fetch)`, where `fetch` calls the facade with the page.
  For a cursor list, subclass `FacadeCursorPagination`, set `ordering`, and return `facade_cursor_page_response(self, fetch)`.
  A cursor stores every ordering field of the row at the page edge, so the contract must expose those fields and `id`.
- Use limit/offset for a list that people browse with a total.
  Use a cursor for a list that grows at the top while people read it, such as batch export runs or deliveries, because offsets shift as rows arrive.
  Do not add page-number lists.
- Every list returns `count`, `next`, `previous` and `results`, so clients and MCP tools page every product the same way.
  Add extra fields beside them when a list needs them, and do not replace them.
- Do not set paginator attributes by hand, build a fake queryset for a paginator, or return a whole list for the view to slice.
  The `no-hand-set-paginator-state` semgrep rule blocks the first.
- Every paginator extends a base in `posthog/api/pagination.py`: `BoundedLimitOffsetPagination`, `BoundedPageNumberPagination` or `StableCursorPagination`.
  `posthog/test/repo_invariants/test_pagination_contract.py` fails for a registered view whose paginator does not.

`products/visual_review/backend/presentation/views.py` shows the limit/offset form.

### Why not mix with the facade?

- Keeps HTTP concerns decoupled
- Allows reusing business logic for async tasks, CLI, future services

### Don't API views leak implementation?

No. Views only call facades, and facades only return frozen dataclasses. The presentation layer remains decoupled from internal details — when the facade hasn't changed, nothing outside the product is affected.

### Management commands

`backend/management/commands/` is an entrypoint, the same as presentation and `tasks/`. A command reads its arguments, calls the facade, and writes its output through `self.stdout` and `self.stderr`. Do not put business logic in a command.

hoglint's `thin-commands` rule holds this: a command that imports its own product's `models`, `logic` or `tasks` past the facade is a finding. Dev seeders that the preset marks as test code are out of its scope.

A command sometimes needs a capability that the facade does not have. Add the necessary facade function. Do not import `logic` or `models` in the command.

# 8. Isolation Rules

### Forbidden

- Importing another product's `models.py` directly
- Importing anything from another product's `logic.py`
- Importing views or serializers from another product
- Returning ORM objects from facades

### Allowed

- Importing another product's `backend.facade` (the facade)
- Using frozen dataclasses returned by facades
- Calling business logic from within the same product
- Presentation calling its own product's facade

### Concrete examples

**Product A needs data from Product B — use the facade:**

```python
# products/revenue_analytics/backend/logic.py
from products.data_warehouse.backend.facade import DataWarehouseAPI

# OK: calling the facade, getting back frozen dataclasses
tables = DataWarehouseAPI.list_tables(team_id=team_id)
```

Not this:

```python
# WRONG: importing models directly from another product
from products.data_warehouse.backend.models.table import DataWarehouseTable
tables = DataWarehouseTable.objects.filter(team_id=team_id)
```

**Product exposing functionality — keep the facade thin:**

```python
# products/signals/backend/facade/api.py — real example from the codebase
async def emit_signal(team_id, source_product, source_type, source_id, description, weight):
    """Other products call this. They never touch signals' models or internals."""
    ...
```

**Using contracts from another product:**

```python
# products/other_product/backend/logic.py
from products.visual_review.backend.facade.contracts import Artifact

def process_artifact(artifact: Artifact) -> None:
    # artifact is a frozen dataclass, not an ORM object
    ...
```

### What hoglint enforces

hoglint reads every Python file and checks the couplings between packages against the rules of the PostHog preset (`tools/hoglint/presets/posthog.toml`), which the root `hoglint.toml` extends.
The main boundary rules:

- `public-surface`: code outside a product reaches only what the product exports, which is its facade and the registration modules core loads. Core production code may also reach a declared permanent interface (the preset's `permanent` assign).
- `export-shape` and `facade-signature`: a facade hands out only contract types, never a model, manager, queryset or command.
- `presentation-uses-facade`: `routes.py` and `presentation/` reach product code only through a facade, their own product's presentation, or an adapter that another product exports. Any new internal module (cache, helpers, etc.) is blocked automatically.
- `facade-no-drf` and `contracts-no-django`: a facade imports no DRF, `django.http` or presentation, and importing a contracts module runs no Django.
- `model-crossings`, `get-model` and `reverse-accessor`: see [Wiring couplings](#wiring-couplings) and [Cross-product foreign keys](#cross-product-foreign-keys).
- `no-new-package-cycles` and `foundation-direction`: no new dependency closes a cycle between products, and a foundation product never depends on a feature product.

`hoglint explain <rule>` prints the page of a rule.
`public-surface`, `model-crossings` and `get-model` only report: a new crossing into another product's internals needs that team's facade work, so CI lists it for the team and does not block it, and the ledger keeps no line for it.
The other rules block. Their existing violations are debt in `hoglint.ledger`.
The pre-commit hook runs `hoglint check --index` on the lines a commit changes, and CI runs `hoglint compare` against the parent commit, so a change cannot add new debt.
Run `hoglint check` locally.

A product that narrows its `backend:contract-check` inputs in its own `turbo.json` claims hoglint's Isolated level, and `hoglint check` fails when the product does not meet it.
The level fails on an unwatched file that code outside the product reaches (`reached-watched`), unwatched wiring (`wiring-watched`), presentation past its facade (`presentation-uses-facade`), and a missing facade (`has-facade`).

> [!TIP]
> Use the `isolating-product-facade-contracts` skill for the full migration workflow — it covers contracts, facades, caller migration, and boundary enforcement step by step.

During migration, existing cross-product model imports stay, and `public-surface` reports them. The goal is to replace them with facade calls over time.

### Cross-product foreign keys

Django allows `ForeignKey` relationships across products. A relation that crosses a boundary creates an **implicit reverse dependency**, even if you never use it:

```python
# visual_review/backend/models.py
project = models.ForeignKey(Project, ...)
```

Django auto-generates a reverse accessor (`project.visualreview_set`), a reverse query name (`filter(visualreview__...)`), migration dependencies, and app loading order dependencies. No import checker can see the accessor, yet any caller can traverse it.

**Rule:** declare every relation field (FK, O2O, M2M) that crosses a product boundary with `related_name="+"`, and do not set an explicit `related_query_name` on it. `related_name="+"` alone removes the reverse accessor and the reverse query name; an explicit `related_query_name` keeps `filter()` traversal alive, and hoglint's `reverse-accessor` rule reports it too. A product may point relations _at_ core models; other products must not reference models _inside_ this product. When a caller needs reverse access, add a facade read function — do not traverse the ORM.

hoglint's `reverse-accessor` rule enforces this: `hoglint.ledger` holds every existing cross-boundary reverse accessor, next to the other debt. The set may only shrink. A new relation without `related_name="+"` fails CI until you seal it. After you seal one, run `hoglint ledger shrink` to drop its stale line.

`db_constraint` is a separate concern: it is migration safety (see the hot-table FK rules in [products/README.md](README.md)) and multi-database planning, not Python isolation. Both `db_constraint=False` and a two-phase validated constraint are sanctioned.

# 9. Turbo Tasks & Contract-Based Testing

Each product is a Turborepo package with tasks defined in its `package.json`.

## Contract files vs. implementation files

Turbo uses file-based inputs to determine cache validity. The key distinction:

**Contract inputs** (used by `backend:contract-check`):

- `backend/facade/contracts.py` — frozen dataclasses (enums can live here too)
- `backend/facade/enums.py` — optional, for exported enums/constants/shared types when contracts.py grows
- the product's wiring locations (`backend/hogql_queries/`, `backend/max_tools.py`, `backend/temporal/`, `backend/tasks/`) — implementations core registers and drives (see [Wiring couplings](#wiring-couplings)); `backend/hogql_queries/` may leave the list once hoglint's `drives` rule records no outside test driving it; core runs the others by name, so `wiring-watched` asks for at least one watched file in each

**Implementation inputs** (used by `backend:test`):

- All `backend/**/*.py` files

Other products depend on a product's **contract files only**. When contract files haven't changed, downstream products don't need retesting.

**Import boundaries** are reported by hoglint's `public-surface` rule (see [What hoglint enforces](#what-hoglint-enforces)). This ensures products don't accidentally import each other's internals, which would break the contract-based isolation model. See the `isolating-product-facade-contracts` skill for the migration workflow.

**Dependency rules for contract files (keep them pure):**

- No Django imports (`from django.*`)
- No DRF imports (`from rest_framework.*`)
- Use stdlib for errors, not `django.core.exceptions`
- No `from_model()` methods — put conversion in implementation code

## How selective testing works

```text
other_product tests
       | depends on
visual_review contracts  (facade/contracts.py, facade/enums.py)
       | does NOT depend on
visual_review impl       (logic.py, models.py)
```

**Scenario: Change `visual_review/logic.py`**

- `visual_review backend:test` → reruns (impl files changed)
- `visual_review backend:contract-check` → cache hit (contract files unchanged)
- `other_product backend:test` → skipped (depends only on contracts, which didn't change)

## CI commands

```bash
# Run all product tests
pnpm turbo run backend:test

# Run specific product tests
pnpm turbo run backend:test --filter=@posthog/products-visual_review

# Run contract checks
pnpm turbo run backend:contract-check
```

# 10. Summary

This document outlines the **future direction** of our codebase:

- Django-idiomatic layout with product boundaries
- Frozen dataclasses as the stable interface between products
- Thin facades as the only public interface
- Business logic isolated and testable
- DRF presentation decoupled from core logic
- Turbo for task caching and selective test execution
- hoglint for Python boundary enforcement

This architecture reduces coupling, enables selective testing, and keeps the system maintainable as we grow.
