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
        "trace_id": StringDatabaseField(name="trace_id", nullable=True),
        "session_id": StringDatabaseField(name="session_id", nullable=True),
        "parent_id": StringDatabaseField(name="parent_id", nullable=True),
        "span_id": StringDatabaseField(name="span_id", nullable=True),
        "span_type": StringDatabaseField(name="span_type", nullable=True),
        "generation_id": StringDatabaseField(name="generation_id", nullable=True),
        # Names
        "span_name": StringDatabaseField(name="span_name", nullable=True),
        "trace_name": StringDatabaseField(name="trace_name", nullable=True),
        "prompt_name": StringDatabaseField(name="prompt_name", nullable=True),
        # Model info
        "model": StringDatabaseField(name="model", nullable=True),
        "provider": StringDatabaseField(name="provider", nullable=True),
        "framework": StringDatabaseField(name="framework", nullable=True),
        # Token counts
        "total_tokens": IntegerDatabaseField(name="total_tokens", nullable=True),
        "input_tokens": IntegerDatabaseField(name="input_tokens", nullable=True),
        "output_tokens": IntegerDatabaseField(name="output_tokens", nullable=True),
        "text_input_tokens": IntegerDatabaseField(name="text_input_tokens", nullable=True),
        "text_output_tokens": IntegerDatabaseField(name="text_output_tokens", nullable=True),
        "image_input_tokens": IntegerDatabaseField(name="image_input_tokens", nullable=True),
        "image_output_tokens": IntegerDatabaseField(name="image_output_tokens", nullable=True),
        "audio_input_tokens": IntegerDatabaseField(name="audio_input_tokens", nullable=True),
        "audio_output_tokens": IntegerDatabaseField(name="audio_output_tokens", nullable=True),
        "video_input_tokens": IntegerDatabaseField(name="video_input_tokens", nullable=True),
        "video_output_tokens": IntegerDatabaseField(name="video_output_tokens", nullable=True),
        "reasoning_tokens": IntegerDatabaseField(name="reasoning_tokens", nullable=True),
        "cache_read_input_tokens": IntegerDatabaseField(name="cache_read_input_tokens", nullable=True),
        "cache_creation_input_tokens": IntegerDatabaseField(name="cache_creation_input_tokens", nullable=True),
        "web_search_count": IntegerDatabaseField(name="web_search_count", nullable=True),
        # Costs
        "input_cost_usd": FloatDatabaseField(name="input_cost_usd", nullable=True),
        "output_cost_usd": FloatDatabaseField(name="output_cost_usd", nullable=True),
        "total_cost_usd": FloatDatabaseField(name="total_cost_usd", nullable=True),
        "request_cost_usd": FloatDatabaseField(name="request_cost_usd", nullable=True),
        "web_search_cost_usd": FloatDatabaseField(name="web_search_cost_usd", nullable=True),
        "audio_cost_usd": FloatDatabaseField(name="audio_cost_usd", nullable=True),
        "image_cost_usd": FloatDatabaseField(name="image_cost_usd", nullable=True),
        "video_cost_usd": FloatDatabaseField(name="video_cost_usd", nullable=True),
        # Timing
        "latency": FloatDatabaseField(name="latency", nullable=True),
        "time_to_first_token": FloatDatabaseField(name="time_to_first_token", nullable=True),
        # Errors
        "is_error": BooleanDatabaseField(name="is_error", nullable=False),
        "error": StringDatabaseField(name="error", nullable=True),
        "error_type": StringDatabaseField(name="error_type", nullable=True),
        "error_normalized": StringDatabaseField(name="error_normalized", nullable=True),
        # Heavy columns (JSON strings — use StringJSONDatabaseField so HogQL
        # handles array/object access via JSONExtract under the hood)
        "input": StringJSONDatabaseField(name="input", nullable=True),
        "output": StringJSONDatabaseField(name="output", nullable=True),
        "output_choices": StringJSONDatabaseField(name="output_choices", nullable=True),
        "input_state": StringJSONDatabaseField(name="input_state", nullable=True),
        "output_state": StringJSONDatabaseField(name="output_state", nullable=True),
        "tools": StringJSONDatabaseField(name="tools", nullable=True),
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
