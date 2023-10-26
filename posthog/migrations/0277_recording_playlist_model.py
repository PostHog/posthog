# Generated by Django 3.2.16 on 2022-11-07 19:08

import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models

import posthog.utils


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0276_organization_usage"),
    ]

    operations = [
        migrations.CreateModel(
            name="SessionRecordingPlaylist",
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
                (
                    "short_id",
                    models.CharField(
                        blank=True,
                        default=posthog.utils.generate_short_id,
                        max_length=12,
                    ),
                ),
                ("name", models.CharField(blank=True, max_length=400, null=True)),
                (
                    "derived_name",
                    models.CharField(blank=True, max_length=400, null=True),
                ),
                ("description", models.TextField(blank=True)),
                ("pinned", models.BooleanField(default=False)),
                ("deleted", models.BooleanField(default=False)),
                ("filters", models.JSONField(default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "last_modified_at",
                    models.DateTimeField(default=django.utils.timezone.now),
                ),
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
                        related_name="modified_recordings",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "team",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="posthog.team"),
                ),
            ],
            options={
                "unique_together": {("team", "short_id")},
            },
        ),
    ]
