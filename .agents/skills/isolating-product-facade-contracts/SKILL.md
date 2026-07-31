---
name: isolating-product-facade-contracts
description: Plan and execute product isolation migrations to a facade plus contract layer in PostHog, following the Visual review architecture. Use when a product still exposes internals (models/logic/views) across boundaries and needs migration toward contracts.py + facade/api.py + presentation separation, with a PR strategy that minimizes review latency and conflicts with parallel work.
---

# Isolating a product with facade and contracts

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
- [products/visual_review/backend/logic.py](../../../products/visual_review/backend/logic.py)
- [products/visual_review/backend/tests/test_api.py](../../../products/visual_review/backend/tests/test_api.py)
- [products/visual_review/backend/tests/test_presentation.py](../../../products/visual_review/backend/tests/test_presentation.py)

Before changing code, get the baseline:

```bash
hogli product:maturity <name>       # scores models, facade, presentation, boundaries, codegen
hogli product:lint <name>           # structural lint + isolation chain (strict if facade/contracts.py exists)
hogli product:isolate:scan <name>   # the recon: import map, coupling gate, preflight (see below)
```

**First, read the baseline to learn which migration phase you're in — you don't start
knowing whether this is untouched or mid-flight, and that decides where you pick up.**
The signals are all in the output above; there is no status file to consult (a hand-kept
one would drift — the maturity score plus the `ignore_imports` TODO set _is_ the status,
and `lint-imports` prunes the latter as modules finish):

- **Fresh** — facade/presentation score zero, no `backend/facade/`, no `ignore_imports`
  entries for the product. Start at step 1.
- **Mid-sweep** — `facade/contracts.py` + `facade/api.py` exist but core still imports
  internals (scan still lists model-access/etc., or `product:lint` warns `has legacy
interface leaks`). The facade design is settled; continue migrating callers (step 4) —
  don't redesign it.
- **Mid presentation-wave** — the chain is mostly intact but `pyproject.toml` still has
  `ignore_imports` TODO entries for the product. The sweep is done; resume the
  presentation wave on exactly those deferred modules.
- **Effectively done** — chain complete, no `ignore_imports` entries left. Verify against
  the done criteria instead of changing anything.

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
  mode so those demands (root `tsconfig.json`, `tasks.py` at `tasks/tasks.py`, only
  canonical `backend/` subdirectories) surface up front instead of mid-migration.
- **Thin/thick signal per view module** — the future `ignore_imports` allowlist size.
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
  imports**. tach, `lint-imports`, and this scan all read the import graph, so none
  of them can see it. "No importers" is necessary, not sufficient.
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

`product:isolate:scan` walks the import graph of `backend.*`. Four kinds of
coupling escape it — none is a dead end, each has a defined move. After the
backend sweep, `git grep "products.<name>"` (not just `.backend`) and read the
scan's string-reference section to find them.

**Test-infrastructure coupling.** Core tests reach into the product's test
helpers, which no facade re-export naturally covers:

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

**Surfaces outside `backend/`.** A product can expose non-Django surfaces at its
root — Dagster assets under `products/<name>/dags/`, for instance — that core
imports directly. The scan only walks `backend.*`, so it won't list them, and
`tach` / `product:lint` fail late with "not part of the public interface" (a
direct interface exposure also trips the legacy-leak check). Re-export them
through a facade submodule (`facade/dags.py` re-exporting the asset modules) and
reroute the core importer, exactly like the temporal and query-runner wiring.

**No external data consumers.** Covered above — the facade serves the product's
own views. Provide facade read functions for its models; wire the cheap views;
defer the expensive ones (nested-serializer or transactional viewsets) as named
`ignore_imports` for the presentation wave. Providing the facade function while
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

## Guardrails

- Keep facades thin; put business rules in `logic.py`.
- Transaction boundaries belong in the facade (or logic), not in views.
- Never return ORM models across product boundaries.
- Keep contracts pure (no Django/DRF imports).
- Filter by `team_id` in querysets.
- Do not add product-specific fields to `Team`; use a Team Extension model.
- Add request/response schema annotations on viewset endpoints (`@validated_request` or `@extend_schema`).
- Regenerate OpenAPI/types (`hogli build:openapi`) when serializer/view changes affect API schema.
- Presentation may only reach internals via the facade — enforced by the
  `presentation must use facade` import-linter contract in `pyproject.toml`
  (`tool.importlinter`). Any new internal module (`cache.py`, `helpers.py`, …) is
  auto-covered; there is no blocklist to maintain. New cross-cutting imports
  must either go through the facade or be temporarily allowlisted there.

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
   - Wiring that core registers (celery beat tasks, temporal workflows/activities/metrics/
     schedule constants, query-runner registry hooks, Dagster assets) crosses the boundary
     as objects, not data — give each its own facade submodule (`facade/tasks.py`,
     `facade/temporal.py`, `facade/queries.py`, `facade/dags.py`) re-exporting exactly what
     core touches. Registry-style consumers dispatch on class identity (`isinstance`), so
     re-export the class itself; monkeypatch consumers need the module object, so re-export
     that too. Keep `facade/api.py` free of heavy imports (HogQL, temporalio) so config-only
     consumers don't drag them onto the `django.setup()` path — and split light shared
     tables (`facade/hogql.py`) out of the heavy runner re-exports for the same reason.
