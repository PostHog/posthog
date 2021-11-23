from infi.clickhouse_orm import migrations

from ee.clickhouse.client import sync_execute
from ee.clickhouse.materialized_columns.columns import get_materialized_columns
from ee.clickhouse.sql.session_recording_events import SESSION_RECORDING_EVENTS_TABLE
from posthog.settings import CLICKHOUSE_CLUSTER, CLICKHOUSE_REPLICATION


def create_has_full_snapshot_materialized_column(database):

    if "has_full_snapshot" in get_materialized_columns(SESSION_RECORDING_EVENTS_TABLE, use_cache=False):
        # Field is already materialized
        return

    if CLICKHOUSE_REPLICATION:
        sync_execute(
            f"""
            ALTER TABLE sharded_{SESSION_RECORDING_EVENTS_TABLE}
            ON CLUSTER {CLICKHOUSE_CLUSTER}
            ADD COLUMN IF NOT EXISTS
            has_full_snapshot BOOLEAN MATERIALIZED JSONExtractBool(snapshot_data, 'has_full_snapshot')
        """
        )
        sync_execute(
            f"""
            ALTER TABLE {SESSION_RECORDING_EVENTS_TABLE}
            ON CLUSTER {CLICKHOUSE_CLUSTER}
            ADD COLUMN IF NOT EXISTS
            has_full_snapshot BOOLEAN
        """
        )
    else:
        sync_execute(
            f"""
            ALTER TABLE {SESSION_RECORDING_EVENTS_TABLE}
            ON CLUSTER {CLICKHOUSE_CLUSTER}
            ADD COLUMN IF NOT EXISTS
            has_full_snapshot BOOLEAN MATERIALIZED JSONExtractBool(snapshot_data, 'has_full_snapshot')
        """
        )

    sync_execute(
        f"""ALTER TABLE {SESSION_RECORDING_EVENTS_TABLE}
         ON CLUSTER {CLICKHOUSE_CLUSTER}
         COMMENT COLUMN has_full_snapshot column_materializer::has_full_snapshot
         """
    )


operations = [migrations.RunPython(create_has_full_snapshot_materialized_column)]
