# Common

Shared libraries, tools, and utilities that predate a better home.

> [!WARNING]
> **`common/` is a holding pen, not a destination — the goal is to shrink it, not grow it.**
> A catch-all "common" reliably rots into a junk drawer: unscoped, unenforced, imported by everything — a second monolith with worse boundaries than the first. The name itself is the smell; context-named homes are the cure. Unlike `products/*` (tach + turbo), nothing mechanically guards what lands here, so this disclaimer is the only thing keeping it honest.

New code should go somewhere with a real boundary first — `products/<name>/`, `tools/`, `services/`, or `packages/` (a clean, published-style leaf like `packages/quill`). Land code in `common/` only when none of those fit _and_ it can't yet be a clean leaf because it still imports app modules (`lib/*`, `scenes/*`). When it can stand alone, graduate it out to `packages/` or the owning product and delete it from here. See [AGENTS.md](AGENTS.md) for the agent-facing version.

- Internal RFC: https://github.com/PostHog/product-internal/pull/703
- Keep folder names `under_score` cased — dashes break Python imports
