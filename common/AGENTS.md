# common/ — read before adding code here

`common/` is a **transitional holding pen, not a destination.** It holds shared code that predates a better home. Do not treat it as the default place for new shared code.

## Disclaimer

The name is the smell. A catch-all `common/` reliably rots into a junk drawer — unscoped, unenforced, imported by everything — i.e. a second monolith with worse boundaries than the first. Unlike `products/*` (guarded by tach + turbo), **nothing mechanically guards what lands here**, so the only thing keeping it honest is this file. The goal for `common/` is to **shrink, not grow.**

## Before adding anything here

Pick a home with a real boundary first, in this order:

- `products/<name>/` — owned by one product
- `tools/` — dev/CI tooling, not shipped at runtime
- `services/` — independently deployed
- `packages/` — a clean, published-style leaf with **no back-edges into app code** (see `packages/quill`)

Fall back to `common/` **only** when none of those fit _and_ the code can't yet be a clean leaf because it still imports app modules (`lib/*`, `scenes/*`, etc.). If you do, treat it as tracked debt: say so in the PR and name the intended graduation target. "It follows an existing `common/` precedent" is not, on its own, a reason to add more.

## Graduating out

When something here becomes a clean leaf (no back-edges into app code), promote it to `packages/` or into the owning product, and delete it from `common/`. That is the success path — `quill` took it.

## Conventions

- Keep folder names `under_score` cased — dashes break Python imports.
- Human-facing overview: [README.md](README.md). Repo-wide layout: [monorepo layout](../docs/internal/monorepo-layout.md).
