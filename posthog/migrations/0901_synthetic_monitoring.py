# Generated manually for synthetic monitoring feature

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

import posthog.models.utils


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0900_team_receive_org_level_activity_logs"),
    ]

    operations = [
        migrations.CreateModel(
            name="SyntheticMonitor",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=posthog.models.utils.uuid7, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("name", models.CharField(max_length=400)),
                ("url", models.URLField()),
                (
                    "frequency_minutes",
                    models.IntegerField(
                        choices=[
                            (1, "1 minute"),
                            (5, "5 minutes"),
                            (15, "15 minutes"),
                            (30, "30 minutes"),
                            (60, "60 minutes"),
                        ]
                    ),
                ),
                (
                    "regions",
                    models.JSONField(
                        default=list,
                        help_text="List of regions to run checks from (e.g., ['us-east-1', 'eu-west-1'])",
                    ),
                ),
                ("method", models.CharField(default="GET", max_length=10)),
                (
                    "headers",
                    models.JSONField(
                        blank=True,
                        help_text="Custom HTTP headers as JSON object (e.g., {'Authorization': 'Bearer ...'})",
                        null=True,
                    ),
                ),
                ("body", models.TextField(blank=True, help_text="Request body for POST/PUT requests", null=True)),
                ("expected_status_code", models.IntegerField(default=200)),
                ("timeout_seconds", models.IntegerField(default=30)),
                ("alert_enabled", models.BooleanField(default=True)),
                (
                    "alert_threshold_failures",
                    models.IntegerField(
                        default=3, help_text="Number of consecutive failures before triggering an alert"
                    ),
                ),
                ("enabled", models.BooleanField(default=True)),
                (
                    "state",
                    models.CharField(
                        choices=[
                            ("healthy", "Healthy"),
                            ("failing", "Failing"),
                            ("error", "Error"),
                            ("disabled", "Disabled"),
                        ],
                        default="healthy",
                        max_length=20,
                    ),
                ),
                ("last_checked_at", models.DateTimeField(blank=True, null=True)),
                ("next_check_at", models.DateTimeField(blank=True, null=True)),
                ("consecutive_failures", models.IntegerField(default=0)),
                ("last_alerted_at", models.DateTimeField(blank=True, null=True)),
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
                        help_text="Slack integration for alert notifications",
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to="posthog.integration",
                    ),
                ),
                ("team", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="posthog.team")),
            ],
            options={
                "abstract": False,
            },
        ),
        migrations.AddField(
            model_name="syntheticmonitor",
            name="alert_recipients",
            field=models.ManyToManyField(
                blank=True,
                help_text="Users to notify when alerts trigger",
                related_name="synthetic_monitors",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddConstraint(
            model_name="syntheticmonitor",
            constraint=models.CheckConstraint(
                condition=models.Q(("frequency_minutes__in", [1, 5, 15, 30, 60])), name="valid_frequency_minutes"
            ),
        ),
        migrations.AddIndex(
            model_name="syntheticmonitor",
            index=models.Index(fields=["team", "enabled"], name="posthog_syn_team_en_idx"),
        ),
        migrations.AddIndex(
            model_name="syntheticmonitor",
            index=models.Index(fields=["next_check_at"], name="posthog_syn_next_ch_idx"),
        ),
    ]
