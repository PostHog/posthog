# Phased migration plan for product isolation

This reference provides a practical execution sequence for converting an existing product
into the facade+contracts pattern used by Visual review.

## Phase 0 — Baseline and scoping

**Prerequisite:** the product must already live under `products/<name>/`. This workflow does not cover moving code out of `posthog/`, `ee/`, or other shared directories — that is a separate step. If the product still lives in legacy/common code, stop here and do the move first.

- Read architecture docs:
  - [products/architecture.md](products/architecture.md)
  - [products/README.md](products/README.md)
  - [docs/internal/monorepo-layout.md](docs/internal/monorepo-layout.md)
- Run `hogli product:lint <name>` — the isolation progress section shows exactly which layers exist,
  what's structurally wrong with each, and what to do next. Use this as the starting point before
  reading code.
- Locate the product's current code under `products/<name>/backend/` and identify what's already there vs. what's still missing (models, logic, presentation, facade).
- Inventory existing tests and gaps in `backend/tests/`.

Suggested commands:

```bash
rg -n "from products\.<target>\.backend\.(models|logic|presentation|tasks|storage)" .
rg -n "products\.<target>\.backend\.facade" .
```

## Phase 1 — Create contract skeleton

Start with read paths before write paths.

1. Add `backend/facade/contracts.py` with frozen dataclasses for existing read responses.
2. Add `backend/facade/__init__.py` exports to make imports straightforward.
3. Add minimal domain enums either in `contracts.py` or `facade/enums.py` if they grow.

Reference patterns:

- [products/visual_review/backend/facade/contracts.py](products/visual_review/backend/facade/contracts.py)
- [products/architecture.md](products/architecture.md)

## Phase 2 — Add thin facade API

1. Add `backend/facade/api.py` with thin methods wrapping logic.
2. Implement `_to_contract` mapper functions close to facade methods.
3. Keep method signatures capability-based (`list_*`, `get_*`, `create_*`, etc.).

Reference patterns:

- [products/visual_review/backend/facade/api.py](products/visual_review/backend/facade/api.py)
- [products/architecture.md](products/architecture.md)

## Phase 3 — Migrate low-risk consumers first

Start with call sites that are easiest to verify:

1. Read-only DRF endpoints.
2. Internal helper modules that only read.
3. Any explicit cross-product imports into `models` or `logic`.

For DRF endpoints:

- Ensure schema annotations are present (`@validated_request` or `@extend_schema`).
- Keep serializers as JSON adapters between API payloads and contract dataclasses.

Docs:

- [docs/published/handbook/engineering/type-system.md](docs/published/handbook/engineering/type-system.md)
- [products/visual_review/backend/presentation/views.py](products/visual_review/backend/presentation/views.py)
- [products/visual_review/backend/presentation/serializers.py](products/visual_review/backend/presentation/serializers.py)

## Phase 4 — Migrate writes and background flows

1. Migrate create/update/delete endpoints to call facade methods.
2. Migrate Celery or async entrypoints to call facade methods, not internals.
3. Keep transaction boundaries in facade where needed.

Reference patterns:

- [products/visual_review/backend/tasks/tasks.py](products/visual_review/backend/tasks/tasks.py)
- [products/architecture.md](products/architecture.md)

## Phase 5 — Tighten boundaries and clean up

1. Remove direct callers of internal modules where facade replacements exist.
2. Add a global `[[interfaces]]` block in `tach.toml` with `expose` patterns for facade and presentation views. Add `backend:contract-check` to `package.json`. Run `tach check --interfaces` and `hogli product:lint` to verify.
3. Remove obsolete adapters and dead helper functions.

Then verify:

- Product tests pass.
- API schema generation remains healthy after serializer/view changes.
- No cross-product internal imports remain.

## Recommended PR plan

Use this template to avoid long, risky PRs:

- PR A: Add contracts + read-only facade + unit tests for facade mapping.
- PR B: Move read-only presentation endpoints to facade.
- PR C: Move write endpoints to facade.
- PR D: Move tasks/background integrations.
- PR E: Boundary enforcement and cleanup (`tach.toml`, dead code removal).

When possible, keep each PR deployable and backward compatible.

## Security and isolation checklist

- All querysets scoped by team.
- No product-specific fields added to `Team`.
- Contracts avoid Django/DRF imports.
- No cross-product ORM imports.
- View endpoints declare schemas for request/response.

Additional references:

- [posthog/models/team/README.md](posthog/models/team/README.md)
- [.agents/security.md](.agents/security.md)
- [docs/published/handbook/engineering/ai/implementing-mcp-tools.md](docs/published/handbook/engineering/ai/implementing-mcp-tools.md)
