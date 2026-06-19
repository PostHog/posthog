# Generated manually for dashboard widget entity

import django.utils.timezone
import django.db.models.manager
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

import posthog.models.utils


class Migration(migrations.Migration):
    dependencies = [
        ("dashboards", "0006_migrate_product_analytics_models"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.CreateModel(
                    name="DashboardWidget",
                    fields=[
                        (
                            "id",
                            models.UUIDField(
                                default=posthog.models.utils.uuid7,
                                editable=False,
                                primary_key=True,
                                serialize=False,
                            ),
                        ),
                        ("widget_type", models.CharField(max_length=64)),
                        ("name", models.CharField(blank=True, max_length=400, null=True)),
                        ("description", models.TextField(blank=True)),
                        ("config", models.JSONField(default=dict)),
                        (
                            "last_modified_at",
                            models.DateTimeField(default=django.utils.timezone.now),
                        ),
                        (
                            "created_by",
                            models.ForeignKey(
                                blank=True,
                                null=True,
                                on_delete=django.db.models.deletion.SET_NULL,
                                to=settings.AUTH_USER_MODEL,
                            ),
                        ),
                        (
                            "last_modified_by",
                            models.ForeignKey(
                                blank=True,
                                null=True,
                                on_delete=django.db.models.deletion.SET_NULL,
                                related_name="modified_dashboard_widgets",
                                to=settings.AUTH_USER_MODEL,
                            ),
                        ),
                        (
                            "team",
                            models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="posthog.team"),
                        ),
                    ],
                    managers=[
                        ("all_teams", django.db.models.manager.Manager()),
                    ],
                    options={
                        "db_table": "posthog_dashboardwidget",
                        "default_manager_name": "all_teams",
                    },
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql="""
                        CREATE TABLE "posthog_dashboardwidget" (
                            "id" uuid NOT NULL PRIMARY KEY,
                            "widget_type" varchar(64) NOT NULL,
                            "name" varchar(400) NULL,
                            "description" text NOT NULL,
                            "config" jsonb NOT NULL,
                            "last_modified_at" timestamp with time zone NOT NULL,
                            "created_by_id" integer NULL REFERENCES "posthog_user" ("id") DEFERRABLE INITIALLY DEFERRED,
                            "last_modified_by_id" integer NULL REFERENCES "posthog_user" ("id") DEFERRABLE INITIALLY DEFERRED,
                            "team_id" integer NOT NULL REFERENCES "posthog_team" ("id") DEFERRABLE INITIALLY DEFERRED
                        );
                        CREATE INDEX IF NOT EXISTS "posthog_dashboardwidget_created_by_id" ON "posthog_dashboardwidget" ("created_by_id");
                        CREATE INDEX IF NOT EXISTS "posthog_dashboardwidget_last_modified_by_id" ON "posthog_dashboardwidget" ("last_modified_by_id");
                        CREATE INDEX IF NOT EXISTS "posthog_dashboardwidget_team_id" ON "posthog_dashboardwidget" ("team_id");
                    """,
                    reverse_sql='DROP TABLE IF EXISTS "posthog_dashboardwidget"',
                ),
            ],
        ),
    ]
