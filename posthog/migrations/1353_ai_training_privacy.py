import django.utils.timezone
from django.db import migrations, models

import posthog.models.utils


class Migration(migrations.Migration):
    dependencies = [("posthog", "1352_email_lookup_indexes")]

    operations = [
        migrations.CreateModel(
            name="AITrainingConsent",
            fields=[
                ("organization_id", models.UUIDField(primary_key=True, serialize=False)),
                ("allowed", models.BooleanField(default=False)),
                ("granted_at_ms", models.BigIntegerField(default=0)),
                ("changed_at_ms", models.BigIntegerField(default=0)),
                ("revision", models.BigIntegerField(default=0)),
            ],
        ),
        migrations.CreateModel(
            name="AITrainingPrivacyRequest",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        primary_key=True, default=posthog.models.utils.uuid7, editable=False, serialize=False
                    ),
                ),
                ("organization_id", models.UUIDField(null=True)),
                ("team_id", models.BigIntegerField(null=True)),
                ("kind", models.CharField(max_length=32)),
                ("identifiers", models.JSONField(default=list)),
                ("allowed", models.BooleanField(null=True)),
                ("granted_at_ms", models.BigIntegerField(default=0)),
                ("changed_at_ms", models.BigIntegerField(default=0)),
                ("revision", models.BigIntegerField(default=0)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("leased_until", models.DateTimeField(default=django.utils.timezone.now)),
                ("completed_at", models.DateTimeField(null=True)),
                ("cursor", models.JSONField(default=dict)),
            ],
            managers=[("all_teams", models.Manager())],
            options={
                "default_manager_name": "all_teams",
                "indexes": [
                    models.Index(
                        fields=["created_at"],
                        condition=models.Q(completed_at__isnull=True),
                        name="ai_training_pending_requests",
                    )
                ],
            },
        ),
    ]
