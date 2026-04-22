import django.db.models.deletion
from django.db import migrations, models

import posthog.models.utils


class Migration(migrations.Migration):
    """Replace TeamConversationsEmailConfig with EmailChannel.

    Removes the old one-per-team model from Django state (table left in DB
    for cleanup later) and creates EmailChannel with UUID PK and
    many-per-team support. Adds Ticket.email_config FK.
    """

    dependencies = [
        ("conversations", "0027_slack_config_unique_slack_team_id"),
    ]

    operations = [
        # Remove old model from Django state and drop FK constraints on the
        # orphaned table so TRUNCATE posthog_team doesn't fail in tests.
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.DeleteModel(name="TeamConversationsEmailConfig"),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql="""
                        DO $$
                        DECLARE r RECORD;
                        BEGIN
                            FOR r IN (
                                SELECT conname FROM pg_constraint
                                WHERE conrelid = 'posthog_conversations_email_config'::regclass
                                AND contype = 'f'
                            ) LOOP
                                EXECUTE format(
                                    'ALTER TABLE posthog_conversations_email_config DROP CONSTRAINT %I', r.conname
                                );
                            END LOOP;
                        EXCEPTION WHEN undefined_table THEN NULL;
                        END $$;
                    """,
                    reverse_sql=migrations.RunSQL.noop,
                ),
            ],
        ),
        # Create new model with UUID PK, ForeignKey to team, different table name
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
        # Add FK column without index — index is created concurrently in 0029.
        # State gets db_index=True (default) so Django knows about the index;
        # DB gets db_index=False so CREATE INDEX is skipped here.
        migrations.SeparateDatabaseAndState(
            state_operations=[
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
            ],
            database_operations=[
                migrations.AddField(
                    model_name="ticket",
                    name="email_config",
                    field=models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="tickets",
                        to="conversations.emailchannel",
                        db_index=False,
                    ),
                ),
            ],
        ),
    ]
