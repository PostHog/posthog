import django.db.models.manager
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

import posthog.uuidt


class Migration(migrations.Migration):
    dependencies = [
        ("dashboards", "0015_dashboard_customization"),
        ("posthog", "1320_remove_oauth_scope_trgm"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="DashboardSavedView",
            fields=[
                (
                    "id",
                    models.UUIDField(default=posthog.uuidt.uuid7, editable=False, primary_key=True, serialize=False),
                ),
                ("name", models.CharField(max_length=200)),
                ("filters", models.JSONField(default=dict)),
                (
                    "scope",
                    models.CharField(
                        choices=[("private", "Private"), ("team", "Team")],
                        db_default="private",
                        default="private",
                        max_length=20,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True, null=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        db_constraint=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "team",
                    models.ForeignKey(
                        db_constraint=False,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="+",
                        to="posthog.team",
                    ),
                ),
            ],
            options={
                "db_table": "posthog_dashboard_saved_view",
                "ordering": ["id"],
                "indexes": [
                    models.Index(
                        fields=["team", "id"],
                        condition=models.Q(scope="team"),
                        name="dash_saved_view_team_idx",
                    ),
                    models.Index(
                        fields=["team", "created_by", "id"],
                        condition=models.Q(scope="private"),
                        name="dash_saved_view_private_idx",
                    ),
                ],
                "abstract": False,
            },
            managers=[
                ("all_teams", django.db.models.manager.Manager()),
            ],
        ),
    ]
