---
name: django-migrations
description: Django migration patterns and safety workflow for PostHog. Use when creating, adjusting, or reviewing Django/Postgres migrations, including non-blocking index/constraint changes, multi-phase schema changes, data backfills, migration conflict rebasing, and product model moves that require SeparateDatabaseAndState.
---

# Django migrations

Read these files first, before writing or editing a migration:

- `docs/published/handbook/engineering/developing-locally.md` (`## Django migrations`, `### Non-blocking migrations`, `### Resolving merge conflicts`)
- `docs/published/handbook/engineering/safe-django-migrations.md`
- `docs/published/handbook/engineering/databases/schema-changes.md`
- `products/README.md` (`## Adding or moving backend models and migrations`) when working in `products/*`

If the task is a ClickHouse migration, use `clickhouse-migrations` instead.

## Workflow

1. Classify the change before generating code.
   - Additive and low-risk: new nullable column, new table, simple state-only changes.
   - Risky: drop/rename table or column, `NOT NULL`, indexes, constraints, large data updates, model moves between apps.
2. Generate or update migration files.
   - Create baseline: `DEBUG=1 ./manage.py makemigrations [app_label]`.
   - For merge conflicts in migration numbering, run `python manage.py rebase_migration <app> && git add <app>/migrations` (`posthog` or `ee` in this repo).
3. Apply safety rules from the docs.
   - Prefer multi-phase rollouts for destructive changes: remove references first, drop later.
   - Avoid rename operations; prefer keeping DB names stable (for fields, use `db_column`).
   - Use `migrations.SeparateDatabaseAndState` when Django state must diverge from immediate DB operations.
   - For concurrent index/constraint operations, use patterns that require `atomic = False`.
   - Keep risky operations isolated; split into multiple migrations when needed.
   - Make raw SQL idempotent with `IF EXISTS` / `IF NOT EXISTS` where applicable.
4. Handle product model moves safely.
   - Follow `products/README.md` pattern when moving models from `posthog/models` to `products/*`.
   - Preserve `db_table`.
   - Use `SeparateDatabaseAndState` in both migrations so no accidental `DROP TABLE`/`CREATE TABLE` data loss occurs.
5. Validate before finishing.
   - Check generated SQL with `./manage.py sqlmigrate <app> <migration_number>`.
   - Run relevant tests for changed apps.
   - Ensure the migration sequence is linear and review-ready.

## Output expectations

When completing a migration task:

- Explain migration risk level and chosen strategy.
- List phases explicitly when using multi-phase rollout.
- Call out operational concerns (locks, runtime, rollback path).
- Note follow-up migrations required for deferred drops or validations.
