from posthog.hogql.ast import Constant, LazyTableType, SelectQuery
from posthog.hogql.base import Expr
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.models import (
    DateDatabaseField,
    DateTimeDatabaseField,
    EventsRetentionTable,
    FieldOrTable,
    FloatDatabaseField,
    IntegerArrayDatabaseField,
    IntegerDatabaseField,
    LazyTable,
    LazyTableToAdd,
    StringDatabaseField,
    Table,
)
from posthog.hogql.parser import parse_expr

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


class StoredMCPIntentAssignmentsTable(Table):
    # Bound only by the lazy query, never registered in the catalog. Its retention check must run after
    # argMax: pruning an expired or unknown newest version first would resurrect an older assignment.
    fields: dict[str, FieldOrTable] = MCP_INTENT_ASSIGNMENTS_FIELDS

    def to_printed_clickhouse(self, context: HogQLContext) -> str:
        return MCP_INTENT_ASSIGNMENTS_DISTRIBUTED_TABLE

    def to_printed_hogql(self) -> str:
        return "stored_mcp_intent_assignments"


class RawMCPIntentAssignmentsTable(StoredMCPIntentAssignmentsTable, EventsRetentionTable):
    description: str = (
        "Every retained intent topic assignment row, one per run. Rows for the same intent are only merged in the "
        "background; query the deduplicated `posthog.mcp_intent_assignments` table instead."
    )
    events_retention_field: str = "source_min_timestamp"

    def get_predicates(self, context: HogQLContext | None = None) -> list[Expr]:
        return [parse_expr("isNotNull(source_min_timestamp)")]

    def to_printed_hogql(self) -> str:
        return RAW_TABLE_ALIAS


def select_latest_assignments(requested_fields: dict[str, list[str | int]], context: HogQLContext) -> SelectQuery:
    # Older rows for an intent can sit in another monthly partition and never merge, so every read
    # keeps only the newest row per intent hash before any filter applies.
    from posthog.hogql import ast

    if "intent_hash" not in requested_fields:
        requested_fields = {**requested_fields, "intent_hash": ["intent_hash"]}
    chains = list(
        dict.fromkeys(
            [
                *(tuple(chain) for chain in requested_fields.values() if chain != ["intent_hash"]),
                ("source_min_timestamp",),
            ]
        )
    )
    # One aggregate tuple keeps payload and provenance together even when assignment timestamps tie.
    latest = SelectQuery(
        select=[
            ast.Alias(alias="intent_hash", expr=ast.Field(chain=[RAW_TABLE_ALIAS, "intent_hash"])),
            ast.Alias(
                alias="assignment",
                expr=ast.Call(
                    name="argMax",
                    args=[
                        ast.Call(name="tuple", args=[ast.Field(chain=[RAW_TABLE_ALIAS, *chain]) for chain in chains]),
                        ast.Field(chain=[RAW_TABLE_ALIAS, "timestamp"]),
                    ],
                ),
            ),
        ],
        select_from=ast.JoinExpr(
            table=ast.Field(chain=["stored_mcp_intent_assignments"]),
            table_schema=StoredMCPIntentAssignmentsTable(),
            alias=RAW_TABLE_ALIAS,
        ),
        group_by=[ast.Field(chain=[RAW_TABLE_ALIAS, "intent_hash"])],
    )

    def latest_field(chain: list[str | int]) -> Expr:
        if chain == ["intent_hash"]:
            return ast.Field(chain=["latest", "intent_hash"])
        return ast.Call(
            name="tupleElement",
            args=[ast.Field(chain=["latest", "assignment"]), Constant(value=chains.index(tuple(chain)) + 1)],
        )

    latest_source = latest_field(["source_min_timestamp"])
    select = SelectQuery(
        select=[ast.Alias(alias=name, expr=latest_field(chain)) for name, chain in requested_fields.items()],
        select_from=ast.JoinExpr(table=latest, alias="latest"),
        where=parse_expr("isNotNull({source})", placeholders={"source": latest_source}),
    )
    if context.events_retention_months is not None:
        assert select.where is not None
        select.where = ast.And(
            exprs=[
                select.where,
                parse_expr(
                    "{source} > now() - toIntervalMonth({months})",
                    placeholders={
                        "source": latest_source,
                        "months": Constant(value=context.events_retention_months),
                    },
                ),
            ]
        )
    return select


class MCPIntentAssignmentsTable(LazyTable):
    description: str = (
        "Latest intent topic assignment per MCP tool intent text, one row per intent hash. Join to `events` on "
        "sha256(toString(properties.$mcp_intent)) = intent_hash to break tool calls down by intent topic."
    )
    fields: dict[str, FieldOrTable] = MCP_INTENT_ASSIGNMENTS_FIELDS

    def lazy_select(self, table_to_add: LazyTableToAdd, context: HogQLContext, node: SelectQuery) -> SelectQuery:
        # Deferred because restricted_properties imports this module.
        from posthog.hogql.restricted_properties import mirrored_column_is_restricted  # noqa: PLC0415

        select = select_latest_assignments(table_to_add.fields_accessed, context)
        # A restricted intent_hash reads as NULL, so the dedupe would merge every intent into one row. Return no rows
        # instead of one misleading row.
        if mirrored_column_is_restricted(LazyTableType(table=self), "intent_hash", context):
            select.where = Constant(value=False)
        return select

    def to_printed_clickhouse(self, context: HogQLContext) -> str:
        return MCP_INTENT_ASSIGNMENTS_DISTRIBUTED_TABLE

    def to_printed_hogql(self) -> str:
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
    description: str = (
        "Hourly MCP tool calls per intent text and tool, written by the intent topics sync run. "
        "A sync that re-reads an hour writes its rows again with a later inserted_at and older copies can remain, "
        "so read only the rows with the latest inserted_at for each hour and intent_hash."
    )
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
        "join topic_id to the topic registry for labels. Each rebuild of a day writes all of that day's rows again "
        "with a later inserted_at and keeps the older rows, so sum only the rows with the latest inserted_at for each day."
    )
    fields: dict[str, FieldOrTable] = MCP_INTENT_TOPIC_DAILY_FIELDS

    def to_printed_clickhouse(self, context: HogQLContext):
        return MCP_INTENT_TOPIC_DAILY_DISTRIBUTED_TABLE

    def to_printed_hogql(self):
        return "mcp_intent_topic_daily"
