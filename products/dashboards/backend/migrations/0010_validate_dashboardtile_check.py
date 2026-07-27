# Generated manually for dashboard widget entity

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("dashboards", "0009_dashboardtile_check_4way"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
                ALTER TABLE "posthog_dashboardtile" VALIDATE CONSTRAINT "dash_tile_exactly_one_related_object";
                ALTER TABLE "posthog_dashboardtile" VALIDATE CONSTRAINT "posthog_dashboardtile_widget_id_fk";
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