4. Migrate callers in one pass by default.
   - The rewrite is mechanical (import swap + call mapping) and fully checked by the
     verification chain; batching it only stretches the window in which master drifts
     under the branch.
   - Core test fixtures that need product models: use `apps.get_model("<app_label>",
"Model")` at runtime plus a `TYPE_CHECKING` import for annotations — tach ignores
     type-only imports.
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
     the surviving `ignore_imports` entries in the PR description.
   - Deferred modules keep exact-pair `ignore_imports` entries in `pyproject.toml`'s
     TODO section. That debt **gates the skip**: while any entry remains the product
     must NOT enable `backend:contract-check` (step 6), so the full suite keeps running
     and there is no coverage hole. This is the soundness boundary — the skip only
     re-runs the suite on facade/presentation changes, so it is honest only once
     presentation is thin. A thick deferred view reaches internals directly, so an
     internals change flowing to HTTP through it would slip past the skip (and past the
     cross-cutting core tests that exercise the product by URL with zero imports).
     `hogli product:lint` enforces the gate — contract-check while `ignore_imports`
     entries exist fails lint. The skip is the reward the presentation-wave PR unlocks
     when it empties them.
   - The mechanical share is one command: `hogli product:isolate:move <name>` (run
     `--dry-run` first) moves the ViewSet modules into `presentation/views/` (auto-detected,
     `--views` to override), `tasks.py` into a `tasks/` package with celery names pinned
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
6. Enforce boundaries and verify. This is a four-step chain — each step depends
   on the previous one, and `hogli product:lint` (via `IsolationChainCheck`)
   fails if any step is skipped:
   1. **Real facade** — `backend/facade/api.py` must have actual function defs,
      not just re-exports from `logic`.
   2. **Tach interfaces** — preferred path is to add the product name to the
      regex in the existing shared `[[interfaces]]` block in `tach.toml` that
      exposes `backend\.facade.*` and `backend\.presentation\.views.*`. Only
      add a new dedicated block if the product needs a non-standard expose
      pattern.
   3. **`backend:contract-check` script** — add to `package.json` so
      turbo-discover treats the product as isolated. This is the **last** piece:
      add it only once the product is fully isolated — no `ignore_imports` entries
      left, presentation thin. `hogli product:lint` blocks the script while deferred
      entries remain, because the skip is unsound until then (see step 5).
   4. **Narrowed `turbo.json` inputs** — restrict `backend:contract-check`
      inputs to `backend/facade/**` and `backend/presentation/**` so the
      Django suite is only re-run on facade/presentation changes (see
      `products/visual_review/turbo.json`). Widen the inputs when core
      depends on the product **outside the import graph**: add
      `backend/models.py` if hogql system tables expose the product's
      tables or core config references its dotted paths (the scan's
      string-reference section surfaces the latter). tach/import-linter
      only police the import channel; a mechanical check for these
      non-import channels is a known gap, noted and deferred.
   - **Permanent-interface exception (irreducible import coupling).** Some
     import coupling genuinely cannot be drained: ClickHouse DDL modules
     (`backend.sql`, `backend.embedding`, …) are imported by core's
     `posthog/clickhouse/schema.py` registry, `conftest.py`, and **frozen**
     ClickHouse migrations that hardcode the import path forever. You cannot
     reroute a frozen migration or move the module. For this, mark the
     tach `[[interfaces]]` block that exposes those modules with a
     `# isolation:permanent-interface` comment on the line(s) directly above
     it. The marker tells `hogli product:lint` the block is a declared,
     irreducible exposure — **not** a legacy leak — so it stops withholding
     `backend:contract-check`. Soundness is preserved by pairing it with
     turbo.json: every permanently-exposed module **must** appear in the
     contract-check `inputs` (e.g. `backend/sql.py`), so a change to it still
     re-runs the full suite. `IsolationChainCheck` enforces that pairing and
     fails if a marked module is missing from the inputs. Use this only for
     coupling that is both non-behavioral-over-HTTP and impossible to reroute
     (frozen-migration / schema-registry DDL) — not as an escape hatch for
     model/logic imports you simply haven't migrated yet. That restriction is
     structural, not stylistic: the marker is only sound when every
     frozen-pinned module contains **only DDL**. `error_tracking` is the worked
     example (`sql` / `embedding` / `indexed_embedding` are pure-DDL modules).
     `cohorts` matches too — migration 0010 pins
     `products.cohorts.backend.models.sql`, a DDL-only submodule, so the marker
     applies to exactly that submodule (not `backend.models.*`).
     `event_definitions` does **not**: migration 0120 pins
     `products.event_definitions.backend.models.property_definition`, a module
     that defines the `PropertyDefinition` model class alongside its DDL
     constant, so marking it permanent would expose model access — precisely
     the escape hatch this exception forbids. Products with that shape need the
     DDL extracted into a dedicated module first, with the frozen import path
     preserved by a re-export shim in the original module; the shim's residual
     exposure (the frozen migration still imports the model module) must be
     documented honestly in the block comment, not papered over by the marker.
   - Verify with `tach check --dependencies --interfaces`, `lint-imports`
     (import-linter contract for presentation → facade), and `hogli product:lint <name>`.
   - Use `hogli product:maturity <name>` for a detailed breakdown of remaining
     isolation work scored across models, facade, presentation, boundaries, codegen.
   - Run focused tests for changed files, then product-level backend tests.

