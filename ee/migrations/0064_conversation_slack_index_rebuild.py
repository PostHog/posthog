from django.db import migrations

from posthog.migration_helpers import CreateIndexConcurrently


class Migration(migrations.Migration):
    atomic = False  # Required for CREATE INDEX CONCURRENTLY

    dependencies = [
        ("ee", "0063_scim_provisioned_user_config_set_null"),
    ]

    operations = [
        # 0035 built this index with raw `CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS`.
        # A cancelled build leaves an invalid index that IF NOT EXISTS then matches by name,
        # so the migration is recorded as applied while the index enforces nothing.
        # State needs no operation here: 0035 already added the UniqueConstraint.
        CreateIndexConcurrently(
            index_name="unique_team_slack_thread_key",
            table_name="ee_conversation",
            columns='("team_id", "slack_thread_key")',
            unique=True,
            where='WHERE "slack_thread_key" IS NOT NULL',
        ),
    ]
