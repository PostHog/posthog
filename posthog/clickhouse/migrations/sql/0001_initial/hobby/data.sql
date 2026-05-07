CREATE DATABASE IF NOT EXISTS default ON CLUSTER 'posthog'

CREATE TABLE IF NOT EXISTS sharded_events ON CLUSTER 'posthog'
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
    
    , $group_0 VARCHAR MATERIALIZED replaceRegexpAll(JSONExtractRaw(properties, '$group_0'), '^"|"$', '') COMMENT 'column_materializer::$group_0'
    , $group_1 VARCHAR MATERIALIZED replaceRegexpAll(JSONExtractRaw(properties, '$group_1'), '^"|"$', '') COMMENT 'column_materializer::$group_1'
    , $group_2 VARCHAR MATERIALIZED replaceRegexpAll(JSONExtractRaw(properties, '$group_2'), '^"|"$', '') COMMENT 'column_materializer::$group_2'
    , $group_3 VARCHAR MATERIALIZED replaceRegexpAll(JSONExtractRaw(properties, '$group_3'), '^"|"$', '') COMMENT 'column_materializer::$group_3'
    , $group_4 VARCHAR MATERIALIZED replaceRegexpAll(JSONExtractRaw(properties, '$group_4'), '^"|"$', '') COMMENT 'column_materializer::$group_4'
    , $window_id VARCHAR MATERIALIZED replaceRegexpAll(JSONExtractRaw(properties, '$window_id'), '^"|"$', '') COMMENT 'column_materializer::$window_id'
    , $session_id VARCHAR MATERIALIZED replaceRegexpAll(JSONExtractRaw(properties, '$session_id'), '^"|"$', '') COMMENT 'column_materializer::$session_id'
    , $session_id_uuid Nullable(UInt128) MATERIALIZED toUInt128(JSONExtract(properties, '$session_id', 'Nullable(UUID)'))
    , elements_chain_href String MATERIALIZED extract(elements_chain, '(?::|")href="(.*?)"')
    , elements_chain_texts Array(String) MATERIALIZED arrayDistinct(extractAll(elements_chain, '(?::|")text="(.*?)"'))
    , elements_chain_ids Array(String) MATERIALIZED arrayDistinct(extractAll(elements_chain, '(?::|")attr_id="(.*?)"'))
    , elements_chain_elements Array(Enum('a', 'button', 'form', 'input', 'select', 'textarea', 'label')) MATERIALIZED arrayDistinct(extractAll(elements_chain, '(?:^|;)(a|button|form|input|select|textarea|label)(?:\.|$|:)'))
    , INDEX `minmax_$group_0` `$group_0` TYPE minmax GRANULARITY 1
    , INDEX `minmax_$group_1` `$group_1` TYPE minmax GRANULARITY 1
    , INDEX `minmax_$group_2` `$group_2` TYPE minmax GRANULARITY 1
    , INDEX `minmax_$group_3` `$group_3` TYPE minmax GRANULARITY 1
    , INDEX `minmax_$group_4` `$group_4` TYPE minmax GRANULARITY 1
    , INDEX `minmax_$window_id` `$window_id` TYPE minmax GRANULARITY 1
    , INDEX `minmax_$session_id` `$session_id` TYPE minmax GRANULARITY 1
    , INDEX `minmax_$session_id_uuid` `$session_id_uuid` TYPE minmax GRANULARITY 1
    ,             properties_group_custom Map(String, String)
            MATERIALIZED mapSort(
                mapFilter((key, _) -> key NOT LIKE '$%' AND key NOT IN ('token', 'distinct_id', 'utm_source', 'utm_medium', 'utm_campaign', 'utm_content', 'utm_term', 'gclid', 'gad_source', 'gclsrc', 'dclid', 'gbraid', 'wbraid', 'fbclid', 'msclkid', 'twclid', 'li_fat_id', 'mc_cid', 'igshid', 'ttclid', 'rdt_cid', 'epik', 'qclid', 'sccid', 'irclid', '_kx'),
                CAST(JSONExtractKeysAndValues(properties, 'String'), 'Map(String, String)'))
            )
            CODEC(ZSTD(1))
        , INDEX properties_group_custom_keys_bf mapKeys(properties_group_custom) TYPE bloom_filter, INDEX properties_group_custom_values_bf mapValues(properties_group_custom) TYPE bloom_filter,             properties_group_ai Map(String, String)
            MATERIALIZED mapSort(
                mapFilter((key, _) -> key LIKE '$ai_%' AND key NOT IN ('$ai_input', '$ai_input_state', '$ai_output', '$ai_output_choices', '$ai_output_state', '$ai_tools'),
                CAST(JSONExtractKeysAndValues(properties, 'String'), 'Map(String, String)'))
            )
            CODEC(ZSTD(1))
        , INDEX properties_group_ai_keys_bf mapKeys(properties_group_ai) TYPE bloom_filter, INDEX properties_group_ai_values_bf mapValues(properties_group_ai) TYPE bloom_filter,             properties_group_ai_large Map(String, String)
            MATERIALIZED mapSort(
                mapFilter((key, _) -> key IN ('$ai_input', '$ai_input_state', '$ai_output', '$ai_output_choices', '$ai_output_state', '$ai_tools'),
                CAST(JSONExtractKeysAndValues(properties, 'String'), 'Map(String, String)'))
            )
            CODEC(ZSTD(1))
        , INDEX properties_group_ai_large_keys_bf mapKeys(properties_group_ai_large) TYPE bloom_filter, INDEX properties_group_ai_large_values_bf mapValues(properties_group_ai_large) TYPE bloom_filter,             properties_group_feature_flags Map(String, String)
            MATERIALIZED mapSort(
                mapFilter((key, _) -> key like '$feature/%',
                CAST(JSONExtractKeysAndValues(properties, 'String'), 'Map(String, String)'))
            )
            CODEC(ZSTD(1))
        , INDEX properties_group_feature_flags_keys_bf mapKeys(properties_group_feature_flags) TYPE bloom_filter, INDEX properties_group_feature_flags_values_bf mapValues(properties_group_feature_flags) TYPE bloom_filter,             person_properties_map_custom Map(String, String)
            MATERIALIZED mapSort(
                mapFilter((key, _) -> key NOT LIKE '$%',
                CAST(JSONExtractKeysAndValues(person_properties, 'String'), 'Map(String, String)'))
            )
            CODEC(ZSTD(1))
        , INDEX person_properties_map_custom_keys_bf mapKeys(person_properties_map_custom) TYPE bloom_filter, INDEX person_properties_map_custom_values_bf mapValues(person_properties_map_custom) TYPE bloom_filter

    
, _timestamp DateTime
, _offset UInt64
, inserted_at Nullable(DateTime64(6, 'UTC')) DEFAULT NOW64(), consumer_breadcrumbs Array(String)
    
    , INDEX kafka_timestamp_minmax_sharded_events _timestamp TYPE minmax GRANULARITY 3
    
) ENGINE = ReplicatedReplacingMergeTree('/clickhouse/tables/{shard}/posthog.events', '{replica}', _timestamp)
PARTITION BY toYYYYMM(timestamp)
ORDER BY (team_id, toDate(timestamp), event, cityHash64(distinct_id), cityHash64(uuid))
SAMPLE BY cityHash64(distinct_id)
