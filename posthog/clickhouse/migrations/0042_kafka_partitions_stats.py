from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.kafka_client.topics import (
    KAFKA_EVENTS_PLUGIN_INGESTION_OVERFLOW,
    KAFKA_SESSION_RECORDING_EVENTS,
)
from posthog.models.kafka_partition_stats.sql import (
    CREATE_PARTITION_STATISTICS_KAFKA_TABLE,
    CREATE_PARTITION_STATISTICS_MV,
)

operations = [
    run_sql_with_exceptions(CREATE_PARTITION_STATISTICS_KAFKA_TABLE(KAFKA_EVENTS_PLUGIN_INGESTION_OVERFLOW)),
    run_sql_with_exceptions(CREATE_PARTITION_STATISTICS_MV(KAFKA_EVENTS_PLUGIN_INGESTION_OVERFLOW)),
    run_sql_with_exceptions(CREATE_PARTITION_STATISTICS_KAFKA_TABLE(KAFKA_SESSION_RECORDING_EVENTS)),
    run_sql_with_exceptions(CREATE_PARTITION_STATISTICS_MV(KAFKA_SESSION_RECORDING_EVENTS)),
]
