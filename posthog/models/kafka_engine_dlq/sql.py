KAFKA_ENGINE_DLQ_BASE_SQL = """
CREATE MATERIALIZED VIEW {database}.{kafka_table_name}_dlq
(
    `topic` String,
    `partition` Int64,
    `offset` Int64,
    `raw` String,
    `error` String
)
ENGINE = MergeTree
ORDER BY (topic, partition, offset)
SETTINGS index_granularity = 8192 AS
SELECT
    _topic AS topic,
    _partition AS partition,
    _offset AS offset,
    _raw_message AS raw,
    _error AS error
FROM {database}.{kafka_table_name}
WHERE length(_error) > 0
"""
