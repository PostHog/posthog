from django.db import migrations

from posthog.migration_helpers.concurrent_index import SafeRemoveIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("posthog", "1340_drop_userproductlist_reason_columns"),
    ]

    operations = [
        SafeRemoveIndexConcurrently(
            model_name="activitylog",
            name="activitylog_detail_gin",
        ),
    ]
