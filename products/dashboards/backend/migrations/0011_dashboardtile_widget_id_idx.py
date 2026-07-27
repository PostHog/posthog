# Generated manually for dashboard widget entity

from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("dashboards", "0010_validate_dashboardtile_check"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddConstraint(
                    model_name="dashboardtile",
                    constraint=models.UniqueConstraint(
                        fields=["dashboard", "widget"],
                        name="unique_dashboard_widget",
                        condition=Q(("widget__isnull", False)),
                    ),
                ),
            ],
        ),
        migrations.RunSQL(
            sql=(
                'CREATE INDEX CONCURRENTLY IF NOT EXISTS "posthog_dashboardtile_widget_id_idx" '
                'ON "posthog_dashboardtile" ("widget_id") '
                'WHERE "widget_id" IS NOT NULL'
            ),
            reverse_sql='DROP INDEX CONCURRENTLY IF EXISTS "posthog_dashboardtile_widget_id_idx"',
        ),
        migrations.RunSQL(
            sql=(
                'CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS "unique_dashboard_widget" '
                'ON "posthog_dashboardtile" ("dashboard_id", "widget_id") '
                'WHERE "widget_id" IS NOT NULL'
            ),
            reverse_sql='DROP INDEX CONCURRENTLY IF EXISTS "unique_dashboard_widget"',
        ),
    ]
