from django.db import migrations

from posthog.migration_helpers import ValidateConstraint, ValidateForeignKey


class Migration(migrations.Migration):
    dependencies = [
        ("dashboards", "0017_dashboard_group_constraints"),
    ]

    operations = [
        ValidateConstraint(model_name="dashboardtile", name="dash_tile_exactly_one_related_object"),
        ValidateConstraint(model_name="dashboardtile", name="dash_tile_group_header_not_member"),
        ValidateForeignKey(model_name="dashboardtile", name="posthog_dashboardtile_dashboard_group_id_fk"),
        ValidateForeignKey(model_name="dashboardtile", name="posthog_dashboardtile_parent_group_id_fk"),
    ]
