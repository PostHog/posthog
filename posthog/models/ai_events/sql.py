from posthog.clickhouse.kafka_engine import CONSUMER_GROUP_AI_EVENTS, kafka_engine
from posthog.clickhouse.table_engines import Distributed, MergeTreeEngine, ReplicationScheme
from posthog.kafka_client.topics import KAFKA_CLICKHOUSE_AI_EVENTS_JSON

TABLE_BASE_NAME = "ai_events"
DATA_TABLE_NAME = f"sharded_{TABLE_BASE_NAME}"
WRITABLE_TABLE_NAME = f"writable_{TABLE_BASE_NAME}"
KAFKA_TABLE_NAME = f"kafka_{TABLE_BASE_NAME}_json"
MV_NAME = f"{TABLE_BASE_NAME}_json_mv"

SHARDING_KEY = "cityHash64(concat(toString(team_id), '-', trace_id, '-', toString(toDate(timestamp))))"

# Heavy AI properties that are stored in dedicated columns and stripped from the properties JSON
# in the materialized view to avoid duplicating large data.
HEAVY_AI_PROPERTIES = [
    "$ai_input",
    "$ai_output",
    "$ai_output_choices",
    "$ai_input_state",
    "$ai_output_state",
    "$ai_tools",
]


def _strip_heavy_properties_sql(properties_col: str) -> str:
    """Strip heavy AI properties from the JSON blob.

    Uses arrayFilter + arrayMap on JSONExtractKeysAndValuesRaw to preserve
    raw JSON value encoding. The previous approach (Map + toJSONString)
    double-quoted string values because raw values include JSON quotes.
    """
    keys_list = ", ".join(f"'{prop}'" for prop in HEAVY_AI_PROPERTIES)
    return (
        f"concat('{{', arrayStringConcat(arrayMap("
        f"x -> concat('\"', x.1, '\":', x.2), "
        f"arrayFilter("
        f"x -> x.1 NOT IN ({keys_list}), "
        f"JSONExtractKeysAndValuesRaw({properties_col})"
        f")), ','), '}}')"
    )


def AI_EVENTS_DATA_TABLE_ENGINE():
    return MergeTreeEngine(
        TABLE_BASE_NAME,
        replication_scheme=ReplicationScheme.SHARDED,
    )


# Kafka engine table — receives the standard RawKafkaEvent JSON format
KAFKA_AI_EVENTS_TABLE_BASE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name}
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
) ENGINE = {engine}
"""

# Data table columns — the actual schema for ai_events
AI_EVENTS_TABLE_BASE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name}
(
    -- Core fields
    uuid UUID,
    event LowCardinality(String),
    timestamp DateTime64(6, 'UTC'),
    team_id Int64,
    distinct_id String,
    person_id UUID,
    properties String DEFAULT '' CODEC(ZSTD(3)),
    retention_days Int16 DEFAULT 30,

    -- Trace structure
    trace_id String DEFAULT '',
    session_id String DEFAULT '',
    parent_id String DEFAULT '',
    span_id String DEFAULT '',
    span_type LowCardinality(String) DEFAULT '',
    generation_id String DEFAULT '',

    -- Names
    span_name String DEFAULT '',
    trace_name String DEFAULT '',
    prompt_name String DEFAULT '',

    -- Model info
    model LowCardinality(String) DEFAULT '',
    provider LowCardinality(String) DEFAULT '',
    framework LowCardinality(String) DEFAULT '',

    -- Token counts
    total_tokens Int64 DEFAULT 0,
    input_tokens Int64 DEFAULT 0,
    output_tokens Int64 DEFAULT 0,
    text_input_tokens Int64 DEFAULT 0,
    text_output_tokens Int64 DEFAULT 0,
    image_input_tokens Int64 DEFAULT 0,
    image_output_tokens Int64 DEFAULT 0,
    audio_input_tokens Int64 DEFAULT 0,
    audio_output_tokens Int64 DEFAULT 0,
    video_input_tokens Int64 DEFAULT 0,
    video_output_tokens Int64 DEFAULT 0,
    reasoning_tokens Int64 DEFAULT 0,
    cache_read_input_tokens Int64 DEFAULT 0,
    cache_creation_input_tokens Int64 DEFAULT 0,
    web_search_count Int64 DEFAULT 0,

    -- Costs
    input_cost_usd Float64 DEFAULT 0,
    output_cost_usd Float64 DEFAULT 0,
    total_cost_usd Float64 DEFAULT 0,
    request_cost_usd Float64 DEFAULT 0,
    web_search_cost_usd Float64 DEFAULT 0,
    audio_cost_usd Float64 DEFAULT 0,
    image_cost_usd Float64 DEFAULT 0,
    video_cost_usd Float64 DEFAULT 0,

    -- Timing
    latency Float64 DEFAULT 0,
    time_to_first_token Float64 DEFAULT 0,

    -- Errors
    is_error UInt8 DEFAULT 0,
    error String DEFAULT '',
    error_type LowCardinality(String) DEFAULT '',
    error_normalized String DEFAULT '',

    -- Heavy columns (large content)
    input String DEFAULT '' CODEC(ZSTD(3)),
    output String DEFAULT '' CODEC(ZSTD(3)),
    output_choices String DEFAULT '' CODEC(ZSTD(3)),
    input_state String DEFAULT '' CODEC(ZSTD(3)),
    output_state String DEFAULT '' CODEC(ZSTD(3)),
    tools String DEFAULT '' CODEC(ZSTD(3)),

    -- Materialized preview columns (extract last input message / first output choice)
    input_preview String MATERIALIZED if(
        JSONType(input) = 'Array',
        left(JSONExtractArrayRaw(input)[length(JSONExtractArrayRaw(input))], 200),
        left(input, 200)
    ),
    output_choices_preview String MATERIALIZED if(
        JSONType(output_choices) = 'Array',
        left(JSONExtractArrayRaw(output_choices)[1], 200),
        left(output_choices, 200)
    ),

    -- Kafka metadata
    _timestamp DateTime,
    _offset UInt64,
    _partition UInt64

    {indexes}
) ENGINE = {engine}
"""

