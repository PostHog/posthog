---
name: isolating-product-facade-contracts
description: Plan and execute product isolation migrations to a facade plus contract layer in PostHog, following the Visual review architecture. Use when a product still exposes internals (models/logic/views) across boundaries and needs migration toward contracts.py + facade/api.py + presentation separation, with a PR strategy that minimizes review latency and conflicts with parallel work.
---

# Isolating a product with facade and contracts

Before you choose a product to isolate, check [things already tried](../../../docs/internal/ci-things-already-tried.md). It records which product was the first candidate, and why the field test moved to another one.

Use this skill to migrate an existing product to the isolated architecture used by Visual review.
Optimize for short calendar exposure, not small diffs: authoring is cheap and the verification
chain catches mechanical breakage, while human review latency and a fast-moving master are the
real bottlenecks. Default to one PR structured in reviewable commits; a separate facade-first PR
exists only as the merge base for team-sliced sweeps — per the PR strategy below.

**Prerequisite:** the product must already live under `products/<name>/`. This skill does not cover moving code out of `posthog/`, `ee/`, or other shared directories — do that first.

## Core docs to load first

Read these before changing code:

1. [products/architecture.md](../../../products/architecture.md)
2. [products/README.md](../../../products/README.md)
3. [docs/internal/monorepo-layout.md](../../../docs/internal/monorepo-layout.md)
4. [posthog/models/team/README.md](../../../posthog/models/team/README.md) (team extension model rule)
5. [docs/published/handbook/engineering/type-system.md](../../../docs/published/handbook/engineering/type-system.md) (serializer/OpenAPI type flow)
6. [docs/published/handbook/engineering/ai/implementing-mcp-tools.md](../../../docs/published/handbook/engineering/ai/implementing-mcp-tools.md) (schema quality and team isolation expectations)
7. [.agents/security.md](../../../.agents/security.md) (SQL/HogQL security guidelines)

Use Visual review as the concrete reference implementation:

- [products/visual_review/backend/facade/contracts.py](../../../products/visual_review/backend/facade/contracts.py)
- [products/visual_review/backend/facade/api.py](../../../products/visual_review/backend/facade/api.py)
- [products/visual_review/backend/presentation/views.py](../../../products/visual_review/backend/presentation/views.py)
- [products/visual_review/backend/presentation/serializers.py](../../../products/visual_review/backend/presentation/serializers.py)
- [products/visual_review/backend/logic/](../../../products/visual_review/backend/logic/)
- [products/visual_review/backend/tests/test_api.py](../../../products/visual_review/backend/tests/test_api.py)
- [products/visual_review/backend/tests/test_presentation.py](../../../products/visual_review/backend/tests/test_presentation.py)

Before changing code, get the baseline:

```bash
hogli product:maturity <name>               # scores models and codegen
hogli product:lint <name>                   # structural lint: product.yaml, root files, markers, backend:test
hogli product:isolate:scan <name>           # the recon: import map, coupling gate, preflight (see below)
rg -F 'products.<name>.' hoglint.ledger     # the product's blocking boundary debt, one line per finding
hoglint check --all --rule public-surface | rg -F 'products.<name>.'  # crossings into it (report only)
```

**First, read the baseline to learn which migration phase you're in — you don't start
knowing whether this is untouched or mid-flight, and that decides where you pick up.**
The signals are all in the output above; there is no status file to consult (a hand-kept
one would drift). The product's rows _are_ the status: its `public-surface` rows, which
only report and so live in hoglint's output rather than the ledger, and its lines in
`hoglint.ledger`. Both shrink as modules finish:

- **Fresh** — no `backend/facade/`, and `public-surface` reports code that reaches the
  product's internals. Start at step 1.
- **Mid-sweep** — `facade/contracts.py` + `facade/api.py` exist but core still imports
  internals (scan still lists model-access/etc., or `public-surface` still reports rows
  into the product). The facade design is settled; continue migrating callers (step 4) —
  don't redesign it.
- **Mid presentation-wave** — the sweep is done, but the ledger still holds
  `presentation-uses-facade` lines for the product. Resume the presentation wave on
  exactly those deferred modules.
- **Effectively done** — no `public-surface` rows into the product and no
  `presentation-uses-facade` lines left for it. Verify against the done criteria instead of changing anything.

