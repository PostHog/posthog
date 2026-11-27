from dataclasses import replace
from time import monotonic

from posthog.hogql.direct_sql.adapter import (
    DirectQueryRequest,
    DirectQueryResult,
    DirectQueryTimeoutError,
    DirectSQLAdapter,
)
from posthog.hogql.errors import ExposedHogQLError

RESULT_TOO_LARGE = "The result is too large. Narrow the inputs or aggregate the source data."


def _bounded_sql(engine: str, sql: str, schema: DirectQueryResult, byte_limit: int, *, pyformat: bool) -> str:
    from sqlglot import exp

    dialect = {"motherduck": "duckdb", "duckgres": "duckdb"}.get(engine, engine)
    columns = schema.print_columns
    names = [exp.to_identifier(name, quoted=True).sql(dialect=dialect) for name in columns]
    if pyformat:
        names = [name.replace("%", "%%") for name in names]
    used_names = {name.casefold() for name in columns}
    if len(used_names) != len(columns):
        raise ExposedHogQLError("Give each result column a unique name before running this calculation.")
    size_name = "_posthog_result_bytes"
    while size_name in used_names:
        size_name += "_"
    match engine:
        case "postgres":
            row_size = "octet_length(convert_to(row_to_json(source_row)::text, 'UTF8'))"
        case "bigquery":
            row_size = "BYTE_LENGTH(TO_JSON_STRING(source_row))"
        case "snowflake":
            row_size = "OCTET_LENGTH(TO_JSON(OBJECT_CONSTRUCT_KEEP_NULL(source_row.*)))"
        case "motherduck" | "duckgres":
            row_size = "octet_length(encode(CAST(to_json(source_row) AS VARCHAR)))"
        case "mysql":
            row_size = " + ".join(f"COALESCE(OCTET_LENGTH(CAST(source_row.{name} AS BINARY)), 4)" for name in names)
        case "redshift":
            values = [
                f"CAST(source_row.{name} AS VARCHAR)" if column in schema.json_text_columns else f"source_row.{name}"
                for column, name in zip(columns, names, strict=True)
            ]
            row_size = " + ".join(f"JSON_SIZE(OBJECT('v', {value}))" for value in values)
        case "trino":
            row_size = " + ".join(f"COALESCE(length(to_utf8(format('%s', source_row.{name}))), 4)" for name in names)
        case _:
            raise ExposedHogQLError("This connection cannot bound the size of a private result.")
    masked = ", ".join(
        f"CASE WHEN result_rows.{size_name} <= {byte_limit} THEN result_rows.{name} END AS {name}" for name in names
    )
    return (
        f"SELECT {masked}, result_rows.{size_name} FROM ("
        f"SELECT source_row.*, SUM({len(columns)} + {row_size}) OVER () AS {size_name} FROM (\n{sql}\n) AS source_row"
        ") AS result_rows"
    )


def execute_with_result_limit(adapter: DirectSQLAdapter, request: DirectQueryRequest) -> DirectQueryResult:
    limit = request.settings.max_result_bytes
    if limit is None or adapter.engine == "clickhouse":
        return adapter.execute(request)
    started = monotonic()
    # LIMIT 0 obtains driver column names and types even for a native SELECT *.
    schema = adapter.execute(replace(request, sql=f"SELECT * FROM (\n{request.sql}\n) AS source_schema LIMIT 0"))
    if schema.error or not schema.print_columns:
        return schema
    if sum(len(name.encode()) for name in schema.print_columns) > limit:
        raise ExposedHogQLError(RESULT_TOO_LARGE)
    sql = _bounded_sql(
        adapter.engine,
        request.sql,
        schema,
        limit,
        pyformat=bool(request.values) and adapter.engine in {"postgres", "mysql", "redshift", "snowflake"},
    )
    settings = request.settings
    if settings.max_execution_time:
        remaining = int(settings.max_execution_time - (monotonic() - started))
        if remaining <= 0:
            raise DirectQueryTimeoutError("The calculation timed out.")
        settings = settings.model_copy(update={"max_execution_time": remaining})
    result = adapter.execute(replace(request, sql=sql, settings=settings))
    if result.error:
        return result
    if any(int(row[-1]) > limit for row in result.results):
        raise ExposedHogQLError(RESULT_TOO_LARGE)
    return replace(schema, results=[row[:-1] for row in result.results])
