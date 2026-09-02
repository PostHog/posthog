from typing import TYPE_CHECKING, Any

from posthog.hogql import ast
from posthog.hogql.database.models import (
    BooleanDatabaseField,
    FieldOrTable,
    IntegerDatabaseField,
    LazyTable,
    LazyTableToAdd,
    StringDatabaseField,
    Table,
    TableNode,
    UUIDDatabaseField,
)

if TYPE_CHECKING:
    from posthog.hogql.context import HogQLContext

RECENT_ISSUE_STATE_HOGQL_CONTEXT_KEY = "error_tracking_recent_issue_state"
RECENT_ISSUE_STATE_EXTERNAL_TABLE_NAME = "__ph_error_tracking_recent_issue_state"

RECENT_ISSUE_STATE_FIELDS: dict[str, FieldOrTable] = {
    "team_id": IntegerDatabaseField(
        name="team_id", nullable=False, description="Team that owns the error tracking issue."
    ),
    "issue_id": UUIDDatabaseField(
        name="issue_id", nullable=False, description="Identifier of the recently changed error tracking issue."
    ),
    "issue_status": StringDatabaseField(
        name="issue_status", nullable=False, description="Authoritative status stored in Postgres."
    ),
    "issue_severity": StringDatabaseField(
        name="issue_severity", nullable=True, description="Authoritative severity stored in Postgres."
    ),
    "issue_name": StringDatabaseField(
        name="issue_name", nullable=True, description="Authoritative issue name stored in Postgres."
    ),
    "issue_description": StringDatabaseField(
        name="issue_description", nullable=True, description="Authoritative issue description stored in Postgres."
    ),
    "assigned_user_id": IntegerDatabaseField(
        name="assigned_user_id", nullable=True, description="Currently assigned user, if any."
    ),
    "assigned_role_id": UUIDDatabaseField(
        name="assigned_role_id", nullable=True, description="Currently assigned role, if any."
    ),
    "is_present": BooleanDatabaseField(
        name="is_present",
        nullable=False,
        description="Whether an authoritative row exists, including when its nullable values are cleared.",
    ),
}

RECENT_ISSUE_STATE_EXTERNAL_STRUCTURE: list[tuple[str, str]] = [
    ("team_id", "Int64"),
    ("issue_id", "UUID"),
    ("issue_status", "String"),
    ("issue_severity", "Nullable(String)"),
    ("issue_name", "Nullable(String)"),
    ("issue_description", "Nullable(String)"),
    ("assigned_user_id", "Nullable(Int64)"),
    ("assigned_role_id", "Nullable(UUID)"),
    ("is_present", "UInt8"),
]


class _ErrorTrackingRecentIssueStateExternalTable(Table):
    description: str = "Query-scoped authoritative state for recently changed error tracking issues."
    fields: dict[str, FieldOrTable] = RECENT_ISSUE_STATE_FIELDS

    def to_printed_clickhouse(self, context: "HogQLContext") -> str:
        return RECENT_ISSUE_STATE_EXTERNAL_TABLE_NAME

    def to_printed_hogql(self) -> str:
        return RECENT_ISSUE_STATE_EXTERNAL_TABLE_NAME


class ErrorTrackingRecentIssueStateTable(LazyTable):
    description: str = "Recent Postgres issue state used to cover ClickHouse synchronization delay."
    fields: dict[str, FieldOrTable] = RECENT_ISSUE_STATE_FIELDS

    def lazy_select(
        self,
        table_to_add: LazyTableToAdd,
        context: "HogQLContext",
        node: ast.SelectQuery,
    ) -> ast.SelectQuery:
        rows: list[dict[str, Any]] = context.data_to_ingest.get(RECENT_ISSUE_STATE_HOGQL_CONTEXT_KEY) or []
        context.external_tables[RECENT_ISSUE_STATE_EXTERNAL_TABLE_NAME] = {
            "name": RECENT_ISSUE_STATE_EXTERNAL_TABLE_NAME,
            "structure": RECENT_ISSUE_STATE_EXTERNAL_STRUCTURE,
            "data": rows,
        }
        if context.database is not None:
            context.database.tables.add_child(
                TableNode(
                    name=RECENT_ISSUE_STATE_EXTERNAL_TABLE_NAME,
                    table=_ErrorTrackingRecentIssueStateExternalTable(),
                    hidden=True,
                ),
                table_conflict_mode="override",
                children_conflict_mode="override",
            )

        selected_fields = set(table_to_add.fields_accessed) | {"team_id"}
        return ast.SelectQuery(
            select=[
                ast.Field(chain=[field_name])
                for field_name in RECENT_ISSUE_STATE_FIELDS
                if field_name in selected_fields
            ],
            select_from=ast.JoinExpr(table=ast.Field(chain=[RECENT_ISSUE_STATE_EXTERNAL_TABLE_NAME])),
        )

    def to_printed_clickhouse(self, context: "HogQLContext") -> str:
        return RECENT_ISSUE_STATE_EXTERNAL_TABLE_NAME

    def to_printed_hogql(self) -> str:
        return "error_tracking_recent_issue_state"
