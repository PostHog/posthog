from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.kafka_client.topics import KAFKA_EVENTS_PLUGIN_INGESTION
from posthog.models.kafka_partition_stats.sql import (
    PartitionStatsKafkaTable,
    CREATE_EVENTS_PLUGIN_INGESTION_PARTITION_STATISTICS_MV,
    EVENTS_PLUGIN_INGESTION_PARTITION_STATISTICS,
)
from posthog.settings.data_stores import KAFKA_HOSTS

operations = [
    run_sql_with_exceptions(
        PartitionStatsKafkaTable(KAFKA_HOSTS, KAFKA_EVENTS_PLUGIN_INGESTION).get_create_table_sql()
    ),
    run_sql_with_exceptions(EVENTS_PLUGIN_INGESTION_PARTITION_STATISTICS()),
    run_sql_with_exceptions(CREATE_EVENTS_PLUGIN_INGESTION_PARTITION_STATISTICS_MV),
]
