from infi.clickhouse_orm import migrations

from posthog.client import sync_execute
from posthog.settings import CLICKHOUSE_CLUSTER


def create_events_summary_mat_columns(database):
    sync_execute(
        f"""
            ALTER TABLE session_recording_events
            ON CLUSTER '{CLICKHOUSE_CLUSTER}'
            ADD COLUMN IF NOT EXISTS
            events_summary Array(String) MATERIALIZED JSONExtract(JSON_QUERY(snapshot_data, '$.events_summary[*]'), 'Array(String)')
        """
    )


operations = [migrations.RunPython(create_events_summary_mat_columns)]
