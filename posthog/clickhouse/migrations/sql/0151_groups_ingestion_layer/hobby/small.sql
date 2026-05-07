CREATE TABLE IF NOT EXISTS writable_groups 
(
    group_type_index UInt8,
    group_key VARCHAR,
    created_at DateTime64,
    team_id Int64,
    group_properties VARCHAR
    
, _timestamp DateTime
, _offset UInt64

) ENGINE = Distributed('posthog_single_shard', 'default', 'groups')

CREATE TABLE IF NOT EXISTS kafka_groups 
(
    group_type_index UInt8,
    group_key VARCHAR,
    created_at DateTime64,
    team_id Int64,
    group_properties VARCHAR
    
) ENGINE = Kafka(msk_cluster, kafka_topic_list = 'clickhouse_groups', kafka_group_name = 'group1', kafka_format = 'JSONEachRow')

CREATE MATERIALIZED VIEW IF NOT EXISTS groups_mv 
TO writable_groups
AS SELECT
group_type_index,
group_key,
created_at,
team_id,
group_properties,
_timestamp,
_offset
FROM kafka_groups
