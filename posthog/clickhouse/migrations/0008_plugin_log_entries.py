from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.plugin_log_entries import (
    KAFKA_PLUGIN_LOG_ENTRIES_TABLE_SQL,
    PLUGIN_LOG_ENTRIES_TABLE,
    PLUGIN_LOG_ENTRIES_TABLE_MV_SQL,
    PLUGIN_LOG_ENTRIES_TABLE_SQL,
)

operations = [
    run_sql_with_exceptions(PLUGIN_LOG_ENTRIES_TABLE_SQL()),
    run_sql_with_exceptions(KAFKA_PLUGIN_LOG_ENTRIES_TABLE_SQL()),
    run_sql_with_exceptions(PLUGIN_LOG_ENTRIES_TABLE_MV_SQL(target_table=PLUGIN_LOG_ENTRIES_TABLE)),
]
