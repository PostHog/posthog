import django.db.models.deletion
from django.db import migrations, models

import posthog.models.utils


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0906_notification_model"),
    ]

    operations = [
        migrations.CreateModel(
            name="NotificationPreference",
            fields=[
                ("id", models.UUIDField(default=posthog.models.utils.uuid7, primary_key=True, serialize=False)),
                (
                    "resource_type",
                    models.CharField(
                        db_index=True,
                        max_length=64,
                        help_text="Type of resource (e.g., 'feature_flag', 'insight', 'alert')",
                    ),
                ),
                (
                    "enabled",
                    models.BooleanField(default=True, help_text="Whether user wants to receive this notification type"),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "team",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="notification_preferences",
                        to="posthog.team",
                        db_index=True,
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="notification_preferences",
                        to="posthog.user",
                        db_index=True,
                    ),
                ),
            ],
            options={
                "db_table": "posthog_notification_preference",
            },
        ),
        migrations.AddConstraint(
            model_name="notificationpreference",
            constraint=models.UniqueConstraint(
                fields=["user", "team", "resource_type"],
                name="unique_user_team_resource_type",
            ),
        ),
        migrations.AddIndex(
            model_name="notificationpreference",
            index=models.Index(fields=["team", "resource_type"], name="notif_pref_team_type_idx"),
        ),
        migrations.AddIndex(
            model_name="notificationpreference",
            index=models.Index(fields=["user", "team"], name="notif_pref_user_team_idx"),
        ),
    ]
