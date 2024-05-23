from posthog.clickhouse.table_engines import AggregatingMergeTree
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.kafka_client.topics import KAFKA_EVENTS_PLUGIN_INGESTION
from posthog.models.kafka_partition_stats.sql import (
    CREATE_PARTITION_STATISTICS_MV,
    PartitionStatsKafkaTable,
)
from posthog.settings import CLICKHOUSE_CLUSTER, CLICKHOUSE_DATABASE
from posthog.settings.data_stores import KAFKA_HOSTS

EVENTS_PLUGIN_INGESTION_PARTITION_STATISTICS = (
    lambda: f"""
CREATE TABLE IF NOT EXISTS `{CLICKHOUSE_DATABASE}`.events_plugin_ingestion_partition_statistics ON CLUSTER '{CLICKHOUSE_CLUSTER}' (
    `timestamp` DateTime64,
    `_topic` String,
    `_partition` String,
    `api_key` String,
    `event` String,
    `distinct_id` String,
    `messages` AggregateFunction(count, UInt64),
    `data_size` AggregateFunction(sum, UInt64)
)
ENGINE = {AggregatingMergeTree("events_plugin_ingestion_partition_statistics")}
ORDER BY (`_topic`, `_partition`, `timestamp`, `api_key`, `distinct_id`)
"""
)

operations = [
    run_sql_with_exceptions(
        PartitionStatsKafkaTable(KAFKA_HOSTS, KAFKA_EVENTS_PLUGIN_INGESTION).get_create_table_sql()
    ),
    run_sql_with_exceptions(EVENTS_PLUGIN_INGESTION_PARTITION_STATISTICS()),
    run_sql_with_exceptions(CREATE_PARTITION_STATISTICS_MV(KAFKA_EVENTS_PLUGIN_INGESTION)),
]
