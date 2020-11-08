from infi.clickhouse_orm import migrations

from ee.clickhouse.sql.session_recording_events import (
    KAFKA_SESSION_RECORDING_EVENTS_TABLE_SQL,
    SESSION_RECORDING_EVENTS_TABLE_MV_SQL,
    SESSION_RECORDING_EVENTS_TABLE_SQL,
)

operations = [
    migrations.RunSQL(SESSION_RECORDING_EVENTS_TABLE_SQL),
    migrations.RunSQL(KAFKA_SESSION_RECORDING_EVENTS_TABLE_SQL),
    migrations.RunSQL(SESSION_RECORDING_EVENTS_TABLE_MV_SQL),
]
