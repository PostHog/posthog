from infi.clickhouse_orm import migrations

from ee.clickhouse.sql.groups import GROUPS_TABLE, GROUPS_TABLE_MV_SQL, KAFKA_GROUPS_TABLE_SQL
from ee.clickhouse.sql.person import KAFKA_PERSONS_TABLE_SQL, PERSONS_TABLE, PERSONS_TABLE_MV_SQL
from ee.clickhouse.sql.plugin_log_entries import (
    KAFKA_PLUGIN_LOG_ENTRIES_TABLE_SQL,
    PLUGIN_LOG_ENTRIES_TABLE,
    PLUGIN_LOG_ENTRIES_TABLE_MV_SQL,
)
from ee.clickhouse.sql.session_recording_events import (
    KAFKA_SESSION_RECORDING_EVENTS_TABLE_SQL,
    SESSION_RECORDING_EVENTS_TABLE_MV_SQL,
)
from posthog.settings.data_stores import CLICKHOUSE_CLUSTER

tables_to_update = [
    (PERSONS_TABLE, KAFKA_PERSONS_TABLE_SQL(), PERSONS_TABLE_MV_SQL),
    (GROUPS_TABLE, KAFKA_GROUPS_TABLE_SQL(), GROUPS_TABLE_MV_SQL),
    (PLUGIN_LOG_ENTRIES_TABLE, KAFKA_PLUGIN_LOG_ENTRIES_TABLE_SQL(), PLUGIN_LOG_ENTRIES_TABLE_MV_SQL),
    ("session_recording_events", KAFKA_SESSION_RECORDING_EVENTS_TABLE_SQL(), SESSION_RECORDING_EVENTS_TABLE_MV_SQL()),
]

operations = [
    op
    for table_name, kafka_table_sql, mv_table_sql in tables_to_update
    for op in [
        migrations.RunSQL(f"DROP TABLE IF EXISTS {table_name}_mv ON CLUSTER {CLICKHOUSE_CLUSTER}"),
        migrations.RunSQL(f"DROP TABLE IF EXISTS kafka_{table_name} ON CLUSTER {CLICKHOUSE_CLUSTER}"),
        migrations.RunSQL(kafka_table_sql),
        migrations.RunSQL(mv_table_sql),
    ]
]
