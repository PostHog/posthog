from infi.clickhouse_orm import migrations

from ee.clickhouse.sql.plugin_log_entries import (
    KAFKA_PLUGIN_LOG_ENTRIES_TABLE_SQL,
    PLUGIN_LOG_ENTRIES_TABLE_MV_SQL,
    PLUGIN_LOG_ENTRIES_TABLE_SQL,
)


def operations(is_backup_host):
    if is_backup_host:
        return [
            migrations.RunSQL(PLUGIN_LOG_ENTRIES_TABLE_SQL),
        ]
    else:
        return [
            migrations.RunSQL(PLUGIN_LOG_ENTRIES_TABLE_SQL),
            migrations.RunSQL(KAFKA_PLUGIN_LOG_ENTRIES_TABLE_SQL),
            migrations.RunSQL(PLUGIN_LOG_ENTRIES_TABLE_MV_SQL),
        ]
