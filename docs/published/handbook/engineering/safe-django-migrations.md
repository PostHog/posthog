---
title: Safe Django Migrations
showTitle: true
noindex: true
---

This guide explains how to safely perform dangerous Django migration operations in production with PostgreSQL. Each section covers a risky operation and provides step-by-step instructions for the safe approach.

> **Rule of thumb:** Never run a migration that drops, renames, or removes anything while any running code could still reference it. Use a two-phase approach: remove references → wait → drop.

**Context:** These guidelines are written for zero-downtime, rolling-deploy environments like PostHog's production setup. In single-instance or development setups, you can take shortcuts at your own risk — but these patterns prevent downtime in production.

## Table of Contents

- [Altering Hot Tables](#altering-hot-tables)
- [Dropping Tables](#dropping-tables)
- [Dropping Columns](#dropping-columns)
- [Renaming Tables](#renaming-tables)
- [Renaming Columns](#renaming-columns)
- [Adding NOT NULL Columns](#adding-not-null-columns)
- [Adding Indexes](#adding-indexes)
- [Adding Constraints](#adding-constraints)
- [Running Data Migrations](#running-data-migrations)
- [Using SeparateDatabaseAndState](#using-separatedatabaseandstate)
- [General Best Practices](#general-best-practices)

## Altering Hot Tables

**Problem:** `posthog_team`, `posthog_user`, `posthog_organization`, and `posthog_project` are read on virtually every request. Every `ALTER TABLE` — including the "safe" patterns elsewhere in this guide, like adding a nullable column — needs an `ACCESS EXCLUSIVE` lock. The danger is not the ALTER itself (a nullable `ADD COLUMN` is metadata-only and takes milliseconds once it runs); it's the **lock queue**: while the ALTER waits behind in-flight queries, Postgres queues every later query on the table behind it. On a hot table that means site-wide request pile-ups and 5xx errors until `lock_timeout` cancels the ALTER — and since `bin/migrate` retries with exponential backoff, the stall repeats in waves until the ALTER finally wins the race.

This is not theoretical: a plain nullable `AddField` on `Team` — exactly what this guide's NOT NULL section recommends as the safe pattern — has caused roughly an hour of recurring 5xx waves in production while it lost the lock race retry after retry.

### Safe Approach: Don't Alter the Table

For `Team`, most new fields shouldn't be on the table at all. Domain-specific fields belong on a **Team extension model** (see `posthog/models/team/README.md`) — that's a `CREATE TABLE`, which takes no lock on `posthog_team` whatsoever.

`CREATE INDEX CONCURRENTLY` (via `SafeAddIndexConcurrently`, see [Adding Indexes](#adding-indexes)) is also fine: it only takes `SHARE UPDATE EXCLUSIVE`, which doesn't block reads or writes.

### If You Genuinely Must Alter a Hot Table

The migration analyzer (`HotTableAlterPolicy`) blocks any DDL on these tables in CI. To accept the risk:

1. Confirm the field really is core (team identity, cross-product settings, SDK config) and not a candidate for an extension model.
2. Add `<app_label>.<migration_name>` to `posthog/management/migration_analysis/hot_table_acknowledged_migrations.txt` — this is the explicit "I accept the risk" act, and it's visible in review.
3. Coordinate the deploy with #team-infrastructure for a low-traffic window.

### Foreign Keys to Hot Tables

**Problem:** The hazard above also fires from the _referencing_ side, and from **any** app — a plain `CreateModel` or `AddField` in a product app with a `ForeignKey(to="posthog.team", ...)` (or `to=settings.AUTH_USER_MODEL`, which resolves to `posthog_user`). Creating the FK constraint takes a `SHARE ROW EXCLUSIVE` lock on the _referenced parent_ table, even though the child table is brand new. That lock conflicts with the `ROW EXCLUSIVE` lock every `INSERT`/`UPDATE`/`DELETE` on the parent holds, so under write traffic the lock request queues behind in-flight writes, `lock_timeout` cancels it, and each `bin/migrate` retry repeats the stall. A `CreateModel` with an FK to `posthog_team` has blocked a deploy this way.

`HotTableAlterPolicy` flags `CreateModel` / `AddField` whose FK target resolves to a hot table (it skips FKs declared `db_constraint=False`). Two options:

**Option A — `db_constraint=False` (the only truly lock-free path):**

```python
# CreateModel / AddField then emit no FK constraint and take NO lock on the parent.
# Referential integrity is enforced in application code only.
team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False)
```

This is the option that avoids the parent lock entirely — reach for it when you can live without database-level enforcement.

**Option B — a real DB constraint, two-phase via the helper:**

Declare the FK `db_constraint=False` (so `CreateModel` / `AddField` take no lock), then add the constraint back in a later migration with `AddForeignKeyNotValid`, and `ValidateForeignKey` after that:

```python
# 00xx_add_fk_not_valid.py  (brief SHARE ROW EXCLUSIVE on the parent — see caveat below)
from posthog.migration_helpers import AddForeignKeyNotValid

operations = [
    AddForeignKeyNotValid(
        model_name="mymodel",
        name="mymodel_team_id_fk",
        column="team_id",
        to_table="posthog_team",
        to_column="id",
    ),
]

# 00yy_validate_fk.py  (SHARE UPDATE EXCLUSIVE on the child, no parent lock)
from posthog.migration_helpers import ValidateForeignKey

operations = [
    ValidateForeignKey(model_name="mymodel", name="mymodel_team_id_fk"),
]
```

Be honest about the lock: `ADD CONSTRAINT ... NOT VALID` still takes a **brief** `SHARE ROW EXCLUSIVE` lock on the parent for the catalog metadata add. It skips the row-validation scan, so it shrinks the lock window to metadata-only — but it does **not** eliminate the parent lock. Only `db_constraint=False` (Option A) is truly lock-free. The follow-up `VALIDATE CONSTRAINT` scans child rows under `SHARE UPDATE EXCLUSIVE` and takes no lock on the parent.

If the FK genuinely must lock the hot table on add, acknowledge it the same way as any other hot-table DDL (add the migration to `hot_table_acknowledged_migrations.txt` and coordinate the deploy).

## Dropping Tables

**Problem:** `DeleteModel` operations drop tables immediately. This breaks backwards compatibility during deployment and **cannot be rolled back** - once data is deleted, any rollback deployment will fail because the table no longer exists.

### Why This Is Dangerous

- **No rollback:** If deployment fails and you need to roll back, the table and all its data are already gone
- **Breaks running code:** Old application servers still reference the table during deployment
- **Data loss is permanent:** Accidentally dropped data cannot be recovered (unless from backups)

### Safe Approach

Deploy table drops in separate phases with safety delays:

**Step 1: Remove model and all references (single PR)**

In one PR, remove the model and all code that references it:

1. Remove all application code that uses the model:
   - Delete imports of the model
   - Remove API endpoints, views, serializers
   - Remove business logic that queries or writes to it
   - Remove references in background jobs, async workers (Celery, plugins), cron tasks

2. Delete the model class from `models.py`

3. Run `makemigrations` - Django will generate a `DeleteModel` operation

4. Wrap the generated migration in `SeparateDatabaseAndState` to only affect Django's state, not the database:

```python
class Migration(migrations.Migration):
    dependencies = []

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.DeleteModel(name='OldFeature'),
            ],
            database_operations=[
                # If table has FKs to frequently-truncated tables (User, Team, Organization),
                # drop those FK constraints to avoid blocking TransactionTestCase teardown.
                # migrations.RunSQL(
                #     sql="ALTER TABLE posthog_oldfeature DROP CONSTRAINT IF EXISTS posthog_oldfeature_team_id_fkey",
                # ),
            ],
        ),
    ]
```

5. Deploy this PR and verify no errors in production

**Test infrastructure note:** If your table has foreign keys pointing TO frequently-truncated tables like `User`, `Team`, or `Organization`, you may see test failures like `cannot truncate a table referenced in a foreign key constraint`. This happens because:

- Django's `TransactionTestCase` uses `TRUNCATE` to clean up between tests
- PostgreSQL won't truncate a table that has FKs pointing to it
- Since the model is removed from Django's state, Django doesn't know to include it in the truncate list
- Fix: Drop the FK constraints in `database_operations` (see commented example above) - you're dropping the table soon anyway

**Step 2: Wait for safety window**

- Wait at least one full deployment cycle
- This ensures no rollback or hotfix can reintroduce code that expects the table
- Allows all application servers, workers, and background jobs to roll over

**Step 3: Drop the table (optional)**

- Safe to leave unused tables temporarily, but long-term they can clutter schema introspection and slow migrations
- Ensure no other models reference this table via foreign keys before dropping (Django won't cascade automatically)
- If you must drop it, use `RunSQL` with raw SQL (see example below)
- In the PR description, reference the model removal PR (e.g., "Model removed in #12345, deployed X days ago") so reviewers can verify the safety window

**Important notes:**

- Drop operations are irreversible - once data is deleted, it's gone and any rollback will fail without the table
- Use `RunSQL(DROP TABLE IF EXISTS)` for explicit control and idempotency

### Example

```python
# ❌ DANGEROUS - Never do this
class Migration(migrations.Migration):
    operations = [
        migrations.DeleteModel(name='OldFeature'),
    ]

# ✅ SAFE - Multi-phase approach with SeparateDatabaseAndState
# Step 1: Remove model and all references (deploy this in one PR)
#   - Delete all code that imports/uses OldFeature
#   - Delete OldFeature class from models.py
#   - Run makemigrations and wrap in SeparateDatabaseAndState
class Migration(migrations.Migration):
    dependencies = []

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.DeleteModel(name='OldFeature'),
            ],
            database_operations=[
                # Drop FK constraints if table references User/Team/Organization
                # to avoid blocking TransactionTestCase TRUNCATE operations
            ],
        ),
    ]

# Step 2: Much later (weeks), optionally drop the table
class Migration(migrations.Migration):
    dependencies = []

    operations = [
        migrations.RunSQL(
            sql="DROP TABLE IF EXISTS posthog_oldfeature",
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
```

### Removing a whole product or app

Removing a product (`products/<name>/`) is the phased table drop above — once per model — plus app teardown. It is **not** a folder delete.

**Do not "remove" a table by deleting its migration file.** The deleted-migration check in the `repo-checks` CI job (the `hogli lint:migration-deletions` command) blocks deleting any migration that exists on master; genuinely intentional, reviewed deletions (a product move, a revert, a squash) are acknowledged in `.github/scripts/migration-deletion-allowlist.txt`. Deleting the file drops nothing:

- The table and its FK constraints stay in every database where the migration already ran.
- The `django_migrations` rows linger as orphans — harmless (Django ignores migrations for apps not in `INSTALLED_APPS`) but never cleaned up.
- Fresh databases never create the table, so production and CI diverge.
- The migration risk analyzer rebuilds master's schema, then checks out each open PR's tree, so any in-flight branch that predates the deletion still carries the file and gets it re-analyzed as a brand-new migration — a phantom "blocked" flag that only clears once that branch merges master.

Safe order:

1. Strip all usage and the model classes, and drop the tables via the [phased approach](#dropping-tables) (state-only `DeleteModel`, wait a deploy cycle, then `DROP TABLE`). Keep the app in `INSTALLED_APPS` so its migrations still run.
2. Only after the drop migration has deployed everywhere, remove the app from `INSTALLED_APPS` and delete the `products/<name>/` folder.
3. Optionally `DELETE FROM django_migrations WHERE app = '<app_label>'` to clear the orphan rows.

Leaving the table in place — code gone, table dropped in a follow-up — is a legitimate shortcut for a small retired product: it dodges the rolling-deploy window where in-flight requests hit a dropped table. Just make the leftover table a tracked follow-up, not an accident.

## Dropping Columns

**Problem:** `RemoveField` operations drop columns immediately. This breaks backwards compatibility during deployment and **cannot be rolled back** - once data is deleted, any rollback deployment will fail because the column no longer exists.

### Safe Approach

Use the same multi-phase pattern as [Dropping Tables](#dropping-tables):

1. Remove the field from your Django model (keeps column in database)
2. Deploy and verify no code references it (application servers, workers, background jobs)
3. Wait at least one full deployment cycle
4. Optionally drop the column with `RemoveField` in a later migration

**Important notes:**

- `RemoveField` operations are irreversible - column data is permanently deleted
- `DROP COLUMN` takes an `ACCESS EXCLUSIVE` lock (briefly) - schedule during low-traffic windows
- Consider leaving unused columns indefinitely to avoid data loss risks

## Renaming Tables

**Problem:** `RenameModel` operations rename tables immediately. This breaks old code that still references the old table name during deployment.

### Safe Approach: Don't Rename

**Strongly recommended:** Accept the original table name even if it's wrong. Renaming tables in production creates significant complexity and risk for minimal benefit. The table name is an implementation detail that users never see.

## Renaming Columns

**Problem:** `RenameField` operations rename columns immediately. This breaks old code that still references the old column name during deployment.

### Safe Approach: Use db_column

**Strongly recommended:** Don't rename columns in production. Accept the original name and use Django's `db_column` parameter to map a better Python name to the existing database column:

```python
class MyModel(models.Model):
    better_name = models.CharField(db_column='old_bad_name', max_length=100)
```

This gives you a clean Python API without the risk of renaming the database column.

## Adding NOT NULL Columns

**Problem:** Adding a `NOT NULL` column without a default (or with a volatile default like `uuid4()` or `now()`) requires rewriting the entire table. This locks the table and can cause deployment timeouts.

### Why This Is Dangerous

- **Table locks:** PostgreSQL must rewrite every row to add the value
- **Long operation time:** On large tables, this can take minutes or hours
- **Deployment timeout:** Migration might exceed timeout limits
- **Blocks all writes:** No data can be written to the table during the migration

### Safe Approach: Three-Phase Deployment

1. Add column as nullable
2. Backfill data
3. Add NOT NULL constraint

> **Note:** "safe" here means no table rewrite. On [hot tables](#altering-hot-tables) even a nullable `ADD COLUMN` can stall traffic while it waits for its lock.

**Step 1: Add column as nullable**

```python
class Migration(migrations.Migration):
    operations = [
        migrations.AddField(
            model_name='mymodel',
            name='new_field',
            field=models.CharField(max_length=100, null=True),  # Allow NULL
        ),
    ]
```

Deploy this change.

**Step 2: Backfill data for all rows**

For small/medium tables with static values, use simple UPDATE:

```python
class Migration(migrations.Migration):
    operations = [
        migrations.RunSQL(
            sql="UPDATE mymodel SET new_field = 'default_value' WHERE new_field IS NULL",
        ),
    ]
```

For large tables, use batching to avoid long locks:

```python
from django.db import migrations

def backfill_in_batches(apps, schema_editor):
    MyModel = apps.get_model('myapp', 'MyModel')
    batch_size = 10000

    while True:
        ids = list(
            MyModel.objects.filter(new_field__isnull=True)
            .values_list('id', flat=True)[:batch_size]
        )
        if not ids:
            break

        MyModel.objects.filter(id__in=ids).update(new_field='default_value')

class Migration(migrations.Migration):
    operations = [
        migrations.RunPython(backfill_in_batches),
    ]
```

**Step 3: Add NOT NULL constraint**

```python
class Migration(migrations.Migration):
    operations = [
        migrations.AlterField(
            model_name='mymodel',
            name='new_field',
            field=models.CharField(max_length=100, null=False),  # Now NOT NULL
        ),
    ]
```

Or use RunSQL for more control:

```python
class Migration(migrations.Migration):
    operations = [
        migrations.RunSQL(
            sql="ALTER TABLE mymodel ALTER COLUMN new_field SET NOT NULL",
            reverse_sql="ALTER TABLE mymodel ALTER COLUMN new_field DROP NOT NULL",
        ),
    ]
```

## Adding Indexes

**Problem:** Creating indexes without `CONCURRENTLY` locks the table for the entire duration of index creation. On large tables, this can take minutes or hours, blocking all writes.

### Why This Is Dangerous

- **Table locks:** Normal `CREATE INDEX` holds an exclusive lock
- **Long operation time:** Index creation on large tables can take hours
- **Blocks all writes:** No data can be written during index creation
- **Deployment timeout:** Migration might exceed timeout limits

### Why `AddIndexConcurrently` Is Not Enough

Do not use `AddIndexConcurrently` / `RemoveIndexConcurrently` directly.
They are non-blocking, but they are **not idempotent**:
Django emits a bare `CREATE INDEX CONCURRENTLY` (or `DROP INDEX CONCURRENTLY`)
with no `IF NOT EXISTS` / `IF EXISTS`, and there is no hook to disable
`lock_timeout` or `statement_timeout` for the build.

Deploy runs migrations under a `lock_timeout`, and `bin/migrate` re-runs the
**entire** migration on failure with exponential backoff.
`CREATE INDEX CONCURRENTLY` is non-transactional and runs with `atomic = False`,
so if the build is cancelled (a single transient `lock_timeout` while another
session holds a conflicting lock is enough; OOM, deploy timeout, statement_timeout,
SIGTERM and PG restarts can do the same) PostgreSQL leaves an **invalid** index
behind with nothing to roll it back.
The next retry then re-issues the same bare statement and fails with
`relation "..." already exists` (or `index "..." does not exist` for drops).
The migration is now stuck and blocks all deploys until someone drops or
`REINDEX`es the invalid index by hand.

`IF NOT EXISTS` alone is **not enough** either. PG's `IF NOT EXISTS` is
name-level, not state-level — it skips when an index with that name exists,
regardless of whether it is valid (`indisvalid = false`). A bare retry under
`IF NOT EXISTS` will silently no-op past an invalid leftover and mark the
migration applied while the index does nothing.

This is enforced: `ConcurrentIndexIdempotencyPolicy` in the migration risk
analyzer blocks any migration that uses `AddIndexConcurrently`,
`RemoveIndexConcurrently`, or a raw `RunSQL` concurrent index without
`IF [NOT] EXISTS`.

### Safe Approach: `SafeAddIndexConcurrently` Helper (Recommended)

**Adding an index? Use `SafeAddIndexConcurrently`.**
It takes a `model_name` + Django `Index` (like Django's `AddIndexConcurrently`), tracks state itself — no `SeparateDatabaseAndState`, no re-spelling the index as raw SQL — and adds the safety the bare Django op lacks: disables `lock_timeout`/`statement_timeout`, skips an already-valid index, and rebuilds an `indisvalid = false` leftover from an interrupted build.

```python
from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False  # Required for CONCURRENTLY

    operations = [
        SafeAddIndexConcurrently(
            model_name="mymodel",
            index=models.Index(fields=["field_name"], name="mymodel_field_idx"),
        ),
    ]
```

Dropping an index uses the mirror helper, `SafeRemoveIndexConcurrently`
(`model_name` + index `name`).

### Raw-SQL variant: `CreateIndexConcurrently` / `DropIndexConcurrently`

When the index doesn't map cleanly to a Django `Index` (e.g. an expression
the ORM can't model), use the raw-SQL helpers. They subclass `RunSQL`, which
doesn't touch Django state, so they must be wrapped in
`SeparateDatabaseAndState` with a matching `AddIndex` / `RemoveIndex`:

```python
from django.db import migrations, models

from posthog.migration_helpers import CreateIndexConcurrently


class Migration(migrations.Migration):
    atomic = False  # Required for CONCURRENTLY

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddIndex(
                    model_name="mymodel",
                    index=models.Index(fields=["field_name"], name="mymodel_field_idx"),
                ),
            ],
            database_operations=[
                CreateIndexConcurrently(
                    index_name="mymodel_field_idx",
                    table_name="mymodel",
                    columns="(field_name)",
                ),
            ],
        ),
    ]
```

### Fallback: Raw `RunSQL` + `lock_timeout = 0` + `IF NOT EXISTS`

For exotic cases the helper doesn't cover (partitioned tables, custom
operator classes the helper hasn't grown a knob for yet, etc.), raw `RunSQL`
is still accepted by the policy as long as it includes `IF [NOT] EXISTS`:

```python
migrations.RunSQL(
    sql="""
        SET lock_timeout = 0;
        SET statement_timeout = 0;
        CREATE INDEX CONCURRENTLY IF NOT EXISTS mymodel_field_idx
        ON mymodel (field_name);
    """,
    reverse_sql="DROP INDEX CONCURRENTLY IF EXISTS mymodel_field_idx;",
)
```

This form is strictly weaker than the helper: it does not detect or clean up
an `indisvalid = false` leftover. If a prior deploy was interrupted by
anything other than `lock_timeout`, manual `REINDEX INDEX CONCURRENTLY` or
`DROP INDEX CONCURRENTLY IF EXISTS` is needed before re-running. Prefer the
helper.

### Key Points

- **Never use `AddIndexConcurrently` / `RemoveIndexConcurrently` directly** — they are non-idempotent and the CI policy blocks them
- **Prefer `SafeAddIndexConcurrently` / `SafeRemoveIndexConcurrently` from `posthog.migration_helpers`** — they take a `model_name` + Index, track Django state themselves (no `SeparateDatabaseAndState`), disable both timeouts, and recover from invalid leftover indexes
- Use the raw-SQL `CreateIndexConcurrently` / `DropIndexConcurrently` (wrapped in `SeparateDatabaseAndState`) only when the index doesn't map to a Django `Index`
- Raw `RunSQL` with `SET lock_timeout = 0; SET statement_timeout = 0; CREATE INDEX CONCURRENTLY IF NOT EXISTS ...` is acceptable as a last-resort fallback but does not recover from invalid leftovers
- Set `atomic = False` (required for all `CONCURRENTLY` operations)
- If a prior deploy already left an invalid index (the helper would catch this on next run, but the fallback won't), clean it up with `REINDEX INDEX CONCURRENTLY` or `DROP INDEX CONCURRENTLY IF EXISTS` before re-running

## Adding Constraints

**Problem:** Adding constraints like `CHECK` or `FOREIGN KEY` validates all existing rows, locking the table during validation.

### Why This Is Dangerous

- **Table locks:** Constraint validation scans the entire table
- **Long operation time:** Validation on large tables can take minutes
- **Blocks writes:** Table is locked during validation
- **Rollback risk:** If validation fails, migration fails

### Safe Approach: NOT VALID Pattern

Add CHECK constraints in two phases — add without validation, then validate separately — using the `posthog.migration_helpers` helpers.
They take a `model_name` + Django constraint (so Django builds the SQL and tracks model state, no `SeparateDatabaseAndState` and no hand-written SQL), and both phases are idempotent under `bin/migrate` retries (the add skips if the constraint exists, the validate skips if it's already validated).

**Step 1: Add the constraint with NOT VALID** — brief lock, no table scan, enforces new/changed rows only.

```python
from django.db import migrations, models
from django.db.models import Q

from posthog.migration_helpers import AddConstraintNotValid


class Migration(migrations.Migration):
    operations = [
        AddConstraintNotValid(
            model_name="mymodel",
            constraint=models.CheckConstraint(condition=Q(field_value__gt=0), name="mymodel_field_check"),
        ),
    ]
```

**Step 2: Validate the constraint in a separate migration** — scans existing rows under `SHARE UPDATE EXCLUSIVE` (allows normal reads/writes).

```python
from django.db import migrations

from posthog.migration_helpers import ValidateConstraint


class Migration(migrations.Migration):
    operations = [
        ValidateConstraint(model_name="mymodel", name="mymodel_field_check"),
    ]
```

Keep the two phases in **separate migrations** (so the add's brief `ACCESS EXCLUSIVE` lock isn't held through the validate scan), or in the same migration with `atomic = False`.
If validation fails, Django marks the migration unapplied — clean the offending rows and re-run.

**Note:** The same NOT VALID / VALIDATE pattern applies to `FOREIGN KEY` constraints via `AddForeignKeyNotValid` / `ValidateForeignKey` — don't hand-write the `RunSQL`. This matters most when the FK points at a hot table; see [Foreign Keys to Hot Tables](#foreign-keys-to-hot-tables). New nullable FK columns to non-hot tables don't need it — the column starts empty, so there's nothing to validate.

### Key Points

- `NOT VALID` makes constraint addition instant
- Validation happens in background, allows concurrent operations
- `VALIDATE CONSTRAINT` takes a `SHARE UPDATE EXCLUSIVE` lock that allows normal reads/writes but blocks DDL operations
- If validation fails, Django marks the migration as unapplied - clean the offending rows and re-run the validation migration
- Can fix data issues and retry validation without blocking production

The same two-phase pattern exists for **foreign keys** via `AddForeignKeyNotValid` / `ValidateForeignKey` — but note that an FK to a hot table needs extra care, since `ADD CONSTRAINT ... NOT VALID` still briefly locks the _referenced parent_. See [Foreign Keys to Hot Tables](#foreign-keys-to-hot-tables).

## Running Data Migrations

**Problem:** `RunSQL` with `UPDATE` or `DELETE` operations can lock rows for extended periods, especially on large tables. `RunPython` operations can be slow and hold locks.

### Why UPDATE/DELETE Are Dangerous

- **Row locks:** Each updated/deleted row is locked
- **Long transactions:** Large updates hold locks for the entire operation
- **Blocks concurrent updates:** Other operations wait for locks
- **Timeout risk:** Large operations may exceed timeout limits
- **Rollback complexity:** Partial completion is hard to recover from

### Safe Approach: Batching

Break large updates into small batches with delays between them.

**Pattern 1: Batched UPDATE in RunSQL**

```python
class Migration(migrations.Migration):
    operations = [
        migrations.RunSQL(
            sql="""
                DO $$
                DECLARE
                    batch_size INTEGER := 1000;
                    rows_updated INTEGER;
                BEGIN
                    LOOP
                        UPDATE mymodel
                        SET new_field = 'value'
                        WHERE id IN (
                            SELECT id FROM mymodel
                            WHERE new_field IS NULL
                            LIMIT batch_size
                        );

                        GET DIAGNOSTICS rows_updated = ROW_COUNT;
                        EXIT WHEN rows_updated = 0;

                        PERFORM pg_sleep(0.1);  -- Brief pause between batches
                    END LOOP;
                END $$;
            """
        ),
    ]
```

**Important:** The `DO $$ ... $$` batching runs inside a **single transaction**. Locks persist through the loop and partial progress cannot be committed. For truly chunked updates with intermediate commits, use Python-level batching (Pattern 2) or background jobs.

**Pattern 2: Batched UPDATE in RunPython**

```python
from django.db import migrations
import time

def backfill_in_batches(apps, schema_editor):
    MyModel = apps.get_model('myapp', 'MyModel')
    batch_size = 10000
    updated_count = 0

    while True:
        # Get batch of IDs that need updating
        ids = list(
            MyModel.objects.filter(new_field__isnull=True)
            .values_list('id', flat=True)[:batch_size]
        )

        if not ids:
            break

        # Update batch
        MyModel.objects.filter(id__in=ids).update(new_field='default_value')
        updated_count += len(ids)

        print(f"Updated {updated_count} rows...")
        time.sleep(0.1)  # Brief pause between batches

class Migration(migrations.Migration):
    operations = [
        migrations.RunPython(backfill_in_batches),
    ]
```

**Pattern 3: Using iterator for memory efficiency**

```python
def process_large_dataset(apps, schema_editor):
    MyModel = apps.get_model('myapp', 'MyModel')

    # Use iterator to avoid loading all rows into memory
    for obj in MyModel.objects.all().iterator(chunk_size=1000):
        obj.new_field = calculate_value(obj)
        obj.save(update_fields=['new_field'])

class Migration(migrations.Migration):
    operations = [
        migrations.RunPython(process_large_dataset),
    ]
```

**Pattern 4: Bulk update for better performance**

```python
def bulk_update_in_batches(apps, schema_editor):
    MyModel = apps.get_model('myapp', 'MyModel')
    batch_size = 1000

    objects_to_update = []

    for obj in MyModel.objects.filter(needs_update=True).iterator(chunk_size=batch_size):
        obj.new_field = calculate_value(obj)
        objects_to_update.append(obj)

        if len(objects_to_update) >= batch_size:
            MyModel.objects.bulk_update(objects_to_update, ['new_field'])
            objects_to_update = []
            print(f"Updated batch of {batch_size} rows")

    # Update remaining objects
    if objects_to_update:
        MyModel.objects.bulk_update(objects_to_update, ['new_field'])

class Migration(migrations.Migration):
    operations = [
        migrations.RunPython(bulk_update_in_batches),
    ]
```

### Key Points for Data Migrations

- **Batch size:** 1,000-10,000 rows per batch (tune based on row size)
- **Add pauses:** Small delays between batches reduce system load
- **Use WHERE clauses:** Limit scope of updates
- **Monitor progress:** Add logging every N rows
- **Test on production data:** Verify performance before deploying
- **Consider background jobs:** For very large updates (millions of rows), use a background job instead of a migration
- **Use `.iterator()`:** Avoids loading all rows into memory
- **Use `.bulk_update()`:** Much faster than individual saves

## Using SeparateDatabaseAndState

`SeparateDatabaseAndState` is a powerful Django operation that separates Django's migration state from actual database changes. This is essential for safe multi-phase deployments.

### When to Use It

1. **Removing models safely** - See [Dropping Tables](#dropping-tables) for the full pattern
2. **Adding models for existing tables** - When a table already exists in the database (created manually or by another system)

### Example: Adding a Model for an Existing Table

```python
class Migration(migrations.Migration):
    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.CreateModel(
                    name='ExistingTable',
                    fields=[
                        ('id', models.BigAutoField(primary_key=True)),
                        ('name', models.CharField(max_length=255)),
                    ],
                ),
            ],
            database_operations=[],  # Table already exists, just update Django state
        ),
    ]
```

### Why This Matters

- Prevents Django state drift when performing staged operations
- Without this, `makemigrations` may generate incorrect migrations trying to sync the state
- Allows you to separate "what Django thinks exists" from "what actually exists in the database"

## General Best Practices

### 1. One Risky Operation Per Migration

Split migrations with multiple risky operations into separate migrations. This makes rollback easier and reduces deployment risk.

```python
# ❌ BAD - Multiple risky operations
class Migration(migrations.Migration):
    operations = [
        migrations.AddIndex(...),  # Risky
        migrations.RunSQL("UPDATE ..."),  # Risky
        migrations.AddField(...),  # Risky
    ]

# ✅ GOOD - Separate migrations
class Migration(migrations.Migration):
    operations = [
        migrations.AddIndex(...),
    ]
```

### 2. Use atomic=False Only for CONCURRENTLY Operations

PostgreSQL's `CONCURRENTLY` operations cannot run inside transactions. Use `atomic=False` **only** when required.

```python
from posthog.migration_helpers import CreateIndexConcurrently


class Migration(migrations.Migration):
    atomic = False  # Required for CONCURRENTLY

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddIndex(
                    model_name="mymodel",
                    index=models.Index(fields=["field_name"], name="mymodel_field_idx"),
                ),
            ],
            database_operations=[
                CreateIndexConcurrently(
                    index_name="mymodel_field_idx",
                    table_name="mymodel",
                    columns="(field_name)",
                ),
            ],
        ),
    ]
```

See [Adding Indexes](#adding-indexes) for why the bare `AddIndexConcurrently` form is unsafe and what the helper does under the hood.

**When to use `atomic=False`:**

- `CREATE INDEX CONCURRENTLY` (required — use `CreateIndexConcurrently`, not `AddIndexConcurrently`)
- `DROP INDEX CONCURRENTLY` (required — use `DropIndexConcurrently`, not `RemoveIndexConcurrently`)
- `REINDEX CONCURRENTLY` (required)

**When NOT to use `atomic=False`:**

- Regular DDL operations (AddField, AlterField, RemoveField, etc.)
- Data migrations (RunPython with UPDATE)
- Any operation that should rollback on failure

**Why this matters - the retry problem:**

Our deployment uses `bin/migrate` with retry logic. If a migration fails mid-execution:

- **With `atomic=True` (default)**: Nothing committed, retry works cleanly
- **With `atomic=False`**: Partial changes committed, retry fails with "column already exists" or similar errors

Example of what goes wrong:

```text
Migration with atomic=False:
  Op1: AddField (commits) ✓
  Op2: AddField (lock_timeout, fails) ✗

Retry:
  Op1: AddField → ERROR: column already exists!
```

**If you need both schema changes AND concurrent index creation:**

Split into separate migrations:

1. Migration 1: Schema changes (`atomic=True`, default)
2. Migration 2: Concurrent index (`atomic=False`)

**How atomic=False works:**

With `atomic=False`, each operation in the migration runs in its own transaction and commits individually. This means:

- Order operations to be safe individually - each one commits before the next starts
- If a migration fails midway, earlier operations have already committed and won't roll back
- Always verify schema consistency after failed runs

**For large data backfills:** If you genuinely need `atomic=False` for long-running operations (not just CONCURRENTLY), ensure idempotency with `IF NOT EXISTS`, `WHERE NOT EXISTS`, or consider using async migrations instead.

### 3. Use IF EXISTS / IF NOT EXISTS for Idempotency

Make operations safe to retry by using conditional SQL.

```python
# Safe to run multiple times
migrations.RunSQL(
    sql="CREATE INDEX CONCURRENTLY IF NOT EXISTS myindex ON mytable (field)",
)

migrations.RunSQL(
    sql="DROP INDEX CONCURRENTLY IF EXISTS myindex",
)
```

### 4. Have a Rollback Plan

Before deploying risky migrations:

- Understand what happens if deployment fails mid-migration
- Know which operations can be rolled back and which cannot (e.g., `DeleteModel`, `RemoveField` are irreversible)
- Have a plan to recover from partial completion
- Consider using `SeparateDatabaseAndState` for complex changes
- **Important:** With `atomic=False`, migrations may partially apply changes. If a migration fails, Django won't automatically roll back the changes. Always verify schema consistency after failed runs and be prepared to manually fix partial states.
- Remember that infra team may roll back deployments at any time for any reason (performance issues, alerts, etc.) - plan for this

## Getting Help

If you're unsure about a migration:

1. Ask in #team-devex for review
2. Check the migration risk analyzer output in your PR
3. Test on a production-sized dataset in a staging environment
4. Consider pair-programming the migration with someone experienced

Remember: **It's always safer to split a migration into multiple phases than to try to do everything at once.**
