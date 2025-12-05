from dataclasses import dataclass

from posthog.clickhouse.kafka_engine import kafka_engine
from posthog.clickhouse.table_engines import MergeTreeEngine
from posthog.settings import CLICKHOUSE_CLUSTER, CLICKHOUSE_DATABASE


@dataclass
class KafkaDebugKafkaTable:
    brokers: list[str]
    topic: str
    consumer_group: str = "debug"
    serialization: str = "LineAsString"

    @property
    def table_name(self) -> str:
        return f"kafka_{self.topic}_debug"

    def get_create_table_sql(self) -> str:
        return f"""
      CREATE TABLE IF NOT EXISTS `{CLICKHOUSE_DATABASE}`.{self.table_name} ON CLUSTER '{CLICKHOUSE_CLUSTER}'
      (
        payload String
      )
      ENGINE={kafka_engine(
          kafka_host=",".join(self.brokers),
          topic=self.topic,
          group=self.consumer_group,
          serialization=self.serialization,
          use_named_collection=False
          )}
      SETTINGS input_format_values_interpret_expressions=0, kafka_handle_error_mode='stream'
    """

    def get_drop_table_sql(self) -> str:
        return f"""
      DROP TABLE IF EXISTS `{CLICKHOUSE_DATABASE}`.{self.table_name} ON CLUSTER '{CLICKHOUSE_CLUSTER}'
    """


@dataclass
class KafkaDebugTable:
    topic: str

    @property
    def table_name(self) -> str:
        return f"{self.topic}_debug"

    def get_create_table_sql(self) -> str:
        engine = MergeTreeEngine(self.table_name)
        return f"""
      CREATE TABLE IF NOT EXISTS `{CLICKHOUSE_DATABASE}`.{self.table_name} ON CLUSTER '{CLICKHOUSE_CLUSTER}' (
        payload String,
        _timestamp DateTime,
        _timestamp_ms Nullable(DateTime64(3)),
        _partition UInt64,
        _offset UInt64,
        _error String,
        _raw_message String
      )
      ENGINE = {engine}
      PARTITION BY toStartOfHour(_timestamp)
      ORDER BY (_partition, _offset)
      TTL _timestamp + INTERVAL 14 DAY
    """

    def get_drop_table_sql(self) -> str:
        return f"""
      DROP TABLE IF EXISTS `{CLICKHOUSE_DATABASE}`.{self.table_name} ON CLUSTER '{CLICKHOUSE_CLUSTER}' SYNC
    """


@dataclass
class KafkaDebugMaterializedView:
    to_table: KafkaDebugTable
    from_table: KafkaDebugKafkaTable

    @property
    def view_name(self) -> str:
        return f"{self.to_table.table_name}_mv"

    def get_create_view_sql(self) -> str:
        return f"""
      CREATE MATERIALIZED VIEW IF NOT EXISTS `{CLICKHOUSE_DATABASE}`.{self.view_name} ON CLUSTER '{CLICKHOUSE_CLUSTER}' TO {self.to_table.table_name}
      AS SELECT
        payload,
        _timestamp,
        _timestamp_ms,
        _partition,
        _offset,
        _error,
        _raw_message
      FROM `{CLICKHOUSE_DATABASE}`.{self.from_table.table_name}
    """

    def get_drop_view_sql(self) -> str:
        return f"""
      DROP TABLE IF EXISTS `{CLICKHOUSE_DATABASE}`.{self.view_name} ON CLUSTER '{CLICKHOUSE_CLUSTER}' SYNC
    """
