import os
import struct
import asyncio
from types import SimpleNamespace
from typing import Any, cast

import pytest
from posthog.test.base import BaseTest
from unittest.mock import patch

import psycopg
from parameterized import parameterized

from posthog.schema import HogQLQueryResponse

from posthog.hogql.service import (
    MAX_STARTUP_PACKET_BYTES,
    MAX_UNAUTHENTICATED_MESSAGE_BYTES,
    POSTGRES_INT8_OID,
    CatalogTable,
    HogQLPostgresWireSession,
    HogQLServiceAuthenticationError,
    HogQLServiceAuthenticator,
    HogQLServiceConfig,
    HogQLServicePermissionError,
    HogQLServiceProtocolError,
    HogQLServiceQueryExecutor,
    HogQLServiceSessionContext,
    PgParameter,
    QueryResult,
    ResultColumn,
    bind_parameters_to_query,
    catalog_table_name,
    is_loopback_host,
    is_loopback_peer,
    parse_database_name,
    rewrite_catalog_table_references,
    rewrite_postgres_pseudo_columns,
    stable_catalog_oid,
)

from posthog.models import Organization, PersonalAPIKey, Team, User
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.data_warehouse.backend.models import ExternalDataSource
from products.data_warehouse.backend.types import ExternalDataSourceType


class TestHogQLServiceAuthenticator(BaseTest):
    def _create_personal_api_key(
        self, scopes: list[str], scoped_teams: list[int] | None = None, scoped_organizations: list[str] | None = None
    ) -> str:
        token = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="HogQL service",
            user=self.user,
            secure_value=hash_key_value(token),
            scopes=scopes,
            scoped_teams=scoped_teams,
            scoped_organizations=scoped_organizations,
        )
        return token

    def test_shared_secret_authenticates_database_user_for_database_team_id(self) -> None:
        context = HogQLServiceAuthenticator(shared_secret="secret").authenticate(
            self.user.email, str(self.team.id), "secret"
        )

        assert context.user == self.user
        assert context.team == self.team
        assert context.authenticated_by == "shared_secret"
        assert context.connection_id is None

    def test_shared_secret_accepts_database_with_direct_connection_id(self) -> None:
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_id="source",
            connection_id="connection",
            destination_id="destination",
            status=ExternalDataSource.Status.RUNNING,
            source_type=ExternalDataSourceType.POSTGRES,
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            job_inputs={},
        )

        context = HogQLServiceAuthenticator(shared_secret="secret").authenticate(
            self.user.email, f"{self.team.id}/{source.id}", "secret"
        )

        assert context.user == self.user
        assert context.team == self.team
        assert context.database == f"{self.team.id}/{source.id}"
        assert context.connection_id == str(source.id)

    def test_shared_secret_rejects_connection_id_from_another_team(self) -> None:
        other_team = Team.objects.create(organization=self.organization)
        source = ExternalDataSource.objects.create(
            team=other_team,
            source_id="source",
            connection_id="connection",
            destination_id="destination",
            status=ExternalDataSource.Status.RUNNING,
            source_type=ExternalDataSourceType.POSTGRES,
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            job_inputs={},
        )

        with self.assertRaises(HogQLServiceAuthenticationError):
            HogQLServiceAuthenticator(shared_secret="secret").authenticate(
                self.user.email, f"{self.team.id}/{source.id}", "secret"
            )

    def test_shared_secret_rejects_user_without_project_access(self) -> None:
        organization = Organization.objects.create(name="Other")
        team = Team.objects.create(organization=organization)

        with self.assertRaises(HogQLServicePermissionError):
            HogQLServiceAuthenticator(shared_secret="secret").authenticate(self.user.email, str(team.id), "secret")

    def test_personal_api_key_authenticates_user_with_query_scope(self) -> None:
        token = self._create_personal_api_key(["query:read"])

        context = HogQLServiceAuthenticator().authenticate(self.user.email, str(self.team.id), token)

        assert context.user == self.user
        assert context.team == self.team
        assert context.authenticated_by == "personal_api_key"

    def test_personal_api_key_rejects_database_user_mismatch(self) -> None:
        token = self._create_personal_api_key(["query:read"])

        with self.assertRaises(HogQLServiceAuthenticationError):
            HogQLServiceAuthenticator().authenticate("someone@example.com", str(self.team.id), token)

    def test_personal_api_key_requires_query_scope(self) -> None:
        token = self._create_personal_api_key(["dashboard:read"])

        with self.assertRaises(HogQLServicePermissionError):
            HogQLServiceAuthenticator().authenticate(self.user.email, str(self.team.id), token)

    def test_personal_api_key_respects_scoped_teams(self) -> None:
        other_team = Team.objects.create(organization=self.organization)
        token = self._create_personal_api_key(["query:read"], scoped_teams=[other_team.id])

        with self.assertRaises(HogQLServicePermissionError):
            HogQLServiceAuthenticator().authenticate(self.user.email, str(self.team.id), token)


