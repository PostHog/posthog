---
name: preflighting-pushes
description: >
  Runs CI-matching validation locally before pushing a PostHog branch so the first
  push is green — regenerates generated artifacts (OpenAPI types, query and MCP
  snapshots), lints, formats, typechecks, and checks Django/ClickHouse migration
  numbering against master. Use before pushing, before opening a PR, after rebasing
  or restacking a branch, or when asked to "make sure CI passes" before push.
---

# Preflighting pushes

Follow-up commits that only regenerate artifacts or appease linters are among the most common commits pushed after a PR opens, and each one costs a full CI round trip.
Run exactly what the diff needs locally, then push once.

## Step 1 — scope the diff

```bash
git fetch origin master
git diff --name-only origin/master...HEAD
```

Everything below is conditional on what appears in that list; skip sections whose trigger paths aren't touched.

## Step 2 — regenerate what CI will validate

| Touched                                                            | Run                                                                        | Why                                                                                                                                                                         |
| ------------------------------------------------------------------ | -------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Any DRF serializer/viewset (`posthog/api/`, `products/*/backend/`) | `hogli build:openapi`                                                      | the "Validate OpenAPI types" check fails on drift; regenerated files under `frontend/src/generated/` and `products/*/frontend/generated/` must be committed with the change |
| HogQL / query runners / ClickHouse SQL                             | rerun the touched backend tests with snapshot update (`--snapshot-update`) | query snapshots drift with any SQL change                                                                                                                                   |
| MCP `tools.yaml`, tool schemas, or MCP-exposed serializers         | rerun the MCP unit tests with snapshot update                              | tool-schema snapshots drift with any schema change                                                                                                                          |

Commit regenerated artifacts in the same commit as the source change — never as a follow-up.

**Stacked branches:** regenerate only on the layer about to merge; regen commits on upper layers are invalidated by every restack.

## Step 3 — lint, format, typecheck

- Python touched: `ruff check . --fix && ruff format .`; verify new and changed functions carry full type annotations — mypy runs only in CI, so a missing annotation is a deferred CI failure.
- Frontend touched: `pnpm --filter=@posthog/frontend format` and `pnpm --filter=@posthog/frontend typescript:check`.
- Rust touched: `cargo fmt` and `cargo clippy` in the touched crate; proto files have their own lint job.

## Step 4 — migration numbering check

Long-lived branches race master's migration counter; a numbering collision blocks review.
For each app with a new migration in the diff:

```bash
git ls-tree origin/master --name-only <app>/migrations/ | sort | tail -3
ls <app>/migrations/ | sort | tail -3
```

If master reached or passed your number, renumber before pushing — see the `django-migrations` skill for the safe rebase procedure.
Apply the same check to ClickHouse migrations under `posthog/clickhouse/migrations/`.

## Step 5 — targeted tests, then one push

Run the tests nearest the change (`hogli test <file_or_dir>` or `hogli test --changed`), then push a single time with everything included.
If the PR is headed for auto-approval, a clean push also avoids dismissing an existing stamphog approval with a non-trivial delta — see `getting-prs-approved`.
