from typing import Any

from posthog.hogql import ast
from posthog.hogql.database.models import (
    BooleanDatabaseField,
    DatabaseField,
    DateDatabaseField,
    DateTimeDatabaseField,
    FieldOrTable,
    IntegerDatabaseField,
    LazyTable,
    LazyTableToAdd,
    StringDatabaseField,
    Table,
)

QUERY_LOG_ARCHIVE_FIELDS: dict[str, FieldOrTable] = {
    "event_date": DateDatabaseField(
        name="event_date", nullable=False, description="Date partition the query was logged under."
    ),
    "event_time": DateTimeDatabaseField(
        name="event_time", nullable=False, description="When the query log entry was written."
    ),
    "query_id": StringDatabaseField(
        name="lc_client_query_id", nullable=False, description="Client-supplied query identifier."
    ),
    "endpoint": StringDatabaseField(
        name="lc_id", nullable=False, description="Identifier of the endpoint/insight that issued the query."
    ),
    "query": StringDatabaseField(name="lc_query__query", nullable=False, description="The executed SQL query text."),
    "query_start_time": DateTimeDatabaseField(
        name="query_start_time", nullable=False, description="When ClickHouse started executing the query."
    ),
    "query_duration_ms": IntegerDatabaseField(
        name="query_duration_ms", nullable=False, description="Total query execution time in milliseconds."
    ),
    "name": StringDatabaseField(
        name="lc_request_name", nullable=False, description="Human-readable name of the originating request."
    ),
    "created_by": IntegerDatabaseField(
        name="lc_user_id", nullable=False, description="ID of the PostHog user who triggered the query."
    ),
    "read_rows": IntegerDatabaseField(
        name="read_rows", nullable=False, description="Number of rows ClickHouse read while executing the query."
    ),
    "read_bytes": IntegerDatabaseField(
        name="read_bytes", nullable=False, description="Number of bytes ClickHouse read while executing the query."
    ),
    "result_rows": IntegerDatabaseField(
        name="result_rows", nullable=False, description="Number of rows returned to the client."
    ),
    "result_bytes": IntegerDatabaseField(
        name="result_bytes", nullable=False, description="Number of bytes returned to the client."
    ),
    "memory_usage": IntegerDatabaseField(
        name="memory_usage", nullable=False, description="Peak memory used by the query in bytes."
    ),
    "status": StringDatabaseField(
        name="type",
        nullable=False,
        description="Query outcome type, e.g. 'QueryFinish' or 'ExceptionWhileProcessing'.",
    ),
    "exception_code": IntegerDatabaseField(
        name="exception_code", nullable=False, description="ClickHouse exception code if the query failed, else 0."
    ),
    "exception_name": StringDatabaseField(
        name="exception_name", nullable=False, description="ClickHouse exception name if the query failed."
    ),
    "is_personal_api_key_request": BooleanDatabaseField(
        name="is_personal_api_key_request",
        nullable=False,
        description="True if the query was issued via a personal API key.",
    ),
    "api_key_label": StringDatabaseField(
        name="lc_api_key_label", nullable=False, description="Label of the API key used, if any."
    ),
    "api_key_mask": StringDatabaseField(
        name="lc_api_key_mask", nullable=False, description="Masked value of the API key used, if any."
    ),
    "cpu_microseconds": IntegerDatabaseField(
        name="ProfileEvents_OSCPUVirtualTimeMicroseconds",
        nullable=False,
        description="CPU time consumed by the query in microseconds.",
    ),
    "RealTimeMicroseconds": IntegerDatabaseField(
        name="ProfileEvents_RealTimeMicroseconds",
        nullable=False,
        description="Wall-clock time consumed by the query in microseconds.",
    ),
    "S3ListObjects": IntegerDatabaseField(
        name="ProfileEvents_S3ListObjects", nullable=False, description="Count of S3 ListObjects calls made."
    ),
    "S3HeadObject": IntegerDatabaseField(
        name="ProfileEvents_S3HeadObject", nullable=False, description="Count of S3 HeadObject calls made."
    ),
    "S3GetObjectAttributes": IntegerDatabaseField(
        name="ProfileEvents_S3GetObjectAttributes",
        nullable=False,
        description="Count of S3 GetObjectAttributes calls made.",
    ),
    "S3GetObject": IntegerDatabaseField(
        name="ProfileEvents_S3GetObject", nullable=False, description="Count of S3 GetObject calls made."
    ),
    "ReadBufferFromS3Bytes": IntegerDatabaseField(
        name="ProfileEvents_ReadBufferFromS3Bytes", nullable=False, description="Bytes read from S3 by the query."
    ),
    # "cost_usd": FloatDatabaseField(name="cost_usd", nullable=False),
}


