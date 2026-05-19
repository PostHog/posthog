from __future__ import annotations

import os
import re
import hmac
import json
import zlib
import struct
import asyncio
import logging
import secrets
import ipaddress
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from django.utils import timezone

import sqlparse
from rest_framework.exceptions import AuthenticationFailed

from posthog.schema import DatabaseSchemaField, DatabaseSerializedFieldType, HogQLQueryResponse

from posthog.hogql.constants import LimitContext
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.errors import ExposedHogQLError, QueryError, ResolutionError
from posthog.hogql.escape_sql import escape_hogql_string
from posthog.hogql.parser import CacheOrigin, parse_select
from posthog.hogql.query import create_default_modifiers_for_team, execute_hogql_query
from posthog.hogql.user_query_validator import validate_user_query

from posthog.auth import PersonalAPIKeyAuthentication
from posthog.constants import AvailableFeature
from posthog.models import OrganizationMembership, Team, User
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.user_permissions import UserPermissions

logger = logging.getLogger(__name__)

PROTOCOL_VERSION_3 = 196608
SSL_REQUEST_CODE = 80877103
GSSENC_REQUEST_CODE = 80877104
CANCEL_REQUEST_CODE = 80877102
MAX_STARTUP_PACKET_BYTES = 64 * 1024
MAX_UNAUTHENTICATED_MESSAGE_BYTES = 64 * 1024

AUTHENTICATION_OK = 0
AUTHENTICATION_CLEARTEXT_PASSWORD = 3

POSTGRES_TEXT_OID = 25
POSTGRES_INT8_OID = 20
POSTGRES_INT4_OID = 23
POSTGRES_INT2_OID = 21
POSTGRES_BOOL_OID = 16
POSTGRES_FLOAT4_OID = 700
POSTGRES_FLOAT8_OID = 701
POSTGRES_NUMERIC_OID = 1700
POSTGRES_DATE_OID = 1082
POSTGRES_TIMESTAMP_OID = 1114
POSTGRES_TIMESTAMPTZ_OID = 1184
POSTGRES_JSON_OID = 114
POSTGRES_UUID_OID = 2950

SQLSTATE_INVALID_PASSWORD = "28P01"
SQLSTATE_INSUFFICIENT_PRIVILEGE = "42501"
SQLSTATE_SYNTAX_ERROR = "42601"
SQLSTATE_PROTOCOL_VIOLATION = "08P01"
SQLSTATE_INTERNAL_ERROR = "XX000"


class HogQLServiceError(Exception):
    sqlstate = SQLSTATE_INTERNAL_ERROR
    query: str | None

    def __init__(self, message: str, *, query: str | None = None):
        super().__init__(message)
        self.query = query


class HogQLServiceAuthenticationError(HogQLServiceError):
    sqlstate = SQLSTATE_INVALID_PASSWORD


class HogQLServicePermissionError(HogQLServiceError):
    sqlstate = SQLSTATE_INSUFFICIENT_PRIVILEGE


class HogQLServiceQueryError(HogQLServiceError):
    sqlstate = SQLSTATE_SYNTAX_ERROR


class HogQLServiceProtocolError(HogQLServiceError):
    sqlstate = SQLSTATE_PROTOCOL_VIOLATION


@dataclass(frozen=True)
class HogQLServiceConfig:
    host: str = "127.0.0.1"
    port: int = 6543
    shared_secret: str | None = None
    max_query_bytes: int = 1024 * 1024

    @classmethod
    def from_env(cls) -> HogQLServiceConfig:
        return cls(
            host=os.environ.get("HOGQL_SERVICE_HOST", "127.0.0.1"),
            port=int(os.environ.get("HOGQL_SERVICE_PORT", "6543")),
            shared_secret=os.environ.get("HOGQL_SERVICE_SHARED_SECRET") or None,
            max_query_bytes=int(os.environ.get("HOGQL_SERVICE_MAX_QUERY_BYTES", str(1024 * 1024))),
        )


@dataclass(frozen=True)
class HogQLServiceDatabaseTarget:
    raw_database: str
    team: Team
    connection_id: str | None = None


@dataclass(frozen=True)
class HogQLServiceSessionContext:
    database_user: str
    database: str
    user: User
    team: Team
    authenticated_by: Literal["shared_secret", "personal_api_key"]
    connection_id: str | None = None
    personal_api_key_id: str | None = None


@dataclass(frozen=True)
class ResultColumn:
    name: str
    type_oid: int = POSTGRES_TEXT_OID
    type_size: int = -1
    type_modifier: int = -1
    format_code: int = 0


@dataclass(frozen=True)
class QueryResult:
    columns: list[ResultColumn]
    rows: list[tuple[Any, ...]]
    command_tag: str


@dataclass(frozen=True)
class PgParameter:
    value: Any


@dataclass(frozen=True)
class CatalogTable:
    oid: int
    schema: str
    name: str
    hogql_name: str
    table_type: str
    fields: list[DatabaseSchemaField]


@dataclass
class PreparedStatement:
    name: str
    query: str
    parameter_type_oids: list[int]


@dataclass
class BoundPortal:
    name: str
    statement_name: str
    query: str
    parameters: list[PgParameter]
    result_formats: list[int]
    result: QueryResult | None = None
    row_description_sent: bool = False


class HogQLServiceAuthenticator:
    def __init__(self, shared_secret: str | None = None):
        self.shared_secret = shared_secret

    def authenticate(self, database_user: str, database: str, password: str) -> HogQLServiceSessionContext:
        database_target = self._get_database_target(database)

        if self.shared_secret and hmac.compare_digest(password, self.shared_secret):
            user = self._get_database_user(database_user)
            self._validate_user_team_access(user, database_target.team)
            return HogQLServiceSessionContext(
                database_user=database_user,
                database=database_target.raw_database,
                user=user,
                team=database_target.team,
                authenticated_by="shared_secret",
                connection_id=database_target.connection_id,
            )

        personal_api_key = self._validate_personal_api_key(password)
        user = personal_api_key.user
        if user is None:
            raise HogQLServiceAuthenticationError("Invalid personal API key.")
        if not self._database_user_matches_user(database_user, user):
            raise HogQLServiceAuthenticationError("Database user does not match the personal API key owner.")

        self._validate_personal_api_key_access(personal_api_key, database_target.team)
        self._validate_user_team_access(user, database_target.team)
        self._mark_personal_api_key_used(personal_api_key)
        return HogQLServiceSessionContext(
            database_user=database_user,
            database=database_target.raw_database,
            user=user,
            team=database_target.team,
            authenticated_by="personal_api_key",
            connection_id=database_target.connection_id,
            personal_api_key_id=personal_api_key.id,
        )

    def _get_database_target(self, database: str) -> HogQLServiceDatabaseTarget:
        normalized_database = database.strip()
        team_id, connection_id = parse_database_name(normalized_database)
        team = self._get_team(team_id)
        if connection_id is not None:
            self._validate_connection_id(team, connection_id)
        return HogQLServiceDatabaseTarget(
            raw_database=normalized_database,
            team=team,
            connection_id=connection_id,
        )

    def _get_team(self, team_id: str) -> Team:
        try:
            parsed_team_id = int(team_id)
        except ValueError as error:
            raise HogQLServiceAuthenticationError(
                "Database must be a PostHog team_id or team_id/connection_id."
            ) from error

        try:
            return Team.objects.select_related("organization").get(pk=parsed_team_id)
        except Team.DoesNotExist as error:
            raise HogQLServiceAuthenticationError(
                "Database must be a PostHog team_id or team_id/connection_id."
            ) from error

    def _validate_connection_id(self, team: Team, connection_id: str) -> None:
        try:
            source_uuid = UUID(connection_id)
        except ValueError as error:
            raise HogQLServiceAuthenticationError("Connection id must be a valid UUID.") from error

        from products.data_warehouse.backend.models import ExternalDataSource

        source = (
            ExternalDataSource.objects.filter(
                team_id=team.pk,
                id=source_uuid,
                access_method=ExternalDataSource.AccessMethod.DIRECT,
            )
            .exclude(deleted=True)
            .first()
        )
        if source is None:
            raise HogQLServiceAuthenticationError("Connection id is invalid for this team.")
        if not source.is_direct_postgres:
            raise HogQLServiceAuthenticationError("Connection id must reference a direct Postgres connection.")

    def _get_database_user(self, database_user: str) -> User:
        username = database_user.strip()
        if not username:
            raise HogQLServiceAuthenticationError("Database user is required.")

        user = self._find_database_user(username)
        if user is None or not user.is_active:
            raise HogQLServiceAuthenticationError("Database user is invalid.")
        return user

    def _find_database_user(self, username: str) -> User | None:
        if username.isdecimal():
            user = User.objects.filter(is_active=True, pk=int(username)).first()
            if user is not None:
                return user

        try:
            user_uuid = UUID(username)
        except ValueError:
            user_uuid = None

        if user_uuid is not None:
            user = User.objects.filter(is_active=True, uuid=user_uuid).first()
            if user is not None:
                return user

        try:
            return User.objects.get_by_natural_key(username)
        except User.DoesNotExist:
            return None

    def _validate_personal_api_key(self, password: str) -> PersonalAPIKey:
        try:
            return PersonalAPIKeyAuthentication.validate_key((password, PersonalAPIKeyAuthentication.SOURCE_HEADER))
        except AuthenticationFailed as error:
            raise HogQLServiceAuthenticationError("Invalid personal API key.") from error

    def _validate_personal_api_key_access(self, personal_api_key: PersonalAPIKey, team: Team) -> None:
        scopes = personal_api_key.scopes or []
        if "*" not in scopes and "query:read" not in scopes and "query:write" not in scopes:
            raise HogQLServicePermissionError("Personal API key is missing the query:read scope.")

        scoped_teams = personal_api_key.scoped_teams or []
        if scoped_teams and team.id not in scoped_teams:
            raise HogQLServicePermissionError("Personal API key does not have access to this project.")

        scoped_organizations = personal_api_key.scoped_organizations or []
        if scoped_organizations and str(team.organization_id) not in scoped_organizations:
            raise HogQLServicePermissionError("Personal API key does not have access to this organization.")

        organization = team.organization
        if not organization.is_feature_available(AvailableFeature.ORGANIZATION_SECURITY_SETTINGS):
            return

        membership = OrganizationMembership.objects.filter(
            user=personal_api_key.user, organization=organization
        ).first()
        if (
            membership is not None
            and not organization.members_can_use_personal_api_keys
            and membership.level < OrganizationMembership.Level.ADMIN
        ):
            raise HogQLServicePermissionError(
                f"Organization '{organization.name}' does not allow using personal API keys."
            )

    def _validate_user_team_access(self, user: User, team: Team) -> None:
        membership_level = UserPermissions(user, team=team).current_team.effective_membership_level
        if membership_level is None:
            raise HogQLServicePermissionError("Database user does not have access to this project.")

    def _mark_personal_api_key_used(self, personal_api_key: PersonalAPIKey) -> None:
        now = timezone.now()
        if personal_api_key.last_used_at is None or now - personal_api_key.last_used_at > timedelta(hours=1):
            personal_api_key.last_used_at = now
            personal_api_key.save(update_fields=["last_used_at"])

    def _database_user_matches_user(self, database_user: str, user: User) -> bool:
        username = database_user.strip()
        if username == str(user.pk) or username == str(user.uuid):
            return True
        return username.casefold() == user.email.casefold()


