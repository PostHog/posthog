import django.utils.timezone
import django.db.models.deletion
import django.contrib.postgres.fields
from django.conf import settings
from django.db import migrations, models

import posthog.models.utils


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1050_rename_slack_twig_to_posthog_code"),
    ]

    operations = [
        migrations.CreateModel(
            name="DataDeletionRequest",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=posthog.models.utils.uuid7,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("team_id", models.IntegerField()),
                (
                    "request_type",
                    models.CharField(
                        choices=[
                            ("property_removal", "Property Removal"),
                            ("event_removal", "Event Removal"),
                        ],
                        max_length=40,
                    ),
                ),
                ("start_time", models.DateTimeField()),
                ("end_time", models.DateTimeField()),
                (
                    "events",
                    django.contrib.postgres.fields.ArrayField(
                        base_field=models.CharField(max_length=400),
                        size=None,
                    ),
                ),
                (
                    "properties",
                    django.contrib.postgres.fields.ArrayField(
                        base_field=models.CharField(max_length=400),
                        blank=True,
                        default=list,
                        size=None,
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("approved", "Approved"),
                            ("in_progress", "In Progress"),
                            ("completed", "Completed"),
                            ("failed", "Failed"),
                        ],
                        default="pending",
                        max_length=40,
                    ),
                ),
                ("count", models.BigIntegerField(blank=True, null=True)),
                ("part_count", models.IntegerField(blank=True, null=True)),
                ("parts_size", models.BigIntegerField(blank=True, null=True)),
                ("notes", models.TextField(blank=True, default="")),
                (
                    "created_at",
                    models.DateTimeField(default=django.utils.timezone.now),
                ),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("requires_approval", models.BooleanField(default=True)),
                ("approved", models.BooleanField(default=False)),
                ("approved_at", models.DateTimeField(blank=True, null=True)),
                (
                    "approved_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="data_deletion_requests_approved",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="data_deletion_requests_created",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
    ]
