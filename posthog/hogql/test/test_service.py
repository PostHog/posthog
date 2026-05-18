import asyncio
from types import SimpleNamespace
from typing import Any, cast

import pytest
from posthog.test.base import BaseTest
from unittest.mock import patch

import psycopg

from posthog.schema import HogQLQueryResponse

from posthog.hogql.service import (
    POSTGRES_INT8_OID,
    HogQLPostgresWireSession,
    HogQLServiceAuthenticationError,
    HogQLServiceAuthenticator,
    HogQLServicePermissionError,
    HogQLServiceQueryExecutor,
    HogQLServiceSessionContext,
    PgParameter,
    QueryResult,
    ResultColumn,
    bind_parameters_to_query,
)

from posthog.models import Organization, PersonalAPIKey, Team, User
from posthog.models.utils import generate_random_token_personal, hash_key_value


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

    @patch("posthog.hogql.service.execute_hogql_query")
    def test_hogql_query_executes_as_connection_user_and_team(self, mock_execute_hogql_query) -> None:
        mock_execute_hogql_query.return_value = HogQLQueryResponse(
            results=[(1,)],
            columns=["one"],
            types=[("one", "Int64")],
        )

        result = HogQLServiceQueryExecutor().execute("SELECT 1 AS one", self._context())

        assert result.rows == [(1,)]
        assert result.columns[0].name == "one"
        assert mock_execute_hogql_query.call_args.kwargs["team"] == self.team
        assert mock_execute_hogql_query.call_args.kwargs["user"] == self.user
        assert mock_execute_hogql_query.call_args.kwargs["query_type"] == "hogql_service"


class TestHogQLServiceParameters(BaseTest):
    def test_bind_parameters_replaces_numbered_placeholders_outside_literals(self) -> None:
        query = "SELECT $1, '$1', \"$1\", `$1`, -- $1\n$2"

        bound = bind_parameters_to_query(query, [PgParameter("a'b"), PgParameter(42)])

        assert bound == "SELECT 'a\\'b', '$1', \"$1\", `$1`, -- $1\n42"

    def test_bind_parameters_rejects_missing_parameter(self) -> None:
        with self.assertRaises(Exception) as error:
            bind_parameters_to_query("SELECT $2", [PgParameter("one")])

        assert "Missing bind parameter $2" in str(error.exception)


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
