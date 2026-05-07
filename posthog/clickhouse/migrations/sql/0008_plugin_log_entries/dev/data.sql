CREATE TABLE IF NOT EXISTS plugin_log_entries ON CLUSTER 'posthog'
(
    id UUID,
    team_id Int64,
    plugin_id Int64,
    plugin_config_id Int64,
    timestamp DateTime64(6, 'UTC'),
    source VARCHAR,
    type VARCHAR,
    message VARCHAR,
    instance_id UUID
    
, _timestamp DateTime
, _offset UInt64

) ENGINE = ReplicatedReplacingMergeTree('/clickhouse/tables/noshard/posthog.plugin_log_entries', '{replica}-{shard}', _timestamp)
PARTITION BY toYYYYMMDD(timestamp) ORDER BY (team_id, plugin_id, plugin_config_id, timestamp)
TTL toDate(timestamp) + INTERVAL 1 WEEK
SETTINGS index_granularity=512

CREATE TABLE IF NOT EXISTS kafka_plugin_log_entries ON CLUSTER 'posthog'
(
    id UUID,
    team_id Int64,
    plugin_id Int64,
    plugin_config_id Int64,
    timestamp DateTime64(6, 'UTC'),
    source VARCHAR,
    type VARCHAR,
    message VARCHAR,
    instance_id UUID
    
) ENGINE = Kafka(msk_cluster, kafka_topic_list = 'plugin_log_entries', kafka_group_name = 'group1', kafka_format = 'JSONEachRow')

CREATE MATERIALIZED VIEW IF NOT EXISTS plugin_log_entries_mv ON CLUSTER 'posthog'
TO plugin_log_entries
AS SELECT
id,
team_id,
plugin_id,
plugin_config_id,
timestamp,
source,
type,
message,
instance_id,
_timestamp,
_offset
FROM kafka_plugin_log_entries
