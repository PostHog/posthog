# Generated migration

import django.db.models.deletion
from django.db import migrations, models

import posthog.models.utils


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0955_alter_organization_is_ai_data_processing_approved"),
    ]

    operations = [
        migrations.CreateModel(
            name="SessionRecordingExternalReference",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=posthog.models.utils.UUIDT, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("external_context", models.JSONField(blank=True, null=True)),
                (
                    "integration",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="posthog.integration"),
                ),
                (
                    "session_recording",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="external_references",
                        related_query_name="external_reference",
                        to="posthog.sessionrecording",
                    ),
                ),
            ],
            options={
                "db_table": "posthog_sessionrecordingexternalreference",
            },
        ),
    ]
