from django.conf import settings

from posthog.clickhouse.kafka_engine import kafka_engine, kafka_num_consumers

from .kafka_metrics import KAFKA_NAMED_COLLECTION, KAFKA_TOPIC


def _db() -> str:
    return settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE


def kafka_metrics_avro_table_sql(
    table_name: str,
    group: str,
    flush_interval_ms: int | None = None,
    max_block_size: int | None = None,
) -> str:
    # The aggregation views group one insert block at a time, so a longer flush interval
    # packs more samples of a series into each row before the merge.
    block_settings = ""
    if flush_interval_ms is not None:
        block_settings += f"\n    kafka_flush_interval_ms = {flush_interval_ms},"
    if max_block_size is not None:
        block_settings += f"\n    kafka_max_block_size = {max_block_size},"
    return f"""
CREATE TABLE IF NOT EXISTS {_db()}.{table_name}
(
    `uuid` String,
    `trace_id` String,
    `span_id` String,
    `trace_flags` Nullable(Int32),
    `timestamp` DateTime64(6),
    `observed_timestamp` DateTime64(6),
    `service_name` Nullable(String),
    `metric_name` Nullable(String),
    `metric_type` Nullable(String),
    `value` Nullable(Float64),
    `count` Nullable(Int64),
    `histogram_bounds` Array(Float64),
    `histogram_counts` Array(Int64),
    `unit` Nullable(String),
    `aggregation_temporality` Nullable(String),
    `is_monotonic` Nullable(UInt8),
    `resource_attributes` Map(String, String),
    `instrumentation_scope` Nullable(String),
    `attributes` Map(String, String),
    `series_fingerprint` Nullable(Int64),
    `has_labels` Nullable(UInt8),
    `retention_days` Nullable(Int32)
)
ENGINE = {kafka_engine(topic=KAFKA_TOPIC, group=group, serialization="Avro", named_collection=KAFKA_NAMED_COLLECTION)}
SETTINGS
    kafka_skip_broken_messages = 100,
    kafka_thread_per_consumer = 1,
    kafka_num_consumers = {kafka_num_consumers(8)},
    kafka_poll_timeout_ms = 3000,
    kafka_poll_max_batch_size = 1000,{block_settings}
    input_format_avro_allow_missing_fields = 1
"""
