from dataclasses import dataclass
from posthog.clickhouse.kafka_engine import kafka_engine
from posthog.clickhouse.table_engines import AggregatingMergeTree, ReplacingMergeTree
from posthog.kafka_client.topics import KAFKA_EVENTS_PLUGIN_INGESTION
from posthog.settings import CLICKHOUSE_CLUSTER, CLICKHOUSE_DATABASE


@dataclass
class PartitionStatsKafkaTable:
    brokers: list[str]
    topic: str
    consumer_group: str = "partition_statistics"

    @property
    def table_name(self) -> str:
        return f"kafka_{self.topic}_partition_statistics"

    def get_create_table_sql(self) -> str:
        return f"""
            CREATE TABLE IF NOT EXISTS `{CLICKHOUSE_DATABASE}`.{self.table_name} ON CLUSTER '{CLICKHOUSE_CLUSTER}'
            (
                `uuid` String,
                `distinct_id` String,
                `ip` String,
                `site_url` String,
                `data` String,
                `team_id` Int64,
                `now` String,
                `sent_at` String,
                `token` String
            )
            ENGINE={kafka_engine(kafka_host=",".join(self.brokers), topic=self.topic, group=self.consumer_group)}
            SETTINGS input_format_values_interpret_expressions=0, kafka_skip_broken_messages = 100
        """

    def get_drop_table_sql(self) -> str:
        return f"""
            DROP TABLE IF EXISTS `{CLICKHOUSE_DATABASE}`.{self.table_name} ON CLUSTER '{CLICKHOUSE_CLUSTER}'
        """


EVENTS_PLUGIN_INGESTION_PARTITION_STATISTICS_TABLE_ENGINE = lambda: AggregatingMergeTree(
    "events_plugin_ingestion_partition_statistics"
)

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
ENGINE = {EVENTS_PLUGIN_INGESTION_PARTITION_STATISTICS_TABLE_ENGINE()}
ORDER BY (`_topic`, `_partition`, `timestamp`, `api_key`, `distinct_id`)
"""
)

DROP_EVENTS_PLUGIN_INGESTION_PARTITION_STATISTICS_TABLE = (
    lambda: f"DROP TABLE IF EXISTS `{CLICKHOUSE_DATABASE}`.events_plugin_ingestion_partition_statistics ON CLUSTER '{CLICKHOUSE_CLUSTER}' SYNC"
)

CREATE_PARTITION_STATISTICS_MV = (
    lambda monitored_topic: f"""
CREATE MATERIALIZED VIEW IF NOT EXISTS `{CLICKHOUSE_DATABASE}`.{monitored_topic}_partition_statistics_mv ON CLUSTER '{CLICKHOUSE_CLUSTER}'
TO `{CLICKHOUSE_DATABASE}`.events_plugin_ingestion_partition_statistics
AS SELECT
    toStartOfMinute(_timestamp) AS `timestamp`,
    `_topic`,
    `_partition`,
    `token` AS `api_key`,
    JSONExtractString(data, 'event') AS `event`,
    `distinct_id`,
    countState(1) AS `messages`,
    sumState(length(data)) AS `data_size`
FROM {CLICKHOUSE_DATABASE}.kafka_{monitored_topic}_partition_statistics
GROUP BY
    `timestamp`,
    `_topic`,
    `_partition`,
    `api_key`,
    `event`,
    `distinct_id`
"""
)

DROP_PARTITION_STATISTICS_MV = (
    lambda monitored_topic: f"""
DROP TABLE IF EXISTS `{CLICKHOUSE_DATABASE}`.{monitored_topic}_partition_statistics_mv ON CLUSTER '{CLICKHOUSE_CLUSTER}' SYNC
"""
)

CREATE_EVENTS_PLUGIN_INGESTION_PARTITION_STATISTICS_MV = CREATE_PARTITION_STATISTICS_MV(KAFKA_EVENTS_PLUGIN_INGESTION)

DROP_EVENTS_PLUGIN_INGESTION_PARTITION_STATISTICS_MV = DROP_PARTITION_STATISTICS_MV(KAFKA_EVENTS_PLUGIN_INGESTION)

# V2


class PartitionStatsV2Table:
    table_name: str = "events_plugin_ingestion_partition_statistics_v2"

    def get_create_table_sql(self) -> str:
        engine = ReplacingMergeTree(self.table_name, ver="timestamp")
        return f"""
            CREATE TABLE IF NOT EXISTS `{CLICKHOUSE_DATABASE}`.{self.table_name} ON CLUSTER '{CLICKHOUSE_CLUSTER}' (
                topic LowCardinality(String),
                partition UInt64,
                offset UInt64,
                token String,
                distinct_id String,
                ip Tuple(v4 IPv4, v6 IPv6),
                event String,
                data_length UInt64,
                timestamp DateTime
            )
            ENGINE = {engine}
            PARTITION BY (topic, toStartOfDay(timestamp))
            ORDER BY (topic, partition, offset)
            TTL timestamp + INTERVAL 30 DAY
        """

    def get_drop_table_sql(self) -> str:
        return f"""
            DROP TABLE IF EXISTS `{CLICKHOUSE_DATABASE}`.{self.table_name} ON CLUSTER '{CLICKHOUSE_CLUSTER}' SYNC
        """


@dataclass
class PartitionStatsV2MaterializedView:
    to_table: PartitionStatsV2Table
    from_table: PartitionStatsKafkaTable

    @property
    def table_name(self) -> str:
        return f"{self.from_table.topic}_partition_statistics_v2_mv"

    def get_create_table_sql(self) -> str:
        return f"""
            CREATE MATERIALIZED VIEW IF NOT EXISTS `{CLICKHOUSE_DATABASE}`.{self.table_name} ON CLUSTER '{CLICKHOUSE_CLUSTER}'
            TO `{CLICKHOUSE_DATABASE}`.{self.to_table.table_name}
            AS SELECT
                _topic AS topic,
                _partition AS partition,
                _offset AS offset,
                token,
                distinct_id,
                (toIPv4OrDefault(kafka_table.ip), toIPv6OrDefault(kafka_table.ip)) AS ip,
                JSONExtractString(data, 'event') AS event,
                length(data) AS data_length,
                _timestamp AS timestamp
            FROM {CLICKHOUSE_DATABASE}.{self.from_table.table_name} AS kafka_table
        """

    def get_drop_table_sql(self) -> str:
        return f"""
            DROP TABLE IF EXISTS `{CLICKHOUSE_DATABASE}`.{self.table_name} ON CLUSTER '{CLICKHOUSE_CLUSTER}' SYNC
        """
