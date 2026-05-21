---
name: isolating-product-facade-contracts
description: Plan and execute incremental product isolation migrations to a facade plus contract layer in PostHog, following the Visual review architecture. Use when a product still exposes internals (models/logic/views) across boundaries and needs a safe, multi-PR migration toward contracts.py + facade/api.py + presentation separation.
---

# Isolating a product with facade and contracts

Use this skill to migrate an existing product to the isolated architecture used by Visual review.
Keep migrations incremental, with narrow PRs that avoid broad breakage.

**Prerequisite:** the product must already live under `products/<name>/`. This skill does not cover moving code out of `posthog/`, `ee/`, or other shared directories — do that first.

## Core docs to load first

Read these before changing code:

1. [products/architecture.md](products/architecture.md)
2. [products/README.md](products/README.md)
3. [docs/internal/monorepo-layout.md](docs/internal/monorepo-layout.md)
4. [posthog/models/team/README.md](posthog/models/team/README.md) (team extension model rule)
5. [docs/published/handbook/engineering/type-system.md](docs/published/handbook/engineering/type-system.md) (serializer/OpenAPI type flow)
6. [docs/published/handbook/engineering/ai/implementing-mcp-tools.md](docs/published/handbook/engineering/ai/implementing-mcp-tools.md) (schema quality and team isolation expectations)

Use Visual review as the concrete reference implementation:

- [products/visual_review/backend/facade/contracts.py](products/visual_review/backend/facade/contracts.py)
- [products/visual_review/backend/facade/api.py](products/visual_review/backend/facade/api.py)
- [products/visual_review/backend/presentation/views.py](products/visual_review/backend/presentation/views.py)
- [products/visual_review/backend/presentation/serializers.py](products/visual_review/backend/presentation/serializers.py)
- [products/visual_review/backend/logic.py](products/visual_review/backend/logic.py)
- [products/visual_review/backend/tests/test_api.py](products/visual_review/backend/tests/test_api.py)
- [products/visual_review/backend/tests/test_presentation.py](products/visual_review/backend/tests/test_presentation.py)

For detailed sequencing, load [references/phased-migration-plan.md](references/phased-migration-plan.md).

## Guardrails

- Keep facades thin; put business rules in `logic.py`.
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
2. Define the minimal contract surface.
   - Start from currently consumed fields only.
   - Create frozen dataclasses in `backend/facade/contracts.py` using `pydantic.dataclasses.dataclass` — same shape as the stdlib variant but with runtime type validation on construction.
3. Introduce a thin facade in `backend/facade/api.py`.
   - Map ORM instances to contracts with explicit mapper functions.
   - Keep method names capability-oriented and stable.
4. Migrate callers in small batches.
   - Replace one caller cluster at a time (single endpoint, single task, or single service area).
   - Keep compatibility shims only when needed; remove promptly.
5. Move presentation to consume the facade.
   - Serializers convert JSON <-> contracts.
   - Views call facade methods only.
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

If `posthog/` or `ee/` still imports product internals (`backend.models`,
`backend.oauth`, …) when you cut the first isolation PR, add a second
`[[interfaces]]` block under the "Legacy leaks" section of `tach.toml`
allow-listing exactly the modules core still touches. This keeps the build
green while you migrate callers in subsequent PRs. Shrink and delete that
block as imports move behind the facade — the final PR removes it entirely.
`hogli product:lint` flags any product that still has legacy leak interfaces
with a `⚠ has legacy interface leaks` warning.

## PR slicing strategy

Default to several PRs instead of one big migration:

- PR 1: Add contracts + facade methods without changing external callers.
- PR 2-N: Migrate caller clusters one-by-one to the facade.
- Final PR: Remove deprecated internal import paths, tighten tach boundaries, and clean dead adapters.

If a product has many endpoints, migrate in this order:

1. Read-only list/detail APIs (lowest risk)
2. Internal service-to-service call sites
3. Write paths (create/update/delete)
4. Background tasks / async entrypoints
5. Remaining edge endpoints and cleanup

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
- `lint-imports` passes (import-linter verifies presentation doesn't bypass the facade internally).
- `hogli product:lint <name>` shows no legacy leak warning and the isolation chain is intact.
- `backend:contract-check` is present in `package.json` with `turbo.json` inputs
  narrowed to `backend/facade/**` and `backend/presentation/**` (enables isolated testing in CI).
