from typing import Literal

from infi.clickhouse_orm import migrations

from ee.clickhouse.client import sync_execute
from ee.clickhouse.materialized_columns.columns import get_materialized_columns, materialized_column_name
from posthog.settings import CLICKHOUSE_CLUSTER, CLICKHOUSE_REPLICATION

HAS_FULL_SNAPSHOT_FIELD_NAME = "has_full_snapshot"
SESSION_RECORDING_EVENTS_TABLE_NAME: Literal["session_recording_events"] = "session_recording_events"


def create_has_full_snapshot_materialized_column(database):

    if HAS_FULL_SNAPSHOT_FIELD_NAME in get_materialized_columns(SESSION_RECORDING_EVENTS_TABLE_NAME, use_cache=False):
        # Field is already materialized
        return

    column_name = materialized_column_name(SESSION_RECORDING_EVENTS_TABLE_NAME, HAS_FULL_SNAPSHOT_FIELD_NAME)

    extract_bool_string = f"JSONExtractBool(snapshot_data, '{HAS_FULL_SNAPSHOT_FIELD_NAME}')"

    if CLICKHOUSE_REPLICATION:
        sync_execute(
            f"""
            ALTER TABLE sharded_{SESSION_RECORDING_EVENTS_TABLE_NAME}
            ON CLUSTER {CLICKHOUSE_CLUSTER}
            ADD COLUMN IF NOT EXISTS
            {column_name} BOOLEAN MATERIALIZED {extract_bool_string}
        """
        )
        sync_execute(
            f"""
            ALTER TABLE {SESSION_RECORDING_EVENTS_TABLE_NAME}
            ON CLUSTER {CLICKHOUSE_CLUSTER}
            ADD COLUMN IF NOT EXISTS
            {column_name} BOOLEAN
        """
        )
    else:
        sync_execute(
            f"""
            ALTER TABLE {SESSION_RECORDING_EVENTS_TABLE_NAME}
            ON CLUSTER {CLICKHOUSE_CLUSTER}
            ADD COLUMN IF NOT EXISTS
            {column_name} BOOLEAN MATERIALIZED {extract_bool_string}
        """
        )

    sync_execute(
        f"""ALTER TABLE {SESSION_RECORDING_EVENTS_TABLE_NAME}
         ON CLUSTER {CLICKHOUSE_CLUSTER}
         COMMENT COLUMN {column_name} %(comment)s
         """,
        {"comment": f"column_materializer::{HAS_FULL_SNAPSHOT_FIELD_NAME}"},
    )


operations = [migrations.RunPython(create_has_full_snapshot_materialized_column)]
