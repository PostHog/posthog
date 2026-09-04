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
    ]
