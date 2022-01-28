from infi.clickhouse_orm import migrations

from ee.clickhouse.sql.plugin_log_entries import (
    KAFKA_PLUGIN_LOG_ENTRIES_TABLE_SQL,
    PLUGIN_LOG_ENTRIES_TABLE_MV_SQL,
    PLUGIN_LOG_ENTRIES_TABLE_SQL,
)

operations = [
    migrations.RunSQL(PLUGIN_LOG_ENTRIES_TABLE_SQL()),
    migrations.RunSQL(KAFKA_PLUGIN_LOG_ENTRIES_TABLE_SQL()),
    migrations.RunSQL(PLUGIN_LOG_ENTRIES_TABLE_MV_SQL),
]
