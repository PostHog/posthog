from django.db import migrations

from posthog.migration_helpers import CreateIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("dashboards", "0018_validate_dashboard_group_constraints"),
    ]

    operations = [
        CreateIndexConcurrently(
            index_name="posthog_dashboardtile_dashboard_group_id_key",
            table_name="posthog_dashboardtile",
            columns='("dashboard_group_id")',
            where='WHERE "dashboard_group_id" IS NOT NULL',
            unique=True,
        ),
        CreateIndexConcurrently(
            index_name="posthog_dashboardtile_parent_group_id_idx",
            table_name="posthog_dashboardtile",
            columns='("parent_group_id")',
            where='WHERE "parent_group_id" IS NOT NULL',
        ),
    ]
