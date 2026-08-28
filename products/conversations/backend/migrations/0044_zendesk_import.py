from django.db import migrations, models

import posthog.models.utils
from posthog.helpers.encrypted_fields import EncryptedJSONField


class Migration(migrations.Migration):
    dependencies = [
        ("conversations", "0043_backfill_identity_verified"),
    ]

    operations = [
        migrations.AddField(
            model_name="ticket",
            name="zendesk_ticket_id",
            field=models.BigIntegerField(blank=True, null=True),
        ),
        migrations.CreateModel(
            name="ZendeskImportJob",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=posthog.models.utils.uuid7, editable=False, primary_key=True, serialize=False
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("running", "Running"),
                            ("completed", "Completed"),
                            ("failed", "Failed"),
                        ],
                        default="pending",
                        max_length=32,
                    ),
                ),
                ("total_tickets", models.BigIntegerField(default=0)),
                ("processed_tickets", models.BigIntegerField(default=0)),
                ("imported_tickets", models.BigIntegerField(default=0)),
                ("skipped_tickets", models.BigIntegerField(default=0)),
                ("failed_tickets", models.BigIntegerField(default=0)),
                ("export_cursor", models.TextField(blank=True, null=True)),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
                ("workflow_id", models.CharField(blank=True, max_length=400, null=True)),
                ("workflow_run_id", models.CharField(blank=True, max_length=400, null=True)),
                ("latest_error", models.TextField(blank=True, null=True)),
                ("job_inputs", EncryptedJSONField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "team",
                    models.ForeignKey(db_constraint=False, on_delete=models.deletion.CASCADE, to="posthog.team"),
                ),
            ],
            options={
                "db_table": "posthog_conversations_zendesk_import_job",
                "indexes": [
                    models.Index(fields=["team", "-created_at"], name="posthog_con_zd_import_team_idx"),
                    models.Index(fields=["team", "status"], name="posthog_con_zd_import_stat_idx"),
                ],
            },
        ),
    ]
