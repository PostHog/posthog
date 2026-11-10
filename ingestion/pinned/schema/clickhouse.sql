-- The ClickHouse objects the Node packages reach, cut from the schema setup_test_environment creates.
-- Refresh with ingestion/pinned/schema/refresh (see SOURCE.json for the source commit).

CREATE TABLE IF NOT EXISTS log_entries 
(
    team_id UInt64,
    -- The name of the service or product that generated the logs.
    -- Examples: batch_exports
    log_source LowCardinality(String),
    -- An id for the log source.
    -- Set log_source to avoid collision with ids from other log sources if the id generation is not safe.
    -- Examples: A batch export id, a cronjob id, a plugin id.
    log_source_id String,
    -- A secondary id e.g. for the instance of log_source that generated this log.
    -- This may be ommitted if log_source is a singleton.
    -- Examples: A batch export run id, a plugin_config id, a thread id, a process id, a machine id.
    instance_id String,
    -- Timestamp indicating when the log was generated.
    timestamp DateTime64(6, 'UTC'),
    -- The log level.
    -- Examples: INFO, WARNING, DEBUG, ERROR.
    level LowCardinality(String),
    -- The actual log message.
    message String
    
, _timestamp DateTime
, _offset UInt64

) ENGINE = ReplicatedReplacingMergeTree('/clickhouse/tables/85bacb5a-d150-4a53-8be3-5d920db0c909_noshard/posthog.log_entries', '{replica}-{shard}', _timestamp)
PARTITION BY toStartOfHour(timestamp) ORDER BY (team_id, log_source, log_source_id, instance_id, timestamp)

SETTINGS index_granularity=512;

CREATE TABLE IF NOT EXISTS log_entries_data 
(
    team_id UInt64,
    -- The name of the service or product that generated the logs.
    -- Examples: batch_exports
    log_source LowCardinality(String),
    -- An id for the log source.
    -- Set log_source to avoid collision with ids from other log sources if the id generation is not safe.
    -- Examples: A batch export id, a cronjob id, a plugin id.
    log_source_id String,
    -- A secondary id e.g. for the instance of log_source that generated this log.
    -- This may be ommitted if log_source is a singleton.
    -- Examples: A batch export run id, a plugin_config id, a thread id, a process id, a machine id.
    instance_id String,
    -- Timestamp indicating when the log was generated.
    timestamp DateTime64(6, 'UTC'),
    -- The log level.
    -- Examples: INFO, WARNING, DEBUG, ERROR.
    level LowCardinality(String),
    -- The actual log message.
    message String
    
, _timestamp DateTime
, _offset UInt64

) ENGINE = ReplicatedReplacingMergeTree('/clickhouse/tables/e1654e30-99fb-4a31-85bc-9832fc901ca3_noshard/posthog.log_entries_data', '{replica}-{shard}', _timestamp)
PARTITION BY toYYYYMMDD(timestamp) ORDER BY (team_id, log_source, log_source_id, instance_id, timestamp)
TTL toDate(timestamp) + INTERVAL 90 DAY DELETE
SETTINGS index_granularity = 1024, ttl_only_drop_parts = 1;

CREATE TABLE IF NOT EXISTS cohortpeople 
(
    person_id UUID,
    cohort_id Int64,
    team_id Int64,
    sign Int8,
    version UInt64
) ENGINE = ReplicatedCollapsingMergeTree('/clickhouse/tables/e0474da1-6d19-4baf-9ac2-efd9d3c50abd_noshard/posthog.cohortpeople', '{replica}-{shard}', sign)
Order By (team_id, cohort_id, person_id, version);

CREATE TABLE IF NOT EXISTS person_static_cohort 
(
    id UUID,
    person_id UUID,
    cohort_id Int64,
    team_id Int64
    
, _timestamp DateTime
, _offset UInt64

) ENGINE = ReplicatedReplacingMergeTree('/clickhouse/tables/bc9a0fba-1225-47a0-b336-33e5eeb3a461_noshard/posthog.person_static_cohort', '{replica}-{shard}', _timestamp)
Order By (team_id, cohort_id, person_id, id);

CREATE TABLE IF NOT EXISTS events_dead_letter_queue 
(
    id UUID,
    event_uuid UUID,
    event VARCHAR,
    properties VARCHAR,
    distinct_id VARCHAR,
    team_id Int64,
    elements_chain VARCHAR,
    created_at DateTime64(6, 'UTC'),
    ip VARCHAR,
    site_url VARCHAR,
    now DateTime64(6, 'UTC'),
    raw_payload VARCHAR,
    error_timestamp DateTime64(6, 'UTC'),
    error_location VARCHAR,
    error VARCHAR,
    tags Array(VARCHAR)
    
    
, _timestamp DateTime
, _offset UInt64

    , INDEX kafka_timestamp_minmax_events_dead_letter_queue _timestamp TYPE minmax GRANULARITY 3
    
) ENGINE = ReplicatedReplacingMergeTree('/clickhouse/tables/0cf1fea6-0da4-4ebf-b731-883e2def3836_noshard/posthog.events_dead_letter_queue', '{replica}-{shard}', _timestamp)
ORDER BY (id, event_uuid, distinct_id, team_id)

SETTINGS index_granularity=512;

CREATE TABLE IF NOT EXISTS sharded_events 
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
    
) ENGINE = ReplicatedReplacingMergeTree('/clickhouse/tables/7a83c417-e05e-4a8c-9753-2e40239421cc_{shard}/posthog.events', '{replica}', _timestamp)
PARTITION BY toYYYYMM(timestamp)
ORDER BY (team_id, toDate(timestamp), event, cityHash64(distinct_id), cityHash64(uuid))
SAMPLE BY cityHash64(distinct_id);

CREATE TABLE IF NOT EXISTS groups 
(
    group_type_index UInt8,
    group_key VARCHAR,
    created_at DateTime64,
    team_id Int64,
    group_properties VARCHAR
    
, _timestamp DateTime
, _offset UInt64

) ENGINE = ReplicatedReplacingMergeTree('/clickhouse/tables/8ebbc70f-13cd-4b86-80d5-944a4dd15749_noshard/posthog.groups', '{replica}-{shard}', _timestamp)
ORDER BY (team_id, group_type_index, group_key);

CREATE TABLE IF NOT EXISTS person 
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

    , INDEX kafka_timestamp_minmax_person _timestamp TYPE minmax GRANULARITY 3
    
) ENGINE = ReplicatedReplacingMergeTree('/clickhouse/tables/8b972e99-2e62-4f84-bc18-04ea420d130b_noshard/posthog.person', '{replica}-{shard}', version)
ORDER BY (team_id, id);

CREATE TABLE IF NOT EXISTS person_distinct_id 
(
    distinct_id VARCHAR,
    person_id UUID,
    team_id Int64,
    _sign Int8 DEFAULT 1,
    is_deleted Int8 ALIAS if(_sign==-1, 1, 0)
    
, _timestamp DateTime
, _offset UInt64

) ENGINE = ReplicatedCollapsingMergeTree('/clickhouse/tables/c6214070-49cb-44c5-884d-f5329d83c2d9_noshard/posthog.person_distinct_id', '{replica}-{shard}', _sign)
Order By (team_id, distinct_id, person_id);

CREATE TABLE IF NOT EXISTS person_distinct_id2 
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
    
) ENGINE = ReplicatedReplacingMergeTree('/clickhouse/tables/fad9e5c6-e089-4eea-9bca-fd512b6752fe_noshard/posthog.person_distinct_id2', '{replica}-{shard}', version)

    ORDER BY (team_id, distinct_id)
    SETTINGS index_granularity = 512;

CREATE TABLE IF NOT EXISTS person_distinct_id_overrides 
(
    team_id Int64,
    distinct_id VARCHAR,
    person_id UUID,
    is_deleted Int8,
    version Int64
    
    
, _timestamp DateTime
, _offset UInt64
, _partition UInt64

    , INDEX kafka_timestamp_minmax_person_distinct_id_overrides _timestamp TYPE minmax GRANULARITY 3
    
) ENGINE = ReplicatedReplacingMergeTree('/clickhouse/tables/e44d83f3-e58d-41eb-96d8-c4f567ae899d_noshard/posthog.person_distinct_id_overrides', '{replica}-{shard}', version)

    ORDER BY (team_id, distinct_id)
    SETTINGS index_granularity = 512;

CREATE TABLE IF NOT EXISTS plugin_log_entries 
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

) ENGINE = ReplicatedReplacingMergeTree('/clickhouse/tables/05a74340-e9c4-4865-983b-8ef75848d8f9_noshard/posthog.plugin_log_entries', '{replica}-{shard}', _timestamp)
PARTITION BY toYYYYMMDD(timestamp) ORDER BY (team_id, plugin_id, plugin_config_id, timestamp)

SETTINGS index_granularity=512;

CREATE TABLE IF NOT EXISTS sharded_ingestion_warnings
(
    team_id Int64,
    source LowCardinality(VARCHAR),
    type VARCHAR,
    details VARCHAR CODEC(ZSTD(3)),
    timestamp DateTime64(6, 'UTC')
    
, _timestamp DateTime
, _offset UInt64
, _partition UInt64

) ENGINE = ReplicatedMergeTree('/clickhouse/tables/37a35c06-1bfe-476b-891c-e13ca0219270_{shard}/posthog.sharded_ingestion_warnings', '{replica}')
PARTITION BY toYYYYMMDD(timestamp)
ORDER BY (team_id, toHour(timestamp), type, source, timestamp);

CREATE TABLE IF NOT EXISTS ingestion_warnings_v2
(
    
    team_id Int64,
    source LowCardinality(String),
    type LowCardinality(String),
    details String,
    timestamp DateTime64(6, 'UTC'),
    category LowCardinality(String) DEFAULT coalesce(nullIf(JSONExtractString(details, 'category'), ''), 'unknown'),
    severity LowCardinality(String) DEFAULT coalesce(nullIf(JSONExtractString(details, 'severity'), ''), 'warning'),
    pipeline_step LowCardinality(String) DEFAULT coalesce(nullIf(JSONExtractString(details, 'pipelineStep'), ''), 'unknown'),
    event_uuid Nullable(UUID) DEFAULT toUUIDOrNull(JSONExtractString(details, 'eventUuid')),
    distinct_id Nullable(String) DEFAULT nullIf(JSONExtractString(details, 'distinctId'), ''),
    group_key Nullable(String) DEFAULT nullIf(JSONExtractString(details, 'groupKey'), ''),
    person_id Nullable(UUID) DEFAULT toUUIDOrNull(JSONExtractString(details, 'personId')),
    _timestamp DateTime,
    _offset UInt64,
    _partition UInt64

) ENGINE = ReplicatedMergeTree('/clickhouse/tables/b834f508-23f1-4141-a8ba-e08900181af6_noshard/posthog.ingestion_warnings_v2', '{replica}-{shard}')
PARTITION BY toYYYYMM(timestamp)
ORDER BY (team_id, type, timestamp);

CREATE TABLE IF NOT EXISTS sharded_app_metrics 
(
    team_id Int64,
    timestamp DateTime64(6, 'UTC'),
    plugin_config_id Int64,
    category LowCardinality(String),
    job_id String,
    successes SimpleAggregateFunction(sum, Int64),
    successes_on_retry SimpleAggregateFunction(sum, Int64),
    failures SimpleAggregateFunction(sum, Int64),
    error_uuid UUID,
    error_type String,
    error_details String CODEC(ZSTD(3))
    
, _timestamp DateTime
, _offset UInt64
, _partition UInt64

)
ENGINE = ReplicatedAggregatingMergeTree('/clickhouse/tables/cc1ccd46-ba6d-4ef5-8b7c-75a2f1f53cc2_{shard}/posthog.sharded_app_metrics', '{replica}')
PARTITION BY toYYYYMM(timestamp)
ORDER BY (team_id, plugin_config_id, job_id, category, toStartOfHour(timestamp), error_type, error_uuid);