The scan does the recon that would otherwise cost a dozen ad-hoc greps, and is the
source of truth for the rest of the flow:

- **References by kind** — every cross-boundary reference to the product's internals,
  classified (model-access, query-runner, celery-task, temporal-wiring, test-fixture,
  string-reference) with the facade pattern each kind maps to. This is the sweep
  checklist; string references (`@patch(...)` mock paths, dotted names in config) are
  included, which import-oriented grepping misses.
- **Core-coupling count** — picks the PR strategy below: near zero means the whole
  migration fits the single-PR default; triple digits means the caller sweep needs
  slicing by owning team.
- **Strict-lint preflight** — `product:lint` switches from lenient to strict the moment
  `facade/contracts.py` exists; the scan runs the structural checks in forced-strict
  mode so those demands (root `tsconfig.json`, `tasks.py` at `tasks/tasks.py`, required
  root files in place) surface up front instead of mid-migration. Strict lint checks
  the required root files only. It does not restrict internal directory names: the
  enforced shape is hoglint's `presentation-uses-facade` rule (`routes.py` and
  `presentation/` reach product code only through `facade/`), so a product may add other
  internal packages (`services/`, `reviewer/`, …) as long as they stay behind the facade.
- **Thin/thick signal per view module** — how many view modules the presentation wave
  must thin before they can move into `presentation/`.
- **Blind spots** — the scan reads `backend.*` imports only. A coupling count of
  zero is necessary, not sufficient: it can't see product-root packages core
  imports (`dags/`) or non-import channels (config dotted strings, hogql system
  tables, in-process API test dispatch). See "Clearing coupling the scan won't
  show" below before declaring a product done.

`--json` emits the machine-readable recipe — keep it with the PR; regenerating the
migration against fresh master starts from a fresh scan.

## When the tooling doesn't fit, fix the tooling

Don't quietly hand-work-around it. If `isolate:scan`/`:move` misses your product's
shape — a layout it doesn't detect, a coupling channel it can't see — and other
products share that shape, extend the tool and update this skill so the next
migration inherits the fix. That's how `backend/api/`-subpackage support and the
Dagster-assets channel got added. Reserve a manual work-around (called out in the
PR) for a true one-off; a silent hand-hack just leaves the next product to hit the
same wall.

## "No in-process callers, so no facade" is the wrong test

The core-coupling count sizes the **sweep** — zero importers means a single-PR
migration with no caller migration — but it does not decide **whether** to isolate.
The facade is also the structural seal that makes the CI skip _sound_, and that has
nothing to do with importer count:

- A product's HTTP API is exercised **in-process** by tests (the Django test client
  dispatches into the view stack in the same process, not over a real socket).
  Cross-cutting tests — permissions, schema, activity-log, "every viewset does X" —
  reach a product's endpoints by URL, coupling to its live behavior with **zero
  imports**. hoglint and this scan both read the code for references, so neither of
  them can see it. "No importers" is necessary, not sufficient.
- Because the channel can't be enumerated, it is closed by construction, not audit:
  keep presentation thin and reaching internals only through the facade, so every
  observable behavior lives in the facade (tested in-product, inside the boundary)
  or in the serializer shape (the OpenAPI schema, whose changes already force the
  full suite); and keep behavior tests in-product.

