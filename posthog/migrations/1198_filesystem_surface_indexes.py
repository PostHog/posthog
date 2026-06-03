from django.db import migrations, models
from django.db.models.expressions import F

from posthog.migration_helpers import CreateIndexConcurrently, DropIndexConcurrently


class Migration(migrations.Migration):
    # Concurrent index builds cannot run inside a transaction.
    atomic = False

    dependencies = [
        ("posthog", "1197_filesystem_surface"),
    ]

    operations = [
        # Re-front the composite indexes with `surface` so per-surface tree queries stay
        # selective. Add the new (surface-fronted) indexes before dropping the old ones, so
        # the table is never left without a covering index mid-deploy. The bare Django
        # AddIndexConcurrently/RemoveIndexConcurrently ops are non-idempotent and blocked by
        # CI; the helpers disable lock_timeout, recover from invalid leftovers, and emit
        # IF [NOT] EXISTS. SeparateDatabaseAndState keeps Django's index state in sync.
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddIndex(
                    model_name="filesystem",
                    index=models.Index(F("team_id"), F("surface"), F("path"), name="posthog_fs_team_s_path"),
                ),
                migrations.AddIndex(
                    model_name="filesystem",
                    index=models.Index(F("team_id"), F("surface"), F("depth"), name="posthog_fs_team_s_depth"),
                ),
                migrations.AddIndex(
                    model_name="filesystem",
                    index=models.Index(
                        F("team_id"), F("surface"), F("type"), F("ref"), name="posthog_fs_team_s_typeref"
                    ),
                ),
                migrations.RemoveIndex(model_name="filesystem", name="posthog_fs_team_path"),
                migrations.RemoveIndex(model_name="filesystem", name="posthog_fs_team_depth"),
                migrations.RemoveIndex(model_name="filesystem", name="posthog_fs_team_typeref"),
            ],
            database_operations=[
                CreateIndexConcurrently(
                    index_name="posthog_fs_team_s_path",
                    table_name="posthog_filesystem",
                    columns="(team_id, surface, path)",
                ),
                CreateIndexConcurrently(
                    index_name="posthog_fs_team_s_depth",
                    table_name="posthog_filesystem",
                    columns="(team_id, surface, depth)",
                ),
                CreateIndexConcurrently(
                    index_name="posthog_fs_team_s_typeref",
                    table_name="posthog_filesystem",
                    columns="(team_id, surface, type, ref)",
                ),
                DropIndexConcurrently(
                    index_name="posthog_fs_team_path",
                    table_name="posthog_filesystem",
                    columns="(team_id, path)",
                ),
                DropIndexConcurrently(
                    index_name="posthog_fs_team_depth",
                    table_name="posthog_filesystem",
                    columns="(team_id, depth)",
                ),
                DropIndexConcurrently(
                    index_name="posthog_fs_team_typeref",
                    table_name="posthog_filesystem",
                    columns="(team_id, type, ref)",
                ),
            ],
        ),
    ]
