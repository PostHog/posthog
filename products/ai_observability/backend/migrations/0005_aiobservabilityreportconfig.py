import django.db.models.manager
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

import posthog.models.utils


class Migration(migrations.Migration):
    dependencies = [
        ("ai_observability", "0004_parserrecipe"),
        ("posthog", "1207_migrate_ai_observability_models"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="AIObservabilityReportConfig",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True, null=True)),
                (
                    "id",
                    models.UUIDField(
                        default=posthog.models.utils.uuid7,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("enabled", models.BooleanField(db_default=True, default=True)),
                ("skill_name", models.CharField(max_length=200)),
                ("slack_channel", models.CharField(max_length=255)),
                ("additional_instructions", models.TextField(blank=True, default="")),
                ("last_run_at", models.DateTimeField(blank=True, null=True)),
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
                    "slack_integration",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to="posthog.integration",
                    ),
                ),
                (
                    "team",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="ai_observability_report_configs",
                        to="posthog.team",
                    ),
                ),
            ],
            options={
                "verbose_name": "AI observability report config",
                "verbose_name_plural": "AI observability report configs",
                "default_manager_name": "all_teams",
            },
            managers=[
                ("all_teams", django.db.models.manager.Manager()),
            ],
        ),
        migrations.AddConstraint(
            model_name="aiobservabilityreportconfig",
            constraint=models.UniqueConstraint(fields=("team",), name="unique_ai_observability_report_config_per_team"),
        ),
    ]
