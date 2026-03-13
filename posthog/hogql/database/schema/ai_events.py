from posthog.hogql.database.models import (
    BooleanDatabaseField,
    DateTimeDatabaseField,
    FieldOrTable,
    FieldTraverser,
    FloatDatabaseField,
    IntegerDatabaseField,
    LazyJoin,
    StringDatabaseField,
    StringJSONDatabaseField,
    Table,
)
from posthog.hogql.database.schema.person_distinct_ids import (
    PersonDistinctIdsTable,
    join_with_person_distinct_ids_table,
)


class AiEventsTable(Table):
    fields: dict[str, FieldOrTable] = {
        # Core
        "uuid": StringDatabaseField(name="uuid", nullable=False),
        "event": StringDatabaseField(name="event", nullable=False),
        "timestamp": DateTimeDatabaseField(name="timestamp", nullable=False),
        "team_id": IntegerDatabaseField(name="team_id", nullable=False),
        "distinct_id": StringDatabaseField(name="distinct_id", nullable=False),
        "person_id": StringDatabaseField(name="person_id", nullable=False),
        "properties": StringJSONDatabaseField(name="properties", nullable=False),
        "retention_days": IntegerDatabaseField(name="retention_days", nullable=False),
        # Trace structure
        "trace_id": StringDatabaseField(name="trace_id", nullable=False),
        "session_id": StringDatabaseField(name="session_id", nullable=False),
        "parent_id": StringDatabaseField(name="parent_id", nullable=False),
        "span_id": StringDatabaseField(name="span_id", nullable=False),
        "span_type": StringDatabaseField(name="span_type", nullable=False),
        "generation_id": StringDatabaseField(name="generation_id", nullable=False),
        # Names
        "span_name": StringDatabaseField(name="span_name", nullable=False),
        "trace_name": StringDatabaseField(name="trace_name", nullable=False),
        "prompt_name": StringDatabaseField(name="prompt_name", nullable=False),
        # Model info
        "model": StringDatabaseField(name="model", nullable=False),
        "provider": StringDatabaseField(name="provider", nullable=False),
        "framework": StringDatabaseField(name="framework", nullable=False),
        # Token counts
        "total_tokens": IntegerDatabaseField(name="total_tokens", nullable=False),
        "input_tokens": IntegerDatabaseField(name="input_tokens", nullable=False),
        "output_tokens": IntegerDatabaseField(name="output_tokens", nullable=False),
        "text_input_tokens": IntegerDatabaseField(name="text_input_tokens", nullable=False),
        "text_output_tokens": IntegerDatabaseField(name="text_output_tokens", nullable=False),
        "image_input_tokens": IntegerDatabaseField(name="image_input_tokens", nullable=False),
        "image_output_tokens": IntegerDatabaseField(name="image_output_tokens", nullable=False),
        "audio_input_tokens": IntegerDatabaseField(name="audio_input_tokens", nullable=False),
        "audio_output_tokens": IntegerDatabaseField(name="audio_output_tokens", nullable=False),
        "video_input_tokens": IntegerDatabaseField(name="video_input_tokens", nullable=False),
        "video_output_tokens": IntegerDatabaseField(name="video_output_tokens", nullable=False),
        "reasoning_tokens": IntegerDatabaseField(name="reasoning_tokens", nullable=False),
        "cache_read_input_tokens": IntegerDatabaseField(name="cache_read_input_tokens", nullable=False),
        "cache_creation_input_tokens": IntegerDatabaseField(name="cache_creation_input_tokens", nullable=False),
        "web_search_count": IntegerDatabaseField(name="web_search_count", nullable=False),
        # Costs
        "input_cost_usd": FloatDatabaseField(name="input_cost_usd", nullable=False),
        "output_cost_usd": FloatDatabaseField(name="output_cost_usd", nullable=False),
        "total_cost_usd": FloatDatabaseField(name="total_cost_usd", nullable=False),
        "request_cost_usd": FloatDatabaseField(name="request_cost_usd", nullable=False),
        "web_search_cost_usd": FloatDatabaseField(name="web_search_cost_usd", nullable=False),
        "audio_cost_usd": FloatDatabaseField(name="audio_cost_usd", nullable=False),
        "image_cost_usd": FloatDatabaseField(name="image_cost_usd", nullable=False),
        "video_cost_usd": FloatDatabaseField(name="video_cost_usd", nullable=False),
        # Timing
        "latency": FloatDatabaseField(name="latency", nullable=False),
        "time_to_first_token": FloatDatabaseField(name="time_to_first_token", nullable=False),
        # Errors
        "is_error": BooleanDatabaseField(name="is_error", nullable=False),
        "error": StringDatabaseField(name="error", nullable=False),
        "error_type": StringDatabaseField(name="error_type", nullable=False),
        "error_normalized": StringDatabaseField(name="error_normalized", nullable=False),
        # Heavy columns (JSON strings — use StringJSONDatabaseField so HogQL
        # handles array/object access via JSONExtract under the hood)
        "input": StringJSONDatabaseField(name="input", nullable=False),
        "output": StringJSONDatabaseField(name="output", nullable=False),
        "output_choices": StringJSONDatabaseField(name="output_choices", nullable=False),
        "input_state": StringJSONDatabaseField(name="input_state", nullable=False),
        "output_state": StringJSONDatabaseField(name="output_state", nullable=False),
        "tools": StringJSONDatabaseField(name="tools", nullable=False),
        # Materialized previews
        "input_preview": StringDatabaseField(name="input_preview", nullable=False),
        "output_choices_preview": StringDatabaseField(name="output_choices_preview", nullable=False),
        # Person join via person_distinct_ids
        "pdi": LazyJoin(
            from_field=["distinct_id"],
            join_table=PersonDistinctIdsTable(),
            join_function=join_with_person_distinct_ids_table,
        ),
        "person": FieldTraverser(chain=["pdi", "person"]),
    }

    def to_printed_clickhouse(self, context):
        return "ai_events"

    def to_printed_hogql(self):
        return "ai_events"
