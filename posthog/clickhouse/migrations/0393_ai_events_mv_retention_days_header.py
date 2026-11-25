from django.conf import settings

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.run_mode import run_mode

# Rows written before this migration keep their retention.
#
# MODIFY QUERY, not drop and recreate: only the SELECT changes, the view stays attached to its Kafka table and
# consumption does not stop. ClickHouse adds retention_days to the view's own column list as part of the ALTER.
#
# The SELECT is a copy of the one sql.py held for this migration, not an import. A node with this migration
# pending has the Kafka table of that time, so a column a later migration adds to the sql.py SELECT does not
# exist there yet.
SELECT_SQL = """
SELECT
    uuid,
    event,
    timestamp,
    team_id,
    distinct_id,
    person_id,
    concat('{{', arrayStringConcat(arrayMap(x -> concat('"', x.1, '":', x.2), arrayFilter(x -> x.1 NOT IN ('$ai_input', '$ai_output', '$ai_output_choices', '$ai_input_state', '$ai_output_state', '$ai_tools'), JSONExtractKeysAndValuesRaw(src.properties))), ','), '}}') AS properties,

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

    -- Retention
    toInt16(least(greatest(toInt16OrDefault(_headers.value[indexOf(_headers.name, 'retention-days')], toInt16(30)), 30), 365)) AS retention_days,

    -- Kafka metadata
    _timestamp,
    _offset,
    _partition
FROM {database}.{kafka_table} AS src
"""

MV_NAME, KAFKA_TABLE_NAME = (
    ("ai_events_json_ws_mv", "kafka_ai_events_json_ws")
    if run_mode().is_deployed_cloud
    else ("ai_events_json_mv", "kafka_ai_events_json")
)

operations = [
    run_sql_with_exceptions(
        f"ALTER TABLE {MV_NAME} MODIFY QUERY "
        + SELECT_SQL.format(database=settings.CLICKHOUSE_DATABASE, kafka_table=KAFKA_TABLE_NAME),
        node_roles=[NodeRole.AI_EVENTS],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
]
