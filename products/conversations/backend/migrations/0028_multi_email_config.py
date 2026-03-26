import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    """Convert TeamConversationsEmailConfig from one-per-team to many-per-team.

    No production data exists, so we drop and recreate the table with:
    - Auto BigAutoField PK instead of team as PK
    - team as ForeignKey instead of OneToOneField
    - unique(from_email) instead of unique(domain)

    Also adds Ticket.email_config FK to link tickets to their receiving config.
    """

    dependencies = [
        ("conversations", "0027_slack_config_unique_slack_team_id"),
    ]

    operations = [
        # The unique_email_domain index is dropped implicitly when the table is deleted.
        # 0026 created it as a raw SQL index (not a Django-managed constraint) via
        # SeparateDatabaseAndState, so RemoveConstraint would fail. DeleteModel handles cleanup.
        migrations.DeleteModel(
            name="TeamConversationsEmailConfig",
        ),
        migrations.CreateModel(
            name="TeamConversationsEmailConfig",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
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
