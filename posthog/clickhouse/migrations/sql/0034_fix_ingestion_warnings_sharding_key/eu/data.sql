DROP TABLE IF EXISTS ingestion_warnings_mv

DROP TABLE IF EXISTS kafka_ingestion_warnings

DROP TABLE IF EXISTS ingestion_warnings

CREATE TABLE IF NOT EXISTS ingestion_warnings
(
    team_id Int64,
    source LowCardinality(VARCHAR),
    type VARCHAR,
    details VARCHAR CODEC(ZSTD(3)),
    timestamp DateTime64(6, 'UTC')
    
, _timestamp DateTime
, _offset UInt64
, _partition UInt64

) ENGINE = Distributed('posthog', 'default', 'sharded_ingestion_warnings', rand())

CREATE TABLE IF NOT EXISTS kafka_ingestion_warnings
(
    team_id Int64,
    source LowCardinality(VARCHAR),
    type VARCHAR,
    details VARCHAR CODEC(ZSTD(3)),
    timestamp DateTime64(6, 'UTC')
    
) ENGINE = Kafka(msk_cluster, kafka_topic_list = 'clickhouse_ingestion_warnings', kafka_group_name = 'group1', kafka_format = 'JSONEachRow')

CREATE MATERIALIZED VIEW IF NOT EXISTS ingestion_warnings_mv
TO default.ingestion_warnings
AS SELECT
team_id,
source,
type,
details,
timestamp,
_timestamp,
_offset,
_partition
FROM default.kafka_ingestion_warnings
