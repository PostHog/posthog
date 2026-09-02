from django.db import migrations


class Migration(migrations.Migration):
    # DROP INDEX CONCURRENTLY cannot run inside a transaction.
    atomic = False

    dependencies = [
        ("posthog", "1333_uploaded_media_library_index"),
    ]

    operations = [
        # The `graphile_worker` schema belonged to the plugin server's old Postgres job
        # queue, removed in #32758. Nothing in this repository reads or writes it, but the
        # schema rides along on databases that descend from the old main application
        # database, so pganalyze keeps filing "unused index" notices for this index.
        #
        # Raw SQL, not the DropIndexConcurrently helper: the helper's reverse is a
        # CREATE INDEX CONCURRENTLY, which fails with UndefinedTable wherever the schema
        # never existed. The index is dead, so the reverse stays a no-op.
        # IF EXISTS makes the drop idempotent under bin/migrate retries and a no-op where
        # the schema is absent. The timeouts are off so lock_timeout cannot cancel it.
        migrations.RunSQL(
            sql="""
                SET lock_timeout = 0;
                SET statement_timeout = 0;
                DROP INDEX CONCURRENTLY IF EXISTS
                    graphile_worker.jobs_priority_run_at_id_locked_at_without_failures_idx;
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
