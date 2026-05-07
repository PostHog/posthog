CREATE TABLE IF NOT EXISTS groups ON CLUSTER 'posthog'
(
    group_type_index UInt8,
    group_key VARCHAR,
    created_at DateTime64,
    team_id Int64,
    group_properties VARCHAR
    
, _timestamp DateTime
, _offset UInt64

) ENGINE = ReplicatedReplacingMergeTree('/clickhouse/tables/noshard/posthog.groups', '{replica}-{shard}', _timestamp)
ORDER BY (team_id, group_type_index, group_key)

CREATE TABLE IF NOT EXISTS kafka_groups ON CLUSTER 'posthog'
(
    group_type_index UInt8,
    group_key VARCHAR,
    created_at DateTime64,
    team_id Int64,
    group_properties VARCHAR
    
) ENGINE = Kafka(msk_cluster, kafka_topic_list = 'clickhouse_groups', kafka_group_name = 'group1', kafka_format = 'JSONEachRow')

CREATE MATERIALIZED VIEW IF NOT EXISTS groups_mv ON CLUSTER 'posthog'
TO groups
AS SELECT
group_type_index,
group_key,
created_at,
team_id,
group_properties,
_timestamp,
_offset
FROM kafka_groups
