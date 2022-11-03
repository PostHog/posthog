# Every table using the Kafka Engine should have this corresponding
# dead letter queue (DLQ) table. This table will host all messages
# that couldn't be consumed by the ClickHouse consumer for the topic
# and inserted into the desired table and their corresponding errors.
# This can then be used to set up monitoring and debugging issues
# with the messages in Kafka, either because we've produced invalid
# messages (which we shouldn't), or because ClickHouse couldn't
# consume them due to a bug or otherwise. This is essential
# to make sure we're not silently dropping events and so we
# can have full oversight over the end-to-end ingestion pipeline.

KAFKA_ENGINE_DLQ_BASE_SQL = """
CREATE TABLE IF NOT EXISTS {table} ON CLUSTER '{cluster}'
(
    topic VARCHAR,
    partition Int64,
    offset Int64,
    raw VARCHAR,
    error VARCHAR
)
ENGINE = {engine}
ORDER BY (topic, partition, offset)
"""

KAFKA_ENGINE_DLQ_MV_BASE_SQL = """
CREATE MATERIALIZED VIEW {view_name}
TO {target_table}
AS SELECT
    _topic AS topic,
    _partition AS partition,
    _offset AS offset,
    _raw_message AS raw,
    _error AS error
FROM {kafka_table_name}
WHERE length(_error) > 0
"""
