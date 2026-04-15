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

## Required migration workflow

1. Build an import map for the target product.
   - Find cross-product imports into target internals (`models`, `logic`, `presentation`, non-facade modules).
   - Classify each usage by capability (read/list, detail/read, create/update/delete, async/task, webhook/event).
2. Define the minimal contract surface.
   - Start from currently consumed fields only.
   - Create frozen dataclasses in `backend/facade/contracts.py`.
3. Introduce a thin facade in `backend/facade/api.py`.
   - Map ORM instances to contracts with explicit mapper functions.
   - Keep method names capability-oriented and stable.
4. Migrate callers in small batches.
   - Replace one caller cluster at a time (single endpoint, single task, or single service area).
   - Keep compatibility shims only when needed; remove promptly.
5. Move presentation to consume the facade.
   - Serializers convert JSON <-> contracts.
   - Views call facade methods only.
6. Enforce boundaries and verify.
   - Add a global `[[interfaces]]` block in `tach.toml` with `expose` patterns for the facade and presentation views.
   - Add `backend:contract-check` to `package.json` so turbo-discover treats the product as isolated.
   - Run `tach check --interfaces` to verify no external imports bypass the facade.
   - Run `hogli product:lint <name>` to verify the product passes all checks.
   - Run focused tests for changed files, then product-level backend tests.

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
- A global `[[interfaces]]` block in `tach.toml` restricts imports to facade + presentation views.
- `tach check --interfaces` passes with no violations for this product.
- `hogli product:lint <name>` shows no legacy leak warning.
- `backend:contract-check` is present in `package.json` (enables isolated testing in CI).