def _setting_values(context: HogQLServiceSessionContext) -> dict[str, str]:
    return {
        "server_version": "16.0 (PostHog HogQL service)",
        "server_version_num": "160000",
        "server_encoding": "UTF8",
        "client_encoding": "UTF8",
        "datestyle": "ISO, MDY",
        "standard_conforming_strings": "on",
        "integer_datetimes": "on",
        "timezone": context.team.timezone,
        "transaction_isolation": "read committed",
        "default_transaction_read_only": "on",
        "search_path": "public",
        "statement_timeout": "0",
        "lock_timeout": "0",
        "idle_in_transaction_session_timeout": "0",
        "extra_float_digits": "1",
    }


class HogQLServiceQueryExecutor:
    def execute(self, sql: str, context: HogQLServiceSessionContext) -> QueryResult:
        stripped_sql = sql.strip()
        if not stripped_sql:
            return QueryResult(columns=[], rows=[], command_tag="")

        builtin_result = self._execute_builtin_query(stripped_sql, context)
        if builtin_result is not None:
            return builtin_result

        hogql_sql = rewrite_catalog_table_references(
            rewrite_postgres_pseudo_columns(strip_public_schema_references(stripped_sql)),
            context,
        )
        try:
            query_ast = parse_select(hogql_sql, cache_origin=CacheOrigin.USER)
            validate_user_query(query_ast, team=context.team)
            response = execute_hogql_query(
                query=query_ast,
                team=context.team,
                user=context.user,
                query_type="hogql_service",
                limit_context=LimitContext.QUERY,
                connection_id=context.connection_id,
                pretty=False,
            )
        except (ExposedHogQLError, QueryError, ResolutionError, ValueError) as error:
            raise HogQLServiceQueryError(str(error), query=stripped_sql) from error

        if response.error:
            raise HogQLServiceQueryError(response.error, query=stripped_sql)

        return self._response_to_query_result(response)

    def _response_to_query_result(self, response: HogQLQueryResponse) -> QueryResult:
        rows = [tuple(row) if isinstance(row, (list, tuple)) else (row,) for row in response.results or []]
        columns = self._response_columns(response)
        return QueryResult(columns=columns, rows=rows, command_tag=f"SELECT {len(rows)}")

    def _response_columns(self, response: HogQLQueryResponse) -> list[ResultColumn]:
        if response.types:
            return [
                ResultColumn(name=name, type_oid=clickhouse_type_to_postgres_oid(clickhouse_type))
                for name, clickhouse_type in response.types
            ]

        return [ResultColumn(name=column) for column in response.columns or []]

    def _execute_builtin_query(self, sql: str, context: HogQLServiceSessionContext) -> QueryResult | None:
        normalized = normalize_sql(sql)

        if normalized in {"begin", "start transaction"}:
            return QueryResult(columns=[], rows=[], command_tag="BEGIN")
        if normalized in {"commit", "end"}:
            return QueryResult(columns=[], rows=[], command_tag="COMMIT")
        if normalized == "rollback":
            return QueryResult(columns=[], rows=[], command_tag="ROLLBACK")
        if normalized.startswith("set ") or normalized.startswith("reset ") or normalized.startswith("discard "):
            return QueryResult(columns=[], rows=[], command_tag="SET")
        if normalized == "show all":
            rows = [(name, value, "") for name, value in _setting_values(context).items()]
            return QueryResult(
                columns=[ResultColumn(name="name"), ResultColumn(name="setting"), ResultColumn(name="description")],
                rows=rows,
                command_tag=f"SHOW {len(rows)}",
            )

        compatibility_select = self._compatibility_select(normalized)
        if compatibility_select is not None:
            columns, rows = compatibility_select
            return QueryResult(
                columns=[
                    ResultColumn(name=column, type_oid=python_value_to_postgres_oid(row_value(rows, column_index)))
                    for column_index, column in enumerate(columns)
                ],
                rows=rows,
                command_tag=f"SELECT {len(rows)}",
            )

        show_value = self._show_value(normalized, context)
        if show_value is not None:
            parameter_name, value = show_value
            return QueryResult(
                columns=[ResultColumn(name=parameter_name)],
                rows=[(value,)],
                command_tag="SHOW",
            )

        catalog_result = self._catalog_query(sql, normalized, context)
        if catalog_result is not None:
            return catalog_result

        builtin_select = self._builtin_select(normalized, context)
        if builtin_select is not None:
            columns, rows = builtin_select
            return QueryResult(
                columns=[
                    ResultColumn(name=column, type_oid=python_value_to_postgres_oid(row_value(rows, column_index)))
                    for column_index, column in enumerate(columns)
                ],
                rows=rows,
                command_tag=f"SELECT {len(rows)}",
            )

        return None

    def _show_value(self, normalized: str, context: HogQLServiceSessionContext) -> tuple[str, str] | None:
        values = _setting_values(context)
        match = re.fullmatch(r"show\s+([a-zA-Z_][a-zA-Z0-9_]*|transaction\s+isolation\s+level)", normalized)
        if not match:
            return None
        parameter_name = match.group(1).replace(" ", "_")
        if parameter_name == "transaction_isolation_level":
            parameter_name = "transaction_isolation"
        value = values.get(parameter_name)
        if value is None:
            return None
        return parameter_name, value

    def _builtin_select(
        self, normalized: str, context: HogQLServiceSessionContext
    ) -> tuple[list[str], list[tuple[Any, ...]]] | None:
        no_from_select = self._builtin_no_from_select(normalized, context)
        if no_from_select is not None:
            return no_from_select

        if normalized in {"select version()", "select pg_catalog.version()"}:
            return ["version"], [("PostgreSQL 16.0 compatible PostHog HogQL service",)]
        if normalized in {"select current_database()", "select pg_catalog.current_database()"}:
            return ["current_database"], [(context.database,)]
        if normalized in {"select current_catalog"}:
            return ["current_catalog"], [(context.database,)]
        if normalized in {"select current_schema()", "select pg_catalog.current_schema()", "select current_schema"}:
            return ["current_schema"], [("public",)]
        if normalized in {"select current_schemas(false)", "select pg_catalog.current_schemas(false)"}:
            return ["current_schemas"], [(["public"],)]
        if normalized in {"select current_schemas(true)", "select pg_catalog.current_schemas(true)"}:
            return ["current_schemas"], [(["pg_catalog", "public"],)]
        if normalized in {"select current_user", "select session_user"}:
            return ["current_user"], [(context.database_user,)]
        if normalized in {"select pg_backend_pid()", "select pg_catalog.pg_backend_pid()"}:
            return ["pg_backend_pid"], [(os.getpid(),)]

        current_setting_match = re.fullmatch(
            r"select\s+(?:pg_catalog\.)?current_setting\('([^']+)'(?:,\s*true)?\)",
            normalized,
        )
        if current_setting_match:
            setting_name = current_setting_match.group(1).replace(" ", "_")
            return ["current_setting"], [(_setting_values(context).get(setting_name),)]
        return None

    def _builtin_no_from_select(
        self, normalized: str, context: HogQLServiceSessionContext
    ) -> tuple[list[str], list[tuple[Any, ...]]] | None:
        if not normalized.startswith("select ") or find_top_level_keyword(normalized, "from") is not None:
            return None

        select_items = [parse_select_item(item) for item in split_top_level_commas(normalized.removeprefix("select "))]
        values: list[Any] = []
        for expression, _label in select_items:
            value = evaluate_builtin_expression(expression, context)
            if value is UNHANDLED_BUILTIN_EXPRESSION:
                return None
            values.append(value)
        return [label for _expression, label in select_items], [tuple(values)]

    def _compatibility_select(self, normalized: str) -> tuple[list[str], list[tuple[Any, ...]]] | None:
        timestamp_sources = (
            r"now\(\)|current_timestamp|transaction_timestamp\(\)|statement_timestamp\(\)|clock_timestamp\(\)"
        )
        if re.match(r"select\s+round\s*\(\s*extract\s*\(\s*epoch\s+from\b", normalized):
            return ["round"], [(round(timezone.now().timestamp() * 1000),)]
        if re.match(r"select\s+extract\s*\(\s*epoch\s+from\b", normalized):
            return ["extract"], [(timezone.now().timestamp(),)]
        if re.fullmatch(
            rf"select\s+round\(extract\(epoch\s+from\s+({timestamp_sources})\)\s*\*\s*1000\)",
            normalized,
        ):
            return ["round"], [(round(timezone.now().timestamp() * 1000),)]
        if re.fullmatch(rf"select\s+extract\(epoch\s+from\s+({timestamp_sources})\)", normalized):
            return ["extract"], [(timezone.now().timestamp(),)]
        return None

    def _catalog_query(self, sql: str, normalized: str, context: HogQLServiceSessionContext) -> QueryResult | None:
        source = catalog_source(normalized)
        if source is None:
            return None

        rows, default_columns = self._catalog_rows(source, context)
        rows = filter_catalog_rows(rows, normalized)
        columns, result_rows = project_catalog_rows(sql, rows, default_columns, context)
        result_columns = [
            ResultColumn(name=column, type_oid=python_value_to_postgres_oid(row_value(result_rows, column_index)))
            for column_index, column in enumerate(columns)
        ]
        return QueryResult(columns=result_columns, rows=result_rows, command_tag=f"SELECT {len(result_rows)}")

    def _catalog_rows(self, source: str, context: HogQLServiceSessionContext) -> tuple[list[dict[str, Any]], list[str]]:
        if source == "pg_catalog.pg_roles":
            return pg_roles_rows(context), EMPTY_CATALOG_COLUMNS["pg_catalog.pg_roles"]
        if source == "pg_user":
            return pg_user_rows(context), EMPTY_CATALOG_COLUMNS["pg_user"]
        if source in EMPTY_CATALOG_COLUMNS:
            return [], EMPTY_CATALOG_COLUMNS[source]

        tables = load_catalog_tables(context)
        schemas = sorted({table.schema for table in tables} | {"information_schema", "pg_catalog", "public"})

        if source == "information_schema.schemata":
            return information_schema_schemata_rows(context, schemas), INFORMATION_SCHEMA_SCHEMATA_COLUMNS
        if source == "information_schema.tables":
            return information_schema_table_rows(context, tables), INFORMATION_SCHEMA_TABLE_COLUMNS
        if source == "information_schema.columns":
            return information_schema_column_rows(context, tables), INFORMATION_SCHEMA_COLUMN_COLUMNS
        if source == "pg_catalog.pg_namespace":
            return pg_namespace_rows(schemas), PG_NAMESPACE_COLUMNS
        if source == "pg_catalog.pg_class":
            return pg_class_rows(tables), PG_CLASS_COLUMNS
        if source == "pg_catalog.pg_attribute":
            return pg_attribute_rows(tables), PG_ATTRIBUTE_COLUMNS
        if source == "pg_catalog.pg_type":
            return pg_type_rows(), PG_TYPE_COLUMNS
        if source == "pg_catalog.pg_database":
            return pg_database_rows(context), PG_DATABASE_COLUMNS

        return [], GENERIC_EMPTY_CATALOG_COLUMNS


