# Safe Django Migration Guide

This guide explains how to safely perform dangerous Django migration operations in production with PostgreSQL. Each section covers a risky operation and provides step-by-step instructions for the safe approach.

> **Rule of thumb:** Never run a migration that drops, renames, or removes anything while any running code could still reference it. Use a two-phase approach: remove references → wait → drop.

**Context:** These guidelines are written for zero-downtime, rolling-deploy environments like PostHog's production setup. In single-instance or development setups, you can take shortcuts at your own risk — but these patterns prevent downtime in production.

## Table of Contents

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

### Safe Approach: Concurrent Index Creation

**Recommended: Use Django's built-in concurrent operations (PostgreSQL only):**

```python
from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations, models

class Migration(migrations.Migration):
    atomic = False  # Required for CONCURRENTLY

    operations = [
        AddIndexConcurrently(
            model_name='mymodel',
            index=models.Index(fields=['field_name'], name='mymodel_field_idx'),
        ),
    ]
```

**If you need `IF NOT EXISTS` for idempotency, use RunSQL:**

```python
from django.db import migrations

class Migration(migrations.Migration):
    atomic = False  # Required for CONCURRENTLY

    operations = [
        migrations.RunSQL(
            sql="""
                CREATE INDEX CONCURRENTLY IF NOT EXISTS mymodel_field_idx
                ON mymodel (field_name)
            """,
            reverse_sql="DROP INDEX CONCURRENTLY IF EXISTS mymodel_field_idx",
        ),
    ]
```

### Key Points

- **Use `AddIndexConcurrently` for existing large tables** - it handles the SQL correctly
- `AddIndexConcurrently` does not support `IF NOT EXISTS` - use `RunSQL` if you need idempotency
- Set `atomic = False` in the migration (required for all CONCURRENTLY operations)
- Concurrent index creation is slower but doesn't block writes
- Use `RemoveIndexConcurrently` to drop indexes safely

## Adding Constraints

**Problem:** Adding constraints like `CHECK` or `FOREIGN KEY` validates all existing rows, locking the table during validation.

### Why This Is Dangerous

- **Table locks:** Constraint validation scans the entire table
- **Long operation time:** Validation on large tables can take minutes
- **Blocks writes:** Table is locked during validation
- **Rollback risk:** If validation fails, migration fails

### Safe Approach: NOT VALID Pattern

Add constraints in two phases - add without validation, then validate separately.

**Example: CHECK Constraint**

**Step 1: Add constraint with NOT VALID**

```python
class Migration(migrations.Migration):
    operations = [
        migrations.RunSQL(
            sql="""
                ALTER TABLE mymodel
                ADD CONSTRAINT mymodel_field_check
                CHECK (field_value > 0)
                NOT VALID
            """,
            reverse_sql="ALTER TABLE mymodel DROP CONSTRAINT mymodel_field_check",
        ),
    ]
```

This adds the constraint but only validates NEW rows (instant operation).

**Step 2: Validate constraint in separate migration**

```python
class Migration(migrations.Migration):
    operations = [
        migrations.RunSQL(
            sql="ALTER TABLE mymodel VALIDATE CONSTRAINT mymodel_field_check",
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
```

Deploy this separately. Validation scans the table but uses `SHARE UPDATE EXCLUSIVE` lock which allows normal reads and writes but blocks other schema changes on that table.

**Note:** This pattern also works for `FOREIGN KEY` constraints.

### Key Points

- `NOT VALID` makes constraint addition instant
- Validation happens in background, allows concurrent operations
- `VALIDATE CONSTRAINT` takes a `SHARE UPDATE EXCLUSIVE` lock that allows normal reads/writes but blocks DDL operations
- If validation fails, Django marks the migration as unapplied - clean the offending rows and re-run the validation migration
- Can fix data issues and retry validation without blocking production

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

### 2. Set atomic=False for Long-Running Operations

PostgreSQL's `CONCURRENTLY` operations cannot run inside transactions. Additionally, set `atomic=False` for large backfills or long-running operations to allow partial progress to commit and avoid transaction timeouts.

```python
class Migration(migrations.Migration):
    atomic = False  # Required for CONCURRENTLY and recommended for long operations

    operations = [
        migrations.RunSQL(
            sql="CREATE INDEX CONCURRENTLY ...",
        ),
    ]
```

**When to use `atomic=False`:**

- `CREATE INDEX CONCURRENTLY` (required - Django's `AddIndexConcurrently` sets this automatically)
- `DROP INDEX CONCURRENTLY` (required - `RemoveIndexConcurrently` sets this automatically)
- `REINDEX CONCURRENTLY` (required)
- Large data backfills that might timeout
- Long-running `RunPython` operations

**How atomic=False works:**

With `atomic=False`, each operation in the migration runs in its own transaction and commits individually. This means:

- Order operations to be safe individually - each one commits before the next starts
- If a migration fails midway, earlier operations have already committed and won't roll back
- Always verify schema consistency after failed runs

**Warning:** With `atomic=False`, migrations may partially apply changes if they fail. Have a recovery plan ready.

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
