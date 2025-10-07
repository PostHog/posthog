from django.conf import settings

from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.kafka_client.topics import (
    KAFKA_EVENTS_PLUGIN_INGESTION,
    KAFKA_EVENTS_PLUGIN_INGESTION_OVERFLOW,
    KAFKA_SESSION_RECORDING_EVENTS,
)

DROP_EVENTS_PLUGIN_INGESTION_PARTITION_STATISTICS_TABLE = (
    lambda: f"DROP TABLE IF EXISTS `{settings.CLICKHOUSE_DATABASE}`.events_plugin_ingestion_partition_statistics ON CLUSTER '{settings.CLICKHOUSE_CLUSTER}' SYNC"
)

DROP_PARTITION_STATISTICS_MV = (
    lambda monitored_topic: f"DROP TABLE IF EXISTS `{settings.CLICKHOUSE_DATABASE}`.{monitored_topic}_partition_statistics_mv ON CLUSTER '{settings.CLICKHOUSE_CLUSTER}' SYNC"
)

operations = map(
    run_sql_with_exceptions,
    [
        DROP_EVENTS_PLUGIN_INGESTION_PARTITION_STATISTICS_TABLE(),
        DROP_PARTITION_STATISTICS_MV(KAFKA_EVENTS_PLUGIN_INGESTION),
        DROP_PARTITION_STATISTICS_MV(KAFKA_EVENTS_PLUGIN_INGESTION_OVERFLOW),
        DROP_PARTITION_STATISTICS_MV(KAFKA_SESSION_RECORDING_EVENTS),
    ],
)
