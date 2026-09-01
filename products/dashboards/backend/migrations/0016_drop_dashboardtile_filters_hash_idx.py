from django.db import migrations

from posthog.migration_helpers import SafeRemoveIndexConcurrently


class Migration(migrations.Migration):
    # Concurrent index drops cannot run inside a transaction.
    atomic = False

    dependencies = [
        ("dashboards", "0015_dashboard_customization"),
    ]

    operations = [
        SafeRemoveIndexConcurrently(
            model_name="dashboardtile",
            name="query_by_filters_hash_idx",
        ),
    ]