class PostgresWireCodec:
    @staticmethod
    def message(message_type: bytes, payload: bytes = b"") -> bytes:
        return message_type + struct.pack("!I", len(payload) + 4) + payload

    @staticmethod
    def authentication_cleartext_password() -> bytes:
        return PostgresWireCodec.message(b"R", struct.pack("!I", AUTHENTICATION_CLEARTEXT_PASSWORD))

    @staticmethod
    def authentication_ok() -> bytes:
        return PostgresWireCodec.message(b"R", struct.pack("!I", AUTHENTICATION_OK))

    @staticmethod
    def parameter_status(name: str, value: str) -> bytes:
        return PostgresWireCodec.message(b"S", encode_cstring(name) + encode_cstring(value))

    @staticmethod
    def backend_key_data(process_id: int, secret_key: int) -> bytes:
        return PostgresWireCodec.message(b"K", struct.pack("!II", process_id, secret_key))

    @staticmethod
    def ready_for_query(status: bytes = b"I") -> bytes:
        return PostgresWireCodec.message(b"Z", status)

    @staticmethod
    def error_response(message: str, sqlstate: str = SQLSTATE_INTERNAL_ERROR, severity: str = "ERROR") -> bytes:
        payload = (
            b"S" + encode_cstring(severity) + b"C" + encode_cstring(sqlstate) + b"M" + encode_cstring(message) + b"\x00"
        )
        return PostgresWireCodec.message(b"E", payload)

    @staticmethod
    def parse_complete() -> bytes:
        return PostgresWireCodec.message(b"1")

    @staticmethod
    def bind_complete() -> bytes:
        return PostgresWireCodec.message(b"2")

    @staticmethod
    def close_complete() -> bytes:
        return PostgresWireCodec.message(b"3")

    @staticmethod
    def no_data() -> bytes:
        return PostgresWireCodec.message(b"n")

    @staticmethod
    def empty_query_response() -> bytes:
        return PostgresWireCodec.message(b"I")

    @staticmethod
    def command_complete(command_tag: str) -> bytes:
        return PostgresWireCodec.message(b"C", encode_cstring(command_tag))

    @staticmethod
    def row_description(columns: list[ResultColumn]) -> bytes:
        payload = struct.pack("!H", len(columns))
        for column in columns:
            payload += encode_cstring(column.name)
            payload += struct.pack(
                "!IhIhih", 0, 0, column.type_oid, column.type_size, column.type_modifier, column.format_code
            )
        return PostgresWireCodec.message(b"T", payload)

    @staticmethod
    def data_row(row: tuple[Any, ...]) -> bytes:
        payload = struct.pack("!H", len(row))
        for value in row:
            if value is None:
                payload += struct.pack("!i", -1)
                continue
            encoded_value = serialize_value(value).encode("utf-8")
            payload += struct.pack("!I", len(encoded_value)) + encoded_value
        return PostgresWireCodec.message(b"D", payload)


class HogQLPostgresWireSession:
    def __init__(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        authenticator: HogQLServiceAuthenticator,
        query_executor: HogQLServiceQueryExecutor,
        max_query_bytes: int,
    ):
        self.reader = reader
        self.writer = writer
        self.authenticator = authenticator
        self.query_executor = query_executor
        self.max_query_bytes = max_query_bytes
        self.context: HogQLServiceSessionContext | None = None
        self.prepared_statements: dict[str, PreparedStatement] = {}
        self.bound_portals: dict[str, BoundPortal] = {}
        self.skip_until_sync = False

    async def run(self) -> None:
        try:
            startup_parameters = await self._read_startup_parameters()
            if startup_parameters is None:
                return

            await self._authenticate(startup_parameters)
            await self._send_startup_ready()
            await self._message_loop()
        except (asyncio.IncompleteReadError, ConnectionResetError):
            return
        except HogQLServiceError as error:
            await self._log_service_error(error, message_type=None)
            self.writer.write(PostgresWireCodec.error_response(str(error), error.sqlstate))
            await self.writer.drain()
        except Exception:
            logger.exception("Unhandled HogQL service connection error")
            self.writer.write(
                PostgresWireCodec.error_response("Internal HogQL service error.", SQLSTATE_INTERNAL_ERROR)
            )
            await self.writer.drain()
        finally:
            self.writer.close()
            await self.writer.wait_closed()

    async def _read_startup_parameters(self) -> dict[str, str] | None:
        while True:
            length_bytes = await self.reader.readexactly(4)
            length = struct.unpack("!I", length_bytes)[0]
            if length < 8 or length > MAX_STARTUP_PACKET_BYTES:
                raise HogQLServiceProtocolError("Invalid startup packet.")

            payload = await self.reader.readexactly(length - 4)
            request_code = struct.unpack("!I", payload[:4])[0]
            if request_code == SSL_REQUEST_CODE or request_code == GSSENC_REQUEST_CODE:
                self.writer.write(b"N")
                await self.writer.drain()
                continue
            if request_code == CANCEL_REQUEST_CODE:
                return None
            if request_code != PROTOCOL_VERSION_3:
                raise HogQLServiceProtocolError("Unsupported Postgres protocol version.")
            return parse_startup_parameters(payload[4:])

    async def _authenticate(self, startup_parameters: dict[str, str]) -> None:
        database_user = startup_parameters.get("user", "")
        database = startup_parameters.get("database") or database_user

        self.writer.write(PostgresWireCodec.authentication_cleartext_password())
        await self.writer.drain()

        message = await self._read_message()
        if message is None or message[0] != b"p":
            raise HogQLServiceAuthenticationError("Password is required.")

        password = message[1].rstrip(b"\x00").decode("utf-8", "replace")
        self.context = await asyncio.to_thread(self.authenticator.authenticate, database_user, database, password)

    async def _send_startup_ready(self) -> None:
        assert self.context is not None
        secret_key = secrets.randbits(32)
        messages = [
            PostgresWireCodec.authentication_ok(),
            PostgresWireCodec.parameter_status("server_version", "16.0"),
            PostgresWireCodec.parameter_status("server_encoding", "UTF8"),
            PostgresWireCodec.parameter_status("client_encoding", "UTF8"),
            PostgresWireCodec.parameter_status("DateStyle", "ISO, MDY"),
            PostgresWireCodec.parameter_status("integer_datetimes", "on"),
            PostgresWireCodec.parameter_status("standard_conforming_strings", "on"),
            PostgresWireCodec.parameter_status("TimeZone", self.context.team.timezone),
            PostgresWireCodec.parameter_status("application_name", "posthog-hogql-service"),
            PostgresWireCodec.backend_key_data(os.getpid(), secret_key),
            PostgresWireCodec.ready_for_query(),
        ]
        for message in messages:
            self.writer.write(message)
        await self.writer.drain()

    async def _message_loop(self) -> None:
        while True:
            message = await self._read_message()
            if message is None:
                return

            message_type, payload = message
            if message_type == b"X":
                return

            if self.skip_until_sync and message_type != b"S":
                continue

            try:
                await self._handle_message(message_type, payload)
            except HogQLServiceError as error:
                await self._log_service_error(error, message_type=message_type)
                self.writer.write(PostgresWireCodec.error_response(str(error), error.sqlstate))
                if message_type != b"Q":
                    self.skip_until_sync = True
                else:
                    self.writer.write(PostgresWireCodec.ready_for_query())
                await self.writer.drain()

    async def _log_service_error(self, error: HogQLServiceError, message_type: bytes | None) -> None:
        context = self.context
        await append_service_log_async(
            f"ERROR sqlstate={error.sqlstate} message_type={message_type!r} "
            f"database={context.database if context else None} team_id={context.team.id if context else None} "
            f"connection_id={context.connection_id if context else None} user={context.database_user if context else None} "
            f"query={error.query!r} error={error!s}"
        )
        logger.warning(
            "HogQL service error: sqlstate=%s query=%r",
            error.sqlstate,
            error.query,
            extra={
                "hogql_service_sqlstate": error.sqlstate,
                "hogql_service_message_type": message_type.decode("ascii", "replace") if message_type else None,
                "hogql_service_query": error.query,
                "hogql_service_database": context.database if context else None,
                "hogql_service_team_id": context.team.id if context else None,
                "hogql_service_connection_id": context.connection_id if context else None,
                "hogql_service_user": context.database_user if context else None,
            },
            exc_info=True,
        )

    async def _read_message(self) -> tuple[bytes, bytes] | None:
        message_type = await self.reader.read(1)
        if not message_type:
            return None
        length_bytes = await self.reader.readexactly(4)
        length = struct.unpack("!I", length_bytes)[0]
        if length < 4:
            raise HogQLServiceProtocolError("Invalid message length.")
        payload_length = length - 4
        max_payload_bytes = self.max_query_bytes if self.context is not None else MAX_UNAUTHENTICATED_MESSAGE_BYTES
        if payload_length > max_payload_bytes:
            raise HogQLServiceProtocolError("Message is too large.")
        payload = await self.reader.readexactly(payload_length)
        return message_type, payload

    async def _handle_message(self, message_type: bytes, payload: bytes) -> None:
        if message_type == b"Q":
            await self._handle_simple_query(payload)
        elif message_type == b"P":
            self._handle_parse(payload)
        elif message_type == b"B":
            self._handle_bind(payload)
        elif message_type == b"D":
            await self._handle_describe(payload)
        elif message_type == b"E":
            await self._handle_execute(payload)
        elif message_type == b"C":
            self._handle_close(payload)
        elif message_type == b"H":
            await self.writer.drain()
        elif message_type == b"S":
            self.skip_until_sync = False
            self.writer.write(PostgresWireCodec.ready_for_query())
            await self.writer.drain()
        else:
            raise HogQLServiceProtocolError(f"Unsupported Postgres message type: {message_type!r}.")

    async def _handle_simple_query(self, payload: bytes) -> None:
        sql = payload.rstrip(b"\x00").decode("utf-8", "replace")
        statements = sqlparse.split(sql)
        if not statements:
            self.writer.write(PostgresWireCodec.empty_query_response())
            self.writer.write(PostgresWireCodec.ready_for_query())
            await self.writer.drain()
            return

        for statement in statements:
            await self._send_query_result(statement, send_row_description=True)

        self.writer.write(PostgresWireCodec.ready_for_query())
        await self.writer.drain()

    def _handle_parse(self, payload: bytes) -> None:
        statement_name, offset = read_cstring(payload, 0)
        query, offset = read_cstring(payload, offset)
        if len(query.encode("utf-8")) > self.max_query_bytes:
            raise HogQLServiceProtocolError("Query is too large.")

        parameter_count = read_uint16(payload, offset)
        offset += 2
        parameter_type_oids = []
        for _ in range(parameter_count):
            parameter_type_oids.append(read_uint32(payload, offset))
            offset += 4

        self.prepared_statements[statement_name] = PreparedStatement(
            name=statement_name,
            query=query,
            parameter_type_oids=parameter_type_oids,
        )
        self.writer.write(PostgresWireCodec.parse_complete())

    def _handle_bind(self, payload: bytes) -> None:
        portal_name, offset = read_cstring(payload, 0)
        statement_name, offset = read_cstring(payload, offset)
        statement = self.prepared_statements.get(statement_name)
        if statement is None:
            raise HogQLServiceProtocolError("Prepared statement does not exist.")

        parameter_format_count = read_uint16(payload, offset)
        offset += 2
        parameter_formats = []
        for _ in range(parameter_format_count):
            parameter_formats.append(read_uint16(payload, offset))
            offset += 2

        parameter_count = read_uint16(payload, offset)
        offset += 2
        parameters = []
        for index in range(parameter_count):
            parameter_length = read_int32(payload, offset)
            offset += 4
            if parameter_length == -1:
                parameters.append(PgParameter(None))
                continue
            parameter_bytes = payload[offset : offset + parameter_length]
            offset += parameter_length
            format_code = (
                parameter_formats[index]
                if len(parameter_formats) > index
                else (parameter_formats[0] if parameter_formats else 0)
            )
            type_oid = (
                statement.parameter_type_oids[index]
                if len(statement.parameter_type_oids) > index
                else POSTGRES_TEXT_OID
            )
            parameters.append(PgParameter(decode_parameter(parameter_bytes, format_code, type_oid)))

        result_format_count = read_uint16(payload, offset)
        offset += 2
        result_formats = []
        for _ in range(result_format_count):
            result_formats.append(read_uint16(payload, offset))
            offset += 2

        self.bound_portals[portal_name] = BoundPortal(
            name=portal_name,
            statement_name=statement_name,
            query=statement.query,
            parameters=parameters,
            result_formats=result_formats,
        )
        self.writer.write(PostgresWireCodec.bind_complete())

    async def _handle_describe(self, payload: bytes) -> None:
        describe_target = payload[:1]
        name = payload[1:].rstrip(b"\x00").decode("utf-8", "replace")
        if describe_target == b"S":
            self.writer.write(PostgresWireCodec.no_data())
            return
        if describe_target != b"P":
            raise HogQLServiceProtocolError("Invalid describe target.")

        portal = self.bound_portals.get(name)
        if portal is None:
            raise HogQLServiceProtocolError("Portal does not exist.")
        result = await self._execute_portal(portal)
        if result.columns:
            self.writer.write(PostgresWireCodec.row_description(result.columns))
            portal.row_description_sent = True
        else:
            self.writer.write(PostgresWireCodec.no_data())

    async def _handle_execute(self, payload: bytes) -> None:
        portal_name, offset = read_cstring(payload, 0)
        _max_rows = read_uint32(payload, offset)
        portal = self.bound_portals.get(portal_name)
        if portal is None:
            raise HogQLServiceProtocolError("Portal does not exist.")

        result = await self._execute_portal(portal)
        await self._send_result(result, send_row_description=not portal.row_description_sent)

    def _handle_close(self, payload: bytes) -> None:
        close_target = payload[:1]
        name = payload[1:].rstrip(b"\x00").decode("utf-8", "replace")
        if close_target == b"S":
            self.prepared_statements.pop(name, None)
        elif close_target == b"P":
            self.bound_portals.pop(name, None)
        else:
            raise HogQLServiceProtocolError("Invalid close target.")
        self.writer.write(PostgresWireCodec.close_complete())

    async def _execute_portal(self, portal: BoundPortal) -> QueryResult:
        if portal.result is not None:
            return portal.result

        query = bind_parameters_to_query(portal.query, portal.parameters)
        portal.result = await self._execute_query(query)
        return portal.result

    async def _send_query_result(self, sql: str, send_row_description: bool) -> None:
        result = await self._execute_query(sql)
        await self._send_result(result, send_row_description=send_row_description)

    async def _execute_query(self, sql: str) -> QueryResult:
        assert self.context is not None
        if len(sql.encode("utf-8")) > self.max_query_bytes:
            raise HogQLServiceProtocolError("Query is too large.")
        await append_service_log_async(
            f"QUERY database={self.context.database} team_id={self.context.team.id} "
            f"connection_id={self.context.connection_id} user={self.context.database_user} query={sql!r}"
        )
        logger.info(
            "HogQL service query: %r",
            sql,
            extra={
                "hogql_service_query": sql,
                "hogql_service_database": self.context.database,
                "hogql_service_team_id": self.context.team.id,
                "hogql_service_connection_id": self.context.connection_id,
                "hogql_service_user": self.context.database_user,
            },
        )
        try:
            result = await asyncio.to_thread(self.query_executor.execute, sql, self.context)
            await self._log_query_result(result)
            return result
        except HogQLServiceError as error:
            if error.query is None:
                error.query = sql
            raise
        except Exception:
            logger.exception(
                "Unhandled HogQL service query error: query=%r",
                sql,
                extra={
                    "hogql_service_query": sql,
                    "hogql_service_database": self.context.database,
                    "hogql_service_team_id": self.context.team.id,
                    "hogql_service_connection_id": self.context.connection_id,
                    "hogql_service_user": self.context.database_user,
                },
            )
            raise

    async def _log_query_result(self, result: QueryResult) -> None:
        assert self.context is not None
        column_names = [column.name for column in result.columns[:20]]
        null_columns = [
            column.name
            for column_index, column in enumerate(result.columns[:20])
            if any(column_index >= len(row) or row[column_index] is None for row in result.rows[:50])
        ]
        await append_service_log_async(
            f"RESULT database={self.context.database} team_id={self.context.team.id} "
            f"connection_id={self.context.connection_id} user={self.context.database_user} "
            f"command={result.command_tag!r} row_count={len(result.rows)} columns={column_names!r} "
            f"null_columns={null_columns!r}"
        )

    async def _send_result(self, result: QueryResult, send_row_description: bool) -> None:
        if send_row_description and result.columns:
            self.writer.write(PostgresWireCodec.row_description(result.columns))
        for row in result.rows:
            self.writer.write(PostgresWireCodec.data_row(row))
        self.writer.write(PostgresWireCodec.command_complete(result.command_tag))
        await self.writer.drain()


