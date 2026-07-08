from posthog.hogql.database.lazy_join_tags import PERSON_DISTINCT_IDS
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
from posthog.hogql.database.schema.person_distinct_ids import PersonDistinctIdsTable


class AiEventsTable(Table):
    description: str = "AI observability events ($ai_generation, $ai_span, $ai_trace, $ai_evaluation, etc.) capturing model calls, token usage, costs, and trace structure."
    fields: dict[str, FieldOrTable] = {
        # Core
        "uuid": StringDatabaseField(name="uuid", nullable=False, description="Unique identifier of this event row."),
        "event": StringDatabaseField(
            name="event",
            nullable=False,
            description="AI observability event name, e.g. '$ai_generation', '$ai_span', '$ai_trace'.",
        ),
        "timestamp": DateTimeDatabaseField(
            name="timestamp", nullable=False, description="When the event occurred (UTC)."
        ),
        "team_id": IntegerDatabaseField(name="team_id", nullable=False),
        "distinct_id": StringDatabaseField(
            name="distinct_id",
            nullable=False,
            description="Identifier of the user/device; resolved to a person via `person_id`.",
        ),
        "person_id": StringDatabaseField(
            name="person_id", nullable=False, description="Stable person identifier this event is attributed to."
        ),
        "properties": StringJSONDatabaseField(
            name="properties",
            nullable=False,
            description="JSON map of event properties (raw properties live here).",
        ),
        "retention_days": IntegerDatabaseField(
            name="retention_days", nullable=False, description="Number of days the event is retained for."
        ),
        # Trace structure
        "trace_id": StringDatabaseField(
            name="trace_id", nullable=False, description="Identifier of the LLM trace this event belongs to."
        ),
        "session_id": StringDatabaseField(
            name="session_id", nullable=True, description="Session this event belongs to, if set."
        ),
        "parent_id": StringDatabaseField(
            name="parent_id", nullable=True, description="Identifier of the parent span/generation in the trace tree."
        ),
        "span_id": StringDatabaseField(
            name="span_id", nullable=True, description="Identifier of this span within the trace."
        ),
        "span_type": StringDatabaseField(
            name="span_type", nullable=True, description="Type of span, e.g. 'generation', 'span', 'embedding'."
        ),
        "generation_id": StringDatabaseField(
            name="generation_id", nullable=True, description="Identifier of the generation, for $ai_generation events."
        ),
        "experiment_id": StringDatabaseField(
            name="experiment_id",
            nullable=True,
            description="AI observability experiment this event is associated with, if any.",
        ),
        # Names
        "span_name": StringDatabaseField(
            name="span_name", nullable=True, description="Human-readable name of the span."
        ),
        "trace_name": StringDatabaseField(
            name="trace_name", nullable=True, description="Human-readable name of the trace."
        ),
        "prompt_name": StringDatabaseField(
            name="prompt_name", nullable=True, description="Name of the managed prompt used, if any."
        ),
        # Model info
        "model": StringDatabaseField(
            name="model", nullable=True, description="Model used for the call, e.g. 'gpt-4o' or 'claude-3-5-sonnet'."
        ),
        "provider": StringDatabaseField(
            name="provider", nullable=True, description="Model provider, e.g. 'openai', 'anthropic'."
        ),
        "framework": StringDatabaseField(
            name="framework", nullable=True, description="Instrumentation framework used, e.g. 'langchain'."
        ),
        # Token counts
        "total_tokens": IntegerDatabaseField(
            name="total_tokens", nullable=True, description="Total tokens for the call (input + output)."
        ),
        "input_tokens": IntegerDatabaseField(
            name="input_tokens", nullable=True, description="Number of input/prompt tokens."
        ),
        "output_tokens": IntegerDatabaseField(
            name="output_tokens", nullable=True, description="Number of output/completion tokens."
        ),
        "text_input_tokens": IntegerDatabaseField(name="text_input_tokens", nullable=True),
        "text_output_tokens": IntegerDatabaseField(name="text_output_tokens", nullable=True),
        "image_input_tokens": IntegerDatabaseField(name="image_input_tokens", nullable=True),
        "image_output_tokens": IntegerDatabaseField(name="image_output_tokens", nullable=True),
        "audio_input_tokens": IntegerDatabaseField(name="audio_input_tokens", nullable=True),
        "audio_output_tokens": IntegerDatabaseField(name="audio_output_tokens", nullable=True),
        "video_input_tokens": IntegerDatabaseField(name="video_input_tokens", nullable=True),
        "video_output_tokens": IntegerDatabaseField(name="video_output_tokens", nullable=True),
        "reasoning_tokens": IntegerDatabaseField(
            name="reasoning_tokens", nullable=True, description="Number of reasoning/thinking tokens."
        ),
        "cache_read_input_tokens": IntegerDatabaseField(
            name="cache_read_input_tokens",
            nullable=True,
            description="Input tokens served from the provider's prompt cache.",
        ),
        "cache_creation_input_tokens": IntegerDatabaseField(
            name="cache_creation_input_tokens",
            nullable=True,
            description="Input tokens written to the provider's prompt cache.",
        ),
        "web_search_count": IntegerDatabaseField(
            name="web_search_count", nullable=True, description="Number of web searches performed during the call."
        ),
        # Costs
        "input_cost_usd": FloatDatabaseField(
            name="input_cost_usd", nullable=True, description="Cost of input tokens, in USD."
        ),
        "output_cost_usd": FloatDatabaseField(
            name="output_cost_usd", nullable=True, description="Cost of output tokens, in USD."
        ),
        "total_cost_usd": FloatDatabaseField(
            name="total_cost_usd", nullable=True, description="Total cost of the call, in USD."
        ),
        "request_cost_usd": FloatDatabaseField(
            name="request_cost_usd", nullable=True, description="Per-request/base cost component, in USD."
        ),
        "web_search_cost_usd": FloatDatabaseField(
            name="web_search_cost_usd", nullable=True, description="Cost of web searches, in USD."
        ),
        "audio_cost_usd": FloatDatabaseField(
            name="audio_cost_usd", nullable=True, description="Cost of audio tokens, in USD."
        ),
        "image_cost_usd": FloatDatabaseField(
            name="image_cost_usd", nullable=True, description="Cost of image tokens, in USD."
        ),
        "video_cost_usd": FloatDatabaseField(
            name="video_cost_usd", nullable=True, description="Cost of video tokens, in USD."
        ),
        # Timing
        "latency": FloatDatabaseField(
            name="latency", nullable=True, description="End-to-end latency of the call, in seconds."
        ),
        "time_to_first_token": FloatDatabaseField(
            name="time_to_first_token", nullable=True, description="Time until the first streamed token, in seconds."
        ),
        # Errors
        "is_error": BooleanDatabaseField(
            name="is_error", nullable=False, description="True if the call resulted in an error."
        ),
        "error": StringDatabaseField(name="error", nullable=True, description="Raw error message, if the call failed."),
        "error_type": StringDatabaseField(name="error_type", nullable=True, description="Classification of the error."),
        "error_normalized": StringDatabaseField(
            name="error_normalized", nullable=True, description="Normalized/grouped error string for aggregation."
        ),
        # Heavy columns (JSON strings — use StringJSONDatabaseField so HogQL
        # handles array/object access via JSONExtract under the hood)
        "input": StringJSONDatabaseField(
            name="input", nullable=True, description="JSON of the model input (prompt/messages)."
        ),
        "output": StringJSONDatabaseField(
            name="output", nullable=True, description="JSON of the model output/completion."
        ),
        "output_choices": StringJSONDatabaseField(
            name="output_choices", nullable=True, description="JSON of the output choices returned by the model."
        ),
        "input_state": StringJSONDatabaseField(
            name="input_state", nullable=True, description="JSON of the input state for span/trace events."
        ),
        "output_state": StringJSONDatabaseField(
            name="output_state", nullable=True, description="JSON of the output state for span/trace events."
        ),
        "tools": StringJSONDatabaseField(
            name="tools", nullable=True, description="JSON of the tool/function definitions available to the model."
        ),
        # Person join via person_distinct_ids
        "pdi": LazyJoin(
            from_field=["distinct_id"],
            join_table=PersonDistinctIdsTable(),
            resolver=PERSON_DISTINCT_IDS,
        ),
        "person": FieldTraverser(
            chain=["pdi", "person"],
            description="The person this event is attributed to; access via `person.properties.*`.",
        ),
    }

    def to_printed_clickhouse(self, context):
        return "ai_events"

    def to_printed_hogql(self):
        return "ai_events"
