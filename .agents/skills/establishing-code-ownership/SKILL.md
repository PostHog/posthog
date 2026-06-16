---
name: establishing-code-ownership
description: Determine which PostHog team owns a file, directory, product, or code path, or conversely enumerate all code a given team owns. Use when assigning a reviewer, attributing a bug or slow query to a team, routing work, or scoping a team-wide audit, sweep, or migration, and when answering "who owns X" or "what does team Y own". Covers the two ownership sources (`products/*/product.yaml` is the source of truth, `.github/CODEOWNERS` and `.github/CODEOWNERS-soft` are the backup), the team-slug vs `@PostHog/` handle conventions, resolving generated files back to their source product, the logical-owner vs literal-GitHub-auto-assignment distinction, verifying stale CODEOWNERS paths, and a last-resort fallback to the feature-ownership handbook when the repo files come up empty. This skill only reads ownership; it does not change ownership or edit CODEOWNERS.
---

# Establishing code ownership

Ownership in this repo lives in two places, and they don't fully overlap. Check them in this order:

1. **`products/*/product.yaml`: the source of truth for anything under `products/`.** Each product declares its owning team(s) under `owners:` as a bare slug, the team's CODEOWNERS handle minus the `@PostHog/` prefix (`conversations`, `logs`, `team-signals`, …). A product owns **all of `products/<name>/**`**. This is what the reviewer auto-assigner uses, and `product.yaml` is self-consistent: it sits inside the directory it owns, so it never goes stale.
2. **`.github/CODEOWNERS` and `.github/CODEOWNERS-soft`: the backup, for paths outside `products/`.** [`.github/CODEOWNERS`](../../../.github/CODEOWNERS) is the hard, blocking file (mostly infrastructure; rarely names product paths). [`.github/CODEOWNERS-soft`](../../../.github/CODEOWNERS-soft) is the advisory one and carries most of the real product mappings for shared code: backend (`posthog/tasks/`, `posthog/hogql/database/schema/`, `posthog/temporal/`), frontend scenes not yet moved into a product, generated artifacts, and sub-folder overrides.

The two questions below run these sources in opposite directions.

## Which team owns this file or directory? (path → team)

1. **Is the path under `products/<name>/`?** Then read `products/<name>/product.yaml` and report its `owners:`. Prefix each slug with `@PostHog/` for the handle (`team-replay` → `@PostHog/team-replay`). This beats any CODEOWNERS entry that also matches: `product.yaml` is the source of truth for product paths. A product owning a path may have **no** CODEOWNERS entry at all, and that's correct, not a gap.
2. **Otherwise, grep the CODEOWNERS files for the path.** Check `.github/CODEOWNERS-soft` first (it has the product mappings), then `.github/CODEOWNERS`. CODEOWNERS precedence is **last-match-wins**: when several patterns match a path, the one that appears latest in the file governs, so don't stop at the first grep hit; find the most specific / latest matching glob.
3. **No entry matches?** The path is owned by whatever broader rule sits above it (a parent-directory glob), or nothing in the repo resolves it. When the repo files come up empty, fall back to the feature-ownership handbook (see below). Say which source the answer came from.

### Generated and derived files

A generated file often has **no CODEOWNERS entry of its own**, so trace it back to the input it's generated from and use that input's owner. For example a generated MCP tool at `services/mcp/src/tools/generated/<x>.ts` is produced from `products/<name>/mcp/tools.yaml`, so its owner is that product's `product.yaml` owner. (CODEOWNERS-soft does pin a few generated paths explicitly, e.g. the AI-observability MCP files, but most generated paths are not pinned.)

When you trace through a generator, distinguish two senses of "owner":

- **Logical owner**: the team that owns the _source_ the artifact is generated from. This is the answer you almost always want, and the one to report.
- **Literal GitHub auto-assignment**: who CODEOWNERS would actually request on a PR touching that exact path. For an unpinned generated file this falls through to a broad parent rule (or nobody), which may not be the logical owner.

When these differ, report the logical owner and flag the discrepancy so the operator can decide whether CODEOWNERS-soft needs a pin.

## What does this team own? (team → code)

Build the full inventory; checking only one source will miss code.

1. **Grep every `products/*/product.yaml` for the team's slug.** Each hit means the team owns all of that `products/<name>/**`. One team often owns **several** products, so don't stop at the first match. A team whose code all lives under `products/` may have nothing in CODEOWNERS, and that's correct.
2. **Grep `.github/CODEOWNERS-soft` (and `.github/CODEOWNERS`) for the team's handle** (`@PostHog/team-surveys`, `@PostHog/conversations`, …) to pick up everything outside `products/`: shared backend, frontend scenes, sub-folder overrides.

**Ownership spans backend AND frontend.** A team's owned paths almost always include `frontend/src/...` as well as backend Python. If a task only matters for one side, say so up front; otherwise enumerate both, or you'll silently under-scope the inventory.

### Verify CODEOWNERS paths exist (they drift; `product.yaml` doesn't)

CODEOWNERS-soft entries go stale: a product that moved under `products/` often leaves its old paths behind. Check each CODEOWNERS-soft path on disk; for any that's gone, the code most likely relocated into a `products/<name>/` the team already owns via `product.yaml`. **Flag the stale entry to the operator** so they can fix CODEOWNERS-soft; don't silently substitute and move on. A stale path you skip is code you never accounted for.

## Last resort: the feature-ownership handbook

If neither `product.yaml` nor the CODEOWNERS files resolve ownership, consult the [feature-ownership handbook page](https://posthog.com/handbook/engineering/feature-ownership), which maps teams to the product areas they own.

Treat it as a genuine last resort, not a primary source, for two reasons. It is coarse-grained: it maps broad feature areas, not files or directories. And it can be stale: it is maintained by hand, so it lags repo moves and team reorgs. Prefer any answer the repo files give you, and when you do rely on the handbook, say so and flag that the result may be out of date.

## Slug and handle conventions

- **Handle** (CODEOWNERS): `@PostHog/<slug>`, e.g. `@PostHog/team-replay`.
- **Slug** (`product.yaml` `owners:`): the handle minus `@PostHog/`, e.g. `team-replay`.
- **The convention isn't uniform.** Some slugs carry the `team-` prefix (`team-signals`), some don't (`conversations`, `logs`). If a team name you were given doesn't resolve, try both the bare and `team-`-prefixed form (`conversations` vs `team-conversations`) before concluding there's no match.