CREATE TABLE IF NOT EXISTS sharded_app_metrics2
(
    team_id Int64,
    timestamp DateTime64(6, 'UTC'),
    -- The name of the service or product that generated the metrics.
    -- Examples: plugins, hog
    app_source LowCardinality(String),
    -- An id for the app source.
    -- Set app_source to avoid collision with ids from other app sources if the id generation is not safe.
    -- Examples: A plugin id, a hog application id
    app_source_id String,
    -- A secondary id e.g. for the instance of app_source that generated this metric.
    -- This may be ommitted if app_source is a singleton.
    -- Examples: A plugin config id, a hog application config id
    instance_id String,
    metric_kind LowCardinality(String),
    metric_name LowCardinality(String),
    count SimpleAggregateFunction(sum, Int64)
    
, _timestamp DateTime
, _offset UInt64
, _partition UInt64

)
ENGINE = ReplicatedAggregatingMergeTree('/clickhouse/tables/522b229f-1bb5-4f7f-8e35-40b4ea0423a8_{shard}/posthog.sharded_app_metrics2', '{replica}')
PARTITION BY toYYYYMM(timestamp)
ORDER BY (team_id, app_source, app_source_id, instance_id, toStartOfHour(timestamp), metric_kind, metric_name);

CREATE TABLE IF NOT EXISTS hog_invocation_results_data
(
    team_id Int64,
    function_kind LowCardinality(String),
    function_id String,
    invocation_id String,
    parent_run_id String,
    status LowCardinality(String),
    attempts UInt8,
    is_retry UInt8,
    scheduled_at DateTime64(6, 'UTC'),
    first_scheduled_at DateTime64(6, 'UTC') DEFAULT scheduled_at,
    started_at Nullable(DateTime64(6, 'UTC')),
    finished_at Nullable(DateTime64(6, 'UTC')),
    duration_ms Nullable(UInt32),
    error_kind LowCardinality(String),
    error_message String,
    event_uuid String,
    distinct_id String,
    person_id String,
    invocation_globals String,
    version UInt64,
    is_deleted UInt8 DEFAULT 0,
    INDEX status_idx     status      TYPE set(8)             GRANULARITY 1,
    INDEX function_idx   function_id TYPE bloom_filter(0.01) GRANULARITY 1,
    INDEX event_uuid_idx event_uuid  TYPE bloom_filter(0.01) GRANULARITY 1,
    INDEX is_retry_idx   is_retry    TYPE set(2)             GRANULARITY 1
    
, _timestamp DateTime
, _offset UInt64
, _partition UInt64

)
ENGINE = ReplicatedReplacingMergeTree('/clickhouse/tables/75c179c7-a2aa-42ac-8af8-9eb7bbf7bbfe_noshard/posthog.hog_invocation_results_data', '{replica}-{shard}', version)
PARTITION BY toYYYYMMDD(scheduled_at)
ORDER BY (team_id, function_kind, function_id, invocation_id)

SETTINGS index_granularity = 1024, ttl_only_drop_parts = 1;

CREATE TABLE IF NOT EXISTS message_assets_data
(
    team_id Int64,
    function_kind LowCardinality(String),
    function_id String,
    parent_run_id String,
    invocation_id String,
    action_id String,
    kind LowCardinality(String),
    distinct_id String,
    person_id String,
    recipient String,
    subject String,
    status LowCardinality(String),
    sent_at DateTime64(6, 'UTC'),
    version UInt64,
    is_deleted UInt8 DEFAULT 0,
    html String CODEC(ZSTD(3)),
    INDEX parent_run_idx parent_run_id TYPE bloom_filter(0.01) GRANULARITY 1,
    INDEX distinct_id_idx distinct_id  TYPE bloom_filter(0.01) GRANULARITY 1,
    INDEX person_id_idx   person_id    TYPE bloom_filter(0.01) GRANULARITY 1,
    INDEX recipient_idx   recipient    TYPE bloom_filter(0.01) GRANULARITY 1
    
, _timestamp DateTime
, _offset UInt64
, _partition UInt64

)
ENGINE = ReplicatedReplacingMergeTree('/clickhouse/tables/79401355-99be-4017-9ccd-ec427a2bca0d_noshard/posthog.message_assets_data', '{replica}-{shard}', version)
PARTITION BY toYYYYMMDD(sent_at)
ORDER BY (team_id, function_kind, function_id, invocation_id, action_id)

SETTINGS index_granularity = 1024, ttl_only_drop_parts = 1;

CREATE TABLE IF NOT EXISTS email_status_data
(
    team_id Int64,
    message_id UUID,
    status LowCardinality(String),
    version UInt64,
    created_at DateTime64(6, 'UTC'),
    status_at DateTime64(6, 'UTC'),
    reason String
    
, _timestamp DateTime
, _offset UInt64
, _partition UInt64

)
ENGINE = ReplicatedReplacingMergeTree('/clickhouse/tables/ad50f87c-1584-4702-aa6c-b7e08f1d7472_noshard/posthog.email_status_data', '{replica}-{shard}', version)
PARTITION BY toYYYYMMDD(created_at)
ORDER BY (team_id, message_id)

SETTINGS index_granularity = 1024, ttl_only_drop_parts = 1;

CREATE TABLE IF NOT EXISTS sharded_session_replay_events 
(
    -- part of order by so will aggregate correctly
    session_id VARCHAR,
    -- part of order by so will aggregate correctly
    team_id Int64,
    -- ClickHouse will pick any value of distinct_id for the session
    -- this is fine since even if the distinct_id changes during a session
    -- it will still (or should still) map to the same person
    distinct_id VARCHAR,
    min_first_timestamp SimpleAggregateFunction(min, DateTime64(6, 'UTC')),
    max_last_timestamp SimpleAggregateFunction(max, DateTime64(6, 'UTC')),
    -- session recording v2 blocks
    block_first_timestamps SimpleAggregateFunction(groupArrayArray, Array(DateTime64(6, 'UTC'))),
    block_last_timestamps SimpleAggregateFunction(groupArrayArray, Array(DateTime64(6, 'UTC'))),
    block_urls SimpleAggregateFunction(groupArrayArray, Array(String)),
    -- store the first url of the session so we can quickly show that in playlists
    first_url AggregateFunction(argMin, Nullable(VARCHAR), DateTime64(6, 'UTC')),
    -- but also store each url so we can query by visited page without having to scan all events
    -- despite the name we can put mobile screens in here as well to give same functionality across platforms
    all_urls SimpleAggregateFunction(groupUniqArrayArray, Array(String)),
    click_count SimpleAggregateFunction(sum, Int64),
    keypress_count SimpleAggregateFunction(sum, Int64),
    mouse_activity_count SimpleAggregateFunction(sum, Int64),
    active_milliseconds SimpleAggregateFunction(sum, Int64),
    console_log_count SimpleAggregateFunction(sum, Int64),
    console_warn_count SimpleAggregateFunction(sum, Int64),
    console_error_count SimpleAggregateFunction(sum, Int64),
    -- this column allows us to estimate the amount of data that is being ingested
    size SimpleAggregateFunction(sum, Int64),
    -- this allows us to count the number of messages received in a session
    -- often very useful in incidents or debugging
    message_count SimpleAggregateFunction(sum, Int64),
    -- this allows us to count the number of snapshot events received in a session
    -- often very useful in incidents or debugging
    -- because we batch events we expect message_count to be lower than event_count
    event_count SimpleAggregateFunction(sum, Int64),
    -- which source the snapshots came from Mobile or Web. Web if absent
    snapshot_source AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),
    -- knowing something is mobile isn't enough, we need to know if e.g. RN or flutter
    snapshot_library AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),
    snapshot_mode_v2 AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),
    _timestamp SimpleAggregateFunction(max, DateTime),
    -- retention period for this session, in days. Useful to show TTL for the recording
    retention_period_days SimpleAggregateFunction(max, Nullable(Int64)),
    -- marks the recording as deleted for crypto shredding; once 1, merges keep it as 1
    is_deleted SimpleAggregateFunction(max, UInt8) DEFAULT 0,
    -- AI-generated session tags from the summarization pipeline (fixed taxonomy)
    ai_tags_fixed SimpleAggregateFunction(groupUniqArrayArray, Array(String)),
    -- AI-generated session tags from the summarization pipeline (free-form)
    ai_tags_freeform SimpleAggregateFunction(groupUniqArrayArray, Array(String)),
    -- AI-generated flag indicating the session is highlighted / worth watching
    ai_highlighted SimpleAggregateFunction(max, UInt8) DEFAULT 0,
    -- Score in [0, 1] from the surfacing scoring sweep used to surface sessions for downstream summarization
    surfacing_score SimpleAggregateFunction(max, Nullable(Float32)),
) ENGINE = ReplicatedAggregatingMergeTree('/clickhouse/tables/f24c1c6b-b84e-4949-8166-b050aa40625a_{shard}/posthog.session_replay_events', '{replica}')

    PARTITION BY toYYYYMM(min_first_timestamp)
    -- order by is used by the aggregating merge tree engine to
    -- identify candidates to merge, e.g. toDate(min_first_timestamp)
    -- would mean we would have one row per day per session_id
    -- if CH could completely merge to match the order by
    -- it is also used to organise data to make queries faster
    -- we want the fewest rows possible but also the fastest queries
    -- since we query by date and not by time
    -- and order by must be in order of increasing cardinality
    -- so we order by date first, then team_id, then session_id
    -- hopefully, this is a good balance between the two
    ORDER BY (toDate(min_first_timestamp), team_id, session_id)
SETTINGS index_granularity=512;

