import django.utils.timezone
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

import posthog.models.utils


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1050_rename_slack_twig_to_posthog_code"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="DashboardWidget",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "widget_type",
                    models.CharField(
                        choices=[
                            ("experiment", "Experiment"),
                            ("logs", "Logs"),
                            ("error_tracking", "Error tracking"),
                            ("session_replays", "Session replays"),
                            ("survey_responses", "Survey responses"),
                        ],
                        max_length=40,
                    ),
                ),
                ("config", models.JSONField(default=dict)),
                ("last_modified_at", models.DateTimeField(default=django.utils.timezone.now)),
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
                ("team", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="posthog.team")),
            ],
        ),
        migrations.AddField(
            model_name="dashboardtile",
            name="widget",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="dashboard_tiles",
                to="posthog.dashboardwidget",
            ),
        ),
        migrations.RemoveConstraint(
            model_name="dashboardtile",
            name="dash_tile_exactly_one_related_object",
        ),
        migrations.AddConstraint(
            model_name="dashboardtile",
            constraint=models.UniqueConstraint(
                condition=models.Q(("widget__isnull", False)),
                fields=("dashboard", "widget"),
                name="unique_dashboard_widget",
            ),
        ),
        migrations.AddConstraint(
            model_name="dashboardtile",
            constraint=models.CheckConstraint(
                check=posthog.models.utils.build_unique_relationship_check(("insight", "text", "widget")),
                name="dash_tile_exactly_one_related_object",
            ),
        ),
    ]
