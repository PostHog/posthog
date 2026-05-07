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

    
) ENGINE = Distributed('ai_events', 'default', 'sharded_ai_events', cityHash64(concat(toString(team_id), '-', trace_id, '-', toString(toDate(timestamp)))))
