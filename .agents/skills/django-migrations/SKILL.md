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

Django's `default=` is applied in Python only — Postgres ends up with `NOT NULL` and **no** column `DEFAULT`, regardless of whether you wrote `default=False`, `default=0`, `default=""`, or `default=list`/`default=dict`/`default=<callable>`. The mechanism differs slightly:

- **Callable defaults** (`default=list`, `default=dict`, `default=uuid.uuid4`) are never emitted into SQL at all.
- **Scalar defaults** (`default=False`, `default=0`, `default=""`) are emitted as `ADD COLUMN ... DEFAULT X NOT NULL` and then immediately dropped by a follow-up `ALTER COLUMN ... DROP DEFAULT` — verify with `./manage.py sqlmigrate`.

If the table is also written by a non-Django writer (plugin-server `nodejs/`, `rust/`, Temporal workers, ad-hoc scripts), raw-SQL inserts that omit the new column will fail the `NOT NULL` constraint.

Before merging, grep for external writers of the table:

```bash
rg -n "INSERT INTO <table>|insertRow\(.*'<table>'" nodejs rust products services
```

If any match, keep a Postgres-level default. Prefer `SeparateDatabaseAndState` so the `ADD COLUMN ... DEFAULT ... NOT NULL` is the only DDL applied — Django's state still sees the field normally:

```python
operations = [
    # Django auto-generates ADD COLUMN ... DEFAULT ... NOT NULL followed by
    # ALTER COLUMN ... DROP DEFAULT. We split state from SQL to keep the
    # Postgres-level default for non-Django writers (rust/, nodejs/, etc.).
    migrations.SeparateDatabaseAndState(
        state_operations=[
            migrations.AddField(
                model_name="<model>",
                name="<col>",
                field=models.BooleanField(default=False, null=False),
            ),
        ],
        database_operations=[
            migrations.RunSQL(
                sql='ALTER TABLE "<table>" ADD COLUMN "<col>" boolean DEFAULT false NOT NULL;',
                reverse_sql='ALTER TABLE "<table>" DROP COLUMN "<col>";',
            ),
        ],
    ),
]
```

For modifying the default on an existing column (no `ADD COLUMN`), use a plain `RunSQL` instead:

```python
migrations.RunSQL(
    sql="ALTER TABLE <table> ALTER COLUMN <col> SET DEFAULT '[]'::jsonb;",
    reverse_sql="ALTER TABLE <table> ALTER COLUMN <col> DROP DEFAULT;",
)
```

Always verify with `./manage.py sqlmigrate <app> <number>` that no stray `DROP DEFAULT` slipped through, and confirm `./manage.py makemigrations --dry-run` reports no state drift.
