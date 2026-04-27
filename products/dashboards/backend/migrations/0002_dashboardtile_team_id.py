from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1072_backfill_condition_aggregation"),
        ("dashboards", "0001_migrate_dashboards_models"),
    ]

    operations = [
        migrations.AddField(
            model_name="dashboardtile",
            name="team",
            field=models.ForeignKey(blank=True, null=True, on_delete=models.deletion.CASCADE, to="posthog.team"),
        ),
        migrations.RunSQL(
            sql="""
            UPDATE posthog_dashboardtile AS tile
            SET team_id = dashboard.team_id
            FROM posthog_dashboard AS dashboard
            WHERE tile.dashboard_id = dashboard.id
              AND tile.team_id IS NULL
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
