from typing import TYPE_CHECKING, cast

import pymysql
import sqlparse
from opentelemetry import trace
from pymysql.constants import FIELD_TYPE as MYSQL_FIELD_TYPE
from sqlparse import tokens as sqlparse_tokens
from sqlparse.sql import Statement

from posthog.hogql.constants import HogQLDialect
from posthog.hogql.direct_sql.adapter import DirectQueryRequest, DirectQueryResult
from posthog.hogql.direct_sql.raw_sql import ensure_single_direct_statement
from posthog.hogql.errors import ExposedHogQLError

if TYPE_CHECKING:
    from posthog.models.team import Team

    from products.warehouse_sources.backend.facade.models import ExternalDataSource
    from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import MySQLSourceConfig
    from products.warehouse_sources.backend.temporal.data_imports.sources.mysql.mysql import MySQLImplementation

DIRECT_MYSQL_DEFAULT_STATEMENT_TIMEOUT_SECONDS = 600
RAW_MYSQL_READ_ONLY_ERROR = "Raw MySQL queries must be read-only SELECT statements."

MYSQL_FIELD_TYPE_TO_CLICKHOUSE_TYPE: dict[int, str] = {
    MYSQL_FIELD_TYPE.TINY: "Int8",
    MYSQL_FIELD_TYPE.SHORT: "Int16",
    MYSQL_FIELD_TYPE.INT24: "Int32",
    MYSQL_FIELD_TYPE.LONG: "Int32",
    MYSQL_FIELD_TYPE.LONGLONG: "Int64",
    MYSQL_FIELD_TYPE.YEAR: "Int32",
    MYSQL_FIELD_TYPE.FLOAT: "Float32",
    MYSQL_FIELD_TYPE.DOUBLE: "Float64",
    MYSQL_FIELD_TYPE.DECIMAL: "Decimal",
    MYSQL_FIELD_TYPE.NEWDECIMAL: "Decimal",
    MYSQL_FIELD_TYPE.DATE: "Date",
    MYSQL_FIELD_TYPE.NEWDATE: "Date",
    MYSQL_FIELD_TYPE.DATETIME: "DateTime",
    MYSQL_FIELD_TYPE.TIMESTAMP: "DateTime",
    MYSQL_FIELD_TYPE.TIME: "String",
    MYSQL_FIELD_TYPE.BIT: "String",
    MYSQL_FIELD_TYPE.JSON: "String",
    MYSQL_FIELD_TYPE.ENUM: "String",
    MYSQL_FIELD_TYPE.SET: "String",
    MYSQL_FIELD_TYPE.TINY_BLOB: "String",
    MYSQL_FIELD_TYPE.MEDIUM_BLOB: "String",
    MYSQL_FIELD_TYPE.LONG_BLOB: "String",
    MYSQL_FIELD_TYPE.BLOB: "String",
    MYSQL_FIELD_TYPE.VAR_STRING: "String",
    MYSQL_FIELD_TYPE.VARCHAR: "String",
    MYSQL_FIELD_TYPE.STRING: "String",
    MYSQL_FIELD_TYPE.GEOMETRY: "String",
}


def mysql_field_type_to_clickhouse_type(type_code: int | None) -> str:
    if type_code is None:
        return "String"
    return MYSQL_FIELD_TYPE_TO_CLICKHOUSE_TYPE.get(type_code, "String")


def mysql_error_to_message(error: Exception) -> str:
    if isinstance(error, pymysql.MySQLError):
        args = error.args
        if len(args) >= 2 and isinstance(args[1], str) and args[1].strip():
            return args[1].strip().splitlines()[0]

    message = str(error).strip()
    if not message:
        return "MySQL query failed."
    return message.splitlines()[0]


def _is_executable_mysql_comment(value: str) -> bool:
    normalized = value.lstrip().upper()
    return normalized.startswith("/*!") or normalized.startswith("/*M!")


def _raw_mysql_token_values(statement: Statement) -> list[str]:
    token_values: list[str] = []
    for token in statement.flatten():
        if token.ttype in sqlparse_tokens.Comment:
            if _is_executable_mysql_comment(token.value):
                raise ExposedHogQLError(RAW_MYSQL_READ_ONLY_ERROR)
            continue
        if token.is_whitespace or token.ttype in sqlparse_tokens.Literal.String:
            continue
        value = token.value.strip().upper()
        if value:
            token_values.append(value)
    return token_values


