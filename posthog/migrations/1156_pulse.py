import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

import posthog.models.utils


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1155_sharingconfiguration_interviewee_context"),
    ]

    operations = [
        migrations.CreateModel(
            name="PulseDigest",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=posthog.models.utils.UUIDT, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("period_start", models.DateTimeField()),
                ("period_end", models.DateTimeField()),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("generating", "Generating"),
                            ("delivered", "Delivered"),
                            ("failed", "Failed"),
                        ],
                        default="pending",
                        max_length=20,
                    ),
                ),
                ("delivered_to", models.JSONField(blank=True, default=dict)),
                ("workflow_run_id", models.CharField(blank=True, default="", max_length=255)),
                ("error", models.JSONField(blank=True, null=True)),
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
                    "team",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="pulse_digests",
                        to="posthog.team",
                    ),
                ),
            ],
            options={
                "abstract": False,
            },
        ),
        migrations.AddIndex(
            model_name="pulsedigest",
            index=models.Index(fields=["team", "-created_at"], name="posthog_pul_team_id_5a6c7d_idx"),
        ),
        migrations.CreateModel(
            name="PulseFinding",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=posthog.models.utils.UUIDT, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("metric_descriptor", models.JSONField()),
                ("metric_label", models.CharField(blank=True, default="", max_length=255)),
                ("current_value", models.FloatField()),
                ("baseline_value", models.FloatField()),
                ("change_pct", models.FloatField()),
                ("z_score", models.FloatField()),
                ("attribution_breakdown", models.JSONField(blank=True, null=True)),
                ("narrative", models.TextField()),
                ("chart_thumbnail_url", models.URLField(blank=True, default="", max_length=2048)),
                (
                    "feedback",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("up", "Thumbs Up"),
                            ("down", "Thumbs Down"),
                            ("dismissed", "Dismissed"),
                            ("snoozed", "Snoozed"),
                        ],
                        default="pending",
                        max_length=20,
                    ),
                ),
                ("feedback_at", models.DateTimeField(blank=True, null=True)),
                ("snoozed_until", models.DateTimeField(blank=True, null=True)),
                ("rank", models.IntegerField(default=0)),
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
                    "feedback_user",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="pulse_feedback",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "digest",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="findings",
                        to="posthog.pulsedigest",
                    ),
                ),
            ],
            options={
                "ordering": ["rank", "-created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="pulsefinding",
            index=models.Index(fields=["digest", "rank"], name="posthog_pul_digest__a1b2c3_idx"),
        ),
        migrations.AddIndex(
            model_name="pulsefinding",
            index=models.Index(fields=["digest", "feedback"], name="posthog_pul_digest__d4e5f6_idx"),
        ),
        migrations.CreateModel(
            name="PulseSubscription",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=posthog.models.utils.UUIDT, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("enabled", models.BooleanField(default=False)),
                (
                    "frequency",
                    models.CharField(
                        choices=[("weekly", "Weekly"), ("daily", "Daily")],
                        default="weekly",
                        max_length=10,
                    ),
                ),
                ("enabled_channels", models.JSONField(blank=True, default=list)),
                ("slack_channel_id", models.CharField(blank=True, default="", max_length=64)),
                ("email_recipients", models.JSONField(blank=True, default=list)),
                ("last_scan_at", models.DateTimeField(blank=True, null=True)),
                ("next_scan_at", models.DateTimeField(blank=True, null=True)),
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
                    "team",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="pulse_subscription",
                        to="posthog.team",
                    ),
                ),
            ],
        ),
    ]