AI_EVENTS_INDEXES = """
    , INDEX idx_trace_id trace_id TYPE bloom_filter(0.001) GRANULARITY 1
    , INDEX idx_session_id session_id TYPE bloom_filter(0.01) GRANULARITY 1
    , INDEX idx_parent_id parent_id TYPE bloom_filter(0.01) GRANULARITY 1
    , INDEX idx_span_id span_id TYPE bloom_filter(0.01) GRANULARITY 1
    , INDEX idx_prompt_name prompt_name TYPE bloom_filter(0.01) GRANULARITY 1
    , INDEX idx_model model TYPE bloom_filter(0.01) GRANULARITY 1
    , INDEX idx_event event TYPE set(20) GRANULARITY 1
    , INDEX idx_is_error is_error TYPE set(2) GRANULARITY 1
    , INDEX idx_provider provider TYPE set(50) GRANULARITY 1
"""


def AI_EVENTS_DATA_TABLE_SQL():
    return (
        AI_EVENTS_TABLE_BASE_SQL
        + """
PARTITION BY (toStartOfDay(timestamp), retention_days)
ORDER BY (team_id, trace_id, timestamp)
TTL toDateTime(timestamp) + toIntervalDay(retention_days)
SETTINGS ttl_only_drop_parts = 1
"""
    ).format(
        table_name=DATA_TABLE_NAME,
        engine=AI_EVENTS_DATA_TABLE_ENGINE(),
        indexes=AI_EVENTS_INDEXES,
    )


def WRITABLE_AI_EVENTS_TABLE_SQL():
    return AI_EVENTS_TABLE_BASE_SQL.format(
        table_name=WRITABLE_TABLE_NAME,
        engine=Distributed(
            data_table=DATA_TABLE_NAME,
            sharding_key=SHARDING_KEY,
        ),
        indexes="",
    )


def DISTRIBUTED_AI_EVENTS_TABLE_SQL():
    return AI_EVENTS_TABLE_BASE_SQL.format(
        table_name=TABLE_BASE_NAME,
        engine=Distributed(
            data_table=DATA_TABLE_NAME,
            sharding_key=SHARDING_KEY,
        ),
        indexes="",
    )


def KAFKA_AI_EVENTS_TABLE_SQL():
    return KAFKA_AI_EVENTS_TABLE_BASE_SQL.format(
        table_name=KAFKA_TABLE_NAME,
        engine=kafka_engine(topic=KAFKA_CLICKHOUSE_AI_EVENTS_JSON, group=CONSUMER_GROUP_AI_EVENTS),
    )


