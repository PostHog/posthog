import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

import posthog.uuidt


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("posthog", "0001_squash_2026_09_07_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="CrossProjectDashboard",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True, null=True, blank=True)),
                (
                    "id",
                    models.UUIDField(default=posthog.uuidt.uuid7, editable=False, primary_key=True, serialize=False),
                ),
                ("name", models.CharField(max_length=400)),
                ("description", models.TextField(blank=True, default="")),
                ("deleted", models.BooleanField(default=False)),
                ("filters", models.JSONField(blank=True, default=dict)),
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
                    "organization",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="cross_project_dashboards",
                        to="posthog.organization",
                    ),
                ),
            ],
            options={"abstract": False},
        ),
        migrations.CreateModel(
            name="CrossProjectDashboardTile",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True, null=True, blank=True)),
                (
                    "id",
                    models.UUIDField(default=posthog.uuidt.uuid7, editable=False, primary_key=True, serialize=False),
                ),
                ("project_id", models.BigIntegerField()),
                ("insight_id", models.BigIntegerField()),
                ("layouts", models.JSONField(blank=True, default=dict)),
                ("color", models.CharField(blank=True, max_length=400, null=True)),
                ("filters_overrides", models.JSONField(blank=True, default=dict)),
                ("deleted", models.BooleanField(default=False)),
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
                    "dashboard",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="tiles",
                        to="cross_project_dashboards.crossprojectdashboard",
                    ),
                ),
                (
                    "organization",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="cross_project_dashboard_tiles",
                        to="posthog.organization",
                    ),
                ),
            ],
            options={"abstract": False},
        ),
        migrations.AddIndex(
            model_name="crossprojectdashboard",
            index=models.Index(fields=["organization", "deleted"], name="cpd_org_deleted_idx"),
        ),
        migrations.AddIndex(
            model_name="crossprojectdashboardtile",
            index=models.Index(fields=["dashboard", "deleted"], name="cpd_tile_dash_deleted_idx"),
        ),
        migrations.AddConstraint(
            model_name="crossprojectdashboardtile",
            constraint=models.UniqueConstraint(
                condition=models.Q(("deleted", False)),
                fields=("dashboard", "project_id", "insight_id"),
                name="unique_live_tile_per_dashboard_insight",
            ),
        ),
    ]