class HogQLPostgresServer:
    def __init__(self, config: HogQLServiceConfig, on_listening: Callable[[str], None] | None = None):
        self.config = config
        self.on_listening = on_listening
        self.authenticator = HogQLServiceAuthenticator(shared_secret=config.shared_secret)
        self.query_executor = HogQLServiceQueryExecutor()

    async def serve_forever(self) -> None:
        server = await asyncio.start_server(self._handle_client, self.config.host, self.config.port)
        addresses = ", ".join(str(socket.getsockname()) for socket in server.sockets or [])
        message = f"HogQL Postgres wire service listening on {addresses}"
        await append_service_log_async(message)
        logger.info(message)
        if not is_loopback_host(self.config.host):
            warning = (
                "HogQL service is running without TLS on a non-loopback bind address; "
                "non-loopback client connections will be rejected."
            )
            await append_service_log_async(warning)
            logger.warning(warning)
        if self.on_listening is not None:
            self.on_listening(message)
        async with server:
            await server.serve_forever()

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peername = writer.get_extra_info("peername")
        if not is_loopback_peer(peername):
            logger.warning("Rejected non-loopback HogQL service connection: peername=%r", peername)
            writer.close()
            await writer.wait_closed()
            return

        session = HogQLPostgresWireSession(
            reader=reader,
            writer=writer,
            authenticator=self.authenticator,
            query_executor=self.query_executor,
            max_query_bytes=self.config.max_query_bytes,
        )
        await session.run()


def normalize_sql(sql: str) -> str:
    without_comments = sqlparse.format(sql.strip().rstrip(";"), strip_comments=True)
    return re.sub(r"\s+", " ", without_comments).strip().lower()


def parse_database_name(database: str) -> tuple[str, str | None]:
    if not database:
        raise HogQLServiceAuthenticationError("Database must be a PostHog team_id or team_id/connection_id.")

    if "/" not in database:
        return database, None

    team_id, connection_id = database.split("/", 1)
    if not team_id or not connection_id or "/" in connection_id:
        raise HogQLServiceAuthenticationError("Database must be a PostHog team_id or team_id/connection_id.")

    return team_id, connection_id


def is_loopback_host(host: str) -> bool:
    if host in {"localhost", "127.0.0.1", "::1"}:
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return address.is_loopback


def is_loopback_peer(peername: object) -> bool:
    if not isinstance(peername, tuple) or not peername:
        return False

    host = peername[0]
    if not isinstance(host, str):
        return False

    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return host == "localhost"

    if address.is_loopback:
        return True
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        return address.ipv4_mapped.is_loopback
    return False


def append_service_log(message: str) -> None:
    log_file = os.environ.get("HOGQL_SERVICE_LOG_FILE", "/tmp/posthog-hogql-service.log")
    try:
        with open(log_file, "a") as file:
            file.write(f"{timezone.now().isoformat()} {message}\n")
    except OSError:
        logger.debug("Failed to write HogQL service log file", exc_info=True)


async def append_service_log_async(message: str) -> None:
    await asyncio.to_thread(append_service_log, message)


