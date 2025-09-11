from infi.clickhouse_orm import migrations

from posthog.clickhouse.client import sync_execute
from posthog.session_recordings.sql.session_recording_event_sql import MATERIALIZED_COLUMNS
from posthog.settings import CLICKHOUSE_CLUSTER


def create_events_summary_mat_columns(database):
    columns_to_add = [
        "events_summary",
        "click_count",
        "keypress_count",
        "timestamps_summary",
        "first_event_timestamp",
        "last_event_timestamp",
        "urls",
    ]

    for column in columns_to_add:
        data = MATERIALIZED_COLUMNS[column]

        sync_execute(
            f"""
            ALTER TABLE sharded_session_recording_events
            ON CLUSTER '{CLICKHOUSE_CLUSTER}'
            ADD COLUMN IF NOT EXISTS
            {column} {data["schema"]} {data["materializer"]}
        """
        )
        sync_execute(
            f"""
            ALTER TABLE session_recording_events
            ON CLUSTER '{CLICKHOUSE_CLUSTER}'
            ADD COLUMN IF NOT EXISTS
            {column} {data["schema"]}
        """
        )

        sync_execute(
            f"""
                ALTER TABLE session_recording_events
                ON CLUSTER '{CLICKHOUSE_CLUSTER}'
                COMMENT COLUMN {column} 'column_materializer::{column}'
            """
        )


operations = [migrations.RunPython(create_events_summary_mat_columns)]
