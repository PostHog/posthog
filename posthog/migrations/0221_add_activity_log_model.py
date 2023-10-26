# Generated by Django 3.2.12 on 2022-03-17 11:39

import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models

import posthog.models.activity_logging.activity_log
import posthog.models.utils


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0220_backfill_primary_dashboards"),
    ]

    operations = [
        migrations.CreateModel(
            name="ActivityLog",
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
                ("team_id", models.PositiveIntegerField(null=True)),
                ("organization_id", models.UUIDField(null=True)),
                ("activity", models.CharField(max_length=79)),
                ("item_id", models.CharField(max_length=72, null=True)),
                ("scope", models.CharField(max_length=79)),
                (
                    "detail",
                    models.JSONField(
                        encoder=posthog.models.activity_logging.activity_log.ActivityDetailEncoder,
                        null=True,
                    ),
                ),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "user",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
        ),
        migrations.AddIndex(
            model_name="activitylog",
            index=models.Index(
                fields=["team_id", "scope", "item_id"],
                name="posthog_act_team_id_13a0a8_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="activitylog",
            constraint=models.CheckConstraint(
                check=models.Q(
                    ("team_id__isnull", False),
                    ("organization_id__isnull", False),
                    _connector="OR",
                ),
                name="must_have_team_or_organization_id",
            ),
        ),
    ]
