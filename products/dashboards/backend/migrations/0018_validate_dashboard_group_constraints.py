from django.db import migrations

from posthog.migration_helpers import ValidateConstraint, ValidateForeignKey


class Migration(migrations.Migration):
    dependencies = [("dashboards", "0017_dashboard_group_constraints")]

    operations = [
        ValidateForeignKey(model_name="dashboardgroup", name="dashboardgroup_team_id_fk"),
        ValidateForeignKey(model_name="dashboardgroup", name="dashboardgroup_created_by_id_fk"),
        ValidateForeignKey(model_name="dashboardgroup", name="dashboardgroup_last_modified_by_id_fk"),
        ValidateForeignKey(model_name="dashboardtile", name="dashboardtile_dashboard_group_id_fk"),
        ValidateForeignKey(model_name="dashboardtile", name="dashboardtile_parent_group_id_fk"),
        ValidateConstraint(model_name="dashboardtile", name="dash_tile_exactly_one_related_object"),
    ]
