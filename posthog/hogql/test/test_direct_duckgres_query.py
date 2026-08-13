from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

import psycopg
from parameterized import parameterized

from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.direct_sql import DuckgresRawAdapter, PostgresAdapter, get_adapter, get_raw_adapter_for_source
from posthog.hogql.errors import ExposedHogQLError
from posthog.hogql.query import HogQLQueryExecutor

from products.warehouse_sources.backend.facade.models import MANAGED_WAREHOUSE_SOURCE_PREFIX, ExternalDataSource
from products.warehouse_sources.backend.facade.types import ExternalDataSourceType


class TestDuckgresRawAdapterSelection(SimpleTestCase):
    def _source(self, **overrides: object) -> ExternalDataSource:
        source = ExternalDataSource(
            source_type=ExternalDataSourceType.POSTGRES,
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            direct_query_enabled=True,
            prefix=MANAGED_WAREHOUSE_SOURCE_PREFIX,
            connection_metadata={"engine": "duckdb", "system_managed": True},
        )
        for field, value in overrides.items():
            setattr(source, field, value)
        return source

    def test_selects_native_adapter_only_for_complete_managed_markers(self) -> None:
        self.assertIsInstance(get_raw_adapter_for_source(self._source()), DuckgresRawAdapter)
        self.assertIsInstance(
            get_raw_adapter_for_source(self._source(prefix="customer_postgres", connection_metadata={})),
            PostgresAdapter,
        )

    def test_managed_source_keeps_postgres_adapter_for_non_raw_queries(self) -> None:
        source = self._source()
        self.assertIsInstance(get_adapter(source.direct_engine), PostgresAdapter)

    @parameterized.expand(
        [
            ("missing_system_managed", {"connection_metadata": {"engine": "duckdb"}}),
            ("wrong_prefix", {"prefix": "ducklake"}),
            ("wrong_engine", {"connection_metadata": {"engine": "postgres", "system_managed": True}}),
            ("wrong_source_type", {"source_type": ExternalDataSourceType.MYSQL}),
            (
                "disabled_direct_query",
                {"access_method": ExternalDataSource.AccessMethod.WAREHOUSE, "direct_query_enabled": False},
            ),
        ]
    )
    def test_incomplete_managed_markers_do_not_select_native_adapter(
        self, _name: str, overrides: dict[str, object]
    ) -> None:
        self.assertNotIsInstance(get_raw_adapter_for_source(self._source(**overrides)), DuckgresRawAdapter)


