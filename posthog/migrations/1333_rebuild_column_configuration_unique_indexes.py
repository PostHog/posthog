from django.db import migrations

from posthog.migration_helpers import CreateIndexConcurrently

# Migration 0987 left both partial unique indexes able to end up invalid (see
# 1332). Migration 1332 removed the conflicting rows; this migration rebuilds
# both indexes through `CreateIndexConcurrently`, which drops an `indisvalid =
# false` leftover before it recreates the index. The index shapes match 0987,
# whose `AddConstraint` still owns them in Django state, so this only repairs the
# database and adds no new state.


class Migration(migrations.Migration):
    # Concurrent index builds cannot run inside a transaction.
    atomic = False

    dependencies = [
        ("posthog", "1332_dedupe_column_configuration_view_names"),
    ]

    operations = [
        CreateIndexConcurrently(
            index_name="unique_user_view_name",
            table_name="posthog_columnconfiguration",
            columns="(team_id, context_key, name, created_by_id)",
            unique=True,
            where="WHERE visibility = 'private'",
        ),
        CreateIndexConcurrently(
            index_name="unique_team_view_name",
            table_name="posthog_columnconfiguration",
            columns="(team_id, context_key, name)",
            unique=True,
            where="WHERE visibility = 'shared'",
        ),
    ]
