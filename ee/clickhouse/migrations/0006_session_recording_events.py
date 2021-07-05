from infi.clickhouse_orm import migrations

from ee.clickhouse.sql.session_recording_events import (
    KAFKA_SESSION_RECORDING_EVENTS_TABLE_SQL,
    SESSION_RECORDING_EVENTS_TABLE_MV_SQL,
    SESSION_RECORDING_EVENTS_TABLE_SQL,
)


def operations(is_backup_host):
    if is_backup_host:
        return [
            migrations.RunSQL(SESSION_RECORDING_EVENTS_TABLE_SQL),
        ]
    else:
        return [
            migrations.RunSQL(SESSION_RECORDING_EVENTS_TABLE_SQL),
            migrations.RunSQL(KAFKA_SESSION_RECORDING_EVENTS_TABLE_SQL),
            migrations.RunSQL(SESSION_RECORDING_EVENTS_TABLE_MV_SQL),
        ]