def ensure_read_only_raw_mysql_statement(sql: str) -> str:
    sql = ensure_single_direct_statement(sql)
    statements = [statement for statement in sqlparse.parse(sql) if str(statement).strip(" \t\r\n;")]
    if len(statements) != 1 or statements[0].get_type() != "SELECT":
        raise ExposedHogQLError(RAW_MYSQL_READ_ONLY_ERROR)

    token_values = _raw_mysql_token_values(statements[0])
    for index, value in enumerate(token_values):
        normalized_value = value.strip("`")
        if value == "INTO":
            raise ExposedHogQLError(RAW_MYSQL_READ_ONLY_ERROR)
        if normalized_value == "LOAD_FILE" and index + 1 < len(token_values) and token_values[index + 1] == "(":
            raise ExposedHogQLError(RAW_MYSQL_READ_ONLY_ERROR)
        if value == "FOR" and index + 1 < len(token_values) and token_values[index + 1] in {"UPDATE", "SHARE"}:
            raise ExposedHogQLError(RAW_MYSQL_READ_ONLY_ERROR)
        if token_values[index : index + 4] == ["LOCK", "IN", "SHARE", "MODE"]:
            raise ExposedHogQLError(RAW_MYSQL_READ_ONLY_ERROR)

    return sql


class MySQLAdapter:
    engine = "mysql"
    dialect: HogQLDialect | None = "mysql"

    def validate_source_config(
        self, source: "ExternalDataSource", team: "Team"
    ) -> tuple["MySQLImplementation", "MySQLSourceConfig"]:
        from products.warehouse_sources.backend.facade.types import ExternalDataSourceType
        from products.warehouse_sources.backend.temporal.data_imports.sources import SourceRegistry
        from products.warehouse_sources.backend.temporal.data_imports.sources.mysql.source import MySQLSource

        if not source.is_direct_mysql:
            raise ExposedHogQLError("Invalid direct MySQL connection.")

        mysql_source = cast(MySQLSource, SourceRegistry.get_source(ExternalDataSourceType.MYSQL))
        config = mysql_source.parse_config(source.job_inputs or {})

        is_ssh_valid, ssh_valid_errors = mysql_source.ssh_tunnel_is_valid(config, team.pk)
        if not is_ssh_valid:
            raise ExposedHogQLError(ssh_valid_errors or "Invalid SSH tunnel configuration.")

        valid_host, host_errors = mysql_source.is_database_host_valid(
            config.host, team.pk, using_ssh_tunnel=config.ssh_tunnel.enabled if config.ssh_tunnel else False
        )
        if not valid_host:
            raise ExposedHogQLError(host_errors or "Invalid MySQL host.")

        return mysql_source.get_implementation, config

    def prepare_raw_sql(self, sql: str) -> str:
        return ensure_read_only_raw_mysql_statement(sql)

    def execute(self, request: DirectQueryRequest) -> DirectQueryResult:
        source = request.source
        mysql_implementation, source_config = self.validate_source_config(source, request.team)
        settings = request.settings
        statement_timeout_seconds = max(
            settings.max_execution_time or DIRECT_MYSQL_DEFAULT_STATEMENT_TIMEOUT_SECONDS, 1
        )

        span = trace.get_current_span()
        span.set_attribute("team_id", request.team.pk)
        span.set_attribute("query_type", request.query_type)
        span.set_attribute("source_id", str(source.id))

        try:
            with request.timings.measure("mysql_execute"):
                with mysql_implementation.connect(source_config, read_timeout=statement_timeout_seconds) as connection:
                    with connection.cursor() as cursor:
                        try:
                            # MySQL 8 only and SELECT-only; MariaDB uses a different variable.
                            # The read_timeout above is the backstop if this is unavailable.
                            cursor.execute(f"SET SESSION MAX_EXECUTION_TIME = {statement_timeout_seconds * 1000}")
                        except pymysql.MySQLError:
                            pass
                        cursor.execute("START TRANSACTION READ ONLY")
                        cursor.execute(  # nosemgrep: python.django.security.injection.sql.sql-injection-using-db-cursor-execute.sql-injection-db-cursor-execute
                            request.sql, request.values or None
                        )
                        results = cursor.fetchall()
                        description = cursor.description or []
        except (pymysql.MySQLError, ExposedHogQLError) as error:
            span.set_attribute("error_type", error.__class__.__name__)
            if request.debug:
                return DirectQueryResult(results=[], types=[], print_columns=[], error=mysql_error_to_message(error))
            raise ExposedHogQLError(mysql_error_to_message(error)) from error

        span.set_attribute("row_count", len(results))
        types: list[tuple[str, str]] = [
            (column[0], mysql_field_type_to_clickhouse_type(column[1])) for column in description
        ]
        print_columns = [column[0] for column in description]
        return DirectQueryResult(results=list(results), types=types, print_columns=print_columns)