CREATE TABLE IF NOT EXISTS writable_session_replay_events 
(
    -- part of order by so will aggregate correctly
    session_id VARCHAR,
    -- part of order by so will aggregate correctly
    team_id Int64,
    -- ClickHouse will pick any value of distinct_id for the session
    -- this is fine since even if the distinct_id changes during a session
    -- it will still (or should still) map to the same person
    distinct_id VARCHAR,
    min_first_timestamp SimpleAggregateFunction(min, DateTime64(6, 'UTC')),
    max_last_timestamp SimpleAggregateFunction(max, DateTime64(6, 'UTC')),
    -- session recording v2 blocks
    block_first_timestamps SimpleAggregateFunction(groupArrayArray, Array(DateTime64(6, 'UTC'))),
    block_last_timestamps SimpleAggregateFunction(groupArrayArray, Array(DateTime64(6, 'UTC'))),
    block_urls SimpleAggregateFunction(groupArrayArray, Array(String)),
    -- store the first url of the session so we can quickly show that in playlists
    first_url AggregateFunction(argMin, Nullable(VARCHAR), DateTime64(6, 'UTC')),
    -- but also store each url so we can query by visited page without having to scan all events
    -- despite the name we can put mobile screens in here as well to give same functionality across platforms
    all_urls SimpleAggregateFunction(groupUniqArrayArray, Array(String)),
    click_count SimpleAggregateFunction(sum, Int64),
    keypress_count SimpleAggregateFunction(sum, Int64),
    mouse_activity_count SimpleAggregateFunction(sum, Int64),
    active_milliseconds SimpleAggregateFunction(sum, Int64),
    console_log_count SimpleAggregateFunction(sum, Int64),
    console_warn_count SimpleAggregateFunction(sum, Int64),
    console_error_count SimpleAggregateFunction(sum, Int64),
    -- this column allows us to estimate the amount of data that is being ingested
    size SimpleAggregateFunction(sum, Int64),
    -- this allows us to count the number of messages received in a session
    -- often very useful in incidents or debugging
    message_count SimpleAggregateFunction(sum, Int64),
    -- this allows us to count the number of snapshot events received in a session
    -- often very useful in incidents or debugging
    -- because we batch events we expect message_count to be lower than event_count
    event_count SimpleAggregateFunction(sum, Int64),
    -- which source the snapshots came from Mobile or Web. Web if absent
    snapshot_source AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),
    -- knowing something is mobile isn't enough, we need to know if e.g. RN or flutter
    snapshot_library AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),
    snapshot_mode_v2 AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),
    _timestamp SimpleAggregateFunction(max, DateTime),
    -- retention period for this session, in days. Useful to show TTL for the recording
    retention_period_days SimpleAggregateFunction(max, Nullable(Int64)),
    -- marks the recording as deleted for crypto shredding; once 1, merges keep it as 1
    is_deleted SimpleAggregateFunction(max, UInt8) DEFAULT 0,
    -- AI-generated session tags from the summarization pipeline (fixed taxonomy)
    ai_tags_fixed SimpleAggregateFunction(groupUniqArrayArray, Array(String)),
    -- AI-generated session tags from the summarization pipeline (free-form)
    ai_tags_freeform SimpleAggregateFunction(groupUniqArrayArray, Array(String)),
    -- AI-generated flag indicating the session is highlighted / worth watching
    ai_highlighted SimpleAggregateFunction(max, UInt8) DEFAULT 0,
    -- Score in [0, 1] from the surfacing scoring sweep used to surface sessions for downstream summarization
    surfacing_score SimpleAggregateFunction(max, Nullable(Float32)),
) ENGINE = Distributed('posthog', 'posthog_test', 'sharded_session_replay_events', sipHash64(distinct_id));

CREATE TABLE IF NOT EXISTS sharded_sessions 
(
    -- part of order by so will aggregate correctly
    session_id VARCHAR,
    -- part of order by so will aggregate correctly
    team_id Int64,
    -- ClickHouse will pick any value of distinct_id for the session
    -- this is fine since even if the distinct_id changes during a session
    -- it will still (or should still) map to the same person
    distinct_id SimpleAggregateFunction(any, String),

    min_timestamp SimpleAggregateFunction(min, DateTime64(6, 'UTC')),
    max_timestamp SimpleAggregateFunction(max, DateTime64(6, 'UTC')),

    urls SimpleAggregateFunction(groupUniqArrayArray, Array(String)),
    entry_url AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
    exit_url AggregateFunction(argMax, String, DateTime64(6, 'UTC')),
    initial_referring_domain AggregateFunction(argMin, String, DateTime64(6, 'UTC')),

    initial_utm_source AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
    initial_utm_campaign AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
    initial_utm_medium AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
    initial_utm_term AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
    initial_utm_content AggregateFunction(argMin, String, DateTime64(6, 'UTC')),

    -- Other Ad / campaign / attribution IDs
    initial_gclid AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
    initial_gad_source AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
    initial_gclsrc AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
    initial_dclid AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
    initial_gbraid AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
    initial_wbraid AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
    initial_fbclid AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
    initial_msclkid AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
    initial_twclid AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
    initial_li_fat_id AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
    initial_mc_cid AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
    initial_igshid AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
    initial_ttclid AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
    initial_epik AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
    initial_qclid AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
    initial_sccid AggregateFunction(argMin, String, DateTime64(6, 'UTC')),

    -- create a map of how many times we saw each event
    event_count_map SimpleAggregateFunction(sumMap, Map(String, Int64)),
    -- duplicate the event count as a specific column for pageviews and autocaptures,
    -- as these are used in some key queries and need to be fast
    pageview_count SimpleAggregateFunction(sum, Int64),
    autocapture_count SimpleAggregateFunction(sum, Int64),
) ENGINE = ReplicatedAggregatingMergeTree('/clickhouse/tables/90719083-0ac3-4559-bf8b-8629a2d189c8_{shard}/posthog.sessions', '{replica}')

    PARTITION BY toYYYYMM(min_timestamp)
    -- order by is used by the aggregating merge tree engine to
    -- identify candidates to merge, e.g. toDate(min_timestamp)
    -- would mean we would have one row per day per session_id
    -- if CH could completely merge to match the order by
    -- it is also used to organise data to make queries faster
    -- we want the fewest rows possible but also the fastest queries
    -- since we query by date and not by time
    -- and order by must be in order of increasing cardinality
    -- so we order by date first, then team_id, then session_id
    -- hopefully, this is a good balance between the two
    ORDER BY (toStartOfDay(min_timestamp), team_id, session_id)
SETTINGS index_granularity=512;

CREATE TABLE IF NOT EXISTS sharded_heatmaps
(
    session_id VARCHAR,
    team_id Int64,
    distinct_id VARCHAR,
    timestamp DateTime64(6, 'UTC'),
    -- x is the x with resolution applied, the resolution converts high fidelity mouse positions into an NxN grid
    x Int16,
    -- y is the y with resolution applied, the resolution converts high fidelity mouse positions into an NxN grid
    y Int16,
    -- stored so that in future we can support other resolutions
    scale_factor Int16,
    viewport_width Int16,
    viewport_height Int16,
    -- some elements move when the page scrolls, others do not
    pointer_target_fixed Bool,
    current_url VARCHAR,
    type LowCardinality(String),
    _timestamp DateTime,
    _offset UInt64,
    _partition UInt64
) ENGINE = ReplicatedMergeTree('/clickhouse/tables/07922881-145d-4f22-ac96-e8568c4005a4_{shard}/posthog.heatmaps', '{replica}')

    PARTITION BY toYYYYMM(timestamp)
    -- almost always this is being queried by
    --   * type,
    --   * team_id,
    --   * date range,
    --   * URL (maybe matching wild cards),
    --   * width
    -- we'll almost never query this by session id
    -- so from least to most cardinality that's
    ORDER BY (type, team_id,  toDate(timestamp), current_url, viewport_width)
    
-- I am purposefully not setting index granularity
-- the default is 8192, and we will be loading a lot of data
-- per query, we tend to copy this 512 around the place but
-- i don't think it applies here;

CREATE TABLE IF NOT EXISTS sharded_flag_evaluations
(
    uuid UUID,
    event LowCardinality(String),
    properties String,
    timestamp DateTime64(6, 'UTC'),
    team_id Int64,
    distinct_id String,
    created_at DateTime64(6, 'UTC'),
    person_id UUID,
    person_properties String DEFAULT '{}',
    person_created_at DateTime64(3),
    inserted_at DateTime64(6, 'UTC') DEFAULT timestamp,
    person_mode Enum8('full' = 0, 'propertyless' = 1, 'force_upgrade' = 2)
    
    , $group_0 String DEFAULT replaceRegexpAll(JSONExtractRaw(properties, '$group_0'), '^"|"$', '') COMMENT 'column_materializer::$group_0'
    , $group_1 String DEFAULT replaceRegexpAll(JSONExtractRaw(properties, '$group_1'), '^"|"$', '') COMMENT 'column_materializer::$group_1'
    , $group_2 String DEFAULT replaceRegexpAll(JSONExtractRaw(properties, '$group_2'), '^"|"$', '') COMMENT 'column_materializer::$group_2'
    , $group_3 String DEFAULT replaceRegexpAll(JSONExtractRaw(properties, '$group_3'), '^"|"$', '') COMMENT 'column_materializer::$group_3'
    , $group_4 String DEFAULT replaceRegexpAll(JSONExtractRaw(properties, '$group_4'), '^"|"$', '') COMMENT 'column_materializer::$group_4'
    , flag_key String DEFAULT replaceRegexpAll(JSONExtractRaw(properties, '$feature_flag'), '^"|"$', '') COMMENT 'column_materializer::properties::$feature_flag'
    , response LowCardinality(String) DEFAULT replaceRegexpAll(JSONExtractRaw(properties, '$feature_flag_response'), '^"|"$', '') COMMENT 'column_materializer::properties::$feature_flag_response'
    , session_id String DEFAULT replaceRegexpAll(JSONExtractRaw(properties, '$session_id'), '^"|"$', '') COMMENT 'column_materializer::properties::$session_id'
    , request_id String DEFAULT replaceRegexpAll(JSONExtractRaw(properties, '$feature_flag_request_id'), '^"|"$', '') COMMENT 'column_materializer::properties::$feature_flag_request_id'

    
    , properties_group_custom Map(String, String) MATERIALIZED mapSort( mapFilter((key, _) -> key NOT LIKE '$%' AND key NOT IN ('token', 'distinct_id', 'utm_source', 'utm_medium', 'utm_campaign', 'utm_content', 'utm_term', 'gclid', 'gad_source', 'gclsrc', 'dclid', 'gbraid', 'wbraid', 'fbclid', 'msclkid', 'twclid', 'li_fat_id', 'mc_cid', 'igshid', 'ttclid', 'rdt_cid', 'epik', 'qclid', 'sccid', 'irclid', '_kx'), CAST(JSONExtractKeysAndValues(properties, 'String'), 'Map(String, String)')) )
    , INDEX properties_group_custom_keys_bf mapKeys(properties_group_custom) TYPE bloom_filter
    , INDEX properties_group_custom_values_bf mapValues(properties_group_custom) TYPE bloom_filter
    , person_properties_map_custom Map(String, String) MATERIALIZED mapSort( mapFilter((key, _) -> key NOT LIKE '$%', CAST(JSONExtractKeysAndValues(person_properties, 'String'), 'Map(String, String)')) )
    , INDEX person_properties_map_custom_keys_bf mapKeys(person_properties_map_custom) TYPE bloom_filter
    , INDEX person_properties_map_custom_values_bf mapValues(person_properties_map_custom) TYPE bloom_filter
    
    , INDEX distinct_id_idx distinct_id TYPE bloom_filter(0.01) GRANULARITY 1
    , INDEX person_id_idx   person_id   TYPE bloom_filter(0.01) GRANULARITY 1
    , INDEX session_id_idx  session_id  TYPE bloom_filter(0.01) GRANULARITY 1
    , INDEX request_id_idx  request_id  TYPE bloom_filter(0.01) GRANULARITY 1
    , INDEX inserted_at_idx inserted_at TYPE minmax GRANULARITY 1

    
, _timestamp DateTime
, _offset UInt64
, _partition UInt64

)
ENGINE = ReplicatedReplacingMergeTree('/clickhouse/tables/a00f5869-6d7e-4912-8a23-0122b9ed7c7b_{shard}/posthog.flag_evaluations', '{replica}', _timestamp)
-- Monthly, matching the events family. Daily partitions would put one partition
-- under the TTL for each retained day, and enough parts across them to strain merges. The cost
-- is coarser expiry: with ttl_only_drop_parts a part only drops once its newest
-- row expires, so rows survive up to a month past the TTL.
PARTITION BY toYYYYMM(timestamp)
ORDER BY (team_id, flag_key, toDate(timestamp), cityHash64(distinct_id), cityHash64(uuid))

SETTINGS ttl_only_drop_parts = 1, materialize_ttl_recalculate_only = 1;

