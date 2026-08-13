from django.db import migrations, models
from django.db.models import Q

import posthog.models.utils
from posthog.migration_helpers import AddConstraintNotValid


class Migration(migrations.Migration):
    dependencies = [
        ("dashboards", "0016_dashboardtile_group_fks"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="dashboardtile",
            name="dash_tile_exactly_one_related_object",
        ),
        AddConstraintNotValid(
            model_name="dashboardtile",
            constraint=models.CheckConstraint(
                condition=posthog.models.utils.build_unique_relationship_check(
                    ("insight", "text", "button_tile", "widget", "dashboard_group")
                ),
                name="dash_tile_exactly_one_related_object",
            ),
        ),
        AddConstraintNotValid(
            model_name="dashboardtile",
            constraint=models.CheckConstraint(
                condition=~Q(dashboard_group__isnull=False, parent_group__isnull=False),
                name="dash_tile_group_header_not_member",
            ),
        ),
    ]
