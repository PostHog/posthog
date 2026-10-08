import django.contrib.postgres.indexes
from django.db import migrations

from posthog.migration_helpers.concurrent_index import SafeRemoveIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("posthog", "1346_untrack_organization_is_hipaa"),
    ]

    operations = [
        SafeRemoveIndexConcurrently(
            model_name="activitylog",
            name="activitylog_detail_gin",
        ),
        # Migration 0854 declared `idx_alog_detail_gin_path_ops` partial in state but created it
        # unfiltered in the database, so both prod regions carry the unfiltered index. Correct the
        # state to match. `detail` is non-null on effectively every row, so the predicate excluded
        # nothing, and rebuilding the index to add it would cost a concurrent GIN build for no gain.
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveIndex(
                    model_name="activitylog",
                    name="idx_alog_detail_gin_path_ops",
                ),
                migrations.AddIndex(
                    model_name="activitylog",
                    index=django.contrib.postgres.indexes.GinIndex(
                        fields=["detail"],
                        name="idx_alog_detail_gin_path_ops",
                        opclasses=["jsonb_path_ops"],
                    ),
                ),
            ],
            database_operations=[],
        ),
    ]
