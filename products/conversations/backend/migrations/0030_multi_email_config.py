import django.db.models.deletion
from django.db import migrations, models

import posthog.models.utils


class Migration(migrations.Migration):
    """Create new TeamConversationsEmailConfig with UUID PK and many-per-team support.

    Old table was renamed in 0029. This creates the new table with:
    - UUID PK instead of team as PK
    - team as ForeignKey instead of OneToOneField
    - unique(from_email) instead of unique(domain)

    Also adds Ticket.email_config FK to link tickets to their receiving config.
    """

    dependencies = [
        ("conversations", "0029_rename_old_email_config_table"),
    ]

    operations = [
        migrations.CreateModel(
            name="TeamConversationsEmailConfig",
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
                        related_name="email_configs",
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
                "db_table": "posthog_conversations_email_config",
                "constraints": [
                    models.UniqueConstraint(fields=["from_email"], name="unique_email_from_email"),
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
                to="conversations.teamconversationsemailconfig",
            ),
        ),
    ]
