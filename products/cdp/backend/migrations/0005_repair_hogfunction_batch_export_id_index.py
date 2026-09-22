from django.db import migrations

from posthog.migration_helpers import CreateIndexConcurrently


class Migration(migrations.Migration):
    # CONCURRENTLY can't run inside a transaction.
    atomic = False

    dependencies = [
        ("cdp", "0004_backfill_internal_event_filter_sources"),
    ]

    operations = [
        # Repair the implicit ForeignKey index on posthog_hogfunction.batch_export_id.
        # Migration posthog/0949 built it with a raw `CREATE INDEX CONCURRENTLY IF NOT EXISTS`,
        # which matches by name, not validity, so an interrupted build left it
        # indisvalid = false and every retry skipped past it. CreateIndexConcurrently
        # drops and rebuilds an invalid leftover; a valid index is left untouched.
        # No SeparateDatabaseAndState state op: the FK's implicit index is already in state.
        CreateIndexConcurrently(
            index_name="posthog_hogfunction_batch_export_id_d64c3403",
            table_name="posthog_hogfunction",
            columns="(batch_export_id)",
        ),
    ]
