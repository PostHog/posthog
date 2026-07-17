from posthog.hogql import ast
from posthog.hogql.database.models import (
    DateTimeDatabaseField,
    FieldOrTable,
    IntegerDatabaseField,
    LazyTable,
    LazyTableToAdd,
    StringDatabaseField,
    Table,
)

LOG_ENTRIES_FIELDS: dict[str, FieldOrTable] = {
    "team_id": IntegerDatabaseField(name="team_id", nullable=False),
    "log_source": StringDatabaseField(
        name="log_source",
        nullable=False,
        description="Origin of the log line, e.g. 'session_replay' (console logs) or 'batch_export'.",
    ),
    "log_source_id": StringDatabaseField(
        name="log_source_id",
        nullable=False,
        description="Identifier of the source entity that produced the log (e.g. the session or batch export id).",
    ),
    "instance_id": StringDatabaseField(
        name="instance_id",
        nullable=False,
        description="Identifier of the specific run/instance that emitted the log line.",
    ),
    "timestamp": DateTimeDatabaseField(name="timestamp", nullable=False, description="When the log line was emitted."),
    "message": StringDatabaseField(name="message", nullable=False, description="The log message text."),
    "level": StringDatabaseField(
        name="level", nullable=False, description="Log severity level, e.g. 'info', 'warn', 'error'."
    ),
}


class LogEntriesTable(Table):
    description: str = (
        "Console/diagnostic log lines emitted by plugins, batch exports, and session replay, filtered by `log_source`."
    )
    fields: dict[str, FieldOrTable] = LOG_ENTRIES_FIELDS

    def to_printed_clickhouse(self, context):
        return "log_entries"

    def to_printed_hogql(self):
        return "log_entries"


class ReplayConsoleLogsLogEntriesTable(LazyTable):
    description: str = "Browser console log lines captured during session replay (`log_source` = 'session_replay')."
    fields: dict[str, FieldOrTable] = LOG_ENTRIES_FIELDS

    def lazy_select(self, table_to_add: LazyTableToAdd, context, node):
        fields: list[ast.Expr] = [
            ast.Field(chain=["log_entries", *chain]) for name, chain in table_to_add.fields_accessed.items()
        ]

        return ast.SelectQuery(
            select=fields,
            select_from=ast.JoinExpr(table=ast.Field(chain=["log_entries"])),
            where=ast.CompareOperation(
                op=ast.CompareOperationOp.Eq,
                left=ast.Field(chain=["log_entries", "log_source"]),
                right=ast.Constant(value="session_replay"),
            ),
        )

    def to_printed_clickhouse(self, context):
        return "console_logs_log_entries"

    def to_printed_hogql(self):
        return "console_logs_log_entries"


class BatchExportLogEntriesTable(LazyTable):
    description: str = "Log lines emitted by batch export runs (`log_source` = 'batch_export')."
    fields: dict[str, FieldOrTable] = LOG_ENTRIES_FIELDS

    def lazy_select(self, table_to_add: LazyTableToAdd, context, node):
        fields: list[ast.Expr] = [
            ast.Field(chain=["log_entries", *chain]) for name, chain in table_to_add.fields_accessed.items()
        ]

        return ast.SelectQuery(
            select=fields,
            select_from=ast.JoinExpr(table=ast.Field(chain=["log_entries"])),
            where=ast.CompareOperation(
                op=ast.CompareOperationOp.Eq,
                left=ast.Field(chain=["log_entries", "log_source"]),
                right=ast.Constant(value="batch_export"),
            ),
        )

    def to_printed_clickhouse(self, context):
        return "batch_export_log_entries"

    def to_printed_hogql(self):
        return "batch_export_log_entries"
