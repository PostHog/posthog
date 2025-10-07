from django.conf import settings

from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.kafka_client.topics import KAFKA_EVENTS_PLUGIN_INGESTION_OVERFLOW, KAFKA_SESSION_RECORDING_EVENTS
from posthog.models.kafka_partition_stats.sql import PartitionStatsKafkaTable
<<<<<<< Updated upstream
=======
from django.conf import settings
>>>>>>> Stashed changes

operations = [
    run_sql_with_exceptions(
        PartitionStatsKafkaTable(settings.KAFKA_HOSTS, KAFKA_EVENTS_PLUGIN_INGESTION_OVERFLOW).get_create_table_sql()
    ),
    run_sql_with_exceptions(
        PartitionStatsKafkaTable(
            settings.SESSION_RECORDING_KAFKA_HOSTS, KAFKA_SESSION_RECORDING_EVENTS
        ).get_create_table_sql()
    ),
]
