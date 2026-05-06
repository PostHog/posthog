from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.kafka_client.topics import KAFKA_EVENTS_PLUGIN_INGESTION_OVERFLOW
from posthog.models.kafka_partition_stats.sql import PartitionStatsKafkaTable
from posthog.settings.kafka import KAFKA_HOSTS

# The session recording partition-stats Kafka table this migration originally created
# was dropped in 0063 and is no longer relevant; its SESSION_RECORDING_KAFKA_HOSTS-driven
# operation has been removed so fresh installs no longer create it.
operations = [
    run_sql_with_exceptions(
        PartitionStatsKafkaTable(KAFKA_HOSTS, KAFKA_EVENTS_PLUGIN_INGESTION_OVERFLOW).get_create_table_sql()
    ),
]