INFORMATION_SCHEMA_SCHEMATA_COLUMNS = [
    "catalog_name",
    "schema_name",
    "schema_owner",
    "default_character_set_catalog",
    "default_character_set_schema",
    "default_character_set_name",
    "sql_path",
]
INFORMATION_SCHEMA_TABLE_COLUMNS = [
    "table_catalog",
    "table_schema",
    "table_name",
    "table_type",
    "self_referencing_column_name",
    "reference_generation",
    "user_defined_type_catalog",
    "user_defined_type_schema",
    "user_defined_type_name",
    "is_insertable_into",
    "is_typed",
    "commit_action",
]
INFORMATION_SCHEMA_COLUMN_COLUMNS = [
    "table_catalog",
    "table_schema",
    "table_name",
    "column_name",
    "ordinal_position",
    "column_default",
    "is_nullable",
    "data_type",
    "character_maximum_length",
    "character_octet_length",
    "numeric_precision",
    "numeric_precision_radix",
    "numeric_scale",
    "datetime_precision",
    "interval_type",
    "interval_precision",
    "character_set_catalog",
    "character_set_schema",
    "character_set_name",
    "collation_catalog",
    "collation_schema",
    "collation_name",
    "domain_catalog",
    "domain_schema",
    "domain_name",
    "udt_catalog",
    "udt_schema",
    "udt_name",
    "scope_catalog",
    "scope_schema",
    "scope_name",
    "maximum_cardinality",
    "dtd_identifier",
    "is_self_referencing",
    "is_identity",
    "identity_generation",
    "identity_start",
    "identity_increment",
    "identity_maximum",
    "identity_minimum",
    "identity_cycle",
    "is_generated",
    "generation_expression",
    "is_updatable",
]
PG_NAMESPACE_COLUMNS = ["oid", "nspname", "nspowner", "nspacl"]
PG_CLASS_COLUMNS = [
    "oid",
    "relname",
    "relnamespace",
    "reltype",
    "relowner",
    "relkind",
    "relpages",
    "reltuples",
    "relhasindex",
    "relisshared",
    "relpersistence",
    "relchecks",
    "relhasrules",
    "relhastriggers",
    "relhassubclass",
    "relrowsecurity",
    "relforcerowsecurity",
    "relispopulated",
    "reloptions",
    "nspname",
    "table_schema",
    "table_name",
    "table_type",
]
PG_ATTRIBUTE_COLUMNS = [
    "attrelid",
    "attname",
    "atttypid",
    "attstattarget",
    "attlen",
    "attnum",
    "attndims",
    "attcacheoff",
    "atttypmod",
    "attbyval",
    "attstorage",
    "attalign",
    "attnotnull",
    "atthasdef",
    "attidentity",
    "attgenerated",
    "attisdropped",
    "attislocal",
    "attinhcount",
    "attcollation",
    "nspname",
    "relname",
    "typname",
    "format_type",
    "data_type",
    "table_schema",
    "table_name",
    "column_name",
    "ordinal_position",
]
PG_TYPE_COLUMNS = [
    "oid",
    "typname",
    "typnamespace",
    "typowner",
    "typlen",
    "typbyval",
    "typtype",
    "typcategory",
    "typispreferred",
    "typisdefined",
    "typdelim",
    "typrelid",
    "typelem",
    "typarray",
    "typinput",
    "typoutput",
    "typreceive",
    "typsend",
    "typmodin",
    "typmodout",
    "typanalyze",
    "typalign",
    "typstorage",
    "typnotnull",
    "typbasetype",
    "typtypmod",
    "typndims",
    "typcollation",
]
PG_DATABASE_COLUMNS = [
    "oid",
    "datname",
    "datdba",
    "encoding",
    "datcollate",
    "datctype",
    "datistemplate",
    "datallowconn",
]
EMPTY_CATALOG_COLUMNS = {
    "information_schema.table_constraints": [
        "constraint_catalog",
        "constraint_schema",
        "constraint_name",
        "table_schema",
        "table_name",
        "constraint_type",
    ],
    "information_schema.key_column_usage": [
        "constraint_catalog",
        "constraint_schema",
        "constraint_name",
        "table_schema",
        "table_name",
        "column_name",
        "ordinal_position",
    ],
    "information_schema.constraint_column_usage": [
        "constraint_catalog",
        "constraint_schema",
        "constraint_name",
        "table_schema",
        "table_name",
        "column_name",
    ],
    "information_schema.views": ["table_catalog", "table_schema", "table_name", "view_definition"],
    "information_schema.routines": ["specific_catalog", "specific_schema", "specific_name", "routine_name"],
    "information_schema.parameters": ["specific_catalog", "specific_schema", "specific_name", "parameter_name"],
    "information_schema.sequences": ["sequence_catalog", "sequence_schema", "sequence_name"],
    "pg_catalog.pg_index": ["indexrelid", "indrelid", "indisunique", "indisprimary", "indisexclusion", "indkey"],
    "pg_catalog.pg_constraint": ["oid", "conname", "contype", "conrelid", "confrelid", "conkey"],
    "pg_catalog.pg_description": ["objoid", "classoid", "objsubid", "description"],
    "pg_catalog.pg_attrdef": ["adrelid", "adnum", "adbin"],
    "pg_catalog.pg_inherits": ["inhrelid", "inhparent", "inhseqno"],
    "pg_catalog.pg_proc": ["oid", "proname", "pronamespace", "prorettype"],
    "pg_catalog.pg_roles": ["oid", "rolname", "rolsuper", "rolinherit", "rolcreaterole", "rolcreatedb", "rolcanlogin"],
    "pg_catalog.pg_trigger": ["oid", "tgrelid", "tgname", "tgfoid", "tgenabled"],
    "pg_catalog.pg_am": ["oid", "amname", "amhandler", "amtype"],
    "pg_catalog.pg_enum": ["oid", "enumtypid", "enumsortorder", "enumlabel"],
    "pg_catalog.pg_auth_members": ["roleid", "member", "grantor", "admin_option"],
    "pg_catalog.pg_available_extensions": ["name", "default_version", "installed_version", "comment"],
    "pg_catalog.pg_cast": ["oid", "castsource", "casttarget", "castfunc", "castcontext", "castmethod"],
    "pg_catalog.pg_collation": ["oid", "collname", "collnamespace", "collowner", "collencoding"],
    "pg_catalog.pg_conversion": ["oid", "conname", "connamespace", "conowner", "conforencoding", "contoencoding"],
    "pg_catalog.pg_db_role_setting": ["setdatabase", "setrole", "setconfig"],
    "pg_catalog.pg_depend": ["classid", "objid", "objsubid", "refclassid", "refobjid", "refobjsubid", "deptype"],
    "pg_catalog.pg_event_trigger": ["oid", "evtname", "evtevent", "evtowner", "evtfoid", "evtenabled", "evttags"],
    "pg_catalog.pg_extension": ["oid", "extname", "extowner", "extnamespace", "extrelocatable", "extversion"],
    "pg_catalog.pg_foreign_data_wrapper": ["oid", "fdwname", "fdwowner", "fdwhandler", "fdwvalidator", "fdwoptions"],
    "pg_catalog.pg_foreign_server": ["oid", "srvname", "srvowner", "srvfdw", "srvtype", "srvversion", "srvoptions"],
    "pg_catalog.pg_locks": ["locktype", "database", "relation", "transactionid", "pid", "mode", "granted"],
    "pg_catalog.pg_language": ["oid", "lanname", "lanowner", "lanispl", "lanpltrusted", "lanplcallfoid"],
    "pg_catalog.pg_opclass": ["oid", "opcmethod", "opcname", "opcnamespace", "opcowner", "opcfamily", "opcintype"],
    "pg_catalog.pg_operator": ["oid", "oprname", "oprnamespace", "oprowner", "oprkind", "oprcanmerge", "oprcanhash"],
    "pg_catalog.pg_opfamily": ["oid", "opfmethod", "opfname", "opfnamespace", "opfowner"],
    "pg_catalog.pg_policy": ["oid", "polname", "polrelid", "polcmd", "polpermissive", "polroles"],
    "pg_catalog.pg_publication": ["oid", "pubname", "pubowner", "puballtables", "pubinsert", "pubupdate", "pubdelete"],
    "pg_catalog.pg_rewrite": ["oid", "rulename", "ev_class", "ev_type", "ev_enabled", "is_instead"],
    "pg_catalog.pg_sequence": ["seqrelid", "seqtypid", "seqstart", "seqincrement", "seqmax", "seqmin", "seqcache"],
    "pg_catalog.pg_shdescription": ["objoid", "classoid", "description"],
    "pg_catalog.pg_stat_activity": [
        "datid",
        "datname",
        "pid",
        "leader_pid",
        "usesysid",
        "usename",
        "application_name",
        "client_addr",
        "client_hostname",
        "client_port",
        "backend_start",
        "xact_start",
        "query_start",
        "state_change",
        "wait_event_type",
        "wait_event",
        "state",
        "backend_xid",
        "backend_xmin",
        "query_id",
        "query",
        "backend_type",
    ],
    "pg_catalog.pg_subscription": ["oid", "subdbid", "subname", "subowner", "subenabled", "subconninfo"],
    "pg_catalog.pg_tablespace": ["oid", "spcname", "spcowner", "spcacl", "spcoptions", "xmin"],
    "pg_catalog.pg_timezone_abbrevs": ["abbrev", "utc_offset", "is_dst"],
    "pg_catalog.pg_timezone_names": ["name", "abbrev", "utc_offset", "is_dst"],
    "pg_catalog.pg_user_mapping": ["oid", "umuser", "umserver", "umoptions"],
    "pg_user": [
        "usename",
        "usesysid",
        "usecreatedb",
        "usesuper",
        "userepl",
        "usebypassrls",
        "passwd",
        "valuntil",
        "useconfig",
    ],
}
GENERIC_EMPTY_CATALOG_COLUMNS = ["oid"]
CATALOG_ALIAS_KEYS = {
    "table_cat": "table_catalog",
    "table_schem": "table_schema",
    "table_schema": "table_schema",
    "table_name": "table_name",
    "table_type": "table_type",
    "remarks": "description",
    "column_name": "column_name",
    "data_type": "data_type",
    "type_name": "data_type",
    "column_size": "character_maximum_length",
    "decimal_digits": "numeric_scale",
    "num_prec_radix": "numeric_precision_radix",
    "nullable": "nullable",
    "is_nullable": "is_nullable",
    "schema_name": "schema_name",
    "schemaid": "relnamespace",
    "table_oid": "oid",
    "column_oid": "attrelid",
    "majoroid": "attrelid",
    "position": "attnum",
}
UNHANDLED_BUILTIN_EXPRESSION = object()


def evaluate_builtin_expression(expression: str, context: HogQLServiceSessionContext) -> Any:
    normalized = normalize_catalog_expression(expression)
    if normalized in {"current_database()", "pg_catalog.current_database()"}:
        return context.database
    if normalized in {"current_catalog"}:
        return context.database
    if normalized in {"current_schema()", "pg_catalog.current_schema()", "current_schema"}:
        return "public"
    if normalized in {"current_schemas(false)", "pg_catalog.current_schemas(false)"}:
        return ["public"]
    if normalized in {"current_schemas(true)", "pg_catalog.current_schemas(true)"}:
        return ["pg_catalog", "public"]
    if normalized in {"current_user", "session_user"}:
        return context.database_user
    if normalized in {"pg_backend_pid()", "pg_catalog.pg_backend_pid()"}:
        return os.getpid()
    if normalized in {"pg_is_in_recovery()", "pg_catalog.pg_is_in_recovery()"}:
        return False
    if normalized in {"txid_current()", "pg_catalog.txid_current()"}:
        return 0
    if normalized.startswith("case when pg_catalog.pg_is_in_recovery() then null else"):
        if "pg_catalog.txid_current()" in normalized:
            return 0
    if normalized.startswith("current_setting(") or normalized.startswith("pg_catalog.current_setting("):
        setting_match = re.match(r"(?:pg_catalog\.)?current_setting\('([^']+)'(?:,\s*true)?\)", normalized)
        if setting_match:
            return _setting_values(context).get(setting_match.group(1).replace(" ", "_"))
    if normalized == "null":
        return None
    if normalized in {"true", "'yes'"}:
        return True
    if normalized in {"false", "'no'"}:
        return False
    if re.fullmatch(r"-?\d+", normalized):
        return int(normalized)
    if normalized.startswith("'") and normalized.endswith("'"):
        return normalized[1:-1].replace("''", "'")
    return UNHANDLED_BUILTIN_EXPRESSION


def catalog_source(normalized: str) -> str | None:
    source_pattern = r"\b(?:from|join)\s+(?:(information_schema|pg_catalog)\.)?([a-z_][a-z0-9_]*)\b"

    outer_select_index = find_top_level_keyword(normalized, "select")
    if outer_select_index is not None:
        outer_from_index = find_top_level_keyword(normalized, "from", start=outer_select_index + len("select"))
        if outer_from_index is not None:
            outer_source = catalog_source_from_fragment(normalized[outer_from_index:], source_pattern)
            if outer_source is not None:
                return outer_source

    return catalog_source_from_fragment(normalized, source_pattern)


