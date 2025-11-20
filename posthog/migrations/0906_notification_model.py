# Generated migration for unified notifications hub

import django.db.models.deletion
from django.db import migrations, models

import posthog.models.utils


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0905_alter_person_table"),
    ]

    operations = [
        migrations.CreateModel(
            name="Notification",
            fields=[
                ("id", models.UUIDField(default=posthog.models.utils.uuid7, primary_key=True, serialize=False)),
                (
                    "resource_type",
                    models.CharField(
                        db_index=True,
                        max_length=64,
                        help_text="Type of resource (e.g., 'feature_flag', 'insight', 'alert', 'approval', 'workflow_error')",
                    ),
                ),
                (
                    "resource_id",
                    models.CharField(
                        blank=True,
                        max_length=255,
                        null=True,
                        help_text="Optional ID of the specific resource for deep linking",
                    ),
                ),
                (
                    "title",
                    models.CharField(
                        max_length=255, help_text="Brief notification title (e.g., 'Feature flag updated')"
                    ),
                ),
                ("message", models.TextField(help_text="Full notification message")),
                (
                    "context",
                    models.JSONField(
                        default=dict, help_text="Additional metadata for rendering (e.g., actor, changes, links)"
                    ),
                ),
                (
                    "priority",
                    models.CharField(
                        choices=[("low", "Low"), ("normal", "Normal"), ("high", "High"), ("urgent", "Urgent")],
                        default="normal",
                        max_length=16,
                        db_index=True,
                    ),
                ),
                (
                    "read_at",
                    models.DateTimeField(
                        blank=True, db_index=True, null=True, help_text="Timestamp when notification was marked as read"
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                (
                    "team",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="notifications",
                        to="posthog.team",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="notifications",
                        to="posthog.user",
                    ),
                ),
            ],
            options={
                "db_table": "posthog_notification",
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="notification",
            index=models.Index(fields=["user", "read_at", "-created_at"], name="notif_user_read_created_idx"),
        ),
        migrations.AddIndex(
            model_name="notification",
            index=models.Index(fields=["team", "resource_type", "-created_at"], name="notif_team_type_created_idx"),
        ),
        migrations.AddIndex(
            model_name="notification",
            index=models.Index(fields=["user", "read_at"], name="notif_user_unread_idx"),
        ),
    ]