CREATE TABLE IF NOT EXISTS cohort_membership
(
    team_id Int64,
    cohort_id Int64,
    person_id UUID,
    status Enum8('entered' = 1, 'left' = 2),
    last_updated DateTime64(6) DEFAULT now64()
) ENGINE = ReplicatedReplacingMergeTree('/clickhouse/tables/2c30508f-cdb3-4e2a-8d5d-17da6e276fac_noshard/posthog.cohort_membership', '{replica}-{shard}', last_updated)
ORDER BY (team_id, cohort_id, person_id);

CREATE TABLE IF NOT EXISTS posthog_test.logs32
(
    `time_bucket` DateTime MATERIALIZED toStartOfDay(timestamp) CODEC(DoubleDelta, ZSTD(1)),
    `original_expiry_timestamp` DateTime64(6) CODEC(DoubleDelta, ZSTD(1)),
    `uuid` String CODEC(ZSTD(1)),
    `team_id` Int32 CODEC(ZSTD(1)),
    `trace_id` String CODEC(ZSTD(1)),
    `span_id` String CODEC(ZSTD(1)),
    `trace_flags` Int32 CODEC(ZSTD(1)),
    `timestamp` DateTime64(6) CODEC(DoubleDelta, ZSTD(1)),
    `observed_timestamp` DateTime64(6) CODEC(DoubleDelta, ZSTD(1)),
    `created_at` DateTime64(6) MATERIALIZED now() CODEC(DoubleDelta, ZSTD(1)),
    `body` String CODEC(ZSTD(1)),
    `severity_text` LowCardinality(String) CODEC(ZSTD(1)),
    `severity_number` Int32 CODEC(ZSTD(1)),
    `service_name` LowCardinality(String) CODEC(ZSTD(1)),
    `resource_attributes` Map(LowCardinality(String), String) CODEC(ZSTD(1)),
    `resource_fingerprint` UInt64 MATERIALIZED cityHash64(resource_attributes) CODEC(DoubleDelta, ZSTD(1)),
    `instrumentation_scope` String CODEC(ZSTD(1)),
    `event_name` String CODEC(ZSTD(1)),
    `attributes_map_str` Map(LowCardinality(String), String) CODEC(ZSTD(1)),
    `level` String ALIAS severity_text,
    `mat_body_ipv4_matches` Array(String) ALIAS extractAll(body, '(\d\.((25[0-5]|(2[0-4]|1(0, 1)[0-9])(0, 1)[0-9])\.)(2, 2)([0-9]))'),
    `time_minute` DateTime ALIAS toStartOfMinute(timestamp),
    `attributes` Map(LowCardinality(String), String) ALIAS mapApply((k, v) -> (left(k, -5), v), attributes_map_str),
    `attributes_map_float` Map(LowCardinality(String), Float64) MATERIALIZED mapFilter((k, v) -> (v IS NOT NULL), mapApply((k, v) -> (concat(left(k, -5), '__float'), toFloat64OrNull(v)), attributes_map_str)) CODEC(ZSTD(1)),
    `attributes_map_datetime` Map(LowCardinality(String), DateTime64(6)) MATERIALIZED mapFilter((k, v) -> (v IS NOT NULL), mapApply((k, v) -> (concat(left(k, -5), '__datetime'), parseDateTimeBestEffortOrNull(v, 6)), attributes_map_str)) CODEC(ZSTD(1)),

    -- temporary columns for materialized views, these expire immediately after initially created but
    -- are around for materialized views which pull off from this table
    `_partition` UInt32 CODEC(DoubleDelta, ZSTD(1)),
    `_topic` String,
    `_offset` UInt64 CODEC(DoubleDelta, ZSTD(1)),
    `_bytes_uncompressed` UInt64 CODEC(DoubleDelta, ZSTD(1)),
    `_bytes_compressed` UInt64 CODEC(DoubleDelta, ZSTD(1)),
    `_record_count` UInt64 CODEC(DoubleDelta, ZSTD(1)),

    -- The dev and test schema builds logs_distributed on this shard, so these columns have to
    -- match the ones on logs34. HogQL reads logs_distributed for every logs query.
    `pattern` String,
    `pattern_version` UInt8,

    INDEX idx_severity_text_set severity_text TYPE set(10) GRANULARITY 1,
    INDEX idx_attributes_str_keys mapKeys(attributes_map_str) TYPE bloom_filter(0.01) GRANULARITY 1,
    INDEX idx_attributes_str_values mapValues(attributes_map_str) TYPE bloom_filter(0.001) GRANULARITY 1,
    INDEX idx_mat_body_ipv4_matches mat_body_ipv4_matches TYPE bloom_filter(0.01) GRANULARITY 1,
    INDEX idx_body_ngram3 lower(body) TYPE ngrambf_v1(3, 25000, 2, 0) GRANULARITY 1,
    INDEX idx_uuid_bloom uuid TYPE bloom_filter(0.01) GRANULARITY 1,
    INDEX idx_observed_minmax observed_timestamp TYPE minmax GRANULARITY 1,
    INDEX idx_timestamp_minmax timestamp TYPE minmax GRANULARITY 1,
    PROJECTION projection_aggregate_counts
    (
        SELECT
            team_id,
            time_bucket,
            toStartOfMinute(timestamp),
            service_name,
            severity_text,
            resource_fingerprint,
            count() AS event_count
        GROUP BY
            team_id,
            time_bucket,
            toStartOfMinute(timestamp),
            service_name,
            severity_text,
            resource_fingerprint
    )
)
ENGINE = ReplicatedMergeTree('/clickhouse/tables/fc08a111-22b5-476e-926c-1187b598df46_noshard/posthog.logs32', '{replica}-{shard}')
PARTITION BY toDate(original_expiry_timestamp)
PRIMARY KEY (team_id, time_bucket, service_name, resource_fingerprint, severity_text, timestamp)
ORDER BY (team_id, time_bucket, service_name, resource_fingerprint, severity_text, timestamp)

SETTINGS
    storage_policy = 'default',
    allow_remote_fs_zero_copy_replication = 1,
    allow_experimental_reverse_key = 1,
    index_granularity_bytes = 104857600,
    index_granularity = 8192,
    ttl_only_drop_parts = 1,
    add_minmax_index_for_numeric_columns = 1;

CREATE TABLE IF NOT EXISTS posthog_test.logs34
(
    `time_bucket` DateTime MATERIALIZED toStartOfDay(timestamp),
    `original_expiry_timestamp` DateTime64(6),
    `uuid` String,
    `team_id` Int32,
    `trace_id` String,
    `span_id` String,
    `trace_flags` Int32,
    `timestamp` DateTime64(6) CODEC(DoubleDelta),
    `observed_timestamp` DateTime64(6),
    `created_at` DateTime64(6) MATERIALIZED now(),
    `body` String,
    `severity_text` LowCardinality(String),
    `severity_number` Int32,
    `service_name` LowCardinality(String),
    `resource_attributes` Map(LowCardinality(String), String),
    `resource_fingerprint` UInt64 MATERIALIZED cityHash64(resource_attributes),
    `instrumentation_scope` String,
    `event_name` String,
    `attributes_map_str` Map(LowCardinality(String), String),
    `level` String ALIAS severity_text,
    `mat_body_ipv4_matches` Array(String) ALIAS extractAll(body, '(\d\.((25[0-5]|(2[0-4]|1(0, 1)[0-9])(0, 1)[0-9])\.)(2, 2)([0-9]))'),
    `time_minute` DateTime ALIAS toStartOfMinute(timestamp),
    `attributes` Map(LowCardinality(String), String) ALIAS mapApply((k, v) -> (left(k, -5), v), attributes_map_str),
    `attributes_map_float` Map(LowCardinality(String), Float64) MATERIALIZED mapFilter((k, v) -> (v IS NOT NULL), mapApply((k, v) -> (concat(left(k, -5), '__float'), toFloat64OrNull(v)), attributes_map_str)),
    `attributes_map_datetime` Map(LowCardinality(String), DateTime64(6)) MATERIALIZED mapFilter((k, v) -> (v IS NOT NULL), mapApply((k, v) -> (concat(left(k, -5), '__datetime'), parseDateTimeBestEffortOrNull(v, 6)), attributes_map_str)),
    `_partition` UInt32,
    `_topic` String,
    `_offset` UInt64,
    `_bytes_uncompressed` UInt64,
    `_bytes_compressed` UInt64,
    `_record_count` UInt64,
    `pattern` String,
    `pattern_version` UInt8,
    `internal_source` LowCardinality(String) DEFAULT '',
    INDEX idx_severity_text_set severity_text TYPE set(10) GRANULARITY 1,
    INDEX idx_attributes_str_keys mapKeys(attributes_map_str) TYPE bloom_filter(0.01) GRANULARITY 1,
    INDEX idx_attributes_str_values mapValues(attributes_map_str) TYPE bloom_filter(0.001) GRANULARITY 1,
    INDEX idx_mat_body_ipv4_matches mat_body_ipv4_matches TYPE bloom_filter(0.01) GRANULARITY 1,
    INDEX idx_body_ngram3 lower(body) TYPE ngrambf_v1(3, 25000, 2, 0) GRANULARITY 1,
    INDEX idx_uuid_bloom uuid TYPE bloom_filter(0.01) GRANULARITY 1,
    INDEX idx_observed_minmax observed_timestamp TYPE minmax GRANULARITY 1,
    INDEX idx_timestamp_minmax timestamp TYPE minmax GRANULARITY 1,
    PROJECTION projection_aggregate_counts
    (
        SELECT
            team_id,
            time_bucket,
            toStartOfMinute(timestamp),
            service_name,
            severity_text,
            resource_fingerprint,
            count() AS event_count
        GROUP BY
            team_id,
            time_bucket,
            toStartOfMinute(timestamp),
            service_name,
            severity_text,
            resource_fingerprint
    )
)
ENGINE = ReplicatedMergeTree('/clickhouse/tables/dbcabd81-eb9a-478b-a11d-1f455e6958b8_noshard/posthog.logs34', '{replica}-{shard}')
PARTITION BY toDate(original_expiry_timestamp)
PRIMARY KEY (team_id, time_bucket, service_name, resource_fingerprint, severity_text, timestamp)
ORDER BY (team_id, time_bucket, service_name, resource_fingerprint, severity_text, timestamp)
TTL original_expiry_timestamp
SETTINGS
    allow_experimental_reverse_key = 1,
    index_granularity_bytes = 104857600,
    index_granularity = 8192,
    ttl_only_drop_parts = 1,
    add_minmax_index_for_numeric_columns = 1,
    map_serialization_version = 'with_buckets';