def catalog_source_from_fragment(fragment: str, source_pattern: str) -> str | None:
    for source_match in re.finditer(source_pattern, fragment):
        schema_name = source_match.group(1)
        table_name = source_match.group(2)
        if schema_name == "information_schema":
            return f"information_schema.{table_name}"
        if table_name == "pg_user":
            return "pg_user"
        if schema_name == "pg_catalog" or table_name.startswith("pg_"):
            return f"pg_catalog.{table_name}"
    return None


def load_catalog_tables(context: HogQLServiceSessionContext) -> list[CatalogTable]:
    modifiers = create_default_modifiers_for_team(context.team)
    database = Database.create_for(
        team=context.team,
        user=context.user,
        modifiers=modifiers,
        connection_id=context.connection_id,
    )
    hogql_context = HogQLContext(
        team=context.team,
        user=context.user,
        database=database,
        modifiers=modifiers,
    )
    serialized_tables = database.serialize(hogql_context)
    tables: list[CatalogTable] = []
    for table_name, table in serialized_tables.items():
        schema_name, relation_name = catalog_table_name(table_name)
        tables.append(
            CatalogTable(
                oid=stable_catalog_oid(f"table:{table_name}"),
                schema=schema_name,
                name=relation_name,
                hogql_name=table_name,
                table_type=postgres_table_type(str(table.type)),
                fields=list(table.fields.values()),
            )
        )
    return sorted(tables, key=lambda table: (table.schema, table.name))


def catalog_table_name(table_name: str) -> tuple[str, str]:
    if "." not in table_name:
        return "public", catalog_safe_identifier(table_name)

    parts = table_name.split(".")
    schema_name = catalog_safe_identifier("_".join(parts[:-1]))
    relation_name = catalog_safe_identifier(parts[-1])
    return schema_name or "public", relation_name


def catalog_safe_identifier(identifier: str) -> str:
    safe_identifier = re.sub(r"[^a-zA-Z0-9_]+", "_", identifier).strip("_")
    return safe_identifier or "unnamed"


def postgres_table_type(table_type: str) -> str:
    if table_type in {"view", "managed_view", "materialized_view", "endpoint"}:
        return "VIEW"
    return "BASE TABLE"


def information_schema_schemata_rows(context: HogQLServiceSessionContext, schemas: list[str]) -> list[dict[str, Any]]:
    return [
        {
            "catalog_name": context.database,
            "schema_name": schema,
            "schema_owner": context.database_user,
            "default_character_set_catalog": None,
            "default_character_set_schema": None,
            "default_character_set_name": "UTF8",
            "sql_path": None,
            "nspname": schema,
            "oid": stable_catalog_oid(f"schema:{schema}"),
        }
        for schema in schemas
    ]


def information_schema_table_rows(
    context: HogQLServiceSessionContext, tables: list[CatalogTable]
) -> list[dict[str, Any]]:
    return [
        {
            "table_catalog": context.database,
            "table_schema": table.schema,
            "table_name": table.name,
            "table_type": table.table_type,
            "self_referencing_column_name": None,
            "reference_generation": None,
            "user_defined_type_catalog": None,
            "user_defined_type_schema": None,
            "user_defined_type_name": None,
            "is_insertable_into": "NO",
            "is_typed": "NO",
            "commit_action": None,
            "oid": table.oid,
            "nspname": table.schema,
            "relname": table.name,
            "description": None,
        }
        for table in tables
    ]


