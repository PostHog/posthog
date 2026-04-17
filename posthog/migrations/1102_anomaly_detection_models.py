# Generated manually

import django.db.models.deletion
from django.db import migrations, models

import posthog.models.utils


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1101_activitylog_client"),
    ]

    operations = [
        migrations.CreateModel(
            name="InsightAnomalyConfig",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=posthog.models.utils.UUIDT,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("excluded", models.BooleanField(default=False)),
                ("last_scored_at", models.DateTimeField(blank=True, null=True)),
                ("next_score_due_at", models.DateTimeField(blank=True, db_index=True, null=True)),
                ("last_trained_at", models.DateTimeField(blank=True, null=True)),
                ("model_storage_key", models.CharField(blank=True, default="", max_length=500)),
                ("model_version", models.IntegerField(default=0)),
                ("interval", models.CharField(blank=True, default="", max_length=20)),
                ("detector_config", models.JSONField(default=dict)),
                (
                    "insight",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="anomaly_config",
                        to="posthog.insight",
                    ),
                ),
                (
                    "team",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to="posthog.team",
                    ),
                ),
            ],
            options={
                "indexes": [
                    models.Index(
                        fields=["team_id", "excluded"],
                        name="anomaly_cfg_team_excluded",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="AnomalyScore",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=posthog.models.utils.UUIDT,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("series_index", models.IntegerField()),
                ("series_label", models.CharField(blank=True, default="", max_length=400)),
                ("timestamp", models.DateTimeField()),
                ("score", models.FloatField()),
                ("is_anomalous", models.BooleanField()),
                ("interval", models.CharField(blank=True, default="", max_length=20)),
                ("data_snapshot", models.JSONField(default=dict)),
                ("scored_at", models.DateTimeField(auto_now_add=True)),
                (
                    "insight",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="anomaly_scores",
                        to="posthog.insight",
                    ),
                ),
                (
                    "team",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to="posthog.team",
                    ),
                ),
            ],
            options={
                "indexes": [
                    models.Index(
                        fields=["team_id", "is_anomalous", "-scored_at"],
                        name="anomaly_score_team_anom_scored",
                    ),
                    models.Index(
                        fields=["team_id", "insight_id", "series_index", "-timestamp"],
                        name="anomaly_score_team_insight_ts",
                    ),
                ],
            },
        ),
    ]