CREATE TABLE IF NOT EXISTS posthog_test.metrics1
(
    `time_bucket` DateTime MATERIALIZED toStartOfDay(timestamp),
    `uuid` String,
    `team_id` Int32,
    `trace_id` String,
    `span_id` String,
    `trace_flags` Int32,
    `timestamp` DateTime64(6),
    `observed_timestamp` DateTime64(6),
    `created_at` DateTime64(6) MATERIALIZED now(),
    `service_name` LowCardinality(String),
    `metric_name` LowCardinality(String),
    `metric_type` LowCardinality(String),
    `value` Float64 CODEC(Gorilla),
    `count` UInt64 DEFAULT 1 CODEC(T64),
    `histogram_bounds` Array(Float64),
    `histogram_counts` Array(UInt64),
    `unit` LowCardinality(String),
    `aggregation_temporality` LowCardinality(String),
    `is_monotonic` Bool DEFAULT false,
    `resource_attributes` Map(LowCardinality(String), String),
    `resource_fingerprint` UInt64 MATERIALIZED cityHash64(resource_attributes),
    `instrumentation_scope` String,
    `attributes_map_str` Map(LowCardinality(String), String),
    `attributes_map_float` Map(LowCardinality(String), Float64),
    `time_minute` DateTime ALIAS toStartOfMinute(timestamp),
    `attributes` Map(String, String) ALIAS mapApply((k, v) -> (left(k, -5), v), attributes_map_str),
    INDEX idx_metric_name_set metric_name TYPE set(100) GRANULARITY 1,
    INDEX idx_metric_type_set metric_type TYPE set(10) GRANULARITY 1,
    INDEX idx_attributes_str_keys mapKeys(attributes_map_str) TYPE bloom_filter(0.01) GRANULARITY 1,
    INDEX idx_attributes_str_values mapValues(attributes_map_str) TYPE bloom_filter(0.001) GRANULARITY 1,
    INDEX idx_observed_minmax observed_timestamp TYPE minmax GRANULARITY 1,
    PROJECTION projection_aggregate_counts
    (
        SELECT
            team_id,
            time_bucket,
            toStartOfMinute(timestamp),
            service_name,
            metric_name,
            metric_type,
            resource_fingerprint,
            count() AS event_count,
            sum(value) AS total_value,
            min(value) AS min_value,
            max(value) AS max_value
        GROUP BY
            team_id,
            time_bucket,
            toStartOfMinute(timestamp),
            service_name,
            metric_name,
            metric_type,
            resource_fingerprint
    )
)
ENGINE = ReplicatedMergeTree('/clickhouse/tables/6a768fdd-0030-4d96-b7a5-c976a868efe2_noshard/posthog.metrics1', '{replica}-{shard}')
PARTITION BY toDate(timestamp)
PRIMARY KEY (team_id, time_bucket, service_name, metric_name, resource_fingerprint, timestamp)
ORDER BY (team_id, time_bucket, service_name, metric_name, resource_fingerprint, timestamp)
SETTINGS
    index_granularity_bytes = 104857600,
    index_granularity = 8192,
    ttl_only_drop_parts = 1;

CREATE TABLE IF NOT EXISTS sharded_tophog
(
    timestamp DateTime64(6, 'UTC'),
    metric LowCardinality(String),
    type LowCardinality(String) DEFAULT 'sum',
    key Map(LowCardinality(String), String),
    value Float64,
    count UInt64 DEFAULT 0,
    pipeline LowCardinality(String),
    lane LowCardinality(String),
    labels Map(LowCardinality(String), String)
) ENGINE = ReplicatedMergeTree('/clickhouse/tables/e4c30aaa-0e7f-45c3-8259-c44229f18b2d_{shard}/posthog.tophog', '{replica}')

PARTITION BY toYYYYMMDD(timestamp)
ORDER BY (pipeline, lane, metric, timestamp, key)

SETTINGS ttl_only_drop_parts = 1;

CREATE TABLE IF NOT EXISTS sharded_ai_events
(
    -- Core fields
    uuid UUID,
    event LowCardinality(String),
    timestamp DateTime64(6, 'UTC'),
    team_id Int64,
    distinct_id String,
    person_id UUID,
    properties String,
    retention_days Int16 DEFAULT 30,
    drop_date Date MATERIALIZED toDate(timestamp) + toIntervalDay(retention_days),

    -- Trace structure
    trace_id String,
    session_id Nullable(String),
    parent_id Nullable(String),
    span_id Nullable(String),
    span_type LowCardinality(Nullable(String)),
    generation_id Nullable(String),
    experiment_id Nullable(String),

    -- Names
    span_name Nullable(String),
    trace_name Nullable(String),
    prompt_name Nullable(String),

    -- Model info
    model LowCardinality(Nullable(String)),
    provider LowCardinality(Nullable(String)),
    framework LowCardinality(Nullable(String)),

    -- Token counts
    total_tokens Nullable(Int64),
    input_tokens Nullable(Int64),
    output_tokens Nullable(Int64),
    text_input_tokens Nullable(Int64),
    text_output_tokens Nullable(Int64),
    image_input_tokens Nullable(Int64),
    image_output_tokens Nullable(Int64),
    audio_input_tokens Nullable(Int64),
    audio_output_tokens Nullable(Int64),
    video_input_tokens Nullable(Int64),
    video_output_tokens Nullable(Int64),
    reasoning_tokens Nullable(Int64),
    cache_read_input_tokens Nullable(Int64),
    cache_creation_input_tokens Nullable(Int64),
    web_search_count Nullable(Int64),

    -- Costs
    input_cost_usd Nullable(Float64),
    output_cost_usd Nullable(Float64),
    total_cost_usd Nullable(Float64),
    request_cost_usd Nullable(Float64),
    web_search_cost_usd Nullable(Float64),
    audio_cost_usd Nullable(Float64),
    image_cost_usd Nullable(Float64),
    video_cost_usd Nullable(Float64),

    -- Timing
    latency Nullable(Float64),
    time_to_first_token Nullable(Float64),

    -- Errors
    is_error UInt8,
    error Nullable(String),
    error_type LowCardinality(Nullable(String)),
    error_normalized Nullable(String),

    -- Heavy columns (large content)
    input Nullable(String),
    output Nullable(String),
    output_choices Nullable(String),
    input_state Nullable(String),
    output_state Nullable(String),
    tools Nullable(String),

    -- Kafka metadata
    _timestamp DateTime,
    _offset UInt64,
    _partition UInt64

    
    , INDEX idx_trace_id trace_id TYPE bloom_filter(0.001) GRANULARITY 1
    , INDEX idx_session_id session_id TYPE bloom_filter(0.01) GRANULARITY 1
    , INDEX idx_parent_id parent_id TYPE bloom_filter(0.01) GRANULARITY 1
    , INDEX idx_span_id span_id TYPE bloom_filter(0.01) GRANULARITY 1
    , INDEX idx_prompt_name prompt_name TYPE bloom_filter(0.01) GRANULARITY 1
    , INDEX idx_model model TYPE bloom_filter(0.01) GRANULARITY 1
    , INDEX idx_experiment_id experiment_id TYPE bloom_filter(0.01) GRANULARITY 1
    , INDEX idx_event event TYPE set(20) GRANULARITY 1
    , INDEX idx_is_error is_error TYPE set(2) GRANULARITY 1
    , INDEX idx_provider provider TYPE set(50) GRANULARITY 1

) ENGINE = ReplicatedMergeTree('/clickhouse/tables/ec50f2cd-a0d7-4a30-9eb3-9ddd912dfcb3_{shard}/posthog.ai_events', '{replica}')

PARTITION BY toYYYYMM(drop_date)
ORDER BY (team_id, trace_id, timestamp)
TTL drop_date
SETTINGS ttl_only_drop_parts = 1;

CREATE TABLE IF NOT EXISTS property_values
(
    `team_id` Int64 CODEC(DoubleDelta, ZSTD(1)),
    `property_type` LowCardinality(String),
    `property_key` LowCardinality(String),
    `property_value` String,
    `property_count` SimpleAggregateFunction(sum, UInt64),
    `last_seen` SimpleAggregateFunction(max, DateTime) DEFAULT now()
    ,
    INDEX idx_property_value_ngrambf lower(property_value) TYPE ngrambf_v1(3, 32768, 3, 0) GRANULARITY 1
) ENGINE = ReplicatedAggregatingMergeTree('/clickhouse/tables/aeda5f79-b7bc-427f-81e7-58d0298ae2f3_noshard/posthog.property_values', '{replica}-{shard}')

ORDER BY (team_id, property_type, property_key, property_value)
TTL last_seen + INTERVAL 30 DAY DELETE
SETTINGS
    index_granularity = 8192;

CREATE TABLE IF NOT EXISTS kafka_log_entries 
(
    team_id UInt64,
    -- The name of the service or product that generated the logs.
    -- Examples: batch_exports
    log_source LowCardinality(String),
    -- An id for the log source.
    -- Set log_source to avoid collision with ids from other log sources if the id generation is not safe.
    -- Examples: A batch export id, a cronjob id, a plugin id.
    log_source_id String,
    -- A secondary id e.g. for the instance of log_source that generated this log.
    -- This may be ommitted if log_source is a singleton.
    -- Examples: A batch export run id, a plugin_config id, a thread id, a process id, a machine id.
    instance_id String,
    -- Timestamp indicating when the log was generated.
    timestamp DateTime64(6, 'UTC'),
    -- The log level.
    -- Examples: INFO, WARNING, DEBUG, ERROR.
    level LowCardinality(String),
    -- The actual log message.
    message String
    
) ENGINE = Kafka(msk_cluster, kafka_topic_list = 'log_entries_test', kafka_group_name = 'group1', kafka_format = 'JSONEachRow');

CREATE TABLE IF NOT EXISTS kafka_person_distinct_id 
(
    distinct_id VARCHAR,
    person_id UUID,
    team_id Int64,
    _sign Nullable(Int8),
    is_deleted Nullable(Int8)
) ENGINE = Kafka(msk_cluster, kafka_topic_list = 'clickhouse_person_unique_id_test', kafka_group_name = 'group1', kafka_format = 'JSONEachRow');

CREATE TABLE IF NOT EXISTS kafka_ingestion_warnings_v2
(
    
    team_id Int64,
    source LowCardinality(String),
    type String,
    details String,
    timestamp DateTime64(6, 'UTC')

) ENGINE = Kafka(warpstream_ingestion, kafka_topic_list = 'clickhouse_ingestion_warnings_test', kafka_group_name = 'clickhouse_ingestion_warnings_v2', kafka_format = 'JSONEachRow');

CREATE TABLE IF NOT EXISTS kafka_hog_invocation_results
(
    team_id Int64,
    function_kind LowCardinality(String),
    function_id String,
    invocation_id String,
    parent_run_id String,
    status LowCardinality(String),
    attempts UInt8,
    is_retry UInt8,
    scheduled_at DateTime64(6, 'UTC'),
    first_scheduled_at DateTime64(6, 'UTC'),
    started_at Nullable(DateTime64(6, 'UTC')),
    finished_at Nullable(DateTime64(6, 'UTC')),
    duration_ms Nullable(UInt32),
    error_kind LowCardinality(String),
    error_message String,
    event_uuid String,
    distinct_id String,
    person_id String,
    invocation_globals String,
    version UInt64,
    is_deleted UInt8
)
ENGINE = Kafka(warpstream_cyclotron, kafka_topic_list = 'clickhouse_hog_invocation_results_test', kafka_group_name = 'clickhouse_hog_invocation_results', kafka_format = 'JSONEachRow')
SETTINGS kafka_skip_broken_messages = 100;

CREATE TABLE IF NOT EXISTS kafka_message_assets
(
    team_id Int64,
    function_kind LowCardinality(String),
    function_id String,
    parent_run_id String,
    invocation_id String,
    action_id String,
    kind LowCardinality(String),
    distinct_id String,
    person_id String,
    recipient String,
    subject String,
    status LowCardinality(String),
    sent_at DateTime64(6, 'UTC'),
    version UInt64,
    is_deleted UInt8,
    html String
)
ENGINE = Kafka(warpstream_cyclotron, kafka_topic_list = 'clickhouse_message_assets_test', kafka_group_name = 'clickhouse_message_assets', kafka_format = 'JSONEachRow')
SETTINGS kafka_skip_broken_messages = 100;

