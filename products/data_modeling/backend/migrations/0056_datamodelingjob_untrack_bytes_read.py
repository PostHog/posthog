from django.db import migrations

from posthog.migration_helpers import untrack_field


class Migration(migrations.Migration):
    dependencies = [
        ("data_modeling", "0055_backfill_datawarehousesavedquery_query_updated_at"),
    ]

    operations = [
        # Only managed warehouse runs wrote bytes_read, and only after it shipped in October 2026.
        # Those runs set last_run_at in the same save, so the bound uses dmjob_usage_run
        # instead of scanning the whole table.
        migrations.RunSQL(
            sql="""
                UPDATE posthog_datamodelingjob
                SET read_bytes = bytes_read, usage_updated_at = last_run_at
                WHERE last_run_at >= '2026-10-01'
                  AND bytes_read IS NOT NULL
                  AND read_bytes IS NULL
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
        untrack_field("datamodelingjob", "bytes_read"),
    ]
