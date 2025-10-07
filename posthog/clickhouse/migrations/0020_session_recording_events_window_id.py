from django.conf import settings

from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.session_recordings.sql.session_recording_event_sql import (
    KAFKA_SESSION_RECORDING_EVENTS_TABLE_SQL,
    SESSION_RECORDING_EVENTS_TABLE_MV_SQL,
)

operations = [
    run_sql_with_exceptions(f"DROP TABLE session_recording_events_mv ON CLUSTER '{settings.CLICKHOUSE_CLUSTER}'"),
    run_sql_with_exceptions(f"DROP TABLE kafka_session_recording_events ON CLUSTER '{settings.CLICKHOUSE_CLUSTER}'"),
    run_sql_with_exceptions(
        f"ALTER TABLE session_recording_events ON CLUSTER '{settings.CLICKHOUSE_CLUSTER}' ADD COLUMN IF NOT EXISTS window_id VARCHAR AFTER session_id"
    ),
    run_sql_with_exceptions(KAFKA_SESSION_RECORDING_EVENTS_TABLE_SQL()),
    run_sql_with_exceptions(SESSION_RECORDING_EVENTS_TABLE_MV_SQL()),
]
