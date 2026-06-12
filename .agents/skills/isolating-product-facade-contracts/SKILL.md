---
name: isolating-product-facade-contracts
description: Plan and execute product isolation migrations to a facade plus contract layer in PostHog, following the Visual review architecture. Use when a product still exposes internals (models/logic/views) across boundaries and needs migration toward contracts.py + facade/api.py + presentation separation, with a PR strategy that minimizes review latency and conflicts with parallel work.
---

# Isolating a product with facade and contracts

Use this skill to migrate an existing product to the isolated architecture used by Visual review.
Optimize for short calendar exposure, not small diffs: authoring is cheap and the verification
chain catches mechanical breakage, while human review latency and a fast-moving master are the
real bottlenecks. Default to two PRs — design, then mechanical sweep — per the PR strategy below.

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
rg -o "(from|import) products\.<name>" posthog ee | wc -l   # core-coupling count
```

The `rg` output is your import map: every line is a caller that needs to migrate to the facade.
The core-coupling count picks the PR strategy below: near zero means the whole migration fits
the two-PR default; triple digits means the caller sweep needs slicing by owning team.

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
2. Define the minimal contract surface.
   - Start from currently consumed fields only.
   - Create frozen dataclasses in `backend/facade/contracts.py` using `pydantic.dataclasses.dataclass` — same shape as the stdlib variant but with runtime type validation on construction.
3. Introduce a thin facade in `backend/facade/api.py`.
   - Map ORM instances to contracts with explicit mapper functions.
   - Keep method names capability-oriented and stable.
4. Migrate callers in one pass by default.
   - The rewrite is mechanical (import swap + call mapping) and fully checked by the
     verification chain; batching it only stretches the window in which master drifts
     under the branch.
   - Compatibility shims exist to bridge between serial PRs — the one-pass shape rarely
     needs them. If one is unavoidable, it dies in the final cleanup PR, not "later".
   - Exception: callers with subtle behavior (transaction boundaries, write-path
     semantics) may move in their own small PR — see the PR strategy below.
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

This is the exception path for high-coupling products whose caller sweep is sliced
across teams (see PR strategy below) — isolation turns on before every core import
has moved. With the two-PR default, all core callers land in the sweep PR and this
block never needs to exist.

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
Every day a migration branch stays open, parallel work lands in the same files; serial
PR chains multiply that exposure because each PR waits in review while the next can't
be authored stably until it merges. Slice to minimize how long branches stay open, and
let the verification chain carry the mechanical review burden.

Default to exactly two PRs:

- **PR 1 — design (where human review matters).** Contracts + facade methods +
  behavioral-parity tests for the facade, with no caller changes. New files only, so it
  cannot conflict with parallel work. The contract surface is the long-lived API —
  spend review attention on naming, capability shape, and field selection, not
  mechanics. For a small product this PR can also flip `api.py`/`webhooks.py` into
  `presentation/` and enable the 4-step chain (see `user_interviews` PR #59132 for
  that combined shape).
- **PR 2 — mechanical sweep (where verification carries it).** All caller migrations,
  the presentation flip, and the 4-step chain. Reviewers sample rather than read
  line-by-line; the parity tests from PR 1 plus tach, import-linter, contract-check,
  and the product tests are the safety net.

Treat PR 2 as regenerable, not rebasable: the import map plus the merged facade fully
determine the rewrite, so on conflict, regenerate the branch against fresh master
instead of hand-resolving. Keep it open only for the review window.

Gate by the core-coupling count from the baseline, not by product size:

- **Low (zero to low double digits):** the two-PR default applies; skip the
  legacy-leaks machinery entirely.
- **High (triple digits):** PR 2 won't review as one unit. Slice the sweep by who owns
  the calling code (the consuming team/area, not the product's own owner) so each team
  reviews its own call sites in parallel — never serially by capability, which trades
  calendar time for an authoring risk that no longer exists. Turn the isolation chain on behind a
  legacy-leaks block (above) and add a final cleanup PR that drops the block,
  `ignore_imports` TODOs, dead adapters, and shims.

Within the sweep, use risk to direct review attention, not PR boundaries: write paths
and transaction boundaries get the close read; read-only list/detail swaps, internal
call sites, and task entrypoints get the sample. If a write path is genuinely subtle,
pull those few callers into their own small PR as the exception.

Trade-off to accept: one sweep PR reverts coarser than many small ones. That is fine
precisely because PR 1 isolated the design risk and the mappers are behavior-preserving —
per-file reverts stay possible, and weeks of serial PRs on a hot product cost more in
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
- `lint-imports` passes (import-linter verifies presentation doesn't bypass the facade internally).
- `hogli product:lint <name>` shows no legacy leak warning and the isolation chain is intact.
- `backend:contract-check` is present in `package.json` with `turbo.json` inputs
  narrowed to `backend/facade/**` and `backend/presentation/**` (enables isolated testing in CI).