def information_schema_column_rows(
    context: HogQLServiceSessionContext, tables: list[CatalogTable]
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for table in tables:
        for ordinal_position, field in enumerate(table.fields, start=1):
            pg_type = postgres_type_for_field(field)
            rows.append(
                {
                    "table_catalog": context.database,
                    "table_schema": table.schema,
                    "table_name": table.name,
                    "column_name": field.name,
                    "ordinal_position": ordinal_position,
                    "column_default": None,
                    "is_nullable": "YES",
                    "data_type": pg_type["data_type"],
                    "character_maximum_length": pg_type["character_maximum_length"],
                    "character_octet_length": pg_type["character_octet_length"],
                    "numeric_precision": pg_type["numeric_precision"],
                    "numeric_precision_radix": pg_type["numeric_precision_radix"],
                    "numeric_scale": pg_type["numeric_scale"],
                    "datetime_precision": pg_type["datetime_precision"],
                    "interval_type": None,
                    "interval_precision": None,
                    "character_set_catalog": None,
                    "character_set_schema": None,
                    "character_set_name": None,
                    "collation_catalog": None,
                    "collation_schema": None,
                    "collation_name": None,
                    "domain_catalog": None,
                    "domain_schema": None,
                    "domain_name": None,
                    "udt_catalog": context.database,
                    "udt_schema": "pg_catalog",
                    "udt_name": pg_type["udt_name"],
                    "scope_catalog": None,
                    "scope_schema": None,
                    "scope_name": None,
                    "maximum_cardinality": None,
                    "dtd_identifier": str(ordinal_position),
                    "is_self_referencing": "NO",
                    "is_identity": "NO",
                    "identity_generation": None,
                    "identity_start": None,
                    "identity_increment": None,
                    "identity_maximum": None,
                    "identity_minimum": None,
                    "identity_cycle": "NO",
                    "is_generated": "NEVER",
                    "generation_expression": None,
                    "is_updatable": "NO",
                    "attrelid": table.oid,
                    "attname": field.name,
                    "atttypid": pg_type["oid"],
                    "attnum": ordinal_position,
                    "typname": pg_type["udt_name"],
                    "format_type": pg_type["data_type"],
                    "nullable": 1,
                    "description": None,
                }
            )
    return rows


def pg_namespace_rows(schemas: list[str]) -> list[dict[str, Any]]:
    return [
        {
            "oid": stable_catalog_oid(f"schema:{schema}"),
            "xmin": 1,
            "nspname": schema,
            "schema_name": schema,
            "nspowner": 10,
            "nspacl": None,
        }
        for schema in schemas
    ]


def pg_class_rows(tables: list[CatalogTable]) -> list[dict[str, Any]]:
    return [
        {
            "oid": table.oid,
            "xmin": 1,
            "relname": table.name,
            "name": table.name,
            "relnamespace": stable_catalog_oid(f"schema:{table.schema}"),
            "schemaid": stable_catalog_oid(f"schema:{table.schema}"),
            "majoroid": table.oid,
            "reltype": stable_catalog_oid(f"type:{table.schema}.{table.name}"),
            "relowner": 10,
            "relkind": "v" if table.table_type == "VIEW" else "r",
            "relpages": 0,
            "reltuples": -1.0,
            "relhasindex": False,
            "relisshared": False,
            "relpersistence": "p",
            "relchecks": 0,
            "relhasrules": False,
            "relhastriggers": False,
            "relhassubclass": False,
            "relrowsecurity": False,
            "relforcerowsecurity": False,
            "relispopulated": True,
            "reloptions": None,
            "nspname": table.schema,
            "table_schema": table.schema,
            "table_name": table.name,
            "table_type": table.table_type,
            "description": None,
        }
        for table in tables
    ]


def pg_attribute_rows(tables: list[CatalogTable]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for table in tables:
        schema_oid = stable_catalog_oid(f"schema:{table.schema}")
        relkind = "v" if table.table_type == "VIEW" else "r"
        for ordinal_position, field in enumerate(table.fields, start=1):
            pg_type = postgres_type_for_field(field)
            rows.append(
                {
                    "table_id": table.oid,
                    "majoroid": table.oid,
                    "relnamespace": schema_oid,
                    "schemaid": schema_oid,
                    "relkind": relkind,
                    "attrelid": table.oid,
                    "oid": table.oid,
                    "object_id": table.oid,
                    "xmin": 1,
                    "attname": field.name,
                    "name": field.name,
                    "atttypid": pg_type["oid"],
                    "attstattarget": -1,
                    "attlen": -1,
                    "attnum": ordinal_position,
                    "position": ordinal_position,
                    "attr_position": ordinal_position,
                    "attndims": 0,
                    "attcacheoff": -1,
                    "atttypmod": -1,
                    "attbyval": False,
                    "attstorage": "x",
                    "attalign": "i",
                    "attnotnull": False,
                    "atthasdef": False,
                    "attfdwoptions": None,
                    "attidentity": "",
                    "attgenerated": "",
                    "attisdropped": False,
                    "attislocal": True,
                    "attinhcount": 0,
                    "attcollation": 0,
                    "attacl": None,
                    "nspname": table.schema,
                    "relname": table.name,
                    "typname": pg_type["udt_name"],
                    "format_type": pg_type["data_type"],
                    "data_type": pg_type["data_type"],
                    "table_schema": table.schema,
                    "table_name": table.name,
                    "column_name": field.name,
                    "ordinal_position": ordinal_position,
                    "nullable": 1,
                    "description": None,
                }
            )
    return rows


def pg_type_rows() -> list[dict[str, Any]]:
    rows = []
    for type_oid, typname in [
        (POSTGRES_BOOL_OID, "bool"),
        (POSTGRES_INT8_OID, "int8"),
        (POSTGRES_INT4_OID, "int4"),
        (POSTGRES_INT2_OID, "int2"),
        (POSTGRES_FLOAT4_OID, "float4"),
        (POSTGRES_FLOAT8_OID, "float8"),
        (POSTGRES_NUMERIC_OID, "numeric"),
        (POSTGRES_DATE_OID, "date"),
        (POSTGRES_TIMESTAMP_OID, "timestamp"),
        (POSTGRES_TIMESTAMPTZ_OID, "timestamptz"),
        (POSTGRES_JSON_OID, "json"),
        (POSTGRES_UUID_OID, "uuid"),
        (POSTGRES_TEXT_OID, "text"),
    ]:
        rows.append(
            {
                "oid": type_oid,
                "xmin": 1,
                "typname": typname,
                "typnamespace": stable_catalog_oid("schema:pg_catalog"),
                "typowner": 10,
                "typlen": -1,
                "typbyval": False,
                "typtype": "b",
                "typcategory": "S",
                "typispreferred": typname == "text",
                "typisdefined": True,
                "typdelim": ",",
                "typrelid": 0,
                "typelem": 0,
                "typarray": 0,
                "typinput": None,
                "typoutput": None,
                "typreceive": None,
                "typsend": None,
                "typmodin": None,
                "typmodout": None,
                "typanalyze": None,
                "typalign": "i",
                "typstorage": "x",
                "typnotnull": False,
                "typbasetype": 0,
                "typtypmod": -1,
                "typndims": 0,
                "typcollation": 0,
            }
        )
    return rows


def pg_database_rows(context: HogQLServiceSessionContext) -> list[dict[str, Any]]:
    return [
        {
            "oid": stable_catalog_oid(f"database:{context.database}"),
            "xmin": 1,
            "datname": context.database,
            "datdba": 10,
            "encoding": 6,
            "datcollate": "C",
            "datctype": "C",
            "datistemplate": False,
            "datallowconn": True,
        }
    ]


def pg_roles_rows(context: HogQLServiceSessionContext) -> list[dict[str, Any]]:
    return [
        {
            "oid": stable_catalog_oid(f"role:{context.database_user}"),
            "xmin": 1,
            "rolname": context.database_user,
            "rolsuper": False,
            "rolinherit": True,
            "rolcreaterole": False,
            "rolcreatedb": False,
            "rolcanlogin": True,
        }
    ]


def pg_user_rows(context: HogQLServiceSessionContext) -> list[dict[str, Any]]:
    return [
        {
            "usename": context.database_user,
            "usesysid": stable_catalog_oid(f"role:{context.database_user}"),
            "usecreatedb": False,
            "usesuper": False,
            "userepl": False,
            "usebypassrls": False,
            "passwd": None,
            "valuntil": None,
            "useconfig": None,
        }
    ]


def postgres_type_for_field(field: DatabaseSchemaField) -> dict[str, Any]:
    field_type = str(field.type)
    if field_type == DatabaseSerializedFieldType.INTEGER.value:
        return postgres_type("bigint", "int8", POSTGRES_INT8_OID, numeric_precision=64, numeric_scale=0)
    if field_type == DatabaseSerializedFieldType.FLOAT.value:
        return postgres_type("double precision", "float8", POSTGRES_FLOAT8_OID, numeric_precision=53)
    if field_type == DatabaseSerializedFieldType.DECIMAL.value:
        return postgres_type("numeric", "numeric", POSTGRES_NUMERIC_OID)
    if field_type == DatabaseSerializedFieldType.DATETIME.value:
        return postgres_type("timestamp with time zone", "timestamptz", POSTGRES_TIMESTAMPTZ_OID, datetime_precision=6)
    if field_type == DatabaseSerializedFieldType.DATE.value:
        return postgres_type("date", "date", POSTGRES_DATE_OID)
    if field_type == DatabaseSerializedFieldType.BOOLEAN.value:
        return postgres_type("boolean", "bool", POSTGRES_BOOL_OID)
    if field_type == DatabaseSerializedFieldType.JSON.value:
        return postgres_type("json", "json", POSTGRES_JSON_OID)
    return postgres_type("text", "text", POSTGRES_TEXT_OID, character_maximum_length=None)


def postgres_type(
    data_type: str,
    udt_name: str,
    oid: int,
    *,
    character_maximum_length: int | None = None,
    numeric_precision: int | None = None,
    numeric_scale: int | None = None,
    datetime_precision: int | None = None,
) -> dict[str, Any]:
    return {
        "data_type": data_type,
        "udt_name": udt_name,
        "oid": oid,
        "character_maximum_length": character_maximum_length,
        "character_octet_length": character_maximum_length,
        "numeric_precision": numeric_precision,
        "numeric_precision_radix": 2 if numeric_precision is not None else None,
        "numeric_scale": numeric_scale,
        "datetime_precision": datetime_precision,
    }


def filter_catalog_rows(rows: list[dict[str, Any]], normalized: str) -> list[dict[str, Any]]:
    if not rows:
        return rows
    if re.search(r"\bwhere\s+(false|1\s*=\s*0)\b", normalized):
        return []

    filters = [
        (("table_schema", "nspname", "schema_name"), extract_equality_filters(normalized, ["table_schema", "nspname"])),
        (("table_name", "relname"), extract_equality_filters(normalized, ["table_name", "relname"])),
        (("column_name", "attname"), extract_equality_filters(normalized, ["column_name", "attname"])),
    ]
    filtered_rows = rows
    for keys, values in filters:
        if not values:
            continue
        filtered_rows = [
            row
            for row in filtered_rows
            if any(str(row.get(key, "")).casefold() in values for key in keys if row.get(key) is not None)
        ]

    namespace_oids = extract_oid_filters(normalized, ["relnamespace", "typnamespace", "pronamespace", "collnamespace"])
    n_oid_filters = extract_oid_filters(normalized, ["n.oid"])
    if namespace_oids or n_oid_filters:
        wanted_oids = namespace_oids | n_oid_filters
        filtered_rows = [
            row
            for row in filtered_rows
            if row_matches_any_oid(
                row, ["relnamespace", "typnamespace", "pronamespace", "collnamespace", "oid"], wanted_oids
            )
        ]

    relkinds = extract_string_in_filters(normalized, "relkind")
    if relkinds:
        filtered_rows = [row for row in filtered_rows if str(row.get("relkind", "")).casefold() in relkinds]
    return filtered_rows


def extract_equality_filters(normalized: str, names: list[str]) -> set[str]:
    values: set[str] = set()
    for name in names:
        pattern = rf"(?:\b[a-z_][a-z0-9_]*\.)?{re.escape(name)}\s*=\s*'([^']*)'"
        values.update(match.group(1).casefold() for match in re.finditer(pattern, normalized))
    return values


def extract_oid_filters(normalized: str, names: list[str]) -> set[int]:
    values: set[int] = set()
    for name in names:
        escaped_name = re.escape(name).replace(r"\.", r"\s*\.\s*")
        equality_pattern = rf"(?:\b[a-z_][a-z0-9_]*\.)?{escaped_name}\s*=\s*(\d+)(?:::oid)?"
        in_pattern = rf"(?:\b[a-z_][a-z0-9_]*\.)?{escaped_name}\s+in\s*\(([^)]*)\)"
        values.update(int(match.group(1)) for match in re.finditer(equality_pattern, normalized))
        for match in re.finditer(in_pattern, normalized):
            values.update(int(value) for value in re.findall(r"\d+", match.group(1)))
    return values


def row_matches_any_oid(row: dict[str, Any], keys: list[str], wanted_oids: set[int]) -> bool:
    for key in keys:
        value = row.get(key)
        if isinstance(value, int) and value in wanted_oids:
            return True
    return False


def extract_string_in_filters(normalized: str, name: str) -> set[str]:
    values: set[str] = set()
    pattern = rf"(?:\b[a-z_][a-z0-9_]*\.)?{re.escape(name)}\s+in\s*\(([^)]*)\)"
    for match in re.finditer(pattern, normalized):
        values.update(value.casefold() for value in re.findall(r"'([^']*)'", match.group(1)))
    return values


def project_catalog_rows(
    sql: str,
    rows: list[dict[str, Any]],
    default_columns: list[str],
    context: HogQLServiceSessionContext,
) -> tuple[list[str], list[tuple[Any, ...]]]:
    if re.search(r"\bcount\s*\(\s*\*\s*\)", sql, flags=re.IGNORECASE):
        return ["count"], [(len(rows),)]

    select_items = parse_select_items(sql)
    if not select_items or any(expression == "*" or expression.endswith(".*") for expression, _label in select_items):
        return default_columns, [tuple(row.get(column) for column in default_columns) for row in rows]

    columns = [label for _expression, label in select_items]
    result_rows = [
        tuple(evaluate_catalog_expression(expression, label, row, context) for expression, label in select_items)
        for row in rows
    ]
    return columns, result_rows


def parse_select_items(sql: str) -> list[tuple[str, str]]:
    select_list = extract_select_list(sql)
    if select_list is None:
        return []
    select_list = re.sub(r"^\s*distinct\s+", "", select_list, flags=re.IGNORECASE)
    return [parse_select_item(item) for item in split_top_level_commas(select_list)]


def extract_select_list(sql: str) -> str | None:
    select_index = find_top_level_keyword(sql, "select")
    if select_index is None:
        return None
    from_index = find_top_level_keyword(sql, "from", start=select_index + len("select"))
    if from_index is None:
        return None
    return sql[select_index + len("select") : from_index].strip()


def parse_select_item(item: str) -> tuple[str, str]:
    stripped_item = item.strip()
    alias_match = re.search(r"\s+as\s+((?:\"[^\"]+\")|(?:[a-zA-Z_][a-zA-Z0-9_$]*))\s*$", stripped_item, re.IGNORECASE)
    if alias_match:
        expression = stripped_item[: alias_match.start()].strip()
        return expression, clean_identifier(alias_match.group(1))

    trailing_alias_match = re.search(r"\s+((?:\"[^\"]+\")|(?:[a-zA-Z_][a-zA-Z0-9_$]*))\s*$", stripped_item)
    if trailing_alias_match and not stripped_item[: trailing_alias_match.start()].strip().lower().endswith("::"):
        expression = stripped_item[: trailing_alias_match.start()].strip()
        if expression and not expression.lower().endswith(("null", "true", "false")):
            return expression, clean_identifier(trailing_alias_match.group(1))

    return stripped_item, label_from_expression(stripped_item)


def evaluate_catalog_expression(
    expression: str,
    label: str,
    row: dict[str, Any],
    context: HogQLServiceSessionContext,
) -> Any:
    label_key = CATALOG_ALIAS_KEYS.get(label.casefold(), label.casefold())
    if label_key in row:
        return row[label_key]

    normalized_expression = normalize_catalog_expression(expression)
    expression_key = CATALOG_ALIAS_KEYS.get(normalized_expression, normalized_expression)
    if expression_key in row:
        return row[expression_key]

    if normalized_expression in {"current_database()", "pg_catalog.current_database()"}:
        return context.database
    if normalized_expression in {"current_schema()", "pg_catalog.current_schema()"}:
        return "public"
    if normalized_expression.startswith("pg_catalog.pg_get_userbyid(") or normalized_expression.startswith(
        "pg_get_userbyid("
    ):
        return context.database_user
    if normalized_expression.startswith("not "):
        value = evaluate_catalog_expression(expression.strip()[4:], label, row, context)
        if isinstance(value, bool):
            return not value
        return None
    translated_value = evaluate_translate_expression(normalized_expression, row)
    if translated_value is not None:
        return translated_value
    if normalized_expression.startswith("pg_catalog.format_type(") or normalized_expression.startswith("format_type("):
        return row.get("format_type") or row.get("data_type")
    if "obj_description(" in normalized_expression or "col_description(" in normalized_expression:
        return row.get("description")
    if normalized_expression == "null":
        return None
    if normalized_expression in {"true", "'yes'"}:
        return True
    if normalized_expression in {"false", "'no'"}:
        return False
    if re.fullmatch(r"-?\d+", normalized_expression):
        return int(normalized_expression)
    if normalized_expression.startswith("'") and normalized_expression.endswith("'"):
        return normalized_expression[1:-1].replace("''", "'")
    return None


def evaluate_translate_expression(normalized_expression: str, row: dict[str, Any]) -> str | None:
    match = re.fullmatch(
        r"(?:pg_catalog\.)?translate\(([^,]+),\s*'([^']*)',\s*'([^']*)'\)",
        normalized_expression,
    )
    if not match:
        return None

    source_expression = normalize_catalog_expression(match.group(1))
    source_key = CATALOG_ALIAS_KEYS.get(source_expression, source_expression)
    source_value = row.get(source_key)
    if source_value is None and source_expression == "kind":
        source_value = row.get("relkind")
    if source_value is None and source_expression.startswith("'") and source_expression.endswith("'"):
        source_value = source_expression[1:-1].replace("''", "'")
    if source_value is None:
        return None
    return str(source_value).translate(str.maketrans(match.group(2), match.group(3)))


def normalize_catalog_expression(expression: str) -> str:
    normalized = expression.strip()
    normalized = re.sub(r"::\s*[a-zA-Z_][a-zA-Z0-9_.]*(?:\[\])?", "", normalized)
    normalized = normalized.strip().casefold()
    normalized = normalized.replace('"', "")
    if "." in normalized and re.fullmatch(r"[a-z_][a-z0-9_$]*\.[a-z_][a-z0-9_$]*", normalized):
        return normalized.rsplit(".", 1)[1]
    return normalized


def label_from_expression(expression: str) -> str:
    normalized = normalize_catalog_expression(expression)
    if normalized in {"current_database()", "pg_catalog.current_database()"}:
        return "current_database"
    if normalized in {"current_schema()", "pg_catalog.current_schema()"}:
        return "current_schema"
    if normalized.startswith("pg_catalog.format_type(") or normalized.startswith("format_type("):
        return "format_type"
    if normalized == "null":
        return "?column?"
    return clean_identifier(normalized.rsplit(".", 1)[-1])


def split_top_level_commas(value: str) -> list[str]:
    parts: list[str] = []
    start = 0
    depth = 0
    quote: str | None = None
    index = 0
    while index < len(value):
        char = value[index]
        if quote is not None:
            if char == quote:
                quote = None
            index += 1
            continue
        if char in {"'", '"'}:
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")":
            depth = max(depth - 1, 0)
        elif char == "," and depth == 0:
            parts.append(value[start:index].strip())
            start = index + 1
        index += 1
    parts.append(value[start:].strip())
    return [part for part in parts if part]


def find_top_level_keyword(sql: str, keyword: str, start: int = 0) -> int | None:
    depth = 0
    quote: str | None = None
    index = start
    lowered = sql.casefold()
    while index < len(sql):
        char = sql[index]
        if quote is not None:
            if char == quote:
                quote = None
            index += 1
            continue
        if char in {"'", '"'}:
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")":
            depth = max(depth - 1, 0)
        elif depth == 0 and lowered.startswith(keyword, index):
            before = lowered[index - 1] if index > 0 else " "
            after_index = index + len(keyword)
            after = lowered[after_index] if after_index < len(lowered) else " "
            if not (before.isalnum() or before == "_") and not (after.isalnum() or after == "_"):
                return index
        index += 1
    return None


def clean_identifier(identifier: str) -> str:
    stripped = identifier.strip()
    if stripped.startswith('"') and stripped.endswith('"'):
        return stripped[1:-1].replace('""', '"')
    return stripped.casefold()


def stable_catalog_oid(key: str) -> int:
    return 10000 + (zlib.crc32(key.encode("utf-8")) & 0x3FFFFFFF)


def row_value(rows: list[tuple[Any, ...]], column_index: int) -> Any:
    for row in rows:
        if column_index < len(row) and row[column_index] is not None:
            return row[column_index]
    return None


def python_value_to_postgres_oid(value: Any) -> int:
    if isinstance(value, bool):
        return POSTGRES_BOOL_OID
    if isinstance(value, int):
        return POSTGRES_INT8_OID
    if isinstance(value, float):
        return POSTGRES_FLOAT8_OID
    if isinstance(value, Decimal):
        return POSTGRES_NUMERIC_OID
    if isinstance(value, date) and not isinstance(value, datetime):
        return POSTGRES_DATE_OID
    if isinstance(value, datetime):
        return POSTGRES_TIMESTAMPTZ_OID
    if isinstance(value, (dict, list)):
        return POSTGRES_JSON_OID
    return POSTGRES_TEXT_OID


def strip_public_schema_references(sql: str) -> str:
    return re.sub(r'(?i)(\bfrom\s+|\bjoin\s+)(?:"public"|public)\.', r"\1", sql)


def rewrite_postgres_pseudo_columns(sql: str) -> str:
    sql = re.sub(r"(?i)(\bselect\s+)(?:[a-z_][a-z0-9_]*\.)?ctid(\s*,)", r"\1NULL AS ctid\2", sql)
    return re.sub(r"(?i)(,\s*)(?:[a-z_][a-z0-9_]*\.)?ctid\b", r"\1NULL AS ctid", sql)


def rewrite_catalog_table_references(sql: str, context: HogQLServiceSessionContext) -> str:
    rewritten_sql = sql
    for table in load_catalog_tables(context):
        hogql_name = table.hogql_name
        catalog_reference = f"{table.schema}.{table.name}"
        replacements: list[tuple[str, str]] = []
        if catalog_reference != hogql_name:
            replacements.append((table.schema, table.name))

        hogql_parts = hogql_name.split(".")
        if len(hogql_parts) > 2:
            replacements.append((hogql_parts[0], ".".join(hogql_parts[1:])))

        for schema_name, table_name in replacements:
            pattern = (
                rf"(?i)(\b(?:from|join)\s+)"
                rf"(?:{quoted_or_unquoted_identifier_pattern(schema_name)})"
                rf"\."
                rf"(?:{quoted_or_unquoted_identifier_pattern(table_name)})"
                rf"(?=\s|$)"
            )
            rewritten_sql = re.sub(
                pattern,
                lambda match, replacement=hogql_name: f"{match.group(1)}{replacement}",
                rewritten_sql,
            )
    return rewritten_sql


def quoted_or_unquoted_identifier_pattern(identifier: str) -> str:
    escaped_identifier = re.escape(identifier)
    escaped_quoted_identifier = re.escape(identifier.replace('"', '""'))
    return rf'"{escaped_quoted_identifier}"|{escaped_identifier}'


def clickhouse_type_to_postgres_oid(clickhouse_type: str) -> int:
    lowered = clickhouse_type.lower()
    if lowered.startswith("nullable("):
        lowered = lowered.removeprefix("nullable(").removesuffix(")")
    if lowered.startswith("array("):
        return POSTGRES_TEXT_OID
    if lowered.startswith("bool"):
        return POSTGRES_BOOL_OID
    if lowered.startswith("uint") or lowered.startswith("int"):
        return POSTGRES_INT8_OID
    if lowered.startswith("float"):
        return POSTGRES_FLOAT8_OID
    if lowered.startswith("decimal"):
        return POSTGRES_NUMERIC_OID
    if lowered.startswith("date32") or lowered == "date":
        return POSTGRES_DATE_OID
    if lowered.startswith("datetime64") or lowered.startswith("datetime"):
        return POSTGRES_TIMESTAMPTZ_OID
    if lowered.startswith("uuid"):
        return POSTGRES_UUID_OID
    if lowered.startswith("json"):
        return POSTGRES_JSON_OID
    return POSTGRES_TEXT_OID


def bind_parameters_to_query(query: str, parameters: list[PgParameter]) -> str:
    output: list[str] = []
    index = 0
    state: Literal["normal", "single", "double", "backtick", "line_comment", "block_comment"] = "normal"

    while index < len(query):
        char = query[index]
        next_char = query[index + 1] if index + 1 < len(query) else ""

        if state == "normal":
            if char == "'":
                state = "single"
                output.append(char)
                index += 1
                continue
            if char == '"':
                state = "double"
                output.append(char)
                index += 1
                continue
            if char == "`":
                state = "backtick"
                output.append(char)
                index += 1
                continue
            if char == "-" and next_char == "-":
                state = "line_comment"
                output.append(char)
                output.append(next_char)
                index += 2
                continue
            if char == "/" and next_char == "*":
                state = "block_comment"
                output.append(char)
                output.append(next_char)
                index += 2
                continue
            if char == "$" and next_char.isdecimal():
                end = index + 2
                while end < len(query) and query[end].isdecimal():
                    end += 1
                parameter_index = int(query[index + 1 : end]) - 1
                if parameter_index < 0 or parameter_index >= len(parameters):
                    raise HogQLServiceProtocolError(f"Missing bind parameter ${parameter_index + 1}.")
                output.append(escape_hogql_string(parameters[parameter_index].value))
                index = end
                continue
        elif state == "single":
            if char == "\\":
                output.append(char)
                if next_char:
                    output.append(next_char)
                    index += 2
                    continue
            elif char == "'" and next_char == "'":
                output.append(char)
                output.append(next_char)
                index += 2
                continue
            elif char == "'":
                state = "normal"
        elif state == "double" and char == '"':
            state = "normal"
        elif state == "backtick" and char == "`":
            state = "normal"
        elif state == "line_comment" and char in {"\n", "\r"}:
            state = "normal"
        elif state == "block_comment" and char == "*" and next_char == "/":
            state = "normal"
            output.append(char)
            output.append(next_char)
            index += 2
            continue

        output.append(char)
        index += 1

    return "".join(output)


def decode_parameter(data: bytes, format_code: int, type_oid: int) -> Any:
    if format_code == 0:
        return data.decode("utf-8")
    if format_code != 1:
        raise HogQLServiceProtocolError("Unsupported bind parameter format.")

    if type_oid == POSTGRES_BOOL_OID:
        return data != b"\x00"
    if type_oid == POSTGRES_INT2_OID:
        return struct.unpack("!h", data)[0]
    if type_oid == POSTGRES_INT4_OID:
        return struct.unpack("!i", data)[0]
    if type_oid == POSTGRES_INT8_OID:
        return struct.unpack("!q", data)[0]
    if type_oid == POSTGRES_FLOAT4_OID:
        return struct.unpack("!f", data)[0]
    if type_oid == POSTGRES_FLOAT8_OID:
        return struct.unpack("!d", data)[0]
    if type_oid in {POSTGRES_TEXT_OID, 1042, 1043}:
        return data.decode("utf-8")

    raise HogQLServiceProtocolError(f"Unsupported binary bind parameter type OID: {type_oid}.")


def serialize_value(value: Any) -> str:
    if isinstance(value, bool):
        return "t" if value else "f"
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (list, tuple, dict)):
        return json.dumps(value, default=str)
    return str(value)


def parse_startup_parameters(payload: bytes) -> dict[str, str]:
    parts = payload.split(b"\x00")
    parameters: dict[str, str] = {}
    index = 0
    while index + 1 < len(parts) and parts[index]:
        key = parts[index].decode("utf-8", "replace")
        value = parts[index + 1].decode("utf-8", "replace")
        parameters[key] = value
        index += 2
    return parameters


def encode_cstring(value: str) -> bytes:
    return value.encode("utf-8") + b"\x00"


def read_cstring(payload: bytes, offset: int) -> tuple[str, int]:
    end = payload.find(b"\x00", offset)
    if end == -1:
        raise HogQLServiceProtocolError("Expected null-terminated string.")
    return payload[offset:end].decode("utf-8", "replace"), end + 1


def read_uint16(payload: bytes, offset: int) -> int:
    return struct.unpack("!H", payload[offset : offset + 2])[0]


def read_uint32(payload: bytes, offset: int) -> int:
    return struct.unpack("!I", payload[offset : offset + 4])[0]


def read_int32(payload: bytes, offset: int) -> int:
    return struct.unpack("!i", payload[offset : offset + 4])[0]
