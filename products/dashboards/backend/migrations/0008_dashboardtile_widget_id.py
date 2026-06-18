# Generated manually for dashboard widget entity

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("dashboards", "0007_dashboardwidget_table"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddField(
                    model_name="dashboardtile",
                    name="widget",
                    field=models.ForeignKey(
                        db_index=False,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="dashboard_tiles",
                        to="dashboards.dashboardwidget",
                    ),
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql="""
                        ALTER TABLE "posthog_dashboardtile" ADD COLUMN "widget_id" uuid NULL;
                        ALTER TABLE "posthog_dashboardtile" ADD CONSTRAINT "posthog_dashboardtile_widget_id_fk" -- existing-table-constraint-ignore
                        FOREIGN KEY ("widget_id") REFERENCES "posthog_dashboardwidget"("id") ON DELETE RESTRICT NOT VALID;
                    """,
                    reverse_sql="""
                        ALTER TABLE "posthog_dashboardtile" DROP CONSTRAINT IF EXISTS "posthog_dashboardtile_widget_id_fk";
                        ALTER TABLE "posthog_dashboardtile" DROP COLUMN IF EXISTS "widget_id";
                    """,
                ),
            ],
        ),
    ]