class QueryLogArchiveTable(LazyTable):
    description: str = (
        "Archived ClickHouse query log for analyzing query performance and cost. One row per executed query, "
        "with friendly column aliases over the raw log; impersonated requests are excluded."
    )
    fields: dict[str, FieldOrTable] = QUERY_LOG_ARCHIVE_FIELDS

    def to_printed_clickhouse(self, context) -> str:
        return "query_log_archive"

    def to_printed_hogql(self) -> str:
        return "query_log"

    def lazy_select(self, table_to_add: LazyTableToAdd, context, node) -> Any:
        requested_fields = table_to_add.fields_accessed

        table_name = "raw_query_log"

        def get_alias(name, chain):
            if name == "endpoint":
                return ast.Alias(alias=name, expr=ast.Field(chain=[table_name, "lc_id"]))
            elif name == "query":
                return ast.Alias(alias=name, expr=ast.Field(chain=[table_name, "lc_query__query"]))
            elif name == "created_by":
                return ast.Alias(alias=name, expr=ast.Field(chain=[table_name, "lc_user_id"]))
            elif name == "status":
                return ast.Alias(alias=name, expr=ast.Field(chain=[table_name, "type"]))
            elif name == "is_personal_api_key_request":
                cmp_expr = ast.CompareOperation(
                    op=ast.CompareOperationOp.Eq,
                    left=ast.Constant(value="personal_api_key"),
                    right=ast.Field(chain=[table_name, "lc_access_method"]),
                )
                return ast.Alias(alias=name, expr=cmp_expr)
            elif name == "cost_usd":
                cost_cpu = ast.ArithmeticOperation(
                    left=ast.Field(chain=[table_name, "ProfileEvents_OSCPUVirtualTimeMicroseconds"]),
                    right=ast.Constant(value=0.000000001),
                    op=ast.ArithmeticOperationOp.Mult,
                )
                cost_bytes = ast.ArithmeticOperation(
                    left=ast.Field(chain=[table_name, "read_bytes"]),
                    right=ast.Constant(value=0.000000000005),  # $5 per TB
                    op=ast.ArithmeticOperationOp.Mult,
                )
                cost_ex = ast.ArithmeticOperation(
                    left=cost_cpu,
                    right=cost_bytes,
                    op=ast.ArithmeticOperationOp.Add,
                )
                return ast.Alias(alias=name, expr=cost_ex)
            else:
                field = QUERY_LOG_ARCHIVE_FIELDS[name]
                if field and isinstance(field, DatabaseField):
                    return ast.Alias(alias=name, expr=ast.Field(chain=[table_name, field.name]))
                return ast.Alias(alias=name, expr=ast.Field(chain=[table_name, *chain]))

        fields: list[ast.Expr] = [get_alias(name, chain) for name, chain in requested_fields.items()]

        where_clause = ast.Not(expr=ast.Field(chain=[table_name, "lc_is_impersonated"]))

        return ast.SelectQuery(
            select=fields,
            select_from=ast.JoinExpr(table=ast.Field(chain=[table_name])),
            where=where_clause,
        )