def AI_EVENTS_MV_SQL(target_table: str = WRITABLE_TABLE_NAME):
    # Use src.properties to avoid alias shadowing — the stripped_properties
    # alias is also called "properties", which would shadow the source column
    # if we didn't qualify with the table alias.
    stripped_properties = _strip_heavy_properties_sql("src.properties")
    return """
CREATE MATERIALIZED VIEW IF NOT EXISTS {mv_name}
TO {target_table}
AS SELECT
    uuid,
    event,
    timestamp,
    team_id,
    distinct_id,
    person_id,
    {stripped_properties} AS properties,

    -- Trace structure
    JSONExtractString(src.properties, '$ai_trace_id') AS trace_id,
    JSONExtractString(src.properties, '$ai_session_id') AS session_id,
    JSONExtractString(src.properties, '$ai_parent_id') AS parent_id,
    JSONExtractString(src.properties, '$ai_span_id') AS span_id,
    JSONExtractString(src.properties, '$ai_span_type') AS span_type,
    JSONExtractString(src.properties, '$ai_generation_id') AS generation_id,

    -- Names
    JSONExtractString(src.properties, '$ai_span_name') AS span_name,
    JSONExtractString(src.properties, '$ai_trace_name') AS trace_name,
    JSONExtractString(src.properties, '$ai_prompt_name') AS prompt_name,

    -- Model info
    JSONExtractString(src.properties, '$ai_model') AS model,
    JSONExtractString(src.properties, '$ai_provider') AS provider,
    JSONExtractString(src.properties, '$ai_framework') AS framework,

    -- Token counts
    JSONExtractInt(src.properties, '$ai_total_tokens') AS total_tokens,
    JSONExtractInt(src.properties, '$ai_input_tokens') AS input_tokens,
    JSONExtractInt(src.properties, '$ai_output_tokens') AS output_tokens,
    JSONExtractInt(src.properties, '$ai_text_input_tokens') AS text_input_tokens,
    JSONExtractInt(src.properties, '$ai_text_output_tokens') AS text_output_tokens,
    JSONExtractInt(src.properties, '$ai_image_input_tokens') AS image_input_tokens,
    JSONExtractInt(src.properties, '$ai_image_output_tokens') AS image_output_tokens,
    JSONExtractInt(src.properties, '$ai_audio_input_tokens') AS audio_input_tokens,
    JSONExtractInt(src.properties, '$ai_audio_output_tokens') AS audio_output_tokens,
    JSONExtractInt(src.properties, '$ai_video_input_tokens') AS video_input_tokens,
    JSONExtractInt(src.properties, '$ai_video_output_tokens') AS video_output_tokens,
    JSONExtractInt(src.properties, '$ai_reasoning_tokens') AS reasoning_tokens,
    JSONExtractInt(src.properties, '$ai_cache_read_input_tokens') AS cache_read_input_tokens,
    JSONExtractInt(src.properties, '$ai_cache_creation_input_tokens') AS cache_creation_input_tokens,
    JSONExtractInt(src.properties, '$ai_web_search_count') AS web_search_count,

    -- Costs
    JSONExtractFloat(src.properties, '$ai_input_cost_usd') AS input_cost_usd,
    JSONExtractFloat(src.properties, '$ai_output_cost_usd') AS output_cost_usd,
    JSONExtractFloat(src.properties, '$ai_total_cost_usd') AS total_cost_usd,
    JSONExtractFloat(src.properties, '$ai_request_cost_usd') AS request_cost_usd,
    JSONExtractFloat(src.properties, '$ai_web_search_cost_usd') AS web_search_cost_usd,
    JSONExtractFloat(src.properties, '$ai_audio_cost_usd') AS audio_cost_usd,
    JSONExtractFloat(src.properties, '$ai_image_cost_usd') AS image_cost_usd,
    JSONExtractFloat(src.properties, '$ai_video_cost_usd') AS video_cost_usd,

    -- Timing
    JSONExtractFloat(src.properties, '$ai_latency') AS latency,
    JSONExtractFloat(src.properties, '$ai_time_to_first_token') AS time_to_first_token,

    -- Errors
    if(JSONExtractString(src.properties, '$ai_is_error') = 'true', 1, 0) AS is_error,
    JSONExtractString(src.properties, '$ai_error') AS error,
    JSONExtractString(src.properties, '$ai_error_type') AS error_type,
    JSONExtractString(src.properties, '$ai_error_normalized') AS error_normalized,

    -- Heavy columns
    JSONExtractRaw(src.properties, '$ai_input') AS input,
    JSONExtractRaw(src.properties, '$ai_output') AS output,
    JSONExtractRaw(src.properties, '$ai_output_choices') AS output_choices,
    JSONExtractRaw(src.properties, '$ai_input_state') AS input_state,
    JSONExtractRaw(src.properties, '$ai_output_state') AS output_state,
    JSONExtractRaw(src.properties, '$ai_tools') AS tools,

    -- Kafka metadata
    _timestamp,
    _offset,
    _partition
FROM {kafka_table} AS src
""".format(
        mv_name=MV_NAME,
        target_table=target_table,
        kafka_table=KAFKA_TABLE_NAME,
        stripped_properties=stripped_properties,
    )


def TRUNCATE_AI_EVENTS_TABLE_SQL():
    return f"TRUNCATE TABLE IF EXISTS {DATA_TABLE_NAME}"
