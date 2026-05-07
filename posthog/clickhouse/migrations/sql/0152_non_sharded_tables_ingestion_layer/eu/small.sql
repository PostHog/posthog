CREATE TABLE IF NOT EXISTS writable_person_distinct_id2 
(
    team_id Int64,
    distinct_id VARCHAR,
    person_id UUID,
    is_deleted Int8,
    version Int64
    
    
, _timestamp DateTime
, _offset UInt64
, _partition UInt64

    
) ENGINE = Distributed('posthog_single_shard', 'default', 'person_distinct_id2')

CREATE TABLE IF NOT EXISTS kafka_person_distinct_id2 
(
    team_id Int64,
    distinct_id VARCHAR,
    person_id UUID,
    is_deleted Int8,
    version Int64
    
) ENGINE = Kafka(msk_cluster, kafka_topic_list = 'clickhouse_person_distinct_id', kafka_group_name = 'group1', kafka_format = 'JSONEachRow')

CREATE MATERIALIZED VIEW IF NOT EXISTS person_distinct_id2_mv 
TO writable_person_distinct_id2
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

CREATE TABLE IF NOT EXISTS writable_person_distinct_id_overrides 
(
    team_id Int64,
    distinct_id VARCHAR,
    person_id UUID,
    is_deleted Int8,
    version Int64
    
    
, _timestamp DateTime
, _offset UInt64
, _partition UInt64

    
) ENGINE = Distributed('posthog_single_shard', 'default', 'person_distinct_id_overrides')

CREATE TABLE IF NOT EXISTS kafka_person_distinct_id_overrides 
(
    team_id Int64,
    distinct_id VARCHAR,
    person_id UUID,
    is_deleted Int8,
    version Int64
    
) ENGINE = Kafka(msk_cluster, kafka_topic_list = 'clickhouse_person_distinct_id', kafka_group_name = 'clickhouse-person-distinct-id-overrides', kafka_format = 'JSONEachRow')

CREATE MATERIALIZED VIEW IF NOT EXISTS person_distinct_id_overrides_mv 
TO writable_person_distinct_id_overrides
AS SELECT
team_id,
distinct_id,
person_id,
is_deleted,
version,
_timestamp,
_offset,
_partition
FROM kafka_person_distinct_id_overrides
WHERE version > 0 -- only store updated rows, not newly inserted ones

CREATE TABLE IF NOT EXISTS writable_plugin_log_entries 
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

) ENGINE = Distributed('posthog_single_shard', 'default', 'plugin_log_entries')

CREATE TABLE IF NOT EXISTS kafka_plugin_log_entries 
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

CREATE MATERIALIZED VIEW IF NOT EXISTS plugin_log_entries_mv 
TO writable_plugin_log_entries
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

CREATE TABLE IF NOT EXISTS writable_person 
(
    id UUID,
    created_at DateTime64,
    team_id Int64,
    properties VARCHAR,
    is_identified Int8,
    is_deleted Int8,
    version UInt64,
    last_seen_at Nullable(DateTime64)
    
, _timestamp DateTime
, _offset UInt64

) ENGINE = Distributed('posthog_single_shard', 'default', 'person')

CREATE TABLE IF NOT EXISTS kafka_person 
(
    id UUID,
    created_at DateTime64,
    team_id Int64,
    properties VARCHAR,
    is_identified Int8,
    is_deleted Int8,
    version UInt64,
    last_seen_at Nullable(DateTime64)
    
) ENGINE = Kafka(msk_cluster, kafka_topic_list = 'clickhouse_person', kafka_group_name = 'group1', kafka_format = 'JSONEachRow')

CREATE MATERIALIZED VIEW IF NOT EXISTS person_mv 
TO writable_person
AS SELECT
id,
created_at,
team_id,
properties,
is_identified,
is_deleted,
version,
last_seen_at,
_timestamp,
_offset
FROM kafka_person
