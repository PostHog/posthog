---
name: establishing-code-ownership
description: Determine which PostHog team owns a file, directory, or code path, or enumerate all code a team owns (via `products/*/product.yaml` and `.github/CODEOWNERS`). Use when assigning a reviewer, attributing a bug or slow query to a team, routing work, scoping a team-wide audit, or answering "who owns X" / "what does team Y own".
---

# Establishing code ownership

Two sources, checked in order:

1. **`products/*/product.yaml`: source of truth under `products/`.** Lists owning team(s) under `owners:` as bare slugs (the CODEOWNERS handle minus `@PostHog/`: `conversations`, `logs`, `team-signals`, …) and owns **all** of `products/<name>/**`. Lives in the dir it owns, so never stale.
2. **`.github/CODEOWNERS` + [`CODEOWNERS-soft`](../../../.github/CODEOWNERS-soft): backup for paths outside `products/`.** [`CODEOWNERS`](../../../.github/CODEOWNERS) is hard/blocking (mostly infra); `CODEOWNERS-soft` carries most product mappings for shared code (backend, frontend scenes, generated artifacts, overrides).

## path → team (who owns this file?)

1. **Under `products/<name>/`?** Read that `product.yaml` `owners:`; prefix each slug with `@PostHog/` (`team-replay` → `@PostHog/team-replay`). This beats any matching CODEOWNERS entry. No CODEOWNERS entry for a product path is fine, not a gap.
2. **Else grep the CODEOWNERS files** (`CODEOWNERS-soft` first, then `CODEOWNERS`). Precedence is **last-match-wins**, so take the latest/most-specific matching glob, not the first hit.
3. **No match?** It's covered by a broader parent glob, or unresolved; fall back to the handbook (below). State which source the answer came from.

**Generated files** often have no CODEOWNERS entry; trace to the input they're generated from and use that owner (e.g. `services/mcp/src/tools/generated/<x>.ts` comes from `products/<name>/mcp/tools.yaml`). Distinguish:

- **Logical owner**: the team owning the _source_, the answer to report.
- **Literal GitHub auto-assignment**: who CODEOWNERS requests on that exact path; for an unpinned generated file, a broad parent rule or nobody.

When they differ, report the logical owner and flag the gap so the operator can decide whether to pin it in `CODEOWNERS-soft`.

## team → code (what does this team own?)

Check both sources or you'll miss code:

1. **Grep every `products/*/product.yaml` for the slug**; each hit is all of that `products/<name>/**`. One team often owns several, so don't stop at the first.
2. **Grep `CODEOWNERS-soft` (and `CODEOWNERS`) for the handle** (`@PostHog/team-surveys`, …) for everything outside `products/`.

**Owned paths span backend AND `frontend/src/...`.** Cover both, or say up front you're doing one side.

**Verify CODEOWNERS-soft paths on disk.** They drift (a moved product leaves old paths behind); `product.yaml` doesn't. For any missing path, the code likely relocated into a `products/<name>/` the team already owns; flag the stale entry to the operator rather than silently substituting.

## Last resort: feature-ownership handbook

If neither `product.yaml` nor CODEOWNERS resolves it, consult the [feature-ownership handbook](https://posthog.com/handbook/engineering/feature-ownership) (teams to product areas). It's a genuine last resort: coarse-grained (broad areas, not files) and hand-maintained (lags repo moves and reorgs). Prefer the repo files, and flag any handbook-sourced answer as possibly stale.

## Slug vs handle

- **Handle** (CODEOWNERS): `@PostHog/<slug>`, e.g. `@PostHog/team-replay`.
- **Slug** (`product.yaml`): handle minus `@PostHog/`, e.g. `team-replay`.
- **Not uniform**: some carry `team-` (`team-signals`), some don't (`conversations`, `logs`). If a name doesn't resolve, try both forms.
