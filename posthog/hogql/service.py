from __future__ import annotations

import os
import re
import hmac
import json
import struct
import asyncio
import logging
import secrets
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from django.utils import timezone

import sqlparse
from rest_framework.exceptions import AuthenticationFailed

from posthog.schema import HogQLQueryResponse

from posthog.hogql.constants import LimitContext
from posthog.hogql.errors import ExposedHogQLError, QueryError, ResolutionError
from posthog.hogql.escape_sql import escape_hogql_string
from posthog.hogql.parser import CacheOrigin, parse_select
from posthog.hogql.query import execute_hogql_query
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
    host: str = "0.0.0.0"
    port: int = 6543
    shared_secret: str | None = None
    max_query_bytes: int = 1024 * 1024

    @classmethod
    def from_env(cls) -> HogQLServiceConfig:
        return cls(
            host=os.environ.get("HOGQL_SERVICE_HOST", "0.0.0.0"),
            port=int(os.environ.get("HOGQL_SERVICE_PORT", "6543")),
            shared_secret=os.environ.get("HOGQL_SERVICE_SHARED_SECRET") or None,
            max_query_bytes=int(os.environ.get("HOGQL_SERVICE_MAX_QUERY_BYTES", str(1024 * 1024))),
        )


@dataclass(frozen=True)
class HogQLServiceSessionContext:
    database_user: str
    database: str
    user: User
    team: Team
    authenticated_by: Literal["shared_secret", "personal_api_key"]
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
        team = self._get_team(database)

        if self.shared_secret and hmac.compare_digest(password, self.shared_secret):
            user = self._get_database_user(database_user)
            self._validate_user_team_access(user, team)
            return HogQLServiceSessionContext(
                database_user=database_user,
                database=database,
                user=user,
                team=team,
                authenticated_by="shared_secret",
            )

        personal_api_key = self._validate_personal_api_key(password)
        user = personal_api_key.user
        if user is None:
            raise HogQLServiceAuthenticationError("Invalid personal API key.")
        if not self._database_user_matches_user(database_user, user):
            raise HogQLServiceAuthenticationError("Database user does not match the personal API key owner.")

        self._validate_personal_api_key_access(personal_api_key, team)
        self._validate_user_team_access(user, team)
        self._mark_personal_api_key_used(personal_api_key)
        return HogQLServiceSessionContext(
            database_user=database_user,
            database=database,
            user=user,
            team=team,
            authenticated_by="personal_api_key",
            personal_api_key_id=personal_api_key.id,
        )

    def _get_team(self, database: str) -> Team:
        try:
            team_id = int(database)
        except ValueError as error:
            raise HogQLServiceAuthenticationError("Database must be a PostHog team_id.") from error

        try:
            return Team.objects.select_related("organization").get(pk=team_id)
        except Team.DoesNotExist as error:
            raise HogQLServiceAuthenticationError("Database must be a PostHog team_id.") from error

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


class HogQLServiceQueryExecutor:
    def execute(self, sql: str, context: HogQLServiceSessionContext) -> QueryResult:
        stripped_sql = sql.strip()
        if not stripped_sql:
            return QueryResult(columns=[], rows=[], command_tag="")

        builtin_result = self._execute_builtin_query(stripped_sql, context)
        if builtin_result is not None:
            return builtin_result

        try:
            query_ast = parse_select(stripped_sql, cache_origin=CacheOrigin.USER)
            validate_user_query(query_ast, team=context.team)
            response = execute_hogql_query(
                query=query_ast,
                team=context.team,
                user=context.user,
                query_type="hogql_service",
                limit_context=LimitContext.QUERY,
                pretty=False,
            )
        except (ExposedHogQLError, QueryError, ResolutionError, ValueError) as error:
            raise HogQLServiceQueryError(str(error)) from error

        if response.error:
            raise HogQLServiceQueryError(response.error)

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

        show_value = self._show_value(normalized, context)
        if show_value is not None:
            parameter_name, value = show_value
            return QueryResult(
                columns=[ResultColumn(name=parameter_name)],
                rows=[(value,)],
                command_tag="SHOW",
            )

        builtin_select = self._builtin_select(normalized, context)
        if builtin_select is not None:
            columns, rows = builtin_select
            return QueryResult(
                columns=[ResultColumn(name=column) for column in columns],
                rows=rows,
                command_tag=f"SELECT {len(rows)}",
            )

        return None

    def _show_value(self, normalized: str, context: HogQLServiceSessionContext) -> tuple[str, str] | None:
        values = {
            "server_version": "16.0 (PostHog HogQL service)",
            "server_encoding": "UTF8",
            "client_encoding": "UTF8",
            "datestyle": "ISO, MDY",
            "standard_conforming_strings": "on",
            "integer_datetimes": "on",
            "timezone": context.team.timezone,
            "transaction_isolation": "read committed",
            "default_transaction_read_only": "on",
        }
        match = re.fullmatch(r"show\s+([a-zA-Z_][a-zA-Z0-9_]*)", normalized)
        if not match:
            return None
        parameter_name = match.group(1)
        value = values.get(parameter_name)
        if value is None:
            return None
        return parameter_name, value

    def _builtin_select(
        self, normalized: str, context: HogQLServiceSessionContext
    ) -> tuple[list[str], list[tuple[Any, ...]]] | None:
        if normalized in {"select version()", "select pg_catalog.version()"}:
            return ["version"], [("PostgreSQL 16.0 compatible PostHog HogQL service",)]
        if normalized in {"select current_database()", "select pg_catalog.current_database()"}:
            return ["current_database"], [(context.database,)]
        if normalized in {"select current_schema()", "select pg_catalog.current_schema()"}:
            return ["current_schema"], [("public",)]
        if normalized in {"select current_user", "select session_user"}:
            return ["current_user"], [(context.database_user,)]
        return None


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
            if length < 8:
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
                self.writer.write(PostgresWireCodec.error_response(str(error), error.sqlstate))
                if message_type != b"Q":
                    self.skip_until_sync = True
                else:
                    self.writer.write(PostgresWireCodec.ready_for_query())
                await self.writer.drain()

    async def _read_message(self) -> tuple[bytes, bytes] | None:
        message_type = await self.reader.read(1)
        if not message_type:
            return None
        length_bytes = await self.reader.readexactly(4)
        length = struct.unpack("!I", length_bytes)[0]
        if length < 4:
            raise HogQLServiceProtocolError("Invalid message length.")
        payload = await self.reader.readexactly(length - 4)
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
        return await asyncio.to_thread(self.query_executor.execute, sql, self.context)

    async def _send_result(self, result: QueryResult, send_row_description: bool) -> None:
        if send_row_description and result.columns:
            self.writer.write(PostgresWireCodec.row_description(result.columns))
        for row in result.rows:
            self.writer.write(PostgresWireCodec.data_row(row))
        self.writer.write(PostgresWireCodec.command_complete(result.command_tag))
        await self.writer.drain()


class HogQLPostgresServer:
    def __init__(self, config: HogQLServiceConfig):
        self.config = config
        self.authenticator = HogQLServiceAuthenticator(shared_secret=config.shared_secret)
        self.query_executor = HogQLServiceQueryExecutor()

    async def serve_forever(self) -> None:
        server = await asyncio.start_server(self._handle_client, self.config.host, self.config.port)
        addresses = ", ".join(str(socket.getsockname()) for socket in server.sockets or [])
        logger.info("HogQL Postgres wire service listening", extra={"addresses": addresses})
        async with server:
            await server.serve_forever()

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
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
