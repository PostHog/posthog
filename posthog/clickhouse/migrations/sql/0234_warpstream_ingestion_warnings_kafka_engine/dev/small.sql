CREATE TABLE IF NOT EXISTS kafka_ingestion_warnings_ws
(
    team_id Int64,
    source LowCardinality(VARCHAR),
    type VARCHAR,
    details VARCHAR CODEC(ZSTD(3)),
    timestamp DateTime64(6, 'UTC')
    
) ENGINE = Kafka(warpstream_ingestion, kafka_topic_list = 'clickhouse_ingestion_warnings', kafka_group_name = 'clickhouse_ingestion_warnings_ws', kafka_format = 'JSONEachRow')

CREATE MATERIALIZED VIEW IF NOT EXISTS ingestion_warnings_ws_mv
TO default.writable_ingestion_warnings
AS SELECT
team_id,
source,
type,
details,
timestamp,
_timestamp,
_offset,
_partition
FROM default.kafka_ingestion_warnings_ws
