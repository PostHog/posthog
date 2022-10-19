from infi.clickhouse_orm import migrations

from posthog.client import sync_execute
from posthog.models.session_recording_event.sql import MATERIALIZED_COLUMNS
from posthog.settings import CLICKHOUSE_CLUSTER, CLICKHOUSE_REPLICATION


def create_events_summary_mat_columns(database):

    columns_to_add = [
        "events_summary",
        "click_count",
        "keypress_count",
        "first_event_timestamp",
        "last_event_timestamp",
        "urls",
    ]

    for column in columns_to_add:
        data = MATERIALIZED_COLUMNS[column]

        if CLICKHOUSE_REPLICATION:
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
        else:
            sync_execute(
                f"""
                ALTER TABLE session_recording_events
                ON CLUSTER '{CLICKHOUSE_CLUSTER}'
                ADD COLUMN IF NOT EXISTS
                {column} {data["schema"]} {data["materializer"]}
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
