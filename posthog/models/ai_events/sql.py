from django.conf import settings

from posthog.clickhouse.kafka_engine import CONSUMER_GROUP_AI_EVENTS, CONSUMER_GROUP_AI_EVENTS_WS, kafka_engine
from posthog.clickhouse.table_engines import Distributed, MergeTreeEngine, ReplicationScheme
from posthog.kafka_client.topics import KAFKA_CLICKHOUSE_AI_EVENTS_JSON

TABLE_BASE_NAME = "ai_events"
DATA_TABLE_NAME = f"sharded_{TABLE_BASE_NAME}"
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
    , INDEX idx_experiment_id experiment_id TYPE bloom_filter(0.01) GRANULARITY 1
    , INDEX idx_event event TYPE set(20) GRANULARITY 1
    , INDEX idx_is_error is_error TYPE set(2) GRANULARITY 1
    , INDEX idx_provider provider TYPE set(50) GRANULARITY 1
"""


def AI_EVENTS_DATA_TABLE_SQL():
    return (
        AI_EVENTS_TABLE_BASE_SQL
        + """
PARTITION BY toYYYYMM(drop_date)
ORDER BY (team_id, trace_id, timestamp)
TTL drop_date
SETTINGS ttl_only_drop_parts = 1
"""
    ).format(
        table_name=DATA_TABLE_NAME,
        engine=AI_EVENTS_DATA_TABLE_ENGINE(),
        indexes=AI_EVENTS_INDEXES,
    )


def DISTRIBUTED_AI_EVENTS_TABLE_SQL():
    return AI_EVENTS_TABLE_BASE_SQL.format(
        table_name=TABLE_BASE_NAME,
        engine=Distributed(
            data_table=DATA_TABLE_NAME,
            sharding_key=SHARDING_KEY,
            cluster=settings.CLICKHOUSE_AI_EVENTS_CLUSTER,
        ),
        indexes="",
    )


def KAFKA_AI_EVENTS_TABLE_SQL():
    return KAFKA_AI_EVENTS_TABLE_BASE_SQL.format(
        table_name=KAFKA_TABLE_NAME,
        engine=kafka_engine(topic=KAFKA_CLICKHOUSE_AI_EVENTS_JSON, group=CONSUMER_GROUP_AI_EVENTS),
    )


def AI_EVENTS_MV_SQL(
    target_table: str = TABLE_BASE_NAME,
    mv_name: str = MV_NAME,
    kafka_table: str = KAFKA_TABLE_NAME,
):
    # AI events do not have a dedicated writable table today, so the MV
    # writes straight to the distributed ai_events table.
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
FROM {kafka_table} AS src
""".format(
        mv_name=mv_name,
        target_table=target_table,
        kafka_table=kafka_table,
        stripped_properties=stripped_properties,
    )


# WarpStream Kafka engine tables (coexist alongside MSK tables, same target)

KAFKA_AI_EVENTS_WS_TABLE = "kafka_ai_events_json_ws"
AI_EVENTS_WS_MV = "ai_events_json_ws_mv"

DROP_KAFKA_AI_EVENTS_WS_TABLE_SQL = f"DROP TABLE IF EXISTS {KAFKA_AI_EVENTS_WS_TABLE}"
DROP_AI_EVENTS_WS_MV_SQL = f"DROP TABLE IF EXISTS {AI_EVENTS_WS_MV}"


def KAFKA_AI_EVENTS_WS_TABLE_SQL():
    return KAFKA_AI_EVENTS_TABLE_BASE_SQL.format(
        table_name=KAFKA_AI_EVENTS_WS_TABLE,
        engine=kafka_engine(
            topic=KAFKA_CLICKHOUSE_AI_EVENTS_JSON,
            group=CONSUMER_GROUP_AI_EVENTS_WS,
            named_collection=settings.CLICKHOUSE_KAFKA_WARPSTREAM_INGESTION_NAMED_COLLECTION,
        ),
    )


def AI_EVENTS_WS_MV_SQL():
    return AI_EVENTS_MV_SQL(
        mv_name=AI_EVENTS_WS_MV,
        kafka_table=KAFKA_AI_EVENTS_WS_TABLE,
    )


def TRUNCATE_AI_EVENTS_TABLE_SQL():
    return f"TRUNCATE TABLE IF EXISTS {DATA_TABLE_NAME}"
