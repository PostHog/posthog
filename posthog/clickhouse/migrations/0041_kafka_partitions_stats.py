from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.kafka_client.topics import KAFKA_EVENTS_PLUGIN_INGESTION
from posthog.models.kafka_partition_stats.sql import PartitionStatsKafkaTable
from posthog.settings.data_stores import KAFKA_HOSTS

operations = [
    run_sql_with_exceptions(
        PartitionStatsKafkaTable(KAFKA_HOSTS, KAFKA_EVENTS_PLUGIN_INGESTION).get_create_table_sql()
    ),
]