CREATE TABLE IF NOT EXISTS kafka_email_status
(
    team_id Int64,
    message_id UUID,
    status LowCardinality(String),
    version UInt64,
    created_at DateTime64(6, 'UTC'),
    status_at DateTime64(6, 'UTC'),
    reason String
)
ENGINE = Kafka(warpstream_cyclotron, kafka_topic_list = 'clickhouse_email_status_test', kafka_group_name = 'clickhouse_email_status', kafka_format = 'JSONEachRow')
SETTINGS kafka_skip_broken_messages = 100,
         kafka_num_consumers = 1,
         kafka_thread_per_consumer = 1,
         kafka_poll_timeout_ms = 10000,
         kafka_max_block_size = 100000;

CREATE TABLE IF NOT EXISTS kafka_session_replay_events 
(
    session_id VARCHAR,
    team_id Int64,
    distinct_id VARCHAR,
    first_timestamp DateTime64(6, 'UTC'),
    last_timestamp DateTime64(6, 'UTC'),
    block_url Nullable(String),
    first_url Nullable(VARCHAR),
    urls Array(String),
    click_count Int64,
    keypress_count Int64,
    mouse_activity_count Int64,
    active_milliseconds Int64,
    console_log_count Int64,
    console_warn_count Int64,
    console_error_count Int64,
    size Int64,
    event_count Int64,
    message_count Int64,
    snapshot_source LowCardinality(Nullable(String)),
    snapshot_library Nullable(String),
    snapshot_mode LowCardinality(Nullable(String)),
    retention_period_days Nullable(Int64),
    is_deleted UInt8,
    ai_tags_fixed Array(String),
    ai_tags_freeform Array(String),
    ai_highlighted UInt8,
    surfacing_score Nullable(Float32),
) ENGINE = Kafka(msk_cluster, kafka_topic_list = 'clickhouse_session_replay_events_test', kafka_group_name = 'group1', kafka_format = 'JSONEachRow');

CREATE TABLE IF NOT EXISTS kafka_flag_evaluations
(
    uuid UUID,
    event LowCardinality(String),
    properties String,
    timestamp DateTime64(6, 'UTC'),
    team_id Int64,
    distinct_id String,
    created_at DateTime64(6, 'UTC'),
    person_id UUID,
    person_properties String,
    person_created_at DateTime64(3),
    inserted_at DateTime64(6, 'UTC'),
    person_mode Enum8('full' = 0, 'propertyless' = 1, 'force_upgrade' = 2)
)
ENGINE = Kafka(warpstream_ingestion, kafka_topic_list = 'clickhouse_flag_evaluations_test', kafka_group_name = 'clickhouse_flag_evaluations', kafka_format = 'JSONEachRow')
-- The block and batch sizes are an order of magnitude below the precalculated
-- Kafka tables on this role: each row carries the full event-properties JSON, so
-- large blocks cost far more memory. The 10s poll timeout is deliberate: it is
-- in the range the other WarpStream consumers use, not the 1s the precalculated
-- tables set.
SETTINGS
    kafka_max_block_size = 10000,
    kafka_poll_max_batch_size = 10000,
    kafka_poll_timeout_ms = 10000,
    kafka_flush_interval_ms = 7500,
    kafka_num_consumers = 1,
    kafka_skip_broken_messages = 100;

CREATE TABLE IF NOT EXISTS kafka_ai_events_json
(
    uuid UUID,
    event VARCHAR,
    properties VARCHAR,
    timestamp DateTime64(6, 'UTC'),
    team_id Int64,
    distinct_id VARCHAR,
    elements_chain VARCHAR,
    created_at DateTime64(6, 'UTC'),
    person_id UUID,
    person_properties VARCHAR,
    person_created_at DateTime64,
    person_mode Enum8('full' = 0, 'propertyless' = 1, 'force_upgrade' = 2)
) ENGINE = Kafka(msk_cluster, kafka_topic_list = 'clickhouse_ai_events_json_test', kafka_group_name = 'group1', kafka_format = 'JSONEachRow');

CREATE TABLE IF NOT EXISTS kafka_property_values
(
    `team_id` Int64,
    `property_type` LowCardinality(String),
    `property_key` String,
    `property_value` String,
    `property_count` UInt64
) ENGINE = Kafka(warpstream_ingestion, kafka_topic_list = 'clickhouse_property_values_test', kafka_group_name = 'clickhouse_property_values', kafka_format = 'JSONEachRow')
SETTINGS kafka_num_consumers = 1, kafka_thread_per_consumer = 1;

CREATE TABLE IF NOT EXISTS log_entries 
(
    team_id UInt64,
    -- The name of the service or product that generated the logs.
    -- Examples: batch_exports
    log_source LowCardinality(String),
    -- An id for the log source.
    -- Set log_source to avoid collision with ids from other log sources if the id generation is not safe.
    -- Examples: A batch export id, a cronjob id, a plugin id.
    log_source_id String,
    -- A secondary id e.g. for the instance of log_source that generated this log.
    -- This may be ommitted if log_source is a singleton.
    -- Examples: A batch export run id, a plugin_config id, a thread id, a process id, a machine id.
    instance_id String,
    -- Timestamp indicating when the log was generated.
    timestamp DateTime64(6, 'UTC'),
    -- The log level.
    -- Examples: INFO, WARNING, DEBUG, ERROR.
    level LowCardinality(String),
    -- The actual log message.
    message String
    
, _timestamp DateTime
, _offset UInt64

) ENGINE = Distributed('aux', 'posthog_test', 'log_entries_data');

CREATE TABLE IF NOT EXISTS events 
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
    
) ENGINE = Distributed('posthog', 'posthog_test', 'sharded_events', sipHash64(distinct_id));

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

) ENGINE = Distributed('posthog', 'posthog_test', 'sharded_ingestion_warnings', rand());

CREATE TABLE IF NOT EXISTS app_metrics
(
    team_id Int64,
    timestamp DateTime64(6, 'UTC'),
    plugin_config_id Int64,
    category LowCardinality(String),
    job_id String,
    successes SimpleAggregateFunction(sum, Int64),
    successes_on_retry SimpleAggregateFunction(sum, Int64),
    failures SimpleAggregateFunction(sum, Int64),
    error_uuid UUID,
    error_type String,
    error_details String CODEC(ZSTD(3))
    
, _timestamp DateTime
, _offset UInt64
, _partition UInt64

)
ENGINE=Distributed('posthog', 'posthog_test', 'sharded_app_metrics', rand());

CREATE TABLE IF NOT EXISTS app_metrics2
(
    team_id Int64,
    timestamp DateTime64(6, 'UTC'),
    -- The name of the service or product that generated the metrics.
    -- Examples: plugins, hog
    app_source LowCardinality(String),
    -- An id for the app source.
    -- Set app_source to avoid collision with ids from other app sources if the id generation is not safe.
    -- Examples: A plugin id, a hog application id
    app_source_id String,
    -- A secondary id e.g. for the instance of app_source that generated this metric.
    -- This may be ommitted if app_source is a singleton.
    -- Examples: A plugin config id, a hog application config id
    instance_id String,
    metric_kind LowCardinality(String),
    metric_name LowCardinality(String),
    count SimpleAggregateFunction(sum, Int64)
    
, _timestamp DateTime
, _offset UInt64
, _partition UInt64

)
ENGINE=Distributed('posthog', 'posthog_test', 'sharded_app_metrics2', rand());

CREATE TABLE IF NOT EXISTS hog_invocation_results
(
    team_id Int64,
    function_kind LowCardinality(String),
    function_id String,
    invocation_id String,
    parent_run_id String,
    status LowCardinality(String),
    attempts UInt8,
    is_retry UInt8,
    scheduled_at DateTime64(6, 'UTC'),
    first_scheduled_at DateTime64(6, 'UTC'),
    started_at Nullable(DateTime64(6, 'UTC')),
    finished_at Nullable(DateTime64(6, 'UTC')),
    duration_ms Nullable(UInt32),
    error_kind LowCardinality(String),
    error_message String,
    event_uuid String,
    distinct_id String,
    person_id String,
    invocation_globals String,
    version UInt64,
    is_deleted UInt8
    
, _timestamp DateTime
, _offset UInt64
, _partition UInt64

)
ENGINE = Distributed('aux', 'posthog_test', 'hog_invocation_results_data');

CREATE TABLE IF NOT EXISTS message_assets
(
    team_id Int64,
    function_kind LowCardinality(String),
    function_id String,
    parent_run_id String,
    invocation_id String,
    action_id String,
    kind LowCardinality(String),
    distinct_id String,
    person_id String,
    recipient String,
    subject String,
    status LowCardinality(String),
    sent_at DateTime64(6, 'UTC'),
    version UInt64,
    is_deleted UInt8,
    html String
    
, _timestamp DateTime
, _offset UInt64
, _partition UInt64

)
ENGINE = Distributed('aux', 'posthog_test', 'message_assets_data');

CREATE TABLE IF NOT EXISTS email_status
(
    team_id Int64,
    message_id UUID,
    status LowCardinality(String),
    version UInt64,
    created_at DateTime64(6, 'UTC'),
    status_at DateTime64(6, 'UTC'),
    reason String
    
, _timestamp DateTime
, _offset UInt64
, _partition UInt64

)
ENGINE = Distributed('aux', 'posthog_test', 'email_status_data');

CREATE TABLE IF NOT EXISTS session_replay_events 
(
    -- part of order by so will aggregate correctly
    session_id VARCHAR,
    -- part of order by so will aggregate correctly
    team_id Int64,
    -- ClickHouse will pick any value of distinct_id for the session
    -- this is fine since even if the distinct_id changes during a session
    -- it will still (or should still) map to the same person
    distinct_id VARCHAR,
    min_first_timestamp SimpleAggregateFunction(min, DateTime64(6, 'UTC')),
    max_last_timestamp SimpleAggregateFunction(max, DateTime64(6, 'UTC')),
    -- session recording v2 blocks
    block_first_timestamps SimpleAggregateFunction(groupArrayArray, Array(DateTime64(6, 'UTC'))),
    block_last_timestamps SimpleAggregateFunction(groupArrayArray, Array(DateTime64(6, 'UTC'))),
    block_urls SimpleAggregateFunction(groupArrayArray, Array(String)),
    -- store the first url of the session so we can quickly show that in playlists
    first_url AggregateFunction(argMin, Nullable(VARCHAR), DateTime64(6, 'UTC')),
    -- but also store each url so we can query by visited page without having to scan all events
    -- despite the name we can put mobile screens in here as well to give same functionality across platforms
    all_urls SimpleAggregateFunction(groupUniqArrayArray, Array(String)),
    click_count SimpleAggregateFunction(sum, Int64),
    keypress_count SimpleAggregateFunction(sum, Int64),
    mouse_activity_count SimpleAggregateFunction(sum, Int64),
    active_milliseconds SimpleAggregateFunction(sum, Int64),
    console_log_count SimpleAggregateFunction(sum, Int64),
    console_warn_count SimpleAggregateFunction(sum, Int64),
    console_error_count SimpleAggregateFunction(sum, Int64),
    -- this column allows us to estimate the amount of data that is being ingested
    size SimpleAggregateFunction(sum, Int64),
    -- this allows us to count the number of messages received in a session
    -- often very useful in incidents or debugging
    message_count SimpleAggregateFunction(sum, Int64),
    -- this allows us to count the number of snapshot events received in a session
    -- often very useful in incidents or debugging
    -- because we batch events we expect message_count to be lower than event_count
    event_count SimpleAggregateFunction(sum, Int64),
    -- which source the snapshots came from Mobile or Web. Web if absent
    snapshot_source AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),
    -- knowing something is mobile isn't enough, we need to know if e.g. RN or flutter
    snapshot_library AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),
    snapshot_mode_v2 AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),
    _timestamp SimpleAggregateFunction(max, DateTime),
    -- retention period for this session, in days. Useful to show TTL for the recording
    retention_period_days SimpleAggregateFunction(max, Nullable(Int64)),
    -- marks the recording as deleted for crypto shredding; once 1, merges keep it as 1
    is_deleted SimpleAggregateFunction(max, UInt8) DEFAULT 0,
    -- AI-generated session tags from the summarization pipeline (fixed taxonomy)
    ai_tags_fixed SimpleAggregateFunction(groupUniqArrayArray, Array(String)),
    -- AI-generated session tags from the summarization pipeline (free-form)
    ai_tags_freeform SimpleAggregateFunction(groupUniqArrayArray, Array(String)),
    -- AI-generated flag indicating the session is highlighted / worth watching
    ai_highlighted SimpleAggregateFunction(max, UInt8) DEFAULT 0,
    -- Score in [0, 1] from the surfacing scoring sweep used to surface sessions for downstream summarization
    surfacing_score SimpleAggregateFunction(max, Nullable(Float32)),
) ENGINE = Distributed('posthog', 'posthog_test', 'sharded_session_replay_events', sipHash64(distinct_id));

