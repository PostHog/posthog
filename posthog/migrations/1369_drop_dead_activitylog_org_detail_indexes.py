from django.db import migrations

from posthog.migration_helpers import SafeRemoveIndexConcurrently


class Migration(migrations.Migration):
    # posthog_activitylog is large and write-heavy, so drop the B-trees CONCURRENTLY to avoid an
    # ACCESS EXCLUSIVE lock on the table. Concurrent drops can't run in a transaction, hence
    # atomic = False.
    atomic = False

    dependencies = [
        ("posthog", "1368_sessionrecording_untrack_lts_fields"),
    ]

    operations = [
        SafeRemoveIndexConcurrently(
            model_name="activitylog",
            name="idx_alog_org_detail_exists",
        ),
        SafeRemoveIndexConcurrently(
            model_name="activitylog",
            name="idx_alog_org_scope_created_at",
        ),
    ]
