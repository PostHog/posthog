# Generated by Django 4.2.14 on 2024-08-16 09:39

from django.conf import settings
import django.core.validators
from django.db import migrations, models
import django.db.models.deletion
import posthog.models.utils


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0457_datawarehousejoin_deleted_at_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="AlertConfiguration",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "id",
                    models.UUIDField(
                        default=posthog.models.utils.UUIDT, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("name", models.CharField(max_length=100)),
                ("notification_targets", models.JSONField(default=dict)),
                ("condition", models.JSONField(default=dict)),
                (
                    "state",
                    models.CharField(
                        choices=[("firing", "Firing"), ("inactive", "Inactive")], default="inactive", max_length=10
                    ),
                ),
                (
                    "notification_frequency",
                    models.IntegerField(
                        default=60,
                        help_text="Frequency in minutes",
                        validators=[
                            django.core.validators.MinValueValidator(60),
                            django.core.validators.MaxValueValidator(1440),
                        ],
                    ),
                ),
                ("last_notified_at", models.DateTimeField(blank=True, null=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL
                    ),
                ),
                ("insight", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="posthog.insight")),
                ("team", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="posthog.team")),
            ],
            options={
                "abstract": False,
            },
        ),
        migrations.CreateModel(
            name="AlertCheck",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=posthog.models.utils.UUIDT, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("calculated_value", models.FloatField(blank=True, null=True)),
                ("condition", models.JSONField(default=dict)),
                ("targets_notified", models.JSONField(default=dict)),
                ("error_message", models.TextField(blank=True, null=True)),
                (
                    "state",
                    models.CharField(
                        choices=[("firing", "Firing"), ("cooldown", "Cooldown"), ("not_met", "Not Met")],
                        default="not_met",
                        max_length=10,
                    ),
                ),
                (
                    "alert_configuration",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="posthog.alertconfiguration"),
                ),
            ],
            options={
                "abstract": False,
            },
        ),
    ]
