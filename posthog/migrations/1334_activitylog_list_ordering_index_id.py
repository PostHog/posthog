from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently, SafeRemoveIndexConcurrently


class Migration(migrations.Migration):
    # Same constraints as migration 1260, which added the narrower pair: posthog_activitylog is
    # large and write-heavy, so build the B-trees CONCURRENTLY and keep atomic = False.
    # Build each wider index before its narrower predecessor goes away, so the list endpoints
    # always have an index for the sort.
    atomic = False

    dependencies = [
        ("posthog", "1333_uploaded_media_library_index"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="activitylog",
            index=models.Index(
                fields=["organization_id", "-created_at", "-id"],
                name="idx_alog_org_created_at_id",
            ),
        ),
        SafeAddIndexConcurrently(
            model_name="activitylog",
            index=models.Index(
                fields=["team_id", "-created_at", "-id"],
                name="idx_alog_team_created_at_id",
            ),
        ),
        SafeRemoveIndexConcurrently(
            model_name="activitylog",
            name="idx_alog_org_created_at",
        ),
        SafeRemoveIndexConcurrently(
            model_name="activitylog",
            name="idx_alog_team_created_at",
        ),
    ]
