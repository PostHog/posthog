from django.db import migrations

from posthog.migration_helpers import CreateIndexConcurrently


class Migration(migrations.Migration):
    # CONCURRENTLY can't run inside a transaction.
    atomic = False

    dependencies = [
        ("posthog", "1333_uploaded_media_library_index"),
    ]

    operations = [
        # `_ccnew` is the transient name Postgres gives the replacement index during
        # REINDEX INDEX CONCURRENTLY. An interrupted reindex left this one behind as
        # indisvalid = false, and no helper can clear it: they all look an index up by
        # its declared name, so a leftover under a transient name stays invisible.
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
        # Rebuild the base index the interrupted reindex was repairing. A valid index
        # is left untouched; an invalid one is dropped and recreated. No state op:
        # migration 1159 already declares this index in Django state.
        CreateIndexConcurrently(
            index_name="posthog_mat_team_sl_idx",
            table_name="posthog_materializedcolumnslot",
            columns="(team_id, slot_index)",
        ),
    ]
