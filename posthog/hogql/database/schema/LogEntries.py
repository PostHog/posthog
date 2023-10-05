from typing import Dict, List

from posthog.hogql import ast
from posthog.hogql.database.models import (
    Table,
    IntegerDatabaseField,
    StringDatabaseField,
    DateTimeDatabaseField,
    LazyTable,
    FieldOrTable,
)

LOG_ENTRIES_FIELDS: Dict[str, FieldOrTable] = {
    "team_id": IntegerDatabaseField(name="team_id"),
    "log_source": StringDatabaseField(name="log_source"),
    "log_source_id": StringDatabaseField(name="log_source_id"),
    "instance_id": StringDatabaseField(name="instance_id"),
    "timestamp": DateTimeDatabaseField(name="timestamp"),
    "message": StringDatabaseField(name="message"),
    "level": StringDatabaseField(name="level"),
}


class LogEntriesTable(Table):
    fields: LOG_ENTRIES_FIELDS

    def to_printed_clickhouse(self, context):
        return "log_entries"

    def to_printed_hogql(self):
        return "log_entries"


class ReplayConsoleLogsLogEntriesTable(LazyTable):
    fields = LOG_ENTRIES_FIELDS

    def lazy_select(self, requested_fields: Dict[str, List[str]]):
        fields: List[ast.Expr] = [ast.Field(chain=["log_entries"] + chain) for name, chain in requested_fields.items()]

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
        return "log_entries"

    def to_printed_hogql(self):
        return "log_entries"


class BatchExportLogEntriesTable(LazyTable):
    fields = LOG_ENTRIES_FIELDS

    def lazy_select(self, requested_fields: Dict[str, List[str]]):
        fields: List[ast.Expr] = [ast.Field(chain=["log_entries"] + chain) for name, chain in requested_fields.items()]

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
        return "log_entries"

    def to_printed_hogql(self):
        return "log_entries"
