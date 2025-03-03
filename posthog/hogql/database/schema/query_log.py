from typing import Any

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
    BooleanDatabaseField,
)

QUERY_LOG_FIELDS: dict[str, FieldOrTable] = {
    "query_id": StringDatabaseField(name="query_id", nullable=False),
    "endpoint": StringDatabaseField(name="endpoint", nullable=False),
    "query": StringDatabaseField(name="query", nullable=False),  #
    "query_start_time": DateTimeDatabaseField(name="event_time", nullable=False),  #
    "query_duration_ms": FloatDatabaseField(name="query_duration_ms", nullable=False),  #
    "hogql_name": StringDatabaseField(name="hogql_name", nullable=False),
    "created_by": IntegerDatabaseField(name="created_by", nullable=False),
    "read_rows": IntegerDatabaseField(name="read_rows", nullable=False),
    "read_bytes": IntegerDatabaseField(name="read_bytes", nullable=False),
    "result_rows": IntegerDatabaseField(name="result_rows", nullable=False),
    "result_bytes": IntegerDatabaseField(name="result_bytes", nullable=False),
    "memory_usage": IntegerDatabaseField(name="memory_usage", nullable=False),
    "status": StringDatabaseField(name="type", nullable=False),
    "is_personal_api_key_request": BooleanDatabaseField(name="is_personal_api_key_request", nullable=False),
}

RAW_QUERY_LOG_FIELDS: dict[str, FieldOrTable] = QUERY_LOG_FIELDS | {
    # below fields are necessary to compute some of the resulting fields
    "type": StringDatabaseField(name="type", nullable=False),
    "is_initial_query": BooleanDatabaseField(name="is_initial_query", nullable=False),
    "log_comment": StringDatabaseField(name="log_comment", nullable=False),
}

STRING_FIELDS = {
    "query_type": ["query_type"],
    "query_id": ["client_query_id"],
    "query": ["query", "query"],
    "kind": ["query", "kind"],
    "hogql_name": ["query", "name"],
}
INT_FIELDS = {"created_by": ["user_id"]}


class QueryLogTable(LazyTable):
    fields: dict[str, FieldOrTable] = QUERY_LOG_FIELDS

    def to_printed_clickhouse(self, context) -> str:
        return "query_log"

    def to_printed_hogql(self) -> str:
        return "query_log"

    def lazy_select(self, table_to_add: LazyTableToAdd, context, node) -> Any:
        requested_fields = table_to_add.fields_accessed

        raw_table_name = "raw_query_log"

        def get_alias(name, chain):
            if name in STRING_FIELDS:
                keys = STRING_FIELDS[name]
                expr = ast.Call(
                    name="JSONExtractString",
                    args=[ast.Field(chain=[raw_table_name, "log_comment"])] + [ast.Constant(value=v) for v in keys],
                )
                return ast.Alias(alias=name, expr=expr)
            if name in INT_FIELDS:
                keys = INT_FIELDS[name]
                expr = ast.Call(
                    name="JSONExtractInt",
                    args=[ast.Field(chain=[raw_table_name, "log_comment"])] + [ast.Constant(value=v) for v in keys],
                )
                return ast.Alias(alias=name, expr=expr)
            if name == "is_personal_api_key_request":
                cmp_expr = ast.CompareOperation(
                    op=ast.CompareOperationOp.Eq,
                    left=ast.Constant(value="personal_api_key"),
                    right=ast.Call(
                        name="JSONExtractString",
                        args=[ast.Field(chain=[raw_table_name, "log_comment"]), ast.Constant(value="access_method")],
                    ),
                )
                return ast.Alias(alias=name, expr=cmp_expr)
            if name == "endpoint":
                if_expr = ast.Call(
                    name="if",
                    args=[
                        ast.CompareOperation(
                            op=ast.CompareOperationOp.Eq,
                            left=ast.Call(
                                name="JSONExtractString",
                                args=[ast.Field(chain=[raw_table_name, "log_comment"]), ast.Constant(value="kind")],
                            ),
                            right=ast.Constant(value="request"),
                        ),
                        ast.Call(
                            name="JSONExtractString",
                            args=[ast.Field(chain=[raw_table_name, "log_comment"]), ast.Constant(value="id")],
                        ),
                        ast.Constant(value=""),
                    ],
                )
                return ast.Alias(alias=name, expr=if_expr)

            return ast.Alias(alias=name, expr=ast.Field(chain=[raw_table_name, *chain]))

        fields: list[ast.Expr] = [get_alias(name, chain) for name, chain in requested_fields.items()]

        return ast.SelectQuery(
            select=fields,
            select_from=ast.JoinExpr(table=ast.Field(chain=[raw_table_name])),
            where=ast.And(
                exprs=[
                    ast.CompareOperation(
                        op=ast.CompareOperationOp.Eq,
                        left=ast.Constant(value=context.team_id),
                        right=ast.Call(
                            name="JSONExtractInt",
                            args=[ast.Field(chain=["log_comment"]), ast.Constant(value="team_id")],
                        ),
                    ),
                    ast.CompareOperation(
                        op=ast.CompareOperationOp.Eq,
                        left=ast.Constant(value="HogQLQuery"),
                        right=ast.Call(
                            name="JSONExtractString",
                            args=[
                                ast.Field(chain=["log_comment"]),
                                ast.Constant(value="query"),
                                ast.Constant(value="kind"),
                            ],
                        ),
                    ),
                    ast.CompareOperation(
                        op=ast.CompareOperationOp.In,
                        left=ast.Field(chain=["type"]),
                        right=ast.Array(
                            exprs=[
                                ast.Constant(value="QueryFinish"),
                                ast.Constant(value="ExceptionBeforeStart"),
                                ast.Constant(value="ExceptionWhileProcessing"),
                            ]
                        ),
                    ),
                    ast.Field(chain=["is_initial_query"]),
                ]
            ),
        )


class RawQueryLogTable(FunctionCallTable):
    fields: dict[str, FieldOrTable] = RAW_QUERY_LOG_FIELDS

    name: str = "raw_query_log"

    def to_printed_clickhouse(self, context) -> str:
        return "clusterAllReplicas(posthog, system.query_log)"

    def to_printed_hogql(self) -> str:
        return "query_log"
