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

) ENGINE = ReplicatedMergeTree('/clickhouse/tables/{shard}/posthog.ai_events', '{replica}')

PARTITION BY toYYYYMM(drop_date)
ORDER BY (team_id, trace_id, timestamp)
TTL drop_date
SETTINGS ttl_only_drop_parts = 1

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
) ENGINE = Kafka(msk_cluster, kafka_topic_list = 'clickhouse_ai_events_json', kafka_group_name = 'group1', kafka_format = 'JSONEachRow')

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
FROM kafka_ai_events_json AS src