class RawQueryLogArchiveTable(Table):
    description: str = (
        "Raw archived ClickHouse query log, exposing the underlying `lc_*` columns directly. "
        "Prefer the `query_log` table, which provides friendly aliases and filters out impersonated requests."
    )
    fields: dict[str, FieldOrTable] = {
        "event_date": DateDatabaseField(name="event_date", nullable=False),
        "event_time": DateTimeDatabaseField(name="event_time", nullable=False),
        "team_id": IntegerDatabaseField(name="team_id", nullable=False),
        "query_id": StringDatabaseField(
            name="query_id", nullable=False, description="ClickHouse-assigned query identifier."
        ),
        "lc_client_query_id": StringDatabaseField(
            name="lc_client_query_id", nullable=False, description="Client-supplied query identifier."
        ),
        "lc_id": StringDatabaseField(
            name="lc_id", nullable=False, description="Identifier of the endpoint/insight that issued the query."
        ),
        "lc_query__query": StringDatabaseField(
            name="lc_query__query", nullable=False, description="The executed SQL query text."
        ),
        "query_start_time": DateTimeDatabaseField(name="query_start_time", nullable=False),
        "query_duration_ms": IntegerDatabaseField(name="query_duration_ms", nullable=False),
        "lc_name": StringDatabaseField(name="lc_name", nullable=False),
        "lc_request_name": StringDatabaseField(name="lc_request_name", nullable=False),
        "lc_user_id": IntegerDatabaseField(
            name="lc_user_id", nullable=False, description="ID of the PostHog user who triggered the query."
        ),
        "read_rows": IntegerDatabaseField(name="read_rows", nullable=False),
        "read_bytes": IntegerDatabaseField(name="read_bytes", nullable=False),
        "result_rows": IntegerDatabaseField(name="result_rows", nullable=False),
        "result_bytes": IntegerDatabaseField(name="result_bytes", nullable=False),
        "memory_usage": IntegerDatabaseField(name="memory_usage", nullable=False),
        "type": StringDatabaseField(
            name="type",
            nullable=False,
            description="Query outcome type, e.g. 'QueryFinish' or 'ExceptionWhileProcessing'.",
        ),
        "exception_code": IntegerDatabaseField(name="exception_code", nullable=False),
        "exception_name": StringDatabaseField(name="exception_name", nullable=False),
        "lc_access_method": StringDatabaseField(
            name="lc_access_method",
            nullable=False,
            description="How the query was authenticated, e.g. 'personal_api_key'.",
        ),
        "lc_is_impersonated": BooleanDatabaseField(
            name="lc_is_impersonated",
            nullable=False,
            description="True if the request was made via staff impersonation.",
        ),
        "lc_api_key_label": StringDatabaseField(name="lc_api_key_label", nullable=False),
        "lc_api_key_mask": StringDatabaseField(name="lc_api_key_mask", nullable=False),
        "lc_query__kind": StringDatabaseField(name="lc_query__kind", nullable=False),
        "ProfileEvents_OSCPUVirtualTimeMicroseconds": IntegerDatabaseField(
            name="ProfileEvents_OSCPUVirtualTimeMicroseconds", nullable=False
        ),
        "ProfileEvents_RealTimeMicroseconds": IntegerDatabaseField(
            name="ProfileEvents_RealTimeMicroseconds", nullable=False
        ),
        "ProfileEvents_S3ListObjects": IntegerDatabaseField(name="ProfileEvents_S3ListObjects", nullable=False),
        "ProfileEvents_S3HeadObject": IntegerDatabaseField(name="ProfileEvents_S3HeadObject", nullable=False),
        "ProfileEvents_S3GetObjectAttributes": IntegerDatabaseField(
            name="ProfileEvents_S3GetObjectAttributes", nullable=False
        ),
        "ProfileEvents_S3GetObject": IntegerDatabaseField(name="ProfileEvents_S3GetObject", nullable=False),
        "ProfileEvents_ReadBufferFromS3Bytes": IntegerDatabaseField(
            name="ProfileEvents_ReadBufferFromS3Bytes", nullable=False
        ),
    }

    def to_printed_clickhouse(self, context) -> str:
        return "query_log_archive"

    def to_printed_hogql(self) -> str:
        return "raw_query_log"
