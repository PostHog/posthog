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

1. **Classify** the change as additive (new nullable column, new table) or risky (drop/rename, `NOT NULL`, indexes, constraints, large data updates, model moves). A change is also risky if it touches a [hot table](#hot-table-hazard), regardless of how additive it looks. See also the [cross-language `NOT NULL` hazard](#cross-language-not-null-hazard) below.
2. **Generate**: `DEBUG=1 ./manage.py makemigrations [app_label]`.
   For merge conflicts: `python manage.py rebase_migration <app> && git add <app>/migrations` (`posthog` or `ee`).
3. **Apply safety rules** from `safe-django-migrations.md` — the doc covers multi-phase rollouts, `SeparateDatabaseAndState`, concurrent operations, idempotency, and all risky patterns in detail.
4. **Validate**: `./manage.py sqlmigrate <app> <migration_number>`, run tests, confirm linear migration sequence.

## Hot table hazard

`posthog_team`, `posthog_user`, `posthog_organization`, and `posthog_project` are read on virtually every request. Any `ALTER TABLE` on them — including a plain nullable `AddField`, which is "safe" everywhere else — needs an `ACCESS EXCLUSIVE` lock, and while that lock request waits behind in-flight queries, every later query on the table queues behind it. Even a metadata-only `ADD COLUMN` can stall site-wide traffic in waves (one per `bin/migrate` retry) until the ALTER wins the lock race. This has caused production 5xx incidents.

Before writing a migration that touches one of these models:

- For `Team`: put domain-specific fields on a Team extension model instead — `posthog/models/team/README.md`. That's a `CREATE TABLE`, no lock on `posthog_team`.
- `CREATE INDEX CONCURRENTLY` (via `CreateIndexConcurrently`) is fine — `SHARE UPDATE EXCLUSIVE` doesn't block reads or writes.
- If the field genuinely belongs on the hot table (core identity, cross-product settings, SDK config), the `HotTableAlterPolicy` analyzer blocks the migration in CI until `<app_label>.<migration_name>` is added to `posthog/management/migration_analysis/hot_table_acknowledged_migrations.txt`. That acknowledgment also means coordinating the deploy with infra for a low-traffic window.

## Cross-language `NOT NULL` hazard

`posthog_user`, `posthog_team`, and other core tables in the main Postgres database are written by Django **and** by `nodejs/` (plugin-server tests via `insertRow`), `rust/` services, and Temporal workers. Those non-Django writers issue raw `INSERT`s that only list the columns they care about, so any new `NOT NULL` column without a Postgres-level `DEFAULT` will break them with `null value in column "<col>" violates not-null constraint`.

Django's `default=` alone does **not** create a Postgres-level default — by design, Django treats it as a Python-only attribute applied at `Model.__init__`:

- **Callable defaults** (`default=list`, `default=dict`, `default=uuid.uuid4`) are never emitted into SQL at all.
- **Scalar defaults** (`default=False`, `default=0`, `default=""`) are emitted as `ADD COLUMN ... DEFAULT X NOT NULL` and then immediately dropped by a follow-up `ALTER COLUMN ... DROP DEFAULT` — verify with `./manage.py sqlmigrate`.

Before merging, grep for external writers of the table:

```bash
rg -n "INSERT INTO <table>|insertRow\(.*'<table>'" nodejs rust products services
```

If any match, add **both** `default=` and `db_default=` to the model field. `db_default=` lands a real Postgres `DEFAULT`; `default=` keeps the Python-side value for ORM creates:

```python
class User(models.Model):
    hide_mcp_hints = models.BooleanField(default=False, db_default=False, null=False)
```

`makemigrations` will emit a plain `AddField(..., db_default=False, default=False, ...)`, and `sqlmigrate` shows just `ADD COLUMN ... DEFAULT false NOT NULL` — no `DROP DEFAULT` follow-up.

`db_default=` is also load-bearing for the nodejs / rust test suites. `posthog/management/commands/setup_test_environment.py` calls `disable_migrations()` and builds the test schema directly from model definitions, skipping the migration entirely. Plain `default=` is invisible to that path; `db_default=` is what Django bakes into the generated `CREATE TABLE`. Without it, the `postgres-parity` and Jest jobs in `.github/workflows/ci-nodejs.yml` will fail on raw `INSERT`s even though `./manage.py migrate` looks correct in isolation.

For modifying the default on an existing column (no `ADD COLUMN`), use a plain `RunSQL` instead:

```python
migrations.RunSQL(
    sql="ALTER TABLE <table> ALTER COLUMN <col> SET DEFAULT '[]'::jsonb;",
    reverse_sql="ALTER TABLE <table> ALTER COLUMN <col> DROP DEFAULT;",
)
```

Always verify with `./manage.py sqlmigrate <app> <number>` that no stray `DROP DEFAULT` slipped through, and confirm `./manage.py makemigrations --dry-run` reports no state drift.
