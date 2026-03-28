import django.db.models.deletion
from django.db import migrations, models

import posthog.models.utils


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1051_backfill_holdout_format"),
        ("conversations", "0024_ticket_channel_detail"),
    ]

    operations = [
        # TeamConversationsEmailConfig
        migrations.CreateModel(
            name="TeamConversationsEmailConfig",
            fields=[
                (
                    "team",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        primary_key=True,
                        serialize=False,
                        to="posthog.team",
                    ),
                ),
                ("inbound_token", models.CharField(max_length=64, unique=True, db_index=True)),
                ("from_email", models.EmailField(max_length=254)),
                ("from_name", models.CharField(max_length=255)),
                ("domain", models.CharField(max_length=255)),
                ("domain_verified", models.BooleanField(default=False)),
                ("dns_records", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "db_table": "posthog_conversations_email_config",
            },
        ),
        # EmailMessageMapping
        migrations.CreateModel(
            name="EmailMessageMapping",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=posthog.models.utils.uuid7, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("message_id", models.CharField(max_length=255, db_index=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "team",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to="posthog.team",
                    ),
                ),
                (
                    "ticket",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to="conversations.ticket",
                    ),
                ),
                (
                    "comment",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to="posthog.comment",
                    ),
                ),
            ],
            options={
                "db_table": "posthog_conversations_email_message_mapping",
                "constraints": [
                    models.UniqueConstraint(fields=["message_id", "team"], name="unique_message_per_team"),
                ],
            },
        ),
        # Ticket email fields
        migrations.AddField(
            model_name="ticket",
            name="email_subject",
            field=models.CharField(blank=True, max_length=500, null=True),
        ),
        migrations.AddField(
            model_name="ticket",
            name="email_from",
            field=models.EmailField(blank=True, max_length=254, null=True),
        ),
    ]