class TestDirectDuckgresQuery(APIBaseTest):
    def _managed_source(self) -> ExternalDataSource:
        return ExternalDataSource.objects.create(
            team=self.team,
            source_id="managed-source",
            connection_id="managed-connection",
            status=ExternalDataSource.Status.COMPLETED,
            source_type=ExternalDataSourceType.POSTGRES,
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            direct_query_enabled=True,
            prefix=MANAGED_WAREHOUSE_SOURCE_PREFIX,
            job_inputs={
                "host": "stale.example.com",
                "port": 5432,
                "database": "stale",
                "user": "stale-user",
                "password": "stale-password",
            },
            connection_metadata={"engine": "duckdb", "system_managed": True},
        )

    @staticmethod
    def _connection_with_result(rows: list[tuple[object, ...]], type_code: int = 23) -> tuple[MagicMock, MagicMock]:
        cursor = MagicMock()
        cursor.fetchall.return_value = rows
        column = MagicMock(type_code=type_code)
        column.name = "value"
        cursor.description = [column]
        connection = MagicMock()
        connection.cursor.return_value.__enter__.return_value = cursor
        return connection, cursor

    @patch("posthog.hogql.direct_sql.duckgres_adapter.make_duckgres_conninfo", return_value="fresh-conninfo")
    @patch("posthog.hogql.direct_sql.duckgres_adapter.psycopg.connect")
    def test_executes_raw_managed_duckgres_without_hogql_or_source_registry(self, connect, make_conninfo) -> None:
        source = self._managed_source()
        connection, cursor = self._connection_with_result([(1,)])
        connect.return_value.__enter__.return_value = connection

        with (
            patch("posthog.hogql.direct_connection.Database.create_for", side_effect=AssertionError),
            patch.object(HogQLQueryExecutor, "_prepare_execution", side_effect=AssertionError),
            patch(
                "products.warehouse_sources.backend.facade.source_management.SourceRegistry.get_source",
                side_effect=AssertionError,
            ),
            patch.object(HogQLQueryExecutor, "_capture_send_raw_query_translation_error", side_effect=AssertionError),
        ):
            response = HogQLQueryExecutor(
                query="SELECT 1 AS value", team=self.team, connection_id=str(source.id), send_raw_query=True
            ).execute()

        self.assertEqual(response.results, [(1,)])
        self.assertEqual(response.columns, ["value"])
        self.assertEqual(response.types, [("value", "Int32")])
        make_conninfo.assert_called_once_with(team_id=self.team.id, organization_id=str(self.team.organization_id))
        connect.assert_called_once_with(
            "fresh-conninfo",
            connect_timeout=15,
            options="-c default_transaction_read_only=on -c statement_timeout=60000",
        )
        connection.execute.assert_called_once_with("USE ducklake")
        cursor.execute.assert_called_once_with("SELECT 1 AS value", None)

    @patch("posthog.hogql.direct_sql.duckgres_adapter.make_duckgres_conninfo", return_value="fresh-conninfo")
    @patch("posthog.hogql.direct_sql.duckgres_adapter.psycopg.connect")
    def test_preserves_timeout_and_empty_utility_results(self, connect, _make_conninfo) -> None:
        source = self._managed_source()
        connection, cursor = self._connection_with_result([])
        cursor.description = None
        connect.return_value.__enter__.return_value = connection

        response = HogQLQueryExecutor(
            query="SET TIME ZONE 'UTC'",
            team=self.team,
            connection_id=str(source.id),
            send_raw_query=True,
            settings=HogQLGlobalSettings(max_execution_time=12),
        ).execute()

        self.assertIsNone(response.error)
        self.assertEqual(response.results, [])
        self.assertEqual(response.columns, [])
        cursor.fetchall.assert_not_called()
        self.assertEqual(
            connect.call_args.kwargs["options"], "-c default_transaction_read_only=on -c statement_timeout=12000"
        )

    @patch("posthog.hogql.direct_sql.duckgres_adapter.make_duckgres_conninfo")
    @patch("posthog.hogql.direct_sql.duckgres_adapter.psycopg.connect")
    @patch("posthog.hogql.query.raw_query_denied_by_table_access", return_value=True)
    def test_table_access_denial_happens_before_credential_lookup(self, _denied, connect, make_conninfo) -> None:
        source = self._managed_source()

        with self.assertRaisesMessage(ExposedHogQLError, "You don't have access to every table"):
            HogQLQueryExecutor(
                query="SELECT 1", team=self.team, connection_id=str(source.id), send_raw_query=True
            ).execute()

        make_conninfo.assert_not_called()
        connect.assert_not_called()

    @patch("posthog.hogql.direct_sql.duckgres_adapter.make_duckgres_conninfo", return_value="fresh-conninfo")
    @patch("posthog.hogql.direct_sql.duckgres_adapter.psycopg.connect")
    def test_maps_driver_errors_to_a_single_safe_message(self, connect, _make_conninfo) -> None:
        source = self._managed_source()
        connect.side_effect = psycopg.OperationalError("query failed\nprivate driver detail")

        with self.assertRaisesMessage(ExposedHogQLError, "query failed"):
            HogQLQueryExecutor(
                query="SELECT 1", team=self.team, connection_id=str(source.id), send_raw_query=True
            ).execute()
