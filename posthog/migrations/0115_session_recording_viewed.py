# Generated by Django 3.0.11 on 2021-01-19 16:11

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0114_fix_team_event_names"),
    ]

    operations = [
        migrations.CreateModel(
            name="SessionRecordingViewed",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True, null=True)),
                ("session_id", models.CharField(max_length=200)),
                (
                    "team",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="posthog.Team"),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
        ),
        migrations.AddIndex(
            model_name="sessionrecordingviewed",
            index=models.Index(
                fields=["team_id", "user_id", "session_id"],
                name="posthog_ses_team_id_465af1_idx",
            ),
        ),
        migrations.AlterUniqueTogether(
            name="sessionrecordingviewed",
            unique_together={("team_id", "user_id", "session_id")},
        ),
    ]
