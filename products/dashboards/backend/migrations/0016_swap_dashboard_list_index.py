from django.db import migrations, models

from posthog.migration_helpers.concurrent_index import SafeAddIndexConcurrently, SafeRemoveIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("dashboards", "0015_dashboard_customization"),
    ]

    operations = [
        # The dropped index is partial on deleted=false and lists team_id last, so the dashboards
        # list query (team_id equality, ORDER BY -pinned, name, no deleted filter) can never use it.
        SafeRemoveIndexConcurrently(
            model_name="dashboard",
            name="idx_dashboard_deleted_team_id",
        ),
        SafeAddIndexConcurrently(
            model_name="dashboard",
            index=models.Index(
                name="idx_dashboard_team_pinned_name",
                fields=["team", "-pinned", "name"],
            ),
        ),
    ]
