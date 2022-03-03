from infi.clickhouse_orm import migrations

from ee.clickhouse.client import sync_execute
from ee.clickhouse.sql.session_recording_events import SESSION_RECORDING_EVENTS_MATERIALIZED_COLUMN_COMMENTS_SQL
from posthog.settings import CLICKHOUSE_CLUSTER, CLICKHOUSE_REPLICATION


def create_has_full_snapshot_materialized_column(database):
    if CLICKHOUSE_REPLICATION:
        sync_execute(
            f"""
            ALTER TABLE sharded_session_recording_events
            ON CLUSTER '{CLICKHOUSE_CLUSTER}'
            ADD COLUMN IF NOT EXISTS
            has_full_snapshot BOOLEAN MATERIALIZED JSONExtractBool(snapshot_data, 'has_full_snapshot')
        """
        )
        sync_execute(
            f"""
            ALTER TABLE session_recording_events
            ON CLUSTER '{CLICKHOUSE_CLUSTER}'
            ADD COLUMN IF NOT EXISTS
            has_full_snapshot BOOLEAN
        """
        )
    else:
        sync_execute(
            f"""
            ALTER TABLE session_recording_events
            ON CLUSTER '{CLICKHOUSE_CLUSTER}'
            ADD COLUMN IF NOT EXISTS
            has_full_snapshot BOOLEAN MATERIALIZED JSONExtractBool(snapshot_data, 'has_full_snapshot')
        """
        )

    sync_execute(SESSION_RECORDING_EVENTS_MATERIALIZED_COLUMN_COMMENTS_SQL())


operations = [migrations.RunPython(create_has_full_snapshot_materialized_column)]
