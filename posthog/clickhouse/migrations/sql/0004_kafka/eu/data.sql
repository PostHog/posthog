CREATE TABLE IF NOT EXISTS kafka_person ON CLUSTER 'posthog'
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

CREATE TABLE IF NOT EXISTS kafka_person_distinct_id ON CLUSTER 'posthog'
(
    distinct_id VARCHAR,
    person_id UUID,
    team_id Int64,
    _sign Nullable(Int8),
    is_deleted Nullable(Int8)
) ENGINE = Kafka(msk_cluster, kafka_topic_list = 'clickhouse_person_unique_id', kafka_group_name = 'group1', kafka_format = 'JSONEachRow')

CREATE MATERIALIZED VIEW IF NOT EXISTS person_mv ON CLUSTER 'posthog'
TO person
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

CREATE MATERIALIZED VIEW IF NOT EXISTS person_distinct_id_mv ON CLUSTER 'posthog'
TO default.person_distinct_id
AS SELECT
distinct_id,
person_id,
team_id,
coalesce(_sign, if(is_deleted==0, 1, -1)) AS _sign,
_timestamp,
_offset
FROM default.kafka_person_distinct_id

CREATE TABLE IF NOT EXISTS writable_events ON CLUSTER 'posthog'
(
    uuid UUID,
    event VARCHAR,
    properties VARCHAR CODEC(ZSTD(3)),
    timestamp DateTime64(6, 'UTC'),
    team_id Int64,
    distinct_id VARCHAR,
    elements_chain VARCHAR,
    created_at DateTime64(6, 'UTC'),
    person_id UUID,
    person_created_at DateTime64,
    person_properties VARCHAR Codec(ZSTD(3)),
    group0_properties VARCHAR Codec(ZSTD(3)),
    group1_properties VARCHAR Codec(ZSTD(3)),
    group2_properties VARCHAR Codec(ZSTD(3)),
    group3_properties VARCHAR Codec(ZSTD(3)),
    group4_properties VARCHAR Codec(ZSTD(3)),
    group0_created_at DateTime64,
    group1_created_at DateTime64,
    group2_created_at DateTime64,
    group3_created_at DateTime64,
    group4_created_at DateTime64,
    person_mode Enum8('full' = 0, 'propertyless' = 1, 'force_upgrade' = 2),
    historical_migration Bool
        , `dmat_string_0` Nullable(String)
    , `dmat_string_1` Nullable(String)
    , `dmat_string_2` Nullable(String)
    , `dmat_string_3` Nullable(String)
    , `dmat_string_4` Nullable(String)
    , `dmat_string_5` Nullable(String)
    , `dmat_string_6` Nullable(String)
    , `dmat_string_7` Nullable(String)
    , `dmat_string_8` Nullable(String)
    , `dmat_string_9` Nullable(String)
    , `dmat_numeric_0` Nullable(Float64)
    , `dmat_numeric_1` Nullable(Float64)
    , `dmat_numeric_2` Nullable(Float64)
    , `dmat_numeric_3` Nullable(Float64)
    , `dmat_numeric_4` Nullable(Float64)
    , `dmat_numeric_5` Nullable(Float64)
    , `dmat_numeric_6` Nullable(Float64)
    , `dmat_numeric_7` Nullable(Float64)
    , `dmat_numeric_8` Nullable(Float64)
    , `dmat_numeric_9` Nullable(Float64)
    , `dmat_bool_0` Nullable(UInt8)
    , `dmat_bool_1` Nullable(UInt8)
    , `dmat_bool_2` Nullable(UInt8)
    , `dmat_bool_3` Nullable(UInt8)
    , `dmat_bool_4` Nullable(UInt8)
    , `dmat_bool_5` Nullable(UInt8)
    , `dmat_bool_6` Nullable(UInt8)
    , `dmat_bool_7` Nullable(UInt8)
    , `dmat_bool_8` Nullable(UInt8)
    , `dmat_bool_9` Nullable(UInt8)
    , `dmat_datetime_0` Nullable(DateTime64(6, 'UTC'))
    , `dmat_datetime_1` Nullable(DateTime64(6, 'UTC'))
    , `dmat_datetime_2` Nullable(DateTime64(6, 'UTC'))
    , `dmat_datetime_3` Nullable(DateTime64(6, 'UTC'))
    , `dmat_datetime_4` Nullable(DateTime64(6, 'UTC'))
    , `dmat_datetime_5` Nullable(DateTime64(6, 'UTC'))
    , `dmat_datetime_6` Nullable(DateTime64(6, 'UTC'))
    , `dmat_datetime_7` Nullable(DateTime64(6, 'UTC'))
    , `dmat_datetime_8` Nullable(DateTime64(6, 'UTC'))
    , `dmat_datetime_9` Nullable(DateTime64(6, 'UTC'))
    
    
, _timestamp DateTime
, _offset UInt64
, consumer_breadcrumbs Array(String)
    
) ENGINE = Distributed('posthog', 'default', 'sharded_events', sipHash64(distinct_id))

