# Generated by Django 4.2.11 on 2024-07-05 17:37

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0433_dashboard_idx_dashboard_deleted_team_id"),
    ]

    operations = [
        migrations.CreateModel(
            name="ErrorTrackingGroup",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("archived", "Archived"),
                            ("active", "Active"),
                            ("resolved", "Resolved"),
                            ("pending_release", "Pending release"),
                        ],
                        default="active",
                        max_length=40,
                    ),
                ),
                (
                    "assignee",
                    models.ForeignKey(
                        blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL
                    ),
                ),
                ("team", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="posthog.team")),
            ],
        ),
        migrations.CreateModel(
            name="ErrorTrackingFingerprint",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("value", models.CharField(max_length=200)),
                (
                    "group",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="posthog.errortrackinggroup"),
                ),
            ],
        ),
    ]
