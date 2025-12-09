import uuid

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from rest_framework import status

from products.data_warehouse.backend.models import ExternalDataSource
from products.data_warehouse.backend.services import DirectQueryExecutor
from products.data_warehouse.backend.services.direct_query_executor import QueryResult, SchemaInfo


class TestDirectQueryAPI(APIBaseTest):
    def _create_query_only_source(self) -> ExternalDataSource:
        return ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            source_type="Postgres",
            created_by=self.user,
            prefix="test_db",
            query_only=True,
            job_inputs={
                "host": "localhost",
                "port": 5432,
                "database": "test_db",
                "user": "test_user",
                "password": "test_pass",
                "schema": "public",
            },
        )

    def test_list_sources_returns_only_query_only_sources(self):
        # Create a query-only source
        query_only_source = self._create_query_only_source()

        # Create a regular source (not query-only)
        ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            source_type="Stripe",
            created_by=self.user,
            prefix="stripe",
            query_only=False,
        )

        response = self.client.get(f"/api/environments/{self.team.pk}/direct_query/sources/")

        assert response.status_code == status.HTTP_200_OK
        assert len(response.json()["sources"]) == 1
        assert response.json()["sources"][0]["id"] == str(query_only_source.pk)

    def test_execute_requires_source_id(self):
        response = self.client.post(
            f"/api/environments/{self.team.pk}/direct_query/execute/",
            data={"sql": "SELECT 1"},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["error"] == "source_id is required"

    def test_execute_requires_sql(self):
        source = self._create_query_only_source()

        response = self.client.post(
            f"/api/environments/{self.team.pk}/direct_query/execute/",
            data={"source_id": str(source.pk)},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["error"] == "sql is required"

    def test_execute_returns_404_for_nonexistent_source(self):
        response = self.client.post(
            f"/api/environments/{self.team.pk}/direct_query/execute/",
            data={"source_id": str(uuid.uuid4()), "sql": "SELECT 1"},
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.json()["error"] == "Query-only source not found"

    def test_execute_returns_404_for_non_query_only_source(self):
        # Create a regular source (not query-only)
        source = ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            source_type="Stripe",
            created_by=self.user,
            prefix="stripe",
            query_only=False,
        )

        response = self.client.post(
            f"/api/environments/{self.team.pk}/direct_query/execute/",
            data={"source_id": str(source.pk), "sql": "SELECT 1"},
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.json()["error"] == "Query-only source not found"

    @patch.object(DirectQueryExecutor, "execute_query")
    def test_execute_returns_query_results(self, mock_execute):
        source = self._create_query_only_source()

        mock_execute.return_value = QueryResult(
            columns=["id", "name"],
            types=["23", "25"],
            rows=[{"id": 1, "name": "test"}],
            row_count=1,
            execution_time_ms=10.5,
        )

        response = self.client.post(
            f"/api/environments/{self.team.pk}/direct_query/execute/",
            data={"source_id": str(source.pk), "sql": "SELECT id, name FROM users"},
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["columns"] == ["id", "name"]
        assert response.json()["rows"] == [{"id": 1, "name": "test"}]
        assert response.json()["row_count"] == 1
        assert response.json()["execution_time_ms"] == 10.5

    @patch.object(DirectQueryExecutor, "execute_query")
    def test_execute_returns_error_on_query_failure(self, mock_execute):
        source = self._create_query_only_source()

        mock_execute.return_value = QueryResult(
            columns=[],
            types=[],
            rows=[],
            row_count=0,
            execution_time_ms=5.0,
            error="Query timed out after 30 seconds.",
        )

        response = self.client.post(
            f"/api/environments/{self.team.pk}/direct_query/execute/",
            data={"source_id": str(source.pk), "sql": "SELECT * FROM huge_table"},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["error"] == "Query timed out after 30 seconds."
        assert response.json()["execution_time_ms"] == 5.0

    def test_get_schema_returns_404_for_nonexistent_source(self):
        response = self.client.get(
            f"/api/environments/{self.team.pk}/direct_query/schema/{uuid.uuid4()}/",
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.json()["error"] == "Query-only source not found"

    @patch.object(DirectQueryExecutor, "get_schema")
    def test_get_schema_returns_table_schema(self, mock_get_schema):
        source = self._create_query_only_source()

        mock_get_schema.return_value = SchemaInfo(
            tables={
                "users": [("id", "integer"), ("name", "character varying")],
                "orders": [("id", "integer"), ("user_id", "integer")],
            }
        )

        response = self.client.get(
            f"/api/environments/{self.team.pk}/direct_query/schema/{source.pk}/",
        )

        assert response.status_code == status.HTTP_200_OK
        assert "users" in response.json()["tables"]
        assert "orders" in response.json()["tables"]

    @patch.object(DirectQueryExecutor, "get_schema")
    def test_get_schema_handles_connection_errors(self, mock_get_schema):
        source = self._create_query_only_source()

        mock_get_schema.side_effect = RuntimeError("Failed to get schema: connection refused")

        response = self.client.get(
            f"/api/environments/{self.team.pk}/direct_query/schema/{source.pk}/",
        )

        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert response.json()["error"] == "Failed to retrieve schema. Please check your connection settings."

    def test_execute_respects_team_isolation(self):
        source = self._create_query_only_source()

        # Create another team and try to access the source
        other_team = self._create_other_team()

        response = self.client.post(
            f"/api/environments/{other_team.pk}/direct_query/execute/",
            data={"source_id": str(source.pk), "sql": "SELECT 1"},
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def _create_other_team(self):
        from posthog.models import Organization, Team

        org = Organization.objects.create(name="Other Org")
        org.members.add(self.user)
        return Team.objects.create(organization=org, name="Other Team")


class TestDirectQueryExecutor(APIBaseTest):
    def test_from_source_extracts_connection_params(self):
        source = ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            source_type="Postgres",
            created_by=self.user,
            prefix="mydb",
            query_only=True,
            job_inputs={
                "host": "db.example.com",
                "port": "5433",
                "database": "production",
                "user": "readonly_user",
                "password": "secret123",
                "schema": "analytics",
            },
        )

        executor = DirectQueryExecutor.from_source(source)

        assert executor.host == "db.example.com"
        assert executor.port == 5433
        assert executor.database == "production"
        assert executor.user == "readonly_user"
        assert executor.password == "secret123"
        assert executor.schema == "analytics"

    def test_from_source_uses_defaults_for_missing_params(self):
        source = ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            source_type="Postgres",
            created_by=self.user,
            prefix="mydb",
            query_only=True,
            job_inputs={
                "host": "localhost",
                "database": "test",
                "user": "user",
                "password": "pass",
            },
        )

        executor = DirectQueryExecutor.from_source(source)

        assert executor.port == 5432
        assert executor.schema == "public"

    @patch("products.data_warehouse.backend.services.direct_query_executor.psycopg.connect")
    def test_execute_query_sets_timeout_and_readonly(self, mock_connect):
        mock_cursor = MagicMock()
        mock_cursor.description = [MagicMock(name="id", type_code=23)]
        mock_cursor.fetchmany.return_value = [{"id": 1}]
        mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
        mock_cursor.__exit__ = MagicMock(return_value=False)

        mock_connection = MagicMock()
        mock_connection.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_connection

        executor = DirectQueryExecutor(
            host="localhost",
            port=5432,
            database="test",
            user="user",
            password="pass",
        )

        executor.execute_query("SELECT 1", timeout_seconds=60)

        # Verify SET statements were called
        calls = mock_cursor.execute.call_args_list
        assert any("statement_timeout" in str(call) and "60s" in str(call) for call in calls)
        assert any("default_transaction_read_only = ON" in str(call) for call in calls)

    @patch("products.data_warehouse.backend.services.direct_query_executor.psycopg.connect")
    def test_execute_query_sanitizes_password_errors(self, mock_connect):
        mock_connect.side_effect = Exception("password authentication failed for user postgres")

        executor = DirectQueryExecutor(
            host="localhost",
            port=5432,
            database="test",
            user="user",
            password="pass",
        )

        result = executor.execute_query("SELECT 1")

        assert result.error == "Connection failed. Please check your credentials."

    @patch("products.data_warehouse.backend.services.direct_query_executor.psycopg.connect")
    def test_execute_query_sanitizes_timeout_errors(self, mock_connect):
        mock_connect.side_effect = Exception("canceling statement due to statement timeout")

        executor = DirectQueryExecutor(
            host="localhost",
            port=5432,
            database="test",
            user="user",
            password="pass",
        )

        result = executor.execute_query("SELECT 1", timeout_seconds=30)

        assert result.error == "Query timed out after 30 seconds."
