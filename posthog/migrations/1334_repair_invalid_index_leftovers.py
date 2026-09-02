from django.db import migrations

from posthog.migration_helpers import CreateIndexConcurrently


class Migration(migrations.Migration):
    # CONCURRENTLY can't run inside a transaction.
    atomic = False

    dependencies = [
        ("posthog", "1333_uploaded_media_library_index"),
    ]

    operations = [
        # Repair the implicit ForeignKey index on posthog_hogfunction.batch_export_id.
        # Migration 0949 built it with a raw `CREATE INDEX CONCURRENTLY IF NOT EXISTS`,
        # which matches by name and not by validity, so an interrupted build left it
        # indisvalid = false and every retry skipped past it. CreateIndexConcurrently
        # drops and rebuilds an invalid leftover, and leaves a valid index untouched.
        # No SeparateDatabaseAndState state op: the FK's implicit index is already in state.
        CreateIndexConcurrently(
            index_name="posthog_hogfunction_batch_export_id_d64c3403",
            table_name="posthog_hogfunction",
            columns="(batch_export_id)",
        ),
        # `_ccnew` is the transient name Postgres gives the replacement index during
        # REINDEX INDEX CONCURRENTLY. An interrupted reindex left this one behind as
        # indisvalid = false, and no helper can clear it, because they all look an index
        # up by its declared name, so a leftover under a transient name stays invisible.
        # One statement per list entry, because Postgres opens an implicit transaction
        # block around a multi-statement query and refuses DROP INDEX CONCURRENTLY there.
        migrations.RunSQL(
            sql=[
                "SET lock_timeout = 0",
                "SET statement_timeout = 0",
                'DROP INDEX CONCURRENTLY IF EXISTS "posthog_mat_team_sl_idx_ccnew"',
            ],
            reverse_sql=migrations.RunSQL.noop,
        ),
        # Rebuild the base index the interrupted reindex was repairing.
        # No state op: migration 1159 already declares this index in Django state.
        CreateIndexConcurrently(
            index_name="posthog_mat_team_sl_idx",
            table_name="posthog_materializedcolumnslot",
            columns="(team_id, slot_index)",
        ),
    ]
