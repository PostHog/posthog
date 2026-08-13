from django.db import migrations, models

import posthog.models.utils


class Migration(migrations.Migration):
    dependencies = [("dashboards", "0020_migrate_dashboard_group_sections")]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveConstraint(
                    model_name="dashboardtile",
                    name="dash_tile_exactly_one_related_object",
                ),
                migrations.RemoveField(
                    model_name="dashboardtile",
                    name="dashboard_group",
                ),
                migrations.AddConstraint(
                    model_name="dashboardtile",
                    constraint=models.CheckConstraint(
                        condition=posthog.models.utils.build_unique_relationship_check(
                            ("insight", "text", "button_tile", "widget")
                        ),
                        name="dash_tile_exactly_one_related_object",
                    ),
                ),
            ],
            database_operations=[],
        )
    ]
