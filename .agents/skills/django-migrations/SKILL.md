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

1. **Classify** the change as additive (new nullable column, new table) or risky (drop/rename, `NOT NULL`, indexes, constraints, large data updates, model moves). See also the [cross-language `NOT NULL` hazard](#cross-language-not-null-hazard) below.
2. **Generate**: `DEBUG=1 ./manage.py makemigrations [app_label]`.
   For merge conflicts: `python manage.py rebase_migration <app> && git add <app>/migrations` (`posthog` or `ee`).
3. **Apply safety rules** from `safe-django-migrations.md` — the doc covers multi-phase rollouts, `SeparateDatabaseAndState`, concurrent operations, idempotency, and all risky patterns in detail.
4. **Validate**: `./manage.py sqlmigrate <app> <migration_number>`, run tests, confirm linear migration sequence.

## Cross-language `NOT NULL` hazard

Django's `default=list`/`default=dict`/`default=<callable>` is applied in Python only — Postgres sees the column as `NOT NULL` with no column `DEFAULT`. If the table is also written by a non-Django writer (plugin-server `nodejs/`, `rust/`, Temporal workers, ad-hoc scripts), raw-SQL inserts that omit the new column will fail the `NOT NULL` constraint.

Before merging, grep for external writers of the table:

```bash
rg -n "INSERT INTO <table>|insertRow\(.*'<table>'" nodejs rust products services
```

If any match, either update those writers to set the column, or set a Postgres-level default in the same migration:

```python
migrations.RunSQL(
    sql="ALTER TABLE <table> ALTER COLUMN <col> SET DEFAULT '[]'::jsonb;",
    reverse_sql="ALTER TABLE <table> ALTER COLUMN <col> DROP DEFAULT;",
)
```