So a product whose only consumers are over HTTP (node services, the TS/MCP codegen)
is **not** facade-optional — there the facade's whole job is sealing its own
presentation (step 2's second demand source). The genuine exception is
a product with essentially no Django-side logic (a thin shim over an external
service): it has nothing to seal, but it is then simply _not isolated_ — no
`backend:contract-check`, still paying the full suite. That is an accept-the-cost
choice, not "isolated without a facade".

This is the third non-import coupling channel, alongside hogql system tables and
dotted-string config (step 6.4) — and the least visible, since the other two at
least leave a string to grep for.

## Clearing coupling the scan won't show

`product:isolate:scan` walks the import graph of `backend.*`. Six kinds of
coupling escape it — none is a dead end, each has a defined move. After the
backend sweep, `git grep "products.<name>"` (not just `.backend`) and read the
scan's string-reference section to find them.

**Reverse accessors.** A relation field (FK, O2O, M2M) that crosses a product
boundary without `related_name="+"` adds a reverse accessor and a reverse query
name to the target class. No import exists, so the scan cannot see it, but any
caller can traverse it. The move: seal the relation with `related_name="+"`,
remove any explicit `related_query_name` (it keeps `filter()` traversal alive,
and hoglint's `reverse-accessor` rule still reports it), and drop its stale line
from `hoglint.ledger` in the same change (`hoglint ledger shrink`); give a
caller that needs reverse access a facade read function. The `reverse-accessor`
rule blocks new unsealed relations. See products/architecture.md § Cross-product
foreign keys.

**Signal coupling.** A receiver whose sender belongs to another boundary runs
that boundary's code inside this one's save path, with no import edge when the
sender is a string. Three moves, by case:

- _Core listens to a product model_ (string sender) — flip the direction: the
  product calls core's public function from its own save path
  (`remote_config.mark_dirty(team_id)`), a normal product→core import.
- _A product reacts to a core save_ — register through a core-owned hook
  (the `register_team_extension_signal` shape), not a raw `@receiver` on a
  foreign sender. The hook registry is the inventory.
- _Either direction_ — never do slow or external work in a receiver body. Use
  `transaction.on_commit` to dispatch a task instead.

**Test-infrastructure coupling.** hoglint's `public-surface` rule judges tests
like production code. A test may import any product's facade, and CI reports a
new test import of another product's internals the same way it reports
production code. Such a test gets one of the moves below. When the product
cannot offer the move yet, the import stays, `public-surface` keeps reporting
it, and `reached-watched` asks for the file it reaches in the product's
contract-check inputs. Never hand the internals out from a facade module under a sanctioned
name to clear the finding. Core tests reach into the product's test helpers,
which no facade re-export naturally covers:

- _Monkeypatch targets_ — a core test base patches a product module attribute
  (e.g. `posthog/test/base.py` patches `execute_hogql_query` on each runner
  module). Re-export the **module object** through the facade
  (`facade/queries.py` re-exports `web_overview`, not just its class) and point
  the patch at the facade path.
- _Shared fixtures / base classes_ — a core test subclasses the product's test
  base. Decide ownership: if the fixture is infrastructure for a **core**
  concern (a preaggregated-table test base, and the tables live in core), move
  it down into core and have both sides import it downward; if the core test is
  really exercising the **product's** behavior, relocate the test into the
  product. Either way the cross-boundary test import disappears.
- _Fixtures that need product rows_ — a core test seeds a product model
  (`InsightViewed`, `Account`) to set up its scenario. Seed through a
  facade write function, with a normal import. If none exists yet, add
  one; that is the same move a production caller makes. A helper that
  only fixtures need goes in a `facade/testing.py` submodule: the facade
  exports it to tests, and a test that reaches any other module past the
  facade is a `public-surface` finding. Never
  `apps.get_model("<label>", "<Model>")` at module scope: it is the same
  dependency with the import edge removed.
  hoglint's `get-model` rule skips tests, mypy and LSP stop seeing it, and
  snob (the PR test selector) does not select the test when the model
  changes, so the break lands on master.
  A `TYPE_CHECKING` import next to it does not restore the edge, because
  snob ignores type-only imports.

**Surfaces outside `backend/`.** A product can expose non-Django surfaces at its
root — Dagster assets under `products/<name>/dags/`, for instance — that core
imports directly. The scan only walks `backend.*`, so it won't list them, and
hoglint reports the core import as a `public-surface` row, and as an unwatched
file (`reached-watched`) once the product claims the Isolated level. Re-export them through a facade submodule (`facade/dags.py`
re-exporting the asset modules) and reroute the core importer, exactly like
the temporal and query-runner wiring.

**No external data consumers.** Covered above — the facade serves the product's
own views. Provide facade read functions for its models; wire the cheap views;
defer the expensive ones (nested-serializer or transactional viewsets) to the
presentation wave, named in the PR. Providing the facade function while
deferring its caller is a legitimate intermediate state, not a half-migration.

**Product-owned HogQL system tables.** When core mounts a product's federated
system tables (`schema/system.py`, `lazy_join_registry.py`), answer two independent questions:

- _Can the reference be a normal facade import?_ Yes — table defs and lazy-join
  functions are plain module-level objects; move them into the product
  (e.g. `facade/hogql.py`) and reroute core's import, like any other wiring.
- _Do the objects enter the **static** pickled catalog?_ Core builds the
  catalog once and reloads it per request through a restricted unpickler
  (`build_database_root_node` in `posthog/hogql/database/database.py`).
  Any product-defined **class** in the catalog tree (a `PostgresTable`/`LazyTable`
  subclass) needs its module added to `_CATALOG_PICKLE_MODULES` — allowlisted
  individually, not by prefix. A missing entry fails the core catalog tests
  with a message naming the module. Warehouse-style per-team tables are built
  at request time and never enter the static catalog, which is why most
  products never hit this.

The web_analytics migration is the worked example of all three: its preagg test
base moved down to core, its timezone integration test moved into the product,
its Dagster assets gained a `facade/dags.py`, and its filter-preset reads landed
in `facade/api.py` with the viewset deferred.

## Model classes a consumer already holds

Some products still hand out model classes under the watched-models allowance
(products/architecture.md § Wiring couplings), and `hoglint.ledger` holds those
hand-outs as debt. That allowance only says the class may leave the product; it
says nothing about what the consumer does with it. Two rules cover that:

- **Default-deny.** A product model may appear in consumer code only in a shape
  hoglint's `model-crossings` rule calls instance-free: an annotation,
  `X.DoesNotExist`, a nested class attribute (`X.Status`), `X._meta`, a manager
  chain ending in `values`/`values_list`/`count`/`exists`/`aggregate`, a chain
  embedded in `Exists(...)`/`Subquery(...)`, a signal sender, or the class passed
  to `cast(...)` or `get_or_create_team_extension(...)`. Anything else is
  disallowed.
- **Move, don't permit.** Code that queries, serializes or writes a model belongs
  in that model's product. The remedy for a disallowed use is a move; the facade
  function is what the move leaves behind, and the consumer keeps orchestration
  and ids.

`apps.get_model('label', 'Class')` is counted too, by hoglint's `get-model` rule, and
for **every** product model, not only the allowance ones. It leaves no import edge,
so an import check cannot refuse it.
Test modules stay out of the rule, which is a blind spot, not permission: a core
test fixture that reaches a model this way is uncounted and unselected (see
"Test-infrastructure coupling" above). Migrations stay out too: the historical
registry is the only way a migration can reach a model. Production code must not
add a call; the rule reports each one.

`hoglint check --all --rule model-crossings` lists the disallowed uses. The
crossing rules (`public-surface`, `model-crossings`, `get-model`) only report:
the fix often needs facade work from the owning team, so CI lists a new use for
that team instead of blocking it, and the ledger keeps no line for it. A
reviewer still asks for the move. See `products/architecture.md` § Wiring
couplings.

## Guardrails

- Keep facades thin; put business rules behind the facade, in `logic/` by default. Other internal packages (`services/`, `reviewer/`, …) are fine as long as they stay behind the facade.
- Transaction boundaries belong in the facade (or logic), not in views.
- A view that serves a contract checks object RBAC through an `ObjectAccessRef`: return one from `safely_get_object()`, or pass one to `self.check_object_permissions(request, ref)`. Never check by hand or in the facade. See `products/architecture.md` § Who owns RBAC?
- A view without a `queryset` declares its URL kwarg types with `path_parameters = {"pk": UUID}`, and does not parse path ids by hand. See `products/architecture.md` § Path ids.
- Never return ORM models across product boundaries.
- A list view pages through the facade: the facade takes a `PageRequest` and returns a `Page`, and the view uses `FacadeLimitOffsetPagination` or `FacadeCursorPagination`. Never set paginator state by hand. See `products/architecture.md` § How do lists page?
- hoglint reads the facades: `facade-signature` (what a public facade function
  accepts and returns), `export-shape` (what a facade module hands out) and
  `facade-logic` (a capability submodule holds no body). `hoglint.ledger` records
  what the facades do today and only shrinks, so a new finding fails `hoglint compare`.
  The rule is `products/architecture.md` § Facades: The Public Interface.
- Declare every relation field that crosses a product boundary with
  `related_name="+"`. hoglint's `reverse-accessor` rule blocks new unsealed ones.
- Do not register a signal receiver on another boundary's sender; use the moves
  in "Signal coupling" above.
- Keep contract files pure (no Django/DRF imports in `facade/contracts.py` or `facade/enums.py`). A choices enum there is a `LabeledStrEnum` / `LabeledIntEnum` from `posthog/enums.py`.
- Filter by `team_id` in querysets.
- Do not add product-specific fields to `Team`; use a Team Extension model.
- Add request/response schema annotations on viewset endpoints (`@validated_request` or `@extend_schema`).
- Regenerate OpenAPI/types (`hogli build:openapi`) when serializer/view changes affect API schema.
- Presentation may only reach internals via the facade. hoglint's
  `presentation-uses-facade` rule enforces it. Any new internal module (`cache.py`,
  `helpers.py`, …) is auto-covered; there is no blocklist to maintain. New
  cross-cutting imports must go through the facade.

## Required migration workflow

1. Build an import map for the target product.
   - Find cross-product imports into target internals (`models`, `logic`, `presentation`, non-facade modules).
   - Classify each usage by capability (read/list, detail/read, create/update/delete, async/task, webhook/event).
2. Define the contract surface from both demand sources.
   - External consumers (core, other products): start from currently consumed fields only.
   - The product's own presentation (step 5): the facade functions its views will call. For
     thick views this share may be deferred — but name the deferral; it decides whether the
     isolation you turn on is sound or optimistic (see step 5).
   - Create frozen dataclasses in `backend/facade/contracts.py` using `pydantic.dataclasses.dataclass` — same shape as the stdlib variant but with runtime type validation on construction.
3. Introduce a thin facade in `backend/facade/api.py`.
   - Map ORM instances to contracts with explicit mapper functions.
   - Keep method names capability-oriented and stable.
   - Wiring that core registers (celery beat tasks, query-runner registry hooks, Dagster
     assets) crosses the boundary as objects, not data — give each its own facade submodule
     (`facade/tasks.py`, `facade/queries.py`, `facade/dags.py`) re-exporting exactly what
     core touches. Temporal code is the exception: `facade/temporal.py` holds one
     `TEMPORAL = TemporalRegistration(...)` declaration that core discovers and validates,
     not re-exported lists (products/architecture.md § Temporal). Registry-style consumers dispatch on class identity (`isinstance`), so
     re-export the class itself; monkeypatch consumers need the module object, so re-export
     that too. Keep `facade/api.py` free of heavy imports (HogQL, temporalio) so config-only
     consumers don't drag them onto the `django.setup()` path — and split light shared
     tables (`facade/hogql.py`) out of the heavy runner re-exports for the same reason.
4. Migrate callers in one pass by default.
   - The rewrite is mechanical (import swap + call mapping) and fully checked by the
     verification chain; batching it only stretches the window in which master drifts
     under the branch.
   - Core test fixtures that need product rows go through the facade's write
     function or a product testing door, with a normal import — not
     `apps.get_model` (see "Test-infrastructure coupling" above for why).
   - Compatibility shims exist to bridge between serial PRs — the one-pass shape rarely
     needs them. If one is unavoidable, it dies in the final cleanup PR, not "later".
   - Exception: callers with subtle behavior (transaction boundaries, write-path
     semantics) may move in their own small PR — see the PR strategy below.
5. Move presentation to consume the facade.
   - Serializers convert JSON <-> contracts; views call facade methods only.
   - Decide **per view module, on a size estimate**, whether its facade refactor lands
     in this PR or defers. Estimate the wave per module: runner-execution swaps are
     cheap (runners already return `posthog.schema` types — no new contracts needed);
     plain model CRUD needs a small contract plus a few functions; transactional or
     cross-product logic embedded in serializers is the expensive tier. Swap every
     module whose wave is cheap; defer only the expensive ones, naming the reason and
     the deferred modules in the PR description.
   - Deferred modules stay where they are, usually `backend/api/`, and their
     `presentation-uses-facade` lines (from `routes.py` or `presentation/`) stay in
     `hoglint.ledger`. Do not move a view that still reaches internals into
     `presentation/`: that adds new `presentation-uses-facade` findings, and
     `hoglint compare` blocks new debt. That debt **gates the skip**: while any line
     remains the product must NOT narrow its `backend:contract-check` inputs (step 6),
     so the full suite keeps running and there is no coverage hole. This is the
     soundness boundary — the skip only re-runs the suite on facade/presentation
     changes, so it is honest only once presentation is thin. A thick deferred view
     reaches internals directly, so an internals change flowing to HTTP through it
     would slip past the skip (and past the cross-cutting core tests that exercise the
     product by URL with zero imports). hoglint enforces the gate:
     `presentation-uses-facade` is strict for the Isolated level, so a product that
     narrows its inputs while the lines remain fails `hoglint check`. The skip is the
     reward the presentation-wave PR unlocks when it empties them.
   - The mechanical share is one command: `hogli product:isolate:move <name>` (run
     `--dry-run` first) moves the ViewSet modules into `presentation/views/` (auto-detected,
     `--views` to override, for example to leave the deferred modules where they are), `tasks.py` into a `tasks/` package with celery names pinned
     (it re-exports the module's public surface, and warns when a _private_ tasks name is
     reached through the package path — e.g. a `@patch("...backend.tasks._helper")` target
     — since those need repointing to `...backend.tasks.tasks._helper` by hand; auto-rewriting
     them would corrupt the pinned `name=` strings), and rewrites the dotted paths
     repo-wide. A `backend/api/` subpackage moves whole:
     production helper subpackages (e.g. `destination_tests/`) keep their structure under
     `presentation/views/` and ride the prefix rename, while test subpackages (`test/`,
     `tests/`) relocate to `backend/tests/api/` — they leave the api namespace, so a naive
     prefix rewrite can't follow them. The move **refuses** if an `api/` module is already
     mirrored at `presentation/<stem>.py` — that means a prior hand-migration left a compat
     shim, and moving it would duplicate the module; delete the shim and repoint its callers
     first, then re-run for the rest (error_tracking is the worked example).
   - Rewriting is a deliberate two-tool split, mirroring the model-migration tooling rather
     than reinventing it: **absolute** fully-qualified paths and string references
     (`@patch(...)` mock paths) go through guarded word-boundary regex (lexically
     unambiguous); **relative** imports (`from ..x import y`, any depth) go through libcst
     (`cst_helpers.py`, ported from the product-model-migration `import_rewriter`) because
     resolving them needs the importing module's package, which a line regex can't know.
6. Enforce boundaries and verify. A product that narrows its
   `backend:contract-check` inputs in `products/<name>/turbo.json` claims
   hoglint's Isolated level, and `hoglint check` fails when the product does
   not meet it. The isolated skip needs all four of these:
   1. **Real facade** — `backend/facade/contracts.py` (or a `contracts/`
      package) and a `backend/facade/api.py` with actual function defs, not
      just re-exports from `logic` (`has-facade`).
   2. **Presentation through the facade** — no `presentation-uses-facade`
      lines left for the product in `hoglint.ledger`.
   3. **`backend:contract-check` script** — add to `package.json` so
      turbo-discover treats the product as isolated. This is the **last** piece,
      together with the narrowed inputs: add it only once the product is fully
      isolated, with no `presentation-uses-facade` lines left and presentation
      thin. hoglint fails the level while lines remain, because the skip is
      unsound until then (see step 5).
   4. **Narrowed `turbo.json` inputs** — restrict `backend:contract-check`
      inputs to `backend/facade/**` and `backend/presentation/**` so the
      Django suite is only re-run on facade/presentation changes (see
      `products/visual_review/turbo.json`). The inputs must also watch the
      whole model surface — `backend/models.py` or `backend/models/**`,
      plus `backend/migrations/**` (required even before the first
      migration lands): a model is reachable without an import
      (`apps.get_model` strings, migrations, admin, hogql system tables,
      dotted-string config), so no import check can prove nothing
      outside observes it. `product:bootstrap` scaffolds the inputs
      already covering it. The inputs must also watch every file that
      hoglint names: `wiring-watched` asks for the model surface and the
      wiring that runs without an import (admin autodiscovery, core's request
      path, app setup, hooks, settings paths, wiring an outside test drives),
      and `reached-watched` asks for each product file that code outside the
      product reaches past the facade. When `hoglint check` names an unwatched
      file, add it to the inputs. Dropping the narrowing instead needs a person.
   - **Permanent-interface exception (irreducible import coupling).** Some
     import coupling genuinely cannot be drained: ClickHouse DDL modules
     (`backend.sql`, `backend.embedding`, …) are imported by core's
     `posthog/clickhouse/schema.py` registry, `conftest.py`, and **frozen**
     ClickHouse migrations that hardcode the import path forever. You cannot
     reroute a frozen migration or move the module. For this, the `permanent`
     assign in the hoglint preset (`tools/hoglint/presets/posthog.toml`) lists
     those modules. The assign tells hoglint the module is a declared,
     irreducible exposure, **not** debt: `public-surface` lets core production
     code (not tests) reach it past the facade. Soundness is preserved by
     pairing it with turbo.json: `wiring-watched` asks for every permanent
     module in the contract-check `inputs` (e.g. `backend/sql.py`), so a change
     to it still re-runs the full suite. Only a person changes the preset. Use
     this only for coupling that is both non-behavioral-over-HTTP and
     impossible to reroute (frozen-migration / schema-registry DDL), not as an
     escape hatch for model/logic imports you simply haven't migrated yet.
     That restriction is structural, not stylistic: the assign is only sound
     when every frozen-pinned module contains **only DDL**. `error_tracking`
     is the worked example (`sql` / `embedding` / `indexed_embedding` are
     pure-DDL modules). `cohorts` has the same shape: migration 0010 pins
     `products.cohorts.backend.models.sql`, a DDL-only submodule, so the
     exception can cover exactly that submodule (not `backend.models.*`).
     `event_definitions` does **not**: migration 0120 pins
     `products.event_definitions.backend.models.property_definition`, a module
     that defines the `PropertyDefinition` model class alongside its DDL
     constant, so marking it permanent would expose model access — precisely
     the escape hatch this exception forbids. Products with that shape need the
     DDL extracted into a dedicated module first, with the frozen import path
     preserved by a re-export shim in the original module; the shim's residual
     exposure (the frozen migration still imports the model module) must be
     documented honestly in a comment next to the assign, not papered over by it.
   - Verify with `hoglint check` (boundaries and the Isolated level) and
     `hogli product:lint <name>` (structure).
   - Use `hogli product:maturity <name>` for the models and codegen scores, and
     the product's `public-surface` rows and lines in `hoglint.ledger` for the
     boundary work that remains.
   - Run focused tests for changed files, then product-level backend tests.

### Legacy leaks during migration

This is the exception path for high-coupling products whose caller sweep is sliced
across teams (see PR strategy below). With the single-PR default, all core callers
land in the same PR and this state never needs to exist.

If `posthog/` or `ee/` still imports product internals (`backend.models`,
`backend.oauth`, …) while the team-sliced PRs land, those imports stay, and
`public-surface` reports each one. Each slice removes some, and CI lists any
new import of an internal for the product's team. The final cleanup PR leaves
no `public-surface` row into the product. Do not narrow
the inputs until then: the Isolated level would ask the product to watch every
file that core still reaches (`reached-watched`).

## PR strategy

The scarce resources are reviewer attention and calendar time — not authoring effort.
Every open migration branch rots as parallel work lands, and every extra PR adds a
serialized review window plus a full-suite CI run (the product isn't isolated yet, so
each migration PR pays the full suite). Use the fewest PRs the merge topology requires,
and let commit structure — not PR boundaries — organize review.

**Default: one PR, structured in reviewable commits.**

1. **Commit — facade.** Contracts + facade (including wiring submodules) +
   behavioral-parity tests. Pure additions; reviewers read this commit as the design.
2. **Commit — sweep.** All caller migrations. Mechanical; reviewers sample, the
   verification chain carries it.
3. **Commit — structure + chain.** Presentation move and rewrites
   (`hogli product:isolate:move`), strict-lint fixes, the shrunk `hoglint.ledger`. Add
   `backend:contract-check` + narrowed `turbo.json` here **only if the product is
   fully isolated in this PR** — no deferred view modules. If any module is deferred
   (`presentation-uses-facade` lines remain), the skip can't turn on yet (hoglint fails
   the Isolated level), so it lands with the presentation-wave PR; this PR ships without
   the skip and keeps paying the full suite, which is sound.

Don't split the facade into its own PR for reviewability: new files cannot conflict
regardless of which PR they sit in, so a standalone design PR buys no conflict
protection — it only serializes two review windows and doubles the migration's CI cost.
Worse, a facade with no callers can only be reviewed in the abstract; in one PR the
caller diffs sit next to the design and justify (or indict) it. See `user_interviews`
PR #59132 and the logs migration (#63180 + #63184, done as two before this was learned)
for the shapes.

In the PR description, enumerate the behavior-bearing edits — write paths, transaction
boundaries, serializer changes, anything renamed or with pinned compatibility (celery
task names). That list is where review attention goes; everything else is sampled. If a
write path is genuinely subtle, pull those few callers into their own small PR as the
exception.

Treat the PR as regenerable, not rebasable: the import map plus the facade design fully
determine the rewrite, so on conflict, regenerate the branch against fresh master
instead of hand-resolving. Keep it open only for the review window.

**A separate facade-first PR exists for exactly one reason: it is the shared merge base
when the sweep must be sliced.** Gate on the core-coupling count from the baseline:

- **Low (zero to low double digits):** single PR, as above; skip the legacy-leaks
  machinery entirely.
- **High (triple digits):** the sweep won't review as one unit. Land contracts + facade
  - parity tests first — that standalone review is meaningful here, because every slice
    is about to code against it — then slice the sweep by who owns the calling code (the
    consuming team/area, not the product's own owner), reviewed in parallel, never
    serially by capability. Core's remaining imports stay as `public-surface` rows (above) while
    slices land, but do NOT add `backend:contract-check` yet: the Isolated level would
    ask the product to watch every file core still reaches. The final cleanup PR drops
    the last of those imports, dead adapters, and shims, and only then enables
    contract-check + narrowed `turbo.json` inputs. The CI payoff for this path lands
    at the end.

**Deferred view modules (step 5) add one follow-up on either path:** the presentation
wave — see the section below for its flow and outputs.

Trade-off to accept: one PR reverts coarser than several. That is fine because the
mappers are behavior-preserving, the behavior-bearing edits are enumerated up front,
and the whole PR is regenerable — weeks of serial PRs on a hot product cost more in
conflicts and forfeited isolated-CI time than an occasional coarse revert.

## Presentation wave

The second demand wave on the same facade: the functions the product's _own views_
need, where the first wave served external consumers. Run it once per product, after
the migration PR lands, working from the deferred modules listed in the PR (the scan's
view-module table is the worklist).

Per deferred module:

1. Design the facade functions its views need. Query endpoints get run-functions that
   take `posthog.schema` query objects and return the runner's response types — those
   are already framework-free, so usually no new contracts. Model-backed endpoints get
   contracts plus CRUD/capability functions (the `DataclassSerializer` pattern from
   visual_review).
2. Draw the line: execution and transaction concerns (`ExecutionMode`, query tagging,
   `select_for_update` caps, cross-product side effects) move behind the facade; HTTP
   concerns (request validation, response codes, `report_user_action` analytics) stay
   in the view.
3. Thin the view to parse → facade → serialize, with parity tests for the new facade
   functions, same as wave one.
4. Move the module into `presentation/` if it still sits in `backend/api/`
   (`hogli product:isolate:move <name> --views <path>`), then run
   `hoglint ledger shrink` to drop its `presentation-uses-facade` lines.
   `hoglint check` must pass. That shrink is the output that marks the module done.

This is a design PR, not a sweep: it carries the same review weight as the facade
commit (the contract and function shapes are the long-lived API), so it gets its own
PR rather than riding along with mechanical work. Refactoring a wave-one function while
here (e.g. subsuming a runner builder under a run-function) is fine — its callers are
few and the parity tests pin behavior. The product's done criteria below are only fully
satisfiable once this wave has emptied the product's `presentation-uses-facade` lines,
and emptying them is what unlocks the skip: the PR that drops the last line is where
`backend:contract-check` + narrowed `turbo.json` are finally added (hoglint fails the
Isolated level until then). For a product that deferred modules, this is when it earns
the CI skip.

## Done criteria

Treat migration as complete only when:

- Cross-product imports use `backend/facade` only.
- Facade returns/accepts contracts, not ORM.
- Presentation layer no longer encodes business logic.
- Tests cover facade and presentation boundaries.
- `public-surface` reports no row for code outside the product that reaches its
  internals.
- `hoglint.ledger` holds **no `presentation-uses-facade` line for this product**. Those
  lines are tracked architectural debt from deferred view modules; the presentation
  wave removes them.
- `hoglint check` passes, including hoglint's Isolated level for the product.
- `hogli product:lint <name>` passes.
- `backend:contract-check` is present in `package.json` with `turbo.json` inputs
  narrowed to `backend/facade/**` and `backend/presentation/**`, plus the files hoglint
  asks to watch (enables the CI skip). This is the **last** thing added: hoglint fails
  the Isolated level until the `presentation-uses-facade` lines above are gone, so the
  skip only ever turns on for a fully isolated product.
