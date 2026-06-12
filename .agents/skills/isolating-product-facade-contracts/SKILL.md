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

1. [products/architecture.md](products/architecture.md)
2. [products/README.md](products/README.md)
3. [docs/internal/monorepo-layout.md](docs/internal/monorepo-layout.md)
4. [posthog/models/team/README.md](posthog/models/team/README.md) (team extension model rule)
5. [docs/published/handbook/engineering/type-system.md](docs/published/handbook/engineering/type-system.md) (serializer/OpenAPI type flow)
6. [docs/published/handbook/engineering/ai/implementing-mcp-tools.md](docs/published/handbook/engineering/ai/implementing-mcp-tools.md) (schema quality and team isolation expectations)
7. [.agents/security.md](.agents/security.md) (SQL/HogQL security guidelines)

Use Visual review as the concrete reference implementation:

- [products/visual_review/backend/facade/contracts.py](products/visual_review/backend/facade/contracts.py)
- [products/visual_review/backend/facade/api.py](products/visual_review/backend/facade/api.py)
- [products/visual_review/backend/presentation/views.py](products/visual_review/backend/presentation/views.py)
- [products/visual_review/backend/presentation/serializers.py](products/visual_review/backend/presentation/serializers.py)
- [products/visual_review/backend/logic.py](products/visual_review/backend/logic.py)
- [products/visual_review/backend/tests/test_api.py](products/visual_review/backend/tests/test_api.py)
- [products/visual_review/backend/tests/test_presentation.py](products/visual_review/backend/tests/test_presentation.py)

Before changing code, get the baseline:

```bash
hogli product:maturity <name>    # scores models, facade, presentation, boundaries, codegen
hogli product:lint <name>        # structural lint + isolation chain (strict if facade/contracts.py exists)
rg -n "from products\.<name>\.backend\.(models|logic|presentation|tasks|storage)" .
rg -o --pcre2 "(from|import) products\.<name>\.backend\.(?!facade)" posthog ee | wc -l   # core-coupling count (internals only)
```

The `rg` output is your import map: every line is a caller that needs to migrate to the facade.
Also search for the bare module paths, not just import statements — string references
(`@patch("products.<name>.backend...")` mock paths, dotted names in config) move with the code too.
The core-coupling count picks the PR strategy below: near zero means the whole migration fits
the single-PR default; triple digits means the caller sweep needs slicing by owning team.

`product:lint` switches from lenient to strict the moment `facade/contracts.py` exists, so check
the strict structural requirements up front instead of discovering them mid-migration: root
`tsconfig.json`, `tasks.py` at `tasks/tasks.py` (pin the celery task `name=` to its pre-move path
so queued messages stay routable), and only canonical `backend/` subdirectories (`_KNOWN_DIRS` in
`tools/hogli-commands/.../product/checks.py` — e.g. `templates/` is recognized, `prompts/` is not).

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
     schedule constants, query-runner registry hooks) crosses the boundary as objects, not
     data — give each its own facade submodule (`facade/tasks.py`, `facade/temporal.py`,
     `facade/queries.py`) re-exporting exactly what core touches. Registry-style consumers
     dispatch on class identity (`isinstance`), so re-export the class itself. Keep
     `facade/api.py` free of heavy imports (HogQL, temporalio) so config-only consumers
     don't drag them onto the `django.setup()` path.
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
   - Thin views (CRUD over models): swap them onto the facade in the same PR — no
     `ignore_imports` allowlist entry should ever exist for them.
   - Thick views (query orchestration, execution modes, export hooks): moving them under
     `presentation/` without the refactor requires exact-pair `ignore_imports` entries in
     `pyproject.toml`'s TODO section. That defers the refactor to a follow-up
     presentation-wave PR — and until the product's entries are gone, the narrowed
     contract inputs are **optimistic, not sound**: an internal change can alter the HTTP
     surface without re-running the full suite. Compensating controls exist (the OpenAPI
     validation job runs on every backend PR, the product's own tests cover its views,
     master pushes run everything), but make the deferral a named decision in the PR.
   - When moving modules, rewrite string references too (`@patch(...)` paths) — and use a
     rewrite tool with real word boundaries (perl; BSD sed's `\b` silently no-ops).
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
      turbo-discover treats the product as isolated.
   4. **Narrowed `turbo.json` inputs** — restrict `backend:contract-check`
      inputs to `backend/facade/**` and `backend/presentation/**` so the
      Django suite is only re-run on facade/presentation changes (see
      `products/visual_review/turbo.json`).
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
3. **Commit — structure + chain.** Presentation move, strict-lint fixes, tach
   interface, `backend:contract-check`, narrowed `turbo.json`.

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

**Thick-views deferral (step 5) adds one optional follow-up on either path:** a
presentation-wave PR that designs the facade functions the views need, swaps the views
onto them, and deletes the product's `ignore_imports` entries — the step that turns the
narrowed contract inputs from optimistic into sound.

Trade-off to accept: one PR reverts coarser than several. That is fine because the
mappers are behavior-preserving, the behavior-bearing edits are enumerated up front,
and the whole PR is regenerable — weeks of serial PRs on a hot product cost more in
conflicts and forfeited isolated-CI time than an occasional coarse revert.

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
  `pyproject.toml` TODO section — the contract passes by allowlist until then, and narrowed
  contract inputs stay optimistic rather than sound while entries remain.
- `hogli product:lint <name>` shows no legacy leak warning and the isolation chain is intact.
- `backend:contract-check` is present in `package.json` with `turbo.json` inputs
  narrowed to `backend/facade/**` and `backend/presentation/**` (enables isolated testing in CI).