class TestHogQLServiceQueryExecutor(BaseTest):
    def _context(self) -> HogQLServiceSessionContext:
        return HogQLServiceSessionContext(
            database_user=self.user.email,
            database=str(self.team.id),
            user=self.user,
            team=self.team,
            authenticated_by="shared_secret",
        )

    def test_builtin_show_query_returns_postgres_wire_setting(self) -> None:
        result = HogQLServiceQueryExecutor().execute("SHOW server_version;", self._context())

        assert [column.name for column in result.columns] == ["server_version"]
        assert result.rows == [("16.0 (PostHog HogQL service)",)]
        assert result.command_tag == "SHOW"

    def test_builtin_timestamp_probe_supports_postgres_extract_epoch(self) -> None:
        result = HogQLServiceQueryExecutor().execute(
            "select round(extract(epoch from current_timestamp) * 1000)",
            self._context(),
        )

        assert [column.name for column in result.columns] == ["round"]
        assert isinstance(result.rows[0][0], int)

    def test_information_schema_tables_lists_hogql_tables(self) -> None:
        result = HogQLServiceQueryExecutor().execute(
            "SELECT table_schema, table_name, table_type FROM information_schema.tables WHERE table_schema = 'public'",
            self._context(),
        )

        assert ("public", "events", "BASE TABLE") in result.rows

    def test_information_schema_columns_lists_hogql_columns(self) -> None:
        result = HogQLServiceQueryExecutor().execute(
            "SELECT table_schema, table_name, column_name, data_type FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'events'",
            self._context(),
        )

        assert ("public", "events", "event", "text") in result.rows

    def test_pg_catalog_class_projection_uses_requested_aliases(self) -> None:
        result = HogQLServiceQueryExecutor().execute(
            "SELECT NULL AS TABLE_CAT, n.nspname AS TABLE_SCHEM, c.relname AS TABLE_NAME, "
            "CASE c.relkind WHEN 'v' THEN 'VIEW' ELSE 'TABLE' END AS TABLE_TYPE "
            "FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'public'",
            self._context(),
        )

        assert [column.name for column in result.columns] == ["table_cat", "table_schem", "table_name", "table_type"]
        assert (None, "public", "events", "BASE TABLE") in result.rows

    def test_pg_catalog_class_ignores_empty_joined_catalog_tables(self) -> None:
        result = HogQLServiceQueryExecutor().execute(
            "SELECT c.relname AS TABLE_NAME, d.description AS REMARKS "
            "FROM pg_catalog.pg_class c "
            "LEFT JOIN pg_catalog.pg_description d ON d.objoid = c.oid "
            "WHERE c.relname = 'events'",
            self._context(),
        )

        assert ("events", None) in result.rows

    def test_unknown_pg_catalog_table_returns_empty_result(self) -> None:
        result = HogQLServiceQueryExecutor().execute(
            "SELECT * FROM pg_catalog.pg_stat_activity",
            self._context(),
        )

        assert [column.name for column in result.columns] == [
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
        ]
        assert result.rows == []

    def test_catalog_source_detection_skips_nested_from_expression(self) -> None:
        result = HogQLServiceQueryExecutor().execute(
            "SELECT E.oid AS id, array(SELECT unnest FROM unnest(available_versions)) AS available_updates "
            "FROM pg_catalog.pg_extension E",
            self._context(),
        )

        assert [column.name for column in result.columns] == ["id", "available_updates"]
        assert result.rows == []

    def test_pg_catalog_class_translates_relkind_for_object_list(self) -> None:
        schema_oid = stable_catalog_oid("schema:public")
        result = HogQLServiceQueryExecutor().execute(
            f"SELECT T.oid AS oid, relnamespace AS schemaId, "
            "pg_catalog.translate(relkind, 'rmvpfS', 'rmvrfS') AS kind, relname AS name "
            "FROM pg_catalog.pg_class T "
            f"WHERE relnamespace IN ( {schema_oid} ) AND relkind IN ('r', 'm', 'v', 'p', 'f', 'S')",
            self._context(),
        )

        assert [column.name for column in result.columns] == ["oid", "schemaid", "kind", "name"]
        assert any(row[3] == "events" for row in result.rows)
        assert all(row[1] == schema_oid for row in result.rows)
        assert {row[2] for row in result.rows} <= {"r", "m", "v", "f", "S"}

    def test_pg_catalog_namespace_returns_non_null_state_number(self) -> None:
        result = HogQLServiceQueryExecutor().execute(
            "SELECT N.oid::bigint AS id, N.xmin AS state_number, nspname AS name FROM pg_catalog.pg_namespace N",
            self._context(),
        )

        assert ("public",) in [(row[2],) for row in result.rows]
        assert all(isinstance(row[1], int) for row in result.rows)

    def test_pg_catalog_attribute_cte_uses_outer_select_list(self) -> None:
        schema_oid = stable_catalog_oid("schema:public")
        result = HogQLServiceQueryExecutor().execute(
            "WITH T AS ( SELECT DISTINCT T.oid AS table_id, T.relname AS table_name "
            "FROM pg_catalog.pg_class T, pg_catalog.pg_attribute A "
            f"WHERE T.relnamespace = {schema_oid}::oid AND T.relkind IN ('r', 'm', 'v', 'f', 'p') "
            "AND A.attrelid = T.oid ) "
            "SELECT T.table_id, C.attnum AS column_position, C.attname AS column_name, "
            "C.xmin AS column_state_number, pg_catalog.format_type(C.atttypid, C.atttypmod) AS type_spec, "
            "NOT C.attislocal AS column_is_inherited "
            "FROM T JOIN pg_catalog.pg_attribute C ON T.table_id = C.attrelid "
            "WHERE attnum > 0 ORDER BY table_id, attnum",
            self._context(),
        )

        assert [column.name for column in result.columns] == [
            "table_id",
            "column_position",
            "column_name",
            "column_state_number",
            "type_spec",
            "column_is_inherited",
        ]
        assert any(row[2] == "event" and row[3] == 1 and row[5] is False for row in result.rows)

    def test_pg_catalog_attribute_cte_returns_schema_id_for_object_list_columns(self) -> None:
        schema_oid = stable_catalog_oid("schema:public")
        result = HogQLServiceQueryExecutor().execute(
            "WITH T AS ( SELECT T.oid AS oid, T.relkind AS kind, T.relnamespace AS schemaId "
            "FROM pg_catalog.pg_class T "
            f"WHERE T.relnamespace IN ( {schema_oid} ) AND T.relkind IN ('r', 'm', 'v', 'f', 'p') ) "
            "SELECT T.schemaId AS schemaId, T.oid AS majorOid, "
            "pg_catalog.translate(T.kind, 'rmvpf', 'rmvrf') AS kind, "
            "C.attnum AS position, C.attname AS name "
            "FROM T JOIN pg_catalog.pg_attribute C ON T.oid = C.attrelid "
            "WHERE C.attnum > 0 AND NOT C.attisdropped "
            "ORDER BY schemaId, majorOid",
            self._context(),
        )

        assert [column.name for column in result.columns] == ["schemaid", "majoroid", "kind", "position", "name"]
        assert any(row[4] == "event" for row in result.rows)
        assert all(row[0] == schema_oid for row in result.rows)
        assert all(row[1] is not None for row in result.rows)

    def test_pg_user_privilege_probe_returns_current_user(self) -> None:
        result = HogQLServiceQueryExecutor().execute(
            "SELECT usesuper FROM pg_user WHERE usename = current_user",
            self._context(),
        )

        assert result.rows == [(False,)]

    def test_builtin_current_txid_probe_returns_zero(self) -> None:
        result = HogQLServiceQueryExecutor().execute(
            "select case when pg_catalog.pg_is_in_recovery() then null "
            "else (pg_catalog.txid_current() % 4294967296)::varchar::bigint end as current_txid",
            self._context(),
        )

        assert [column.name for column in result.columns] == ["current_txid"]
        assert result.rows == [(0,)]

    @patch("posthog.hogql.service.execute_hogql_query")
    def test_hogql_query_executes_as_connection_user_and_team(self, mock_execute_hogql_query) -> None:
        mock_execute_hogql_query.return_value = HogQLQueryResponse(
            results=[(1,)],
            columns=["one"],
            types=[("one", "Int64")],
        )

        result = HogQLServiceQueryExecutor().execute("SELECT event FROM events LIMIT 1", self._context())

        assert result.rows == [(1,)]
        assert result.columns[0].name == "one"
        assert mock_execute_hogql_query.call_args.kwargs["team"] == self.team
        assert mock_execute_hogql_query.call_args.kwargs["user"] == self.user
        assert mock_execute_hogql_query.call_args.kwargs["query_type"] == "hogql_service"
        assert mock_execute_hogql_query.call_args.kwargs["connection_id"] is None

    @patch("posthog.hogql.service.execute_hogql_query")
    def test_hogql_query_passes_connection_id(self, mock_execute_hogql_query) -> None:
        mock_execute_hogql_query.return_value = HogQLQueryResponse(results=[(1,)], columns=["one"])

        context = HogQLServiceSessionContext(
            database_user=self.user.email,
            database=f"{self.team.id}/018f0000-0000-7000-8000-000000000000",
            user=self.user,
            team=self.team,
            authenticated_by="shared_secret",
            connection_id="018f0000-0000-7000-8000-000000000000",
        )
        HogQLServiceQueryExecutor().execute("SELECT event FROM events LIMIT 1", context)

        assert mock_execute_hogql_query.call_args.kwargs["connection_id"] == "018f0000-0000-7000-8000-000000000000"

    @patch("posthog.hogql.service.execute_hogql_query")
    def test_hogql_query_rewrites_postgres_ctid_pseudo_column(self, mock_execute_hogql_query) -> None:
        mock_execute_hogql_query.return_value = HogQLQueryResponse(results=[(None,)], columns=["ctid"])

        HogQLServiceQueryExecutor().execute("SELECT t.*, CTID FROM public.events t LIMIT 501", self._context())

        assert mock_execute_hogql_query.call_args.kwargs["team"] == self.team


