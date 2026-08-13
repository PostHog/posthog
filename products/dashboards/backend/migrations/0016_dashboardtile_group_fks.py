import django.db.models.deletion
from django.db import migrations, models

from posthog.migration_helpers import AddForeignKeyNotValid


class Migration(migrations.Migration):
    dependencies = [
        ("dashboards", "0015_dashboard_groups"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddField(
                    model_name="dashboardtile",
                    name="dashboard_group",
                    field=models.OneToOneField(
                        db_constraint=False,
                        db_index=False,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="tile",
                        to="dashboards.dashboardgroup",
                    ),
                ),
                migrations.AddField(
                    model_name="dashboardtile",
                    name="parent_group",
                    field=models.ForeignKey(
                        blank=True,
                        db_constraint=False,
                        db_index=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="member_tiles",
                        to="dashboards.dashboardgroup",
                    ),
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql="""
                        ALTER TABLE "posthog_dashboardtile" ADD COLUMN "dashboard_group_id" uuid NULL;
                        ALTER TABLE "posthog_dashboardtile" ADD COLUMN "parent_group_id" uuid NULL;
                    """,
                    reverse_sql="""
                        ALTER TABLE "posthog_dashboardtile" DROP COLUMN IF EXISTS "parent_group_id";
                        ALTER TABLE "posthog_dashboardtile" DROP COLUMN IF EXISTS "dashboard_group_id";
                    """,
                ),
            ],
        ),
        AddForeignKeyNotValid(
            model_name="dashboardtile",
            name="posthog_dashboardtile_dashboard_group_id_fk",
            column="dashboard_group_id",
            to_table="posthog_dashboardgroup",
        ),
        AddForeignKeyNotValid(
            model_name="dashboardtile",
            name="posthog_dashboardtile_parent_group_id_fk",
            column="parent_group_id",
            to_table="posthog_dashboardgroup",
        ),
    ]
