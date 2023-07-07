from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.kafka_partition_stats.sql import (
    CREATE_EVENTS_PLUGIN_INGESTION_PARTITION_STATISTICS_MV,
    CREATE_KAFKA_EVENTS_PLUGIN_INGESTION_PARTITION_STATISTICS,
    EVENTS_PLUGIN_INGESTION_PARTITION_STATISTICS,
)

operations = [
    run_sql_with_exceptions(CREATE_KAFKA_EVENTS_PLUGIN_INGESTION_PARTITION_STATISTICS),
    run_sql_with_exceptions(EVENTS_PLUGIN_INGESTION_PARTITION_STATISTICS()),
    run_sql_with_exceptions(CREATE_EVENTS_PLUGIN_INGESTION_PARTITION_STATISTICS_MV),
]
