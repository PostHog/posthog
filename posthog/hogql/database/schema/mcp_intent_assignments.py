from posthog.hogql.ast import Constant, LazyTableType, SelectQuery
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.argmax import argmax_select
from posthog.hogql.database.models import (
    DateDatabaseField,
    DateTimeDatabaseField,
    FieldOrTable,
    FloatDatabaseField,
    IntegerArrayDatabaseField,
    IntegerDatabaseField,
    LazyTable,
    LazyTableToAdd,
    StringDatabaseField,
    Table,
)

from products.mcp_analytics.backend.facade.clickhouse_schema import (
    MCP_INTENT_ASSIGNMENTS_DISTRIBUTED_TABLE,
    MCP_INTENT_CALLS_HOURLY_DISTRIBUTED_TABLE,
    MCP_INTENT_TOPIC_DAILY_DISTRIBUTED_TABLE,
)

MCP_INTENT_ASSIGNMENTS_FIELDS: dict[str, FieldOrTable] = {
    "team_id": IntegerDatabaseField(name="team_id", nullable=False),
    "intent_hash": StringDatabaseField(
        name="intent_hash",
        nullable=False,
        description="sha256 hex of the raw `$mcp_intent` text; join to events with sha256(toString(properties.$mcp_intent)).",
    ),
    "run_id": StringDatabaseField(name="run_id", nullable=False, description="Pipeline run that wrote the row."),
    "topic_id": StringDatabaseField(
        name="topic_id", nullable=True, description="Assigned intent topic id; NULL when no topic was within reach."
    ),
    "distance": FloatDatabaseField(
        name="distance", nullable=False, description="Cosine distance to the assigned topic centroid."
    ),
    "x": FloatDatabaseField(name="x", nullable=False, description="2D map position."),
    "y": FloatDatabaseField(name="y", nullable=False, description="2D map position."),
    "is_outlier": IntegerDatabaseField(
        name="is_outlier", nullable=False, description="1 when the intent sits outside its topic's outlier distance."
    ),
    "intent_text": StringDatabaseField(
        name="intent_text", nullable=False, description="Truncated intent text for display."
    ),
    "calls_in_run": IntegerDatabaseField(
        name="calls_in_run", nullable=False, description="Calls carrying this intent when it was embedded."
    ),
    "timestamp": DateTimeDatabaseField(
        name="timestamp", nullable=False, description="When the assignment was made; the newest row per intent wins."
    ),
}


RAW_TABLE_ALIAS = "raw_mcp_intent_assignments"


class RawMCPIntentAssignmentsTable(Table):
    description: str = (
        "Every intent topic assignment row, one per run. Rows for the same intent are only merged in the "
        "background; query the deduplicated `posthog.mcp_intent_assignments` table instead."
    )
    fields: dict[str, FieldOrTable] = MCP_INTENT_ASSIGNMENTS_FIELDS

    def to_printed_clickhouse(self, context: HogQLContext):
        return MCP_INTENT_ASSIGNMENTS_DISTRIBUTED_TABLE

    def to_printed_hogql(self):
        return "raw_mcp_intent_assignments"


def select_latest_assignments(requested_fields: dict[str, list[str | int]]) -> SelectQuery:
    # Older rows for an intent can sit in another monthly partition and never merge, so every read
    # keeps only the newest row per intent hash before any filter applies.
    from posthog.hogql import ast

    if "intent_hash" not in requested_fields:
        requested_fields = {**requested_fields, "intent_hash": ["intent_hash"]}
    select = argmax_select(
        table_name=RAW_TABLE_ALIAS,
        select_fields=requested_fields,
        group_fields=["intent_hash"],
        argmax_field="timestamp",
    )
    select.select_from = ast.JoinExpr(table=ast.Field(chain=["posthog", RAW_TABLE_ALIAS]), alias=RAW_TABLE_ALIAS)
    return select


