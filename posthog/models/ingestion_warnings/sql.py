from posthog.clickhouse.kafka_engine import CONSUMER_GROUP_INGESTION_WARNINGS, kafka_engine
from posthog.kafka_client.topics import KAFKA_INGESTION_WARNINGS

# WarpStream Kafka engine tables (coexist alongside MSK tables, same target)


# This table is responsible for writing to sharded_ingestion_warnings based on a sharding key.


INSERT_INGESTION_WARNING = f"""
INSERT INTO sharded_ingestion_warnings (team_id, source, type, details, timestamp, _timestamp, _offset, _partition)
SELECT %(team_id)s, %(source)s, %(type)s, %(details)s, %(timestamp)s, now(), 0, 0
"""


def INGESTION_WARNINGS_TABLE_BASE_SQL():
    return """
CREATE TABLE IF NOT EXISTS {table_name}
(
    team_id Int64,
    source LowCardinality(VARCHAR),
    type VARCHAR,
    details VARCHAR CODEC(ZSTD(3)),
    timestamp DateTime64(6, 'UTC')
    {extra_fields}
) ENGINE = {engine}
"""


def KAFKA_INGESTION_WARNINGS_TABLE_SQL():
    return INGESTION_WARNINGS_TABLE_BASE_SQL().format(
        table_name="kafka_ingestion_warnings",
        engine=kafka_engine(topic=KAFKA_INGESTION_WARNINGS, group=CONSUMER_GROUP_INGESTION_WARNINGS),
        materialized_columns="",
        extra_fields="",
    )
