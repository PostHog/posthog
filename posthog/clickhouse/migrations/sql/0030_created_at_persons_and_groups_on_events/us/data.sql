DROP TABLE IF EXISTS events_json_mv ON CLUSTER 'posthog'

DROP TABLE IF EXISTS kafka_events_json ON CLUSTER 'posthog'

CREATE TABLE IF NOT EXISTS kafka_events_json ON CLUSTER 'posthog'
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
    
    
    
) ENGINE = Kafka(msk_cluster, kafka_topic_list = 'clickhouse_events_json', kafka_group_name = 'clickhouse_events_json', kafka_format = 'JSONEachRow')

    SETTINGS kafka_skip_broken_messages = 100

CREATE MATERIALIZED VIEW IF NOT EXISTS events_json_mv ON CLUSTER 'posthog'
TO default.writable_events
AS SELECT
uuid,
event,
properties,
timestamp,
team_id,
distinct_id,
elements_chain,
created_at,
person_id,
person_created_at,
person_properties,
group0_properties,
group1_properties,
group2_properties,
group3_properties,
group4_properties,
group0_created_at,
group1_created_at,
group2_created_at,
group3_created_at,
group4_created_at,
person_mode,
historical_migration,
dmat_string_0,
dmat_string_1,
dmat_string_2,
dmat_string_3,
dmat_string_4,
dmat_string_5,
dmat_string_6,
dmat_string_7,
dmat_string_8,
dmat_string_9,
dmat_numeric_0,
dmat_numeric_1,
dmat_numeric_2,
dmat_numeric_3,
dmat_numeric_4,
dmat_numeric_5,
dmat_numeric_6,
dmat_numeric_7,
dmat_numeric_8,
dmat_numeric_9,
dmat_bool_0,
dmat_bool_1,
dmat_bool_2,
dmat_bool_3,
dmat_bool_4,
dmat_bool_5,
dmat_bool_6,
dmat_bool_7,
dmat_bool_8,
dmat_bool_9,
dmat_datetime_0,
dmat_datetime_1,
dmat_datetime_2,
dmat_datetime_3,
dmat_datetime_4,
dmat_datetime_5,
dmat_datetime_6,
dmat_datetime_7,
dmat_datetime_8,
dmat_datetime_9,
_timestamp,
_offset,
arrayMap(
    i -> _headers.value[i],
    arrayFilter(
        i -> _headers.name[i] = 'kafka-consumer-breadcrumbs',
        arrayEnumerate(_headers.name)
    )
) as consumer_breadcrumbs
FROM default.kafka_events_json
