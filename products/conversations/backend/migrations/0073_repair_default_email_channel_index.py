from django.db import migrations

from posthog.migration_helpers import CreateIndexConcurrently


class Migration(migrations.Migration):
    # CONCURRENTLY can't run inside a transaction.
    atomic = False

    dependencies = [
        ("conversations", "0072_clear_duplicate_default_email_channels"),
    ]

    operations = [
        # Repair the partial unique index from 0049. Its `CREATE UNIQUE INDEX CONCURRENTLY IF NOT
        # EXISTS` matches by name, not validity, so a failed build left the index with
        # indisvalid = false and every retry skipped it. CreateIndexConcurrently drops and
        # rebuilds an invalid index and leaves a valid one as it is.
        # No SeparateDatabaseAndState state op: 0049 already put the constraint in state.
        CreateIndexConcurrently(
            index_name="unique_default_email_channel_per_team",
            table_name="posthog_conversations_email_channel",
            columns='("team_id")',
            unique=True,
            where='WHERE "is_default"',
        ),
    ]
