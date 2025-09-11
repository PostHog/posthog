from dataclasses import dataclass

from posthog.clickhouse.kafka_engine import kafka_engine
from posthog.clickhouse.table_engines import ReplacingMergeTree
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
