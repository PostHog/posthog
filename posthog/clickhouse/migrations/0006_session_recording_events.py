from infi.clickhouse_orm import migrations

from posthog.models.session_recording_event.sql import (
    DISTRIBUTED_SESSION_RECORDING_EVENTS_TABLE_SQL,
    KAFKA_SESSION_RECORDING_EVENTS_TABLE_SQL,
    SESSION_RECORDING_EVENTS_TABLE_MV_SQL,
    SESSION_RECORDING_EVENTS_TABLE_SQL,
    WRITABLE_SESSION_RECORDING_EVENTS_TABLE_SQL,
)
from posthog.settings.data_stores import CLICKHOUSE_CLUSTER, CLICKHOUSE_REPLICATION

SESSION_RECORDING_EVENTS_MATERIALIZED_COLUMN_COMMENTS_SQL = lambda: """
    ALTER TABLE session_recording_events
    ON CLUSTER '{cluster}'
    COMMENT COLUMN has_full_snapshot 'column_materializer::has_full_snapshot'
""".format(
    cluster=CLICKHOUSE_CLUSTER
)

operations = [
    migrations.RunSQL(SESSION_RECORDING_EVENTS_TABLE_SQL()),
    migrations.RunSQL(SESSION_RECORDING_EVENTS_MATERIALIZED_COLUMN_COMMENTS_SQL()),
    migrations.RunSQL(KAFKA_SESSION_RECORDING_EVENTS_TABLE_SQL()),
    migrations.RunSQL(SESSION_RECORDING_EVENTS_TABLE_MV_SQL()),
]

if CLICKHOUSE_REPLICATION:
    operations = [
        migrations.RunSQL(WRITABLE_SESSION_RECORDING_EVENTS_TABLE_SQL()),
        migrations.RunSQL(DISTRIBUTED_SESSION_RECORDING_EVENTS_TABLE_SQL()),
    ] + operations