CREATE TABLE IF NOT EXISTS sessions 
(
    -- part of order by so will aggregate correctly
    session_id VARCHAR,
    -- part of order by so will aggregate correctly
    team_id Int64,
    -- ClickHouse will pick any value of distinct_id for the session
    -- this is fine since even if the distinct_id changes during a session
    -- it will still (or should still) map to the same person
    distinct_id SimpleAggregateFunction(any, String),

    min_timestamp SimpleAggregateFunction(min, DateTime64(6, 'UTC')),
    max_timestamp SimpleAggregateFunction(max, DateTime64(6, 'UTC')),

    urls SimpleAggregateFunction(groupUniqArrayArray, Array(String)),
    entry_url AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
    exit_url AggregateFunction(argMax, String, DateTime64(6, 'UTC')),
    initial_referring_domain AggregateFunction(argMin, String, DateTime64(6, 'UTC')),

    initial_utm_source AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
    initial_utm_campaign AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
    initial_utm_medium AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
    initial_utm_term AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
    initial_utm_content AggregateFunction(argMin, String, DateTime64(6, 'UTC')),

    -- Other Ad / campaign / attribution IDs
    initial_gclid AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
    initial_gad_source AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
    initial_gclsrc AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
    initial_dclid AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
    initial_gbraid AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
    initial_wbraid AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
    initial_fbclid AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
    initial_msclkid AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
    initial_twclid AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
    initial_li_fat_id AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
    initial_mc_cid AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
    initial_igshid AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
    initial_ttclid AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
    initial_epik AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
    initial_qclid AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
    initial_sccid AggregateFunction(argMin, String, DateTime64(6, 'UTC')),

    -- create a map of how many times we saw each event
    event_count_map SimpleAggregateFunction(sumMap, Map(String, Int64)),
    -- duplicate the event count as a specific column for pageviews and autocaptures,
    -- as these are used in some key queries and need to be fast
    pageview_count SimpleAggregateFunction(sum, Int64),
    autocapture_count SimpleAggregateFunction(sum, Int64),
) ENGINE = Distributed('posthog', 'posthog_test', 'sharded_sessions', sipHash64(session_id));

CREATE TABLE IF NOT EXISTS heatmaps
(
    session_id VARCHAR,
    team_id Int64,
    distinct_id VARCHAR,
    timestamp DateTime64(6, 'UTC'),
    -- x is the x with resolution applied, the resolution converts high fidelity mouse positions into an NxN grid
    x Int16,
    -- y is the y with resolution applied, the resolution converts high fidelity mouse positions into an NxN grid
    y Int16,
    -- stored so that in future we can support other resolutions
    scale_factor Int16,
    viewport_width Int16,
    viewport_height Int16,
    -- some elements move when the page scrolls, others do not
    pointer_target_fixed Bool,
    current_url VARCHAR,
    type LowCardinality(String),
    _timestamp DateTime,
    _offset UInt64,
    _partition UInt64
) ENGINE = Distributed('posthog', 'posthog_test', 'sharded_heatmaps', cityHash64(concat(toString(team_id), '-', session_id, '-', toString(toDate(timestamp)))));

CREATE TABLE IF NOT EXISTS flag_evaluations
(
    uuid UUID,
    event LowCardinality(String),
    properties String,
    timestamp DateTime64(6, 'UTC'),
    team_id Int64,
    distinct_id String,
    created_at DateTime64(6, 'UTC'),
    person_id UUID,
    person_properties String DEFAULT '{}',
    person_created_at DateTime64(3),
    inserted_at DateTime64(6, 'UTC') DEFAULT timestamp,
    person_mode Enum8('full' = 0, 'propertyless' = 1, 'force_upgrade' = 2)
    
    , $group_0 String COMMENT 'column_materializer::$group_0'
    , $group_1 String COMMENT 'column_materializer::$group_1'
    , $group_2 String COMMENT 'column_materializer::$group_2'
    , $group_3 String COMMENT 'column_materializer::$group_3'
    , $group_4 String COMMENT 'column_materializer::$group_4'
    , flag_key String COMMENT 'column_materializer::properties::$feature_flag'
    , response LowCardinality(String) COMMENT 'column_materializer::properties::$feature_flag_response'
    , session_id String COMMENT 'column_materializer::properties::$session_id'
    , request_id String COMMENT 'column_materializer::properties::$feature_flag_request_id'

    , properties_group_custom Map(String, String)
    , person_properties_map_custom Map(String, String)
    
, _timestamp DateTime
, _offset UInt64
, _partition UInt64

)
ENGINE = Distributed('posthog', 'posthog_test', 'sharded_flag_evaluations', sipHash64(distinct_id));

CREATE TABLE IF NOT EXISTS posthog_test.logs AS posthog_test.logs32 ENGINE = Distributed('posthog_single_shard', 'posthog_test', 'logs32');

CREATE TABLE IF NOT EXISTS posthog_test.logs_distributed AS posthog_test.logs32 ENGINE = Distributed('posthog_single_shard', 'posthog_test', 'logs32');

CREATE TABLE IF NOT EXISTS posthog_test.metrics AS posthog_test.metrics1 ENGINE = Distributed('posthog_single_shard', 'posthog_test', 'metrics1');

CREATE TABLE IF NOT EXISTS tophog
(
    timestamp DateTime64(6, 'UTC'),
    metric LowCardinality(String),
    type LowCardinality(String) DEFAULT 'sum',
    key Map(LowCardinality(String), String),
    value Float64,
    count UInt64 DEFAULT 0,
    pipeline LowCardinality(String),
    lane LowCardinality(String),
    labels Map(LowCardinality(String), String)
) ENGINE = Distributed('posthog', 'posthog_test', 'sharded_tophog', cityHash64(toString(key)));

CREATE TABLE IF NOT EXISTS ai_events
(
    -- Core fields
    uuid UUID,
    event LowCardinality(String),
    timestamp DateTime64(6, 'UTC'),
    team_id Int64,
    distinct_id String,
    person_id UUID,
    properties String,
    retention_days Int16 DEFAULT 30,
    drop_date Date MATERIALIZED toDate(timestamp) + toIntervalDay(retention_days),

    -- Trace structure
    trace_id String,
    session_id Nullable(String),
    parent_id Nullable(String),
    span_id Nullable(String),
    span_type LowCardinality(Nullable(String)),
    generation_id Nullable(String),
    experiment_id Nullable(String),

    -- Names
    span_name Nullable(String),
    trace_name Nullable(String),
    prompt_name Nullable(String),

    -- Model info
    model LowCardinality(Nullable(String)),
    provider LowCardinality(Nullable(String)),
    framework LowCardinality(Nullable(String)),

    -- Token counts
    total_tokens Nullable(Int64),
    input_tokens Nullable(Int64),
    output_tokens Nullable(Int64),
    text_input_tokens Nullable(Int64),
    text_output_tokens Nullable(Int64),
    image_input_tokens Nullable(Int64),
    image_output_tokens Nullable(Int64),
    audio_input_tokens Nullable(Int64),
    audio_output_tokens Nullable(Int64),
    video_input_tokens Nullable(Int64),
    video_output_tokens Nullable(Int64),
    reasoning_tokens Nullable(Int64),
    cache_read_input_tokens Nullable(Int64),
    cache_creation_input_tokens Nullable(Int64),
    web_search_count Nullable(Int64),

    -- Costs
    input_cost_usd Nullable(Float64),
    output_cost_usd Nullable(Float64),
    total_cost_usd Nullable(Float64),
    request_cost_usd Nullable(Float64),
    web_search_cost_usd Nullable(Float64),
    audio_cost_usd Nullable(Float64),
    image_cost_usd Nullable(Float64),
    video_cost_usd Nullable(Float64),

    -- Timing
    latency Nullable(Float64),
    time_to_first_token Nullable(Float64),

    -- Errors
    is_error UInt8,
    error Nullable(String),
    error_type LowCardinality(Nullable(String)),
    error_normalized Nullable(String),

    -- Heavy columns (large content)
    input Nullable(String),
    output Nullable(String),
    output_choices Nullable(String),
    input_state Nullable(String),
    output_state Nullable(String),
    tools Nullable(String),

    -- Kafka metadata
    _timestamp DateTime,
    _offset UInt64,
    _partition UInt64

    
) ENGINE = Distributed('ai_events', 'posthog_test', 'sharded_ai_events', cityHash64(concat(toString(team_id), '-', trace_id, '-', toString(toDate(timestamp)))));

CREATE MATERIALIZED VIEW IF NOT EXISTS log_entries_mv ON CLUSTER 'posthog'
TO posthog_test.log_entries
AS SELECT
team_id,
log_source,
log_source_id,
instance_id,
timestamp,
level,
message,
_timestamp,
_offset
FROM posthog_test.kafka_log_entries;

CREATE MATERIALIZED VIEW IF NOT EXISTS person_distinct_id_mv ON CLUSTER 'posthog'
TO posthog_test.person_distinct_id
AS SELECT
distinct_id,
person_id,
team_id,
coalesce(_sign, if(is_deleted==0, 1, -1)) AS _sign,
_timestamp,
_offset
FROM posthog_test.kafka_person_distinct_id;

CREATE MATERIALIZED VIEW IF NOT EXISTS ingestion_warnings_v2_mv
TO posthog_test.ingestion_warnings_v2
AS SELECT
    team_id,
    source,
    type,
    details,
    timestamp,
    _timestamp,
    _offset,
    _partition
FROM posthog_test.kafka_ingestion_warnings_v2;

