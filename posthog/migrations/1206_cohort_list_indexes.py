from django.contrib.postgres.indexes import GinIndex
from django.db import migrations, models

from posthog.migration_helpers import CreateIndexConcurrently


class Migration(migrations.Migration):
    # CONCURRENTLY can't run inside a transaction.
    atomic = False

    dependencies = [
        ("posthog", "1205_delete_batch_export_models"),
    ]

    operations = [
        # `CreateIndexConcurrently` (vs Django's `AddIndexConcurrently`) disables
        # lock_timeout/statement_timeout, drops any invalid leftover from an
        # interrupted build, and uses IF NOT EXISTS — so a transient cancellation
        # during deploy doesn't wedge retries. `SeparateDatabaseAndState` keeps the
        # Django model state in sync via the matching `AddIndex`. pg_trgm is already
        # installed (migration 0034), so the gin_trgm_ops index needs no extension op.
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddIndex(
                    model_name="cohort",
                    index=models.Index(fields=["team", "-created_at"], name="cohort_team_created_idx"),
                ),
            ],
            database_operations=[
                CreateIndexConcurrently(
                    index_name="cohort_team_created_idx",
                    table_name="posthog_cohort",
                    columns="(team_id, created_at DESC)",
                ),
            ],
        ),
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddIndex(
                    model_name="cohort",
                    index=GinIndex(fields=["name"], name="cohort_name_trgm_idx", opclasses=["gin_trgm_ops"]),
                ),
            ],
            database_operations=[
                CreateIndexConcurrently(
                    index_name="cohort_name_trgm_idx",
                    table_name="posthog_cohort",
                    columns="(name gin_trgm_ops)",
                    using="gin",
                ),
            ],
        ),
    ]
