import django.db.models.deletion
from django.db import migrations, models

import posthog.models.utils


class Migration(migrations.Migration):
    """Create EmailChannel model with UUID PK and many-per-team support.

    Also adds Ticket.email_config FK to link tickets to their receiving channel.
    """

    dependencies = [
        ("conversations", "0028_remove_old_email_config"),
    ]

    operations = [
        migrations.CreateModel(
            name="EmailChannel",
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
                (
                    "team",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="email_channels",
                        to="posthog.team",
                    ),
                ),
                ("inbound_token", models.CharField(db_index=True, max_length=64, unique=True)),
                ("from_email", models.EmailField(max_length=254)),
                ("from_name", models.CharField(max_length=255)),
                ("domain", models.CharField(max_length=255)),
                ("domain_verified", models.BooleanField(default=False)),
                ("dns_records", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "db_table": "posthog_conversations_email_channel",
                "constraints": [
                    models.UniqueConstraint(fields=["from_email"], name="unique_email_channel_from_email"),
                ],
            },
        ),
        migrations.AddField(
            model_name="ticket",
            name="email_config",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="tickets",
                to="conversations.emailchannel",
            ),
        ),
    ]
