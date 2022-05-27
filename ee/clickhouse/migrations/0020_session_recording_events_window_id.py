from infi.clickhouse_orm import migrations

from ee.clickhouse.sql.session_recording_events import (
    KAFKA_SESSION_RECORDING_EVENTS_TABLE_SQL,
    SESSION_RECORDING_EVENTS_TABLE_MV_SQL,
)
from posthog.settings import CLICKHOUSE_CLUSTER

operations = [
    migrations.RunSQL(f"DROP TABLE session_recording_events_mv ON CLUSTER '{CLICKHOUSE_CLUSTER}'"),
    migrations.RunSQL(f"DROP TABLE kafka_session_recording_events ON CLUSTER '{CLICKHOUSE_CLUSTER}'"),
    migrations.RunSQL(
        f"ALTER TABLE session_recording_events ON CLUSTER '{CLICKHOUSE_CLUSTER}' ADD COLUMN IF NOT EXISTS window_id VARCHAR AFTER session_id"
    ),
    migrations.RunSQL(KAFKA_SESSION_RECORDING_EVENTS_TABLE_SQL()),
    migrations.RunSQL(SESSION_RECORDING_EVENTS_TABLE_MV_SQL()),
]
