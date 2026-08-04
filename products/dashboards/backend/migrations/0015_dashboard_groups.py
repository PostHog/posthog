import django.utils.timezone
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

import posthog.models.utils


class Migration(migrations.Migration):
    dependencies = [("dashboards", "0014_backfill_dashboardtemplate_button_tile_type")]

    operations = [
        migrations.CreateModel(
            name="DashboardGroup",
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
                ("name", models.CharField(max_length=400)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("last_modified_at", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        db_constraint=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "dashboard",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="groups",
                        to="dashboards.dashboard",
                    ),
                ),
                (
                    "last_modified_by",
                    models.ForeignKey(
                        blank=True,
                        db_constraint=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="modified_dashboard_groups",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "team",
                    models.ForeignKey(
                        db_constraint=False,
                        on_delete=django.db.models.deletion.CASCADE,
                        to="posthog.team",
                    ),
                ),
            ],
            options={"db_table": "posthog_dashboardgroup", "default_manager_name": "all_teams"},
            managers=[("all_teams", models.Manager())],
        ),
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
                        db_constraint=False,
                        db_index=False,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="member_tiles",
                        to="dashboards.dashboardgroup",
                    ),
                ),
                migrations.RemoveConstraint(
                    model_name="dashboardtile",
                    name="dash_tile_exactly_one_related_object",
                ),
                migrations.AddConstraint(
                    model_name="dashboardtile",
                    constraint=models.CheckConstraint(
                        condition=posthog.models.utils.build_unique_relationship_check(
                            ("insight", "text", "button_tile", "widget", "dashboard_group")
                        ),
                        name="dash_tile_exactly_one_related_object",
                    ),
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql="""
                        SET LOCAL lock_timeout = '5s';
                        ALTER TABLE "posthog_dashboardtile" ADD COLUMN "dashboard_group_id" uuid NULL;
                        ALTER TABLE "posthog_dashboardtile" ADD COLUMN "parent_group_id" uuid NULL;
                    """,
                    reverse_sql="""
                        ALTER TABLE "posthog_dashboardtile" DROP COLUMN IF EXISTS "parent_group_id";
                        ALTER TABLE "posthog_dashboardtile" DROP COLUMN IF EXISTS "dashboard_group_id";
                    """,
                )
            ],
        ),
    ]
