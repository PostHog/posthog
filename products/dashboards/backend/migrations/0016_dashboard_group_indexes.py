from django.db import migrations

from posthog.migration_helpers import CreateIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [("dashboards", "0015_dashboard_groups")]

    operations = [
        CreateIndexConcurrently(
            index_name="dashboardtile_dashboard_group_uidx",
            table_name="posthog_dashboardtile",
            columns="(dashboard_group_id)",
            unique=True,
        ),
        CreateIndexConcurrently(
            index_name="dashboardtile_parent_group_idx",
            table_name="posthog_dashboardtile",
            columns="(parent_group_id)",
        ),
        CreateIndexConcurrently(
            index_name="dashboardtile_dashboard_parent_group_idx",
            table_name="posthog_dashboardtile",
            columns="(dashboard_id, parent_group_id)",
        ),
    ]
