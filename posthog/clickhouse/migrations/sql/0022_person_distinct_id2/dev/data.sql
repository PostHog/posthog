CREATE TABLE IF NOT EXISTS person_distinct_id2 ON CLUSTER 'posthog'
(
    team_id Int64,
    distinct_id VARCHAR,
    person_id UUID,
    is_deleted Int8,
    version Int64
    
    
, _timestamp DateTime
, _offset UInt64

    , _partition UInt64
    , INDEX kafka_timestamp_minmax_person_distinct_id2 _timestamp TYPE minmax GRANULARITY 3
    
) ENGINE = ReplicatedReplacingMergeTree('/clickhouse/tables/noshard/posthog.person_distinct_id2', '{replica}-{shard}', version)

    ORDER BY (team_id, distinct_id)
    SETTINGS index_granularity = 512

CREATE TABLE IF NOT EXISTS kafka_person_distinct_id2 ON CLUSTER 'posthog'
(
    team_id Int64,
    distinct_id VARCHAR,
    person_id UUID,
    is_deleted Int8,
    version Int64
    
) ENGINE = Kafka(msk_cluster, kafka_topic_list = 'clickhouse_person_distinct_id', kafka_group_name = 'group1', kafka_format = 'JSONEachRow')

CREATE MATERIALIZED VIEW IF NOT EXISTS person_distinct_id2_mv ON CLUSTER 'posthog'
TO person_distinct_id2
AS SELECT
team_id,
distinct_id,
person_id,
is_deleted,
version,
_timestamp,
_offset,
_partition
FROM kafka_person_distinct_id2