CREATE TABLE IF NOT EXISTS events ON CLUSTER 'posthog'
(
    uuid UUID,
    event VARCHAR,
    properties VARCHAR CODEC(ZSTD(3)),
    timestamp DateTime64(6, 'UTC'),
    team_id Int64,
    distinct_id VARCHAR,
    elements_chain VARCHAR,
    created_at DateTime64(6, 'UTC'),
    person_id UUID,
    person_created_at DateTime64,
    person_properties VARCHAR Codec(ZSTD(3)),
    group0_properties VARCHAR Codec(ZSTD(3)),
    group1_properties VARCHAR Codec(ZSTD(3)),
    group2_properties VARCHAR Codec(ZSTD(3)),
    group3_properties VARCHAR Codec(ZSTD(3)),
    group4_properties VARCHAR Codec(ZSTD(3)),
    group0_created_at DateTime64,
    group1_created_at DateTime64,
    group2_created_at DateTime64,
    group3_created_at DateTime64,
    group4_created_at DateTime64,
    person_mode Enum8('full' = 0, 'propertyless' = 1, 'force_upgrade' = 2),
    historical_migration Bool
        , `dmat_string_0` Nullable(String)
    , `dmat_string_1` Nullable(String)
    , `dmat_string_2` Nullable(String)
    , `dmat_string_3` Nullable(String)
    , `dmat_string_4` Nullable(String)
    , `dmat_string_5` Nullable(String)
    , `dmat_string_6` Nullable(String)
    , `dmat_string_7` Nullable(String)
    , `dmat_string_8` Nullable(String)
    , `dmat_string_9` Nullable(String)
    , `dmat_numeric_0` Nullable(Float64)
    , `dmat_numeric_1` Nullable(Float64)
    , `dmat_numeric_2` Nullable(Float64)
    , `dmat_numeric_3` Nullable(Float64)
    , `dmat_numeric_4` Nullable(Float64)
    , `dmat_numeric_5` Nullable(Float64)
    , `dmat_numeric_6` Nullable(Float64)
    , `dmat_numeric_7` Nullable(Float64)
    , `dmat_numeric_8` Nullable(Float64)
    , `dmat_numeric_9` Nullable(Float64)
    , `dmat_bool_0` Nullable(UInt8)
    , `dmat_bool_1` Nullable(UInt8)
    , `dmat_bool_2` Nullable(UInt8)
    , `dmat_bool_3` Nullable(UInt8)
    , `dmat_bool_4` Nullable(UInt8)
    , `dmat_bool_5` Nullable(UInt8)
    , `dmat_bool_6` Nullable(UInt8)
    , `dmat_bool_7` Nullable(UInt8)
    , `dmat_bool_8` Nullable(UInt8)
    , `dmat_bool_9` Nullable(UInt8)
    , `dmat_datetime_0` Nullable(DateTime64(6, 'UTC'))
    , `dmat_datetime_1` Nullable(DateTime64(6, 'UTC'))
    , `dmat_datetime_2` Nullable(DateTime64(6, 'UTC'))
    , `dmat_datetime_3` Nullable(DateTime64(6, 'UTC'))
    , `dmat_datetime_4` Nullable(DateTime64(6, 'UTC'))
    , `dmat_datetime_5` Nullable(DateTime64(6, 'UTC'))
    , `dmat_datetime_6` Nullable(DateTime64(6, 'UTC'))
    , `dmat_datetime_7` Nullable(DateTime64(6, 'UTC'))
    , `dmat_datetime_8` Nullable(DateTime64(6, 'UTC'))
    , `dmat_datetime_9` Nullable(DateTime64(6, 'UTC'))
    
    , $group_0 VARCHAR COMMENT 'column_materializer::$group_0'
    , $group_1 VARCHAR COMMENT 'column_materializer::$group_1'
    , $group_2 VARCHAR COMMENT 'column_materializer::$group_2'
    , $group_3 VARCHAR COMMENT 'column_materializer::$group_3'
    , $group_4 VARCHAR COMMENT 'column_materializer::$group_4'
    , $window_id VARCHAR COMMENT 'column_materializer::$window_id'
    , $session_id VARCHAR COMMENT 'column_materializer::$session_id'
    , $session_id_uuid Nullable(UInt128)
    , elements_chain_href String COMMENT 'column_materializer::elements_chain::href'
    , elements_chain_texts Array(String) COMMENT 'column_materializer::elements_chain::texts'
    , elements_chain_ids Array(String) COMMENT 'column_materializer::elements_chain::ids'
    , elements_chain_elements Array(Enum('a', 'button', 'form', 'input', 'select', 'textarea', 'label')) COMMENT 'column_materializer::elements_chain::elements'
    , properties_group_custom Map(String, String), properties_group_ai Map(String, String), properties_group_ai_large Map(String, String), properties_group_feature_flags Map(String, String), person_properties_map_custom Map(String, String)

    
, _timestamp DateTime
, _offset UInt64
, inserted_at Nullable(DateTime64(6, 'UTC')) DEFAULT NOW64(), consumer_breadcrumbs Array(String)
    
) ENGINE = Distributed('posthog', 'default', 'sharded_events', sipHash64(distinct_id))