class MCPIntentAssignmentsTable(LazyTable):
    description: str = (
        "Latest intent topic assignment per MCP tool intent text, one row per intent hash. Join to `events` on "
        "sha256(toString(properties.$mcp_intent)) = intent_hash to break tool calls down by intent topic."
    )
    fields: dict[str, FieldOrTable] = MCP_INTENT_ASSIGNMENTS_FIELDS

    def lazy_select(self, table_to_add: LazyTableToAdd, context: HogQLContext, node: SelectQuery):
        # Deferred because restricted_properties imports this module.
        from posthog.hogql.restricted_properties import mirrored_column_is_restricted  # noqa: PLC0415

        select = select_latest_assignments(table_to_add.fields_accessed)
        # A restricted intent_hash reads as NULL, so the dedupe would merge every intent into one row. Return no rows
        # instead of one misleading row.
        if mirrored_column_is_restricted(LazyTableType(table=self), "intent_hash", context):
            select.where = Constant(value=False)
        return select

    def to_printed_clickhouse(self, context: HogQLContext):
        return MCP_INTENT_ASSIGNMENTS_DISTRIBUTED_TABLE

    def to_printed_hogql(self):
        return "mcp_intent_assignments"


MCP_INTENT_CALLS_HOURLY_FIELDS: dict[str, FieldOrTable] = {
    "team_id": IntegerDatabaseField(name="team_id", nullable=False),
    "hour": DateTimeDatabaseField(name="hour", nullable=False, description="Start of the hour, UTC."),
    "intent_hash": StringDatabaseField(
        name="intent_hash", nullable=False, description="sha256 hex of the raw intent text."
    ),
    "tool": StringDatabaseField(name="tool", nullable=False, description="Effective tool name."),
    "calls": IntegerDatabaseField(name="calls", nullable=False),
    "conversation_hashes": IntegerArrayDatabaseField(
        name="conversation_hashes", nullable=False, description="cityHash64 of each distinct MCP conversation id."
    ),
    "inserted_at": DateTimeDatabaseField(name="inserted_at", nullable=False),
}


class MCPIntentCallsHourlyTable(Table):
    description: str = "Hourly MCP tool calls per intent text and tool, written by the intent topics sync run."
    fields: dict[str, FieldOrTable] = MCP_INTENT_CALLS_HOURLY_FIELDS

    def to_printed_clickhouse(self, context: HogQLContext):
        return MCP_INTENT_CALLS_HOURLY_DISTRIBUTED_TABLE

    def to_printed_hogql(self):
        return "mcp_intent_calls_hourly"


MCP_INTENT_TOPIC_DAILY_FIELDS: dict[str, FieldOrTable] = {
    "team_id": IntegerDatabaseField(name="team_id", nullable=False),
    "day": DateDatabaseField(name="day", nullable=False),
    "tool": StringDatabaseField(name="tool", nullable=False, description="Effective tool name."),
    "topic_id": StringDatabaseField(
        name="topic_id", nullable=False, description="Intent topic id; empty when the intent had no topic yet."
    ),
    "calls": IntegerDatabaseField(name="calls", nullable=False),
    "conversation_hashes": IntegerArrayDatabaseField(
        name="conversation_hashes", nullable=False, description="cityHash64 of each distinct MCP conversation id."
    ),
    "outlier_calls": IntegerDatabaseField(name="outlier_calls", nullable=False),
    "intents": IntegerDatabaseField(name="intents", nullable=False, description="Distinct intent texts."),
    "inserted_at": DateTimeDatabaseField(name="inserted_at", nullable=False),
}


class MCPIntentTopicDailyTable(Table):
    description: str = (
        "Daily MCP tool calls per tool and intent topic. The fast path for intent topic trends; "
        "join topic_id to the topic registry for labels."
    )
    fields: dict[str, FieldOrTable] = MCP_INTENT_TOPIC_DAILY_FIELDS

    def to_printed_clickhouse(self, context: HogQLContext):
        return MCP_INTENT_TOPIC_DAILY_DISTRIBUTED_TABLE

    def to_printed_hogql(self):
        return "mcp_intent_topic_daily"
