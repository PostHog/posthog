from django.db import migrations

from posthog.migration_helpers import AddForeignKeyNotValid


class Migration(migrations.Migration):
    dependencies = [("dashboards", "0016_dashboard_group_indexes")]

    operations = [
        AddForeignKeyNotValid(
            model_name="dashboardgroup",
            name="dashboardgroup_team_id_fk",
            column="team_id",
            to_table="posthog_team",
        ),
        AddForeignKeyNotValid(
            model_name="dashboardgroup",
            name="dashboardgroup_created_by_id_fk",
            column="created_by_id",
            to_table="posthog_user",
        ),
        AddForeignKeyNotValid(
            model_name="dashboardgroup",
            name="dashboardgroup_last_modified_by_id_fk",
            column="last_modified_by_id",
            to_table="posthog_user",
        ),
        AddForeignKeyNotValid(
            model_name="dashboardtile",
            name="dashboardtile_dashboard_group_id_fk",
            column="dashboard_group_id",
            to_table="posthog_dashboardgroup",
        ),
        AddForeignKeyNotValid(
            model_name="dashboardtile",
            name="dashboardtile_parent_group_id_fk",
            column="parent_group_id",
            to_table="posthog_dashboardgroup",
        ),
        migrations.RunSQL(
            sql="""
                SET LOCAL lock_timeout = '5s';
                ALTER TABLE "posthog_dashboardtile" DROP CONSTRAINT IF EXISTS "dash_tile_exactly_one_related_object";
                ALTER TABLE "posthog_dashboardtile" ADD CONSTRAINT "dash_tile_exactly_one_related_object"
                CHECK (
                    (CASE WHEN "insight_id" IS NOT NULL THEN 1 ELSE 0 END) +
                    (CASE WHEN "text_id" IS NOT NULL THEN 1 ELSE 0 END) +
                    (CASE WHEN "button_tile_id" IS NOT NULL THEN 1 ELSE 0 END) +
                    (CASE WHEN "widget_id" IS NOT NULL THEN 1 ELSE 0 END) +
                    (CASE WHEN "dashboard_group_id" IS NOT NULL THEN 1 ELSE 0 END) = 1
                ) NOT VALID;
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
