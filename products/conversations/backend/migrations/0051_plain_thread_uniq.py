from django.db import migrations, models

from posthog.migration_helpers import CreateIndexConcurrently


class Migration(migrations.Migration):
    # Required for CREATE INDEX CONCURRENTLY (the partial unique index backing the constraint).
    atomic = False

    dependencies = [
        ("conversations", "0050_plain_import"),
    ]

    operations = [
        # posthog_conversations_ticket is an existing, populated table, so the partial unique
        # index must be built concurrently to avoid an ACCESS EXCLUSIVE lock on writes.
        # SeparateDatabaseAndState keeps Django's state as a UniqueConstraint while the DB
        # gets the equivalent partial unique index under the same name.
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddConstraint(
                    model_name="ticket",
                    constraint=models.UniqueConstraint(
                        fields=("team", "plain_thread_id"),
                        condition=models.Q(("plain_thread_id__isnull", False)),
                        name="posthog_con_plain_thread_uniq",
                    ),
                ),
            ],
            database_operations=[
                CreateIndexConcurrently(
                    index_name="posthog_con_plain_thread_uniq",
                    table_name="posthog_conversations_ticket",
                    columns="(team_id, plain_thread_id)",
                    unique=True,
                    where="WHERE plain_thread_id IS NOT NULL",
                ),
            ],
        ),
    ]
