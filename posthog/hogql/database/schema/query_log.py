from posthog.hogql import ast
from posthog.hogql.database.models import (
    IntegerDatabaseField,
    StringDatabaseField,
    DateTimeDatabaseField,
    LazyTable,
    FieldOrTable,
    LazyTableToAdd,
    FloatDatabaseField,
    FunctionCallTable,
)
from posthog.hogql.parser import parse_expr

QUERY_LOG_FIELDS: dict[str, FieldOrTable] = {
    "query": StringDatabaseField(name="query"),
    "query_start_time": DateTimeDatabaseField(name="event_time"),
    "query_duration_ms": FloatDatabaseField(name="query_duration_ms"),
    "log_comment": StringDatabaseField(name="log_comment"),
    "created_by": IntegerDatabaseField(name="created_by"),
    "exception": StringDatabaseField(name="exception"),
    "cache_key": StringDatabaseField(name="cache_key"),
    "type": StringDatabaseField(name="type"),
    "query_type": StringDatabaseField(name="query_type"),
    # "query_1": ExpressionField(name="query_1", ),
}

STRING_FIELDS = {
    "cache_key": "cache_key",
    "query_type": "query_type",
    "query": ["query", "query"],
}
INT_FIELDS = {"created_by": "user_id"}


def format_extract_args(keys):
    if isinstance(keys, str):
        return f"'{keys}'"
    return ",".join([f'"{k}"' for k in keys])


class QueryLogTable(LazyTable):
    fields: dict[str, FieldOrTable] = QUERY_LOG_FIELDS

    def to_printed_clickhouse(self, context):
        return "query_log"

    def to_printed_hogql(self):
        return "query_log"

    def lazy_select(self, table_to_add: LazyTableToAdd, context, node):
        requested_fields = table_to_add.fields_accessed

        raw_table_name = "raw_query_log"

        def get_alias(name, chain):
            if name in STRING_FIELDS:
                keys = format_extract_args(STRING_FIELDS[name])
                return ast.Alias(alias=name, expr=parse_expr(f"JSONExtractString(log_comment, {keys})"))
            if name in INT_FIELDS:
                keys = format_extract_args(INT_FIELDS[name])
                return ast.Alias(alias=name, expr=parse_expr(f"JSONExtractInt(log_comment, {keys})"))
            return ast.Alias(alias=name, expr=ast.Field(chain=[raw_table_name, *chain]))

        fields: list[ast.Expr] = [get_alias(name, chain) for name, chain in requested_fields.items()]

        return ast.SelectQuery(
            select=fields,
            select_from=ast.JoinExpr(table=ast.Field(chain=[raw_table_name])),
        )


class RawQueryLogTable(FunctionCallTable):
    fields: dict[str, FieldOrTable] = QUERY_LOG_FIELDS

    name: str = "raw_query_log"

    def to_printed_clickhouse(self, context):
        return "clusterAllReplicas(posthog, system.query_log)"

    def to_printed_hogql(self, context):
        return "query_log"