CREATE MATERIALIZED VIEW IF NOT EXISTS hog_invocation_results_mv
TO hog_invocation_results_data
AS SELECT
    team_id,
    function_kind,
    function_id,
    invocation_id,
    parent_run_id,
    status,
    attempts,
    is_retry,
    scheduled_at,
    -- Defensive fallback: if the producer omits the field (e.g. an older build
    -- still in rollout), the Kafka JSONEachRow parser populates the column
    -- with epoch 0. Substitute `scheduled_at` in that case so the column reads
    -- sensibly. Once every producer carries the field, this resolves to a
    -- straight passthrough.
    if(first_scheduled_at = toDateTime64('1970-01-01 00:00:00', 6, 'UTC'), scheduled_at, first_scheduled_at) AS first_scheduled_at,
    started_at,
    finished_at,
    duration_ms,
    error_kind,
    error_message,
    event_uuid,
    distinct_id,
    person_id,
    invocation_globals,
    version,
    is_deleted,
    _timestamp,
    _offset,
    _partition
FROM kafka_hog_invocation_results;

CREATE MATERIALIZED VIEW IF NOT EXISTS message_assets_mv
TO message_assets_data
AS SELECT
    team_id,
    function_kind,
    function_id,
    parent_run_id,
    invocation_id,
    action_id,
    kind,
    distinct_id,
    person_id,
    recipient,
    subject,
    status,
    sent_at,
    version,
    is_deleted,
    html,
    _timestamp,
    _offset,
    _partition
FROM kafka_message_assets;

CREATE MATERIALIZED VIEW IF NOT EXISTS email_status_mv
TO email_status_data
AS 
SELECT
    team_id,
    message_id,
    status,
    version,
    created_at,
    status_at,
    reason,
    _timestamp,
    _offset,
    _partition
FROM kafka_email_status
WHERE status NOT IN ('opened', 'clicked');

CREATE MATERIALIZED VIEW IF NOT EXISTS session_replay_events_mv 
TO posthog_test.writable_session_replay_events (
`session_id` String, `team_id` Int64, `distinct_id` String,
`min_first_timestamp` DateTime64(6, 'UTC'),
`max_last_timestamp` DateTime64(6, 'UTC'),
`block_first_timestamps` SimpleAggregateFunction(groupArrayArray, Array(DateTime64(6, 'UTC'))),
`block_last_timestamps` SimpleAggregateFunction(groupArrayArray, Array(DateTime64(6, 'UTC'))),
`block_urls` SimpleAggregateFunction(groupArrayArray, Array(String)),
`first_url` AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),
`all_urls` SimpleAggregateFunction(groupUniqArrayArray, Array(String)),
`click_count` Int64, `keypress_count` Int64,
`mouse_activity_count` Int64, `active_milliseconds` Int64,
`console_log_count` Int64, `console_warn_count` Int64,
`console_error_count` Int64, `size` Int64, `message_count` Int64,
`event_count` Int64,
`snapshot_source` AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),
`snapshot_library` AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),
`_timestamp` Nullable(DateTime)
,`retention_period_days` SimpleAggregateFunction(max, Nullable(Int64))
,`is_deleted` SimpleAggregateFunction(max, UInt8)
,`ai_tags_fixed` SimpleAggregateFunction(groupUniqArrayArray, Array(String))
,`ai_tags_freeform` SimpleAggregateFunction(groupUniqArrayArray, Array(String))
,`ai_highlighted` SimpleAggregateFunction(max, UInt8)
,`surfacing_score` SimpleAggregateFunction(max, Nullable(Float32))
,`snapshot_mode_v2` AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))
)
AS SELECT
session_id,
team_id,
any(distinct_id) as distinct_id,
min(first_timestamp) AS min_first_timestamp,
max(last_timestamp) AS max_last_timestamp,
groupArray(if(block_url != '', first_timestamp, NULL)) AS block_first_timestamps,
groupArray(if(block_url != '', last_timestamp, NULL)) AS block_last_timestamps,
groupArray(block_url) AS block_urls,
-- TRICKY: ClickHouse will pick a relatively random first_url
-- when it collapses the aggregating merge tree
-- unless we teach it what we want...
-- argMin ignores null values
-- so this will get the first non-null value of first_url
-- for each group of session_id and team_id
-- by min of first_timestamp in the batch
-- this is an aggregate function, not a simple aggregate function
-- so we have to write to argMinState, and query with argMinMerge
argMinState(first_url, first_timestamp) as first_url,
groupUniqArrayArray(urls) as all_urls,
sum(click_count) as click_count,
sum(keypress_count) as keypress_count,
sum(mouse_activity_count) as mouse_activity_count,
sum(active_milliseconds) as active_milliseconds,
sum(console_log_count) as console_log_count,
sum(console_warn_count) as console_warn_count,
sum(console_error_count) as console_error_count,
sum(size) as size,
-- we can count the number of kafka messages instead of sending it explicitly
sum(message_count) as message_count,
sum(event_count) as event_count,
argMinState(replay.snapshot_source, first_timestamp) as snapshot_source,
argMinState(snapshot_library, first_timestamp) as snapshot_library,
max(_timestamp) as _timestamp
,max(retention_period_days) as retention_period_days
,max(is_deleted) as is_deleted
,groupUniqArrayArray(ai_tags_fixed) as ai_tags_fixed
,groupUniqArrayArray(ai_tags_freeform) as ai_tags_freeform
,max(ai_highlighted) as ai_highlighted
,max(surfacing_score) as surfacing_score
,argMinState(replay.snapshot_mode, first_timestamp) as snapshot_mode_v2
FROM posthog_test.kafka_session_replay_events AS replay
group by session_id, team_id;

CREATE MATERIALIZED VIEW IF NOT EXISTS ai_events_json_mv
TO ai_events
AS SELECT
    uuid,
    event,
    timestamp,
    team_id,
    distinct_id,
    person_id,
    concat('{', arrayStringConcat(arrayMap(x -> concat('"', x.1, '":', x.2), arrayFilter(x -> x.1 NOT IN ('$ai_input', '$ai_output', '$ai_output_choices', '$ai_input_state', '$ai_output_state', '$ai_tools'), JSONExtractKeysAndValuesRaw(src.properties))), ','), '}') AS properties,

    -- Trace structure
    JSONExtractString(src.properties, '$ai_trace_id') AS trace_id,
    JSONExtract(src.properties, '$ai_session_id', 'Nullable(String)') AS session_id,
    JSONExtract(src.properties, '$ai_parent_id', 'Nullable(String)') AS parent_id,
    JSONExtract(src.properties, '$ai_span_id', 'Nullable(String)') AS span_id,
    JSONExtract(src.properties, '$ai_span_type', 'Nullable(String)') AS span_type,
    JSONExtract(src.properties, '$ai_generation_id', 'Nullable(String)') AS generation_id,
    JSONExtract(src.properties, '$ai_experiment_id', 'Nullable(String)') AS experiment_id,

    -- Names
    JSONExtract(src.properties, '$ai_span_name', 'Nullable(String)') AS span_name,
    JSONExtract(src.properties, '$ai_trace_name', 'Nullable(String)') AS trace_name,
    JSONExtract(src.properties, '$ai_prompt_name', 'Nullable(String)') AS prompt_name,

    -- Model info
    JSONExtract(src.properties, '$ai_model', 'Nullable(String)') AS model,
    JSONExtract(src.properties, '$ai_provider', 'Nullable(String)') AS provider,
    JSONExtract(src.properties, '$ai_framework', 'Nullable(String)') AS framework,

    -- Token counts
    JSONExtract(src.properties, '$ai_total_tokens', 'Nullable(Int64)') AS total_tokens,
    JSONExtract(src.properties, '$ai_input_tokens', 'Nullable(Int64)') AS input_tokens,
    JSONExtract(src.properties, '$ai_output_tokens', 'Nullable(Int64)') AS output_tokens,
    JSONExtract(src.properties, '$ai_text_input_tokens', 'Nullable(Int64)') AS text_input_tokens,
    JSONExtract(src.properties, '$ai_text_output_tokens', 'Nullable(Int64)') AS text_output_tokens,
    JSONExtract(src.properties, '$ai_image_input_tokens', 'Nullable(Int64)') AS image_input_tokens,
    JSONExtract(src.properties, '$ai_image_output_tokens', 'Nullable(Int64)') AS image_output_tokens,
    JSONExtract(src.properties, '$ai_audio_input_tokens', 'Nullable(Int64)') AS audio_input_tokens,
    JSONExtract(src.properties, '$ai_audio_output_tokens', 'Nullable(Int64)') AS audio_output_tokens,
    JSONExtract(src.properties, '$ai_video_input_tokens', 'Nullable(Int64)') AS video_input_tokens,
    JSONExtract(src.properties, '$ai_video_output_tokens', 'Nullable(Int64)') AS video_output_tokens,
    JSONExtract(src.properties, '$ai_reasoning_tokens', 'Nullable(Int64)') AS reasoning_tokens,
    JSONExtract(src.properties, '$ai_cache_read_input_tokens', 'Nullable(Int64)') AS cache_read_input_tokens,
    JSONExtract(src.properties, '$ai_cache_creation_input_tokens', 'Nullable(Int64)') AS cache_creation_input_tokens,
    JSONExtract(src.properties, '$ai_web_search_count', 'Nullable(Int64)') AS web_search_count,

    -- Costs
    JSONExtract(src.properties, '$ai_input_cost_usd', 'Nullable(Float64)') AS input_cost_usd,
    JSONExtract(src.properties, '$ai_output_cost_usd', 'Nullable(Float64)') AS output_cost_usd,
    JSONExtract(src.properties, '$ai_total_cost_usd', 'Nullable(Float64)') AS total_cost_usd,
    JSONExtract(src.properties, '$ai_request_cost_usd', 'Nullable(Float64)') AS request_cost_usd,
    JSONExtract(src.properties, '$ai_web_search_cost_usd', 'Nullable(Float64)') AS web_search_cost_usd,
    JSONExtract(src.properties, '$ai_audio_cost_usd', 'Nullable(Float64)') AS audio_cost_usd,
    JSONExtract(src.properties, '$ai_image_cost_usd', 'Nullable(Float64)') AS image_cost_usd,
    JSONExtract(src.properties, '$ai_video_cost_usd', 'Nullable(Float64)') AS video_cost_usd,

    -- Timing
    JSONExtract(src.properties, '$ai_latency', 'Nullable(Float64)') AS latency,
    JSONExtract(src.properties, '$ai_time_to_first_token', 'Nullable(Float64)') AS time_to_first_token,

    -- Errors
    if(JSONExtractRaw(src.properties, '$ai_is_error') IN ('true', '"true"'), 1, 0) AS is_error,
    JSONExtract(src.properties, '$ai_error', 'Nullable(String)') AS error,
    JSONExtract(src.properties, '$ai_error_type', 'Nullable(String)') AS error_type,
    JSONExtract(src.properties, '$ai_error_normalized', 'Nullable(String)') AS error_normalized,

    -- Heavy columns
    nullIf(JSONExtractRaw(src.properties, '$ai_input'), '') AS input,
    nullIf(JSONExtractRaw(src.properties, '$ai_output'), '') AS output,
    nullIf(JSONExtractRaw(src.properties, '$ai_output_choices'), '') AS output_choices,
    nullIf(JSONExtractRaw(src.properties, '$ai_input_state'), '') AS input_state,
    nullIf(JSONExtractRaw(src.properties, '$ai_output_state'), '') AS output_state,
    nullIf(JSONExtractRaw(src.properties, '$ai_tools'), '') AS tools,

    -- Kafka metadata
    _timestamp,
    _offset,
    _partition
FROM kafka_ai_events_json AS src;

CREATE MATERIALIZED VIEW IF NOT EXISTS property_values_mv
TO property_values
AS SELECT
    team_id,
    property_type,
    property_key,
    property_value,
    property_count,
    coalesce(_timestamp, now()) as last_seen
FROM posthog_test.kafka_property_values;
