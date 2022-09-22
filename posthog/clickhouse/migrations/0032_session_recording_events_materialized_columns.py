from infi.clickhouse_orm import migrations

from posthog.client import sync_execute
from posthog.settings import CLICKHOUSE_CLUSTER, CLICKHOUSE_REPLICATION


def create_events_summary_mat_columns(database):
    columns = {
        "events_summary": {
            "schema": "Array(String)",
            "materializer": "MATERIALIZED JSONExtract(JSON_QUERY(snapshot_data, '$.events_summary[*]'), 'Array(String)')",
        },
        "click_count": {
            "schema": "Int8",
            "materializer": "MATERIALIZED length(arrayFilter((x) -> JSONExtractInt(x, 'type') = 3 AND JSONExtractInt(x, 'data', 'source') = 2 AND JSONExtractInt(x, 'data', 'source') = 2, events_summary))",
        },
        "keypress_count": {
            "schema": "Int8",
            "materializer": "MATERIALIZED length(arrayFilter((x) -> JSONExtractInt(x, 'type') = 3 AND JSONExtractInt(x, 'data', 'source') = 5, events_summary))",
        },
        "first_event_timestamp": {
            "schema": "DateTime64(6, 'UTC')",
            "materializer": "MATERIALIZED toDateTime(arrayReduce('min', arrayMap((x) -> JSONExtractInt(x, 'timestamp'), events_summary)) / 1000)",
        },
        "last_event_timestamp": {
            "schema": "DateTime64(6, 'UTC')",
            "materializer": "MATERIALIZED toDateTime(arrayReduce('max', arrayMap((x) -> JSONExtractInt(x, 'timestamp'), events_summary)) / 1000)",
        },
    }

    for column, data in columns.items():
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
