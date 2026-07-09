---
name: establishing-code-ownership
description: Determine which PostHog team owns a file, directory, or code path, or enumerate all code a team owns (via `products/*/product.yaml` and `.github/CODEOWNERS(-soft)?`). Use when assigning a reviewer, attributing a bug or slow query to a team, routing work, scoping a team-wide audit, or answering "who owns X" / "what does team Y own".
---

# Establishing code ownership

Two sources, checked in order:

1. **`products/*/product.yaml`: source of truth under `products/`.** Lists owning team(s) under `owners:` as bare slugs (the CODEOWNERS handle minus `@PostHog/`: `conversations`, `logs`, `team-self-driving`, …) and owns **all** of `products/<name>/**`. Lives in the dir it owns, so never stale.
2. **`.github/CODEOWNERS` + [`CODEOWNERS-soft`](../../../.github/CODEOWNERS-soft): backup for paths outside `products/`.** [`CODEOWNERS`](../../../.github/CODEOWNERS) is hard/blocking (mostly infra); `CODEOWNERS-soft` carries most product mappings for shared code (backend, frontend scenes, generated artifacts, overrides).

## Fast path: `ownership.js`

[`ownership.js`](ownership.js) automates the deterministic repo-file resolution for both lookups. It finds the repo root from its own location (cwd- and worktree-independent) and enumerates tracked files via `git ls-files`. Run it first, then fall back to the manual reasoning below for what it can't resolve.

```bash
S=.agents/skills/establishing-code-ownership/ownership.js
node $S file posthog/hogql/printer.py   # who owns this file (pass --all to see every matching CODEOWNERS rule)
node $S team team-surveys               # every tracked file the team owns (slug or @PostHog/ handle both work)
node $S unowned                          # every tracked file with no owner (append path prefixes to scope, e.g. `unowned products/ frontend/`)
```

For glob matching it uses the vendored, GitHub-faithful matcher [`.github/scripts/codeowners.js`](../../../.github/scripts/codeowners.js) (a zero-dependency JS port of [hmarr/codeowners](https://github.com/hmarr/codeowners)), the same matcher the reviewer auto-assigner runs in CI, so answers track what CI assigns rather than a separate reimplementation. That matcher reproduces GitHub's own CODEOWNERS rules: a slash-free pattern matches at any depth, a trailing slash matches a directory and its contents, and `dir/*` matches only direct children. So a `CODEOWNERS-soft` entry the script shows as unowned is genuinely dead — both CI and GitHub skip it too, not a quirk of a stricter local matcher.

Precedence: `product.yaml` for `products/<name>/**`; else a blocking `CODEOWNERS` owner; else the last-matching `CODEOWNERS-soft` rule. A blocking `CODEOWNERS` glob with **no owner** (a reset, e.g. `posthog/hogql/database/schema/**`) only clears the blocking owner, it does not erase a soft mapping. `file` prints the source line behind each answer.

It does **not** trace generated files to their source's owner, consult the handbook, or search Slack. When it returns no owner (or the path is a generated file), keep going with the steps below.

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

## Even-last-er resort: ask Slack

If even the handbook fails and the Slack MCP is available, search Slack. It's the least authoritative source (opinions, stale threads), so verify against the repo files and flag the answer as Slack-sourced.

## Slug vs handle

- **Handle** (CODEOWNERS): `@PostHog/<slug>`, e.g. `@PostHog/team-replay`.
- **Slug** (`product.yaml`): handle minus `@PostHog/`, e.g. `team-replay`.
- **Not uniform**: some carry `team-` (`team-self-driving`), some don't (`conversations`, `logs`). If a name doesn't resolve, try both forms.
