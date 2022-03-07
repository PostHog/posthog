# Generated by Django 3.2.12 on 2022-03-07 12:02

import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models

import posthog.models.historical_version
import posthog.models.utils


class Migration(migrations.Migration):

    dependencies = [
        ("posthog", "0216_insight_placeholder_name"),
    ]

    operations = [
        migrations.CreateModel(
            name="HistoricalVersion",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=posthog.models.utils.UUIDT, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("state", models.JSONField(encoder=posthog.models.historical_version.HistoricalVersionJSONEncoder)),
                ("name", models.CharField(max_length=79)),
                (
                    "action",
                    models.CharField(
                        blank=True,
                        choices=[("create", "Create"), ("update", "Update"), ("delete", "Delete")],
                        max_length=6,
                    ),
                ),
                ("item_id", models.CharField(max_length=72)),
                ("versioned_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("team_id", models.PositiveIntegerField(null=True)),
                ("organization_id", models.UUIDField(null=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL
                    ),
                ),
            ],
        ),
        migrations.AddIndex(
            model_name="historicalversion",
            index=models.Index(fields=["item_id", "team_id", "name"], name="posthog_his_item_id_4f5ae5_idx"),
        ),
        migrations.AddConstraint(
            model_name="historicalversion",
            constraint=models.UniqueConstraint(
                fields=("organization_id", "team_id", "name", "versioned_at"), name="unique_version"
            ),
        ),
        migrations.AddConstraint(
            model_name="historicalversion",
            constraint=models.CheckConstraint(
                check=models.Q(("team_id__isnull", False), ("organization_id__isnull", False), _connector="OR"),
                name="must_have_team_or_organization_id",
            ),
        ),
    ]