### Legacy leaks during migration

This is the exception path for high-coupling products whose caller sweep is sliced
across teams (see PR strategy below) — the tach boundary turns on before every core
import has moved, while the `backend:contract-check` CI switch must wait until the
block is gone (`hogli product:lint` rejects the script while leaks remain). With the
single-PR default, all core callers land in the same PR and this block never needs to
exist.

If `posthog/` or `ee/` still imports product internals (`backend.models`,
`backend.oauth`, …) when the isolation chain turns on, add a second
`[[interfaces]]` block under the "Legacy leaks" section of `tach.toml`
allow-listing exactly the modules core still touches. This keeps the build
green while the remaining team-sliced PRs land. Shrink and delete that
block as imports move behind the facade — the final cleanup PR removes it entirely.
`hogli product:lint` flags any product that still has legacy leak interfaces
with a `⚠ has legacy interface leaks` warning.

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
   (`hogli product:isolate:move`), strict-lint fixes, tach interface. Add
   `backend:contract-check` + narrowed `turbo.json` here **only if the product is
   fully isolated in this PR** — no deferred view modules. If any module is deferred
   (`ignore_imports` entries remain), the skip can't turn on yet (`product:lint` blocks
   it), so it lands with the presentation-wave PR; this PR ships without the skip and
   keeps paying the full suite, which is sound.

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
    serially by capability. Add the legacy-leaks tach block (above) while slices land,
    but do NOT add `backend:contract-check` yet — `hogli product:lint` rejects that
    script while leaks remain. The final cleanup PR drops the block, `ignore_imports`
    TODOs, dead adapters, and shims, and only then enables contract-check + narrowed
    `turbo.json` inputs — the CI payoff for this path lands at the end.

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
4. Delete the module's `ignore_imports` entries — `lint-imports` must pass without
   them. That deletion is the output that marks the module done.

This is a design PR, not a sweep: it carries the same review weight as the facade
commit (the contract and function shapes are the long-lived API), so it gets its own
PR rather than riding along with mechanical work. Refactoring a wave-one function while
here (e.g. subsuming a runner builder under a run-function) is fine — its callers are
few and the parity tests pin behavior. The product's done criteria below are only fully
satisfiable once this wave has emptied the allowlist — and emptying it is what unlocks
the skip: the PR that deletes the last `ignore_imports` entry is where
`backend:contract-check` + narrowed `turbo.json` are finally added (`product:lint`
blocks them until then). For a product that deferred modules, this is when it earns the
CI skip.

## Done criteria

Treat migration as complete only when:

- Cross-product imports use `backend/facade` only.
- Facade returns/accepts contracts, not ORM.
- Presentation layer no longer encodes business logic.
- Tests cover facade and presentation boundaries.
- The product is listed in the shared `[[interfaces]]` block in `tach.toml`
  exposing `backend.facade.*` and `backend.presentation.views.*` — no legacy
  leak block remains.
- `tach check --dependencies --interfaces` passes with no violations for this product.
- `lint-imports` passes **with no `ignore_imports` entries left for this product** in the
  `pyproject.toml` TODO section — entries are tracked architectural debt from deferred
  view modules; the presentation wave deletes them.
- `hogli product:lint <name>` shows no legacy leak warning and the isolation chain is intact.
- `backend:contract-check` is present in `package.json` with `turbo.json` inputs
  narrowed to `backend/facade/**` and `backend/presentation/**` (enables the CI skip).
  This is the **last** thing added — `product:lint` blocks it until the `ignore_imports`
  entries above are gone, so the skip only ever turns on for a fully isolated product.
