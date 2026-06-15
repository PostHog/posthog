from django.db import migrations, models
from django.db.models.expressions import F
from django.db.models.functions import Lower

from posthog.migration_helpers import CreateIndexConcurrently


class Migration(migrations.Migration):
    # Concurrent index builds cannot run inside a transaction.
    atomic = False

    dependencies = [
        ("posthog", "1219_filesystemfoldercontextgeneration"),
    ]

    operations = [
        # Add a functional index on LOWER(path) so the default tree-listing
        # `ORDER BY LOWER(path)` is served by an index instead of a full filesort.
        # Built CONCURRENTLY (non-blocking); SeparateDatabaseAndState keeps Django's
        # index state in sync. The helper disables lock_timeout, recovers from invalid
        # leftover indexes, and emits IF NOT EXISTS so deploy-time retries are safe.
        # It is reversible on its own (reverse = DROP INDEX CONCURRENTLY).
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddIndex(
                    model_name="filesystem",
                    index=models.Index(F("team_id"), F("surface"), Lower("path"), name="posthog_fs_team_s_lpath"),
                ),
            ],
            database_operations=[
                CreateIndexConcurrently(
                    index_name="posthog_fs_team_s_lpath",
                    table_name="posthog_filesystem",
                    columns="(team_id, surface, lower(path))",
                ),
            ],
        ),
    ]
