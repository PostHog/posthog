from django.db import migrations, models

from posthog.migration_helpers import CreateIndexConcurrently


class Migration(migrations.Migration):
    # CREATE INDEX CONCURRENTLY cannot run inside a transaction.
    atomic = False

    dependencies = [
        ("posthog", "1298_commentslackthread_import_error_and_more"),
    ]

    operations = [
        # A conditional UniqueConstraint is a partial unique index in Postgres, which has no
        # NOT VALID form — so build the index concurrently (lock-free) and record the constraint
        # state-only. The helper is idempotent under bin/migrate retries and drops an invalid
        # leftover from an interrupted build before retrying.
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddConstraint(
                    model_name="commentslackthread",
                    constraint=models.UniqueConstraint(
                        condition=models.Q(("slack_thread_ts", ""), _negated=True),
                        fields=("integration", "slack_channel_id", "slack_thread_ts"),
                        name="unique_slack_thread_per_integration",
                    ),
                ),
            ],
            database_operations=[
                CreateIndexConcurrently(
                    index_name="unique_slack_thread_per_integration",
                    table_name="posthog_commentslackthread",
                    columns='("integration_id", "slack_channel_id", "slack_thread_ts")',
                    unique=True,
                    where="WHERE NOT (\"slack_thread_ts\" = '')",
                ),
            ],
        ),
    ]