class TestHogQLServiceParameters(BaseTest):
    def test_config_defaults_to_loopback_host(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            assert HogQLServiceConfig().host == "127.0.0.1"
            assert HogQLServiceConfig.from_env().host == "127.0.0.1"

    def test_parse_database_name_accepts_team_id(self) -> None:
        assert parse_database_name("123") == ("123", None)

    def test_parse_database_name_accepts_team_id_and_connection_id(self) -> None:
        assert parse_database_name("123/018f0000-0000-7000-8000-000000000000") == (
            "123",
            "018f0000-0000-7000-8000-000000000000",
        )

    def test_parse_database_name_rejects_invalid_combo(self) -> None:
        with self.assertRaises(HogQLServiceAuthenticationError):
            parse_database_name("123/")

    def test_bind_parameters_replaces_numbered_placeholders_outside_literals(self) -> None:
        query = "SELECT $1, '$1', \"$1\", `$1`, -- $1\n$2"

        bound = bind_parameters_to_query(query, [PgParameter("a'b"), PgParameter(42)])

        assert bound == "SELECT 'a\\'b', '$1', \"$1\", `$1`, -- $1\n42"

    def test_bind_parameters_rejects_missing_parameter(self) -> None:
        with self.assertRaises(Exception) as error:
            bind_parameters_to_query("SELECT $2", [PgParameter("one")])

        assert "Missing bind parameter $2" in str(error.exception)

    def test_rewrite_postgres_pseudo_columns_replaces_ctid(self) -> None:
        assert (
            rewrite_postgres_pseudo_columns("SELECT t.*, CTID FROM public.events t LIMIT 501")
            == "SELECT t.*, NULL AS ctid FROM public.events t LIMIT 501"
        )

    def test_catalog_table_name_flattens_hogql_multipart_names(self) -> None:
        assert catalog_table_name("bigquery.bqds.sometable") == ("bigquery_bqds", "sometable")

    @parameterized.expand(
        [
            ("localhost", True),
            ("127.0.0.1", True),
            ("::1", True),
            ("0.0.0.0", False),
            ("192.168.1.10", False),
        ]
    )
    def test_is_loopback_host(self, host: str, expected: bool) -> None:
        assert is_loopback_host(host) is expected

    @parameterized.expand(
        [
            (("127.0.0.1", 5432), True),
            (("::1", 5432, 0, 0), True),
            (("::ffff:127.0.0.1", 5432, 0, 0), True),
            (("192.168.1.10", 5432), False),
            (None, False),
        ]
    )
    def test_is_loopback_peer(self, peername: object, expected: bool) -> None:
        assert is_loopback_peer(peername) is expected

    def test_rewrite_catalog_table_references_accepts_safe_and_cached_multipart_names(self) -> None:
        table = CatalogTable(
            oid=1,
            schema="bigquery_bqds",
            name="sometable33",
            hogql_name="bigquery.bqds.sometable33",
            table_type="BASE TABLE",
            fields=[],
        )
        context = HogQLServiceSessionContext(
            database_user="user@example.com",
            database="1",
            user=cast(User, SimpleNamespace(email="user@example.com")),
            team=cast(Team, SimpleNamespace(id=1, timezone="UTC")),
            authenticated_by="shared_secret",
        )

        with patch("posthog.hogql.service.load_catalog_tables", return_value=[table]):
            assert (
                rewrite_catalog_table_references("SELECT * FROM bigquery_bqds.sometable33 t", context)
                == "SELECT * FROM bigquery.bqds.sometable33 t"
            )
            assert (
                rewrite_catalog_table_references('SELECT * FROM bigquery."bqds.sometable33" t', context)
                == "SELECT * FROM bigquery.bqds.sometable33 t"
            )


class FakeAuthenticator:
    def authenticate(self, database_user: str, database: str, password: str) -> HogQLServiceSessionContext:
        return HogQLServiceSessionContext(
            database_user=database_user,
            database=database,
            user=cast(User, SimpleNamespace(email=database_user)),
            team=cast(Team, SimpleNamespace(id=int(database), timezone="UTC")),
            authenticated_by="shared_secret",
        )


class FakeQueryExecutor:
    def execute(self, sql: str, context: HogQLServiceSessionContext) -> QueryResult:
        return QueryResult(
            columns=[ResultColumn(name="answer", type_oid=POSTGRES_INT8_OID)],
            rows=[(42,)],
            command_tag="SELECT 1",
        )


class FakeWriter:
    def __init__(self) -> None:
        self.writes: list[bytes] = []

    def write(self, data: bytes) -> None:
        self.writes.append(data)

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        return None

    async def wait_closed(self) -> None:
        return None

    def get_extra_info(self, name: str) -> object:
        if name == "peername":
            return ("127.0.0.1", 5432)
        return None


def _session_with_wire_data(data: bytes, *, max_query_bytes: int = 1024) -> HogQLPostgresWireSession:
    reader = asyncio.StreamReader()
    reader.feed_data(data)
    reader.feed_eof()
    return HogQLPostgresWireSession(
        reader=reader,
        writer=cast(asyncio.StreamWriter, FakeWriter()),
        authenticator=FakeAuthenticator(),
        query_executor=FakeQueryExecutor(),
        max_query_bytes=max_query_bytes,
    )


@pytest.mark.asyncio
async def test_postgres_wire_session_rejects_oversized_startup_packet_before_payload_read() -> None:
    session = _session_with_wire_data(struct.pack("!I", MAX_STARTUP_PACKET_BYTES + 1))

    with pytest.raises(HogQLServiceProtocolError, match="Invalid startup packet"):
        await session._read_startup_parameters()


@pytest.mark.asyncio
async def test_postgres_wire_session_rejects_oversized_unauthenticated_message_before_payload_read() -> None:
    length = MAX_UNAUTHENTICATED_MESSAGE_BYTES + 5
    session = _session_with_wire_data(b"p" + struct.pack("!I", length))

    with pytest.raises(HogQLServiceProtocolError, match="Message is too large"):
        await session._read_message()


@pytest.mark.asyncio
async def test_postgres_wire_session_rejects_authenticated_message_above_query_limit_before_payload_read() -> None:
    session = _session_with_wire_data(b"Q" + struct.pack("!I", 15), max_query_bytes=10)
    session.context = HogQLServiceSessionContext(
        database_user="user@example.com",
        database="1",
        user=cast(User, SimpleNamespace(email="user@example.com")),
        team=cast(Team, SimpleNamespace(id=1, timezone="UTC")),
        authenticated_by="shared_secret",
    )

    with pytest.raises(HogQLServiceProtocolError, match="Message is too large"):
        await session._read_message()


@pytest.mark.asyncio
async def test_postgres_wire_session_accepts_psycopg_extended_query() -> None:
    async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        session = HogQLPostgresWireSession(
            reader=reader,
            writer=writer,
            authenticator=FakeAuthenticator(),
            query_executor=FakeQueryExecutor(),
            max_query_bytes=1024,
        )
        await session.run()

    server = await asyncio.start_server(handle_client, "127.0.0.1", 0)
    assert server.sockets is not None
    port = server.sockets[0].getsockname()[1]

    def run_query() -> tuple[list[tuple[Any, ...]], list[str]]:
        with psycopg.connect(
            host="127.0.0.1",
            port=port,
            dbname="1",
            user="user@example.com",
            password="secret",
            sslmode="disable",
        ) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 42 AS answer")
                return cursor.fetchall(), [column.name for column in cursor.description or []]

    try:
        rows, columns = await asyncio.to_thread(run_query)
    finally:
        server.close()
        await server.wait_closed()

    assert rows == [(42,)]
    assert columns == ["answer"]
