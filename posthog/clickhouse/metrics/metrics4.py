from .metrics2 import kafka_metrics_avro_table_sql

KAFKA_METRICS4_TABLE_NAME = "kafka_metrics_avro4"

KAFKA_METRICS4_GROUP = "clickhouse-metrics-avro4"

KAFKA_METRICS4_FLUSH_INTERVAL_MS = 30_000

KAFKA_METRICS4_MAX_BLOCK_SIZE = 1_000_000


def KAFKA_METRICS_AVRO4_TABLE_SQL() -> str:
    return kafka_metrics_avro_table_sql(
        KAFKA_METRICS4_TABLE_NAME,
        KAFKA_METRICS4_GROUP,
        flush_interval_ms=KAFKA_METRICS4_FLUSH_INTERVAL_MS,
        max_block_size=KAFKA_METRICS4_MAX_BLOCK_SIZE,
    )
