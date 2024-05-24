from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.kafka_client.topics import KAFKA_EVENTS_PLUGIN_INGESTION_OVERFLOW, KAFKA_SESSION_RECORDING_EVENTS
from posthog.settings import CLICKHOUSE_CLUSTER, CLICKHOUSE_DATABASE
from posthog.settings.data_stores import KAFKA_EVENTS_PLUGIN_INGESTION


def get_drop_table_sql(table: str) -> str:
    return f"""\
        DROP TABLE IF EXISTS `{CLICKHOUSE_DATABASE}`.{table}
        ON CLUSTER '{CLICKHOUSE_CLUSTER}' SYNC
        SETTINGS max_table_size_to_drop = 0
    """


DROP_EVENTS_PLUGIN_INGESTION_PARTITION_STATISTICS_TABLE = get_drop_table_sql(
    "events_plugin_ingestion_partition_statistics"
)

DROP_PARTITION_STATISTICS_MV = lambda monitored_topic: get_drop_table_sql(f"{monitored_topic}_partition_statistics_mv")

operations = map(
    run_sql_with_exceptions,
    [
        DROP_EVENTS_PLUGIN_INGESTION_PARTITION_STATISTICS_TABLE,
        DROP_PARTITION_STATISTICS_MV(KAFKA_EVENTS_PLUGIN_INGESTION),
        DROP_PARTITION_STATISTICS_MV(KAFKA_EVENTS_PLUGIN_INGESTION_OVERFLOW),
        DROP_PARTITION_STATISTICS_MV(KAFKA_SESSION_RECORDING_EVENTS),
    ],
)
