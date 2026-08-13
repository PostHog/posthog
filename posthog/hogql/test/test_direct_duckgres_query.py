import socket
from collections.abc import Generator

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

import psycopg
from parameterized import parameterized
from psycopg import pq

from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.direct_sql import DuckgresRawAdapter, PostgresAdapter, get_adapter, get_raw_adapter_for_source
from posthog.hogql.direct_sql.duckgres_adapter import _DuckgresStreamingClientCursor
from posthog.hogql.errors import ExposedHogQLError
from posthog.hogql.query import HogQLQueryExecutor

from posthog.constants import AvailableFeature
from posthog.models import OrganizationMembership

from products.managed_warehouse.backend.facade.api import persist_duckgres_server_for_org
from products.managed_warehouse.backend.models import DuckgresServer
from products.warehouse_sources.backend.facade.models import (
    MANAGED_WAREHOUSE_SOURCE_PREFIX,
    DataWarehouseTable,
    ExternalDataSource,
)
from products.warehouse_sources.backend.facade.types import ExternalDataSourceType

from ee.models import AccessControl


class TestDuckgresRawAdapterSelection(SimpleTestCase):
    def _source(self, **overrides: object) -> ExternalDataSource:
        source = ExternalDataSource(
            source_type=ExternalDataSourceType.POSTGRES,
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            direct_query_enabled=True,
            prefix=MANAGED_WAREHOUSE_SOURCE_PREFIX,
            connection_metadata={
                "engine": "duckdb",
                "system_managed": True,
            },
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
            (
                "wrong_engine",
                {
                    "connection_metadata": {
                        "engine": "postgres",
                        "system_managed": True,
                    }
                },
            ),
            ("wrong_source_type", {"source_type": ExternalDataSourceType.MYSQL}),
            (
                "disabled_direct_query",
                {"access_method": ExternalDataSource.AccessMethod.WAREHOUSE, "direct_query_enabled": False},
            ),
            (
                "synced_direct_query",
                {"access_method": ExternalDataSource.AccessMethod.WAREHOUSE, "direct_query_enabled": True},
            ),
        ]
    )
    def test_incomplete_managed_markers_do_not_select_native_adapter(
        self, _name: str, overrides: dict[str, object]
    ) -> None:
        self.assertNotIsInstance(get_raw_adapter_for_source(self._source(**overrides)), DuckgresRawAdapter)


class TestDuckgresStreamingClientCursor(SimpleTestCase):
    @parameterized.expand(
        [
            ("empty_query", pq.ExecStatus.EMPTY_QUERY),
            ("empty_select", pq.ExecStatus.TUPLES_OK),
            ("command", pq.ExecStatus.COMMAND_OK),
        ]
    )
    def test_retains_terminal_result(self, _name: str, status: pq.ExecStatus) -> None:
        terminal_result = MagicMock(status=status)
        results = iter([terminal_result, None])

        def fake_fetch(_connection: object) -> Generator[None, None, object | None]:
            if False:
                yield None
            return next(results)

        cursor = MagicMock()
        with patch("posthog.hogql.direct_sql.duckgres_adapter.fetch", side_effect=fake_fetch):
            self.assertEqual(list(_DuckgresStreamingClientCursor._stream_fetchone_gen(cursor, first=True)), [])

        cursor._set_results.assert_called_once_with([terminal_result])

    def test_streams_with_the_simple_query_protocol(self) -> None:
        postgres_query = object()

        def empty_generator(*_args: object, **_kwargs: object) -> Generator[None]:
            if False:
                yield None

        cursor = MagicMock()
        cursor._start_query.side_effect = empty_generator
        cursor._convert_query.return_value = postgres_query
        with patch("posthog.hogql.direct_sql.duckgres_adapter.send", side_effect=empty_generator):
            self.assertEqual(
                list(
                    _DuckgresStreamingClientCursor._stream_send_gen(
                        cursor,
                        "UPDATE example SET value = 1 RETURNING value",
                        size=1,
                    )
                ),
                [],
            )

        cursor._execute_send.assert_called_once_with(postgres_query, binary=None)
        cursor._pgconn.set_single_row_mode.assert_called_once()


class TestDirectDuckgresQuery(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        persist_duckgres_server_for_org(
            self.organization.id,
            host="managed.example.com",
            port=5432,
            database="ducklake",
            username="stored-login",
            password="secret",
        )

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
            connection_metadata={
                "engine": "duckdb",
                "system_managed": True,
            },
        )

    @staticmethod
    def _connection_with_result(rows: list[tuple[object, ...]], type_code: int = 23) -> tuple[MagicMock, MagicMock]:
        cursor = MagicMock()
        cursor.stream_closed = False

        def stream_rows() -> Generator[tuple[object, ...]]:
            try:
                yield from rows
            finally:
                cursor.stream_closed = True

        cursor.stream.return_value = stream_rows()
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
            cursor_factory=_DuckgresStreamingClientCursor,
        )
        connection.execute.assert_called_once_with("USE ducklake")
        cursor.stream.assert_called_once_with("SELECT 1 AS value", None)

    @patch("posthog.hogql.direct_sql.duckgres_adapter.make_duckgres_conninfo")
    @patch("posthog.hogql.direct_sql.duckgres_adapter.psycopg.connect")
    def test_rejects_multiple_statements_before_loading_credentials(self, connect, make_conninfo) -> None:
        source = self._managed_source()

        with self.assertRaisesMessage(ExposedHogQLError, "Raw queries must contain a single statement"):
            HogQLQueryExecutor(
                query="SELECT 1; SELECT 2",
                team=self.team,
                connection_id=str(source.id),
                send_raw_query=True,
            ).execute()

        make_conninfo.assert_not_called()
        connect.assert_not_called()

    @patch("posthog.hogql.direct_sql.duckgres_adapter.make_duckgres_conninfo", return_value="fresh-conninfo")
    @patch("posthog.hogql.direct_sql.duckgres_adapter.psycopg.connect")
    @patch("posthog.hogql.direct_sql.duckgres_adapter.threading.Timer")
    def test_schedules_cancellation_and_preserves_empty_utility_results(self, timer, connect, _make_conninfo) -> None:
        source = self._managed_source()
        connection, cursor = self._connection_with_result([])
        cursor.description = None
        connect.return_value.__enter__.return_value = connection
        connection.commit.side_effect = lambda: self.assertFalse(timer.return_value.cancel.called)

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
        cursor.stream.assert_called_once_with("SET TIME ZONE 'UTC'", None)
        self.assertEqual(timer.call_args.args[0], 12)
        connection.commit.assert_called_once_with()

    @patch("posthog.hogql.direct_sql.duckgres_adapter.make_duckgres_conninfo", return_value="fresh-conninfo")
    @patch("posthog.hogql.direct_sql.duckgres_adapter.psycopg.connect")
    def test_preserves_columns_for_an_empty_select(self, connect, _make_conninfo) -> None:
        source = self._managed_source()
        connection, _cursor = self._connection_with_result([])
        connect.return_value.__enter__.return_value = connection

        response = HogQLQueryExecutor(
            query="SELECT 1 AS value WHERE false",
            team=self.team,
            connection_id=str(source.id),
            send_raw_query=True,
        ).execute()

        self.assertEqual(response.results, [])
        self.assertEqual(response.columns, ["value"])
        self.assertEqual(response.types, [("value", "Int32")])

    @patch("posthog.hogql.direct_sql.duckgres_adapter.make_duckgres_conninfo", return_value="fresh-conninfo")
    @patch("posthog.hogql.direct_sql.duckgres_adapter.psycopg.connect")
    @patch("posthog.hogql.direct_sql.duckgres_adapter.threading.Timer")
    @patch("posthog.hogql.direct_sql.duckgres_adapter.socket.socket")
    def test_cancels_queries_at_the_execution_deadline(self, socket_factory, timer, connect, _make_conninfo) -> None:
        source = self._managed_source()
        connection, _cursor = self._connection_with_result([(1,)])
        connection.pgconn.socket = 42
        connect.return_value.__enter__.return_value = connection
        timer.return_value.start.side_effect = lambda: timer.call_args.args[1]()

        with self.assertRaisesMessage(ExposedHogQLError, "exceeded the execution time limit"):
            HogQLQueryExecutor(
                query="SELECT slow_value",
                team=self.team,
                connection_id=str(source.id),
                send_raw_query=True,
                settings=HogQLGlobalSettings(max_execution_time=12),
            ).execute()

        self.assertEqual(connection.cancel_safe.call_count, 3)
        connection.cancel_safe.assert_called_with(timeout=1)
        socket_factory.assert_called_once_with(fileno=42)
        socket_factory.return_value.shutdown.assert_called_once_with(socket.SHUT_RDWR)
        socket_factory.return_value.detach.assert_called_once_with()
        connection.close.assert_not_called()
        connection.commit.assert_not_called()

    def test_non_raw_managed_query_ignores_warehouse_object_access_control(self) -> None:
        source = self._managed_source()
        table = DataWarehouseTable.objects.create(
            name="managed_table",
            format="Parquet",
            team=self.team,
            external_data_source=source,
            url_pattern="",
            columns={"value": {"hogql": "IntegerDatabaseField", "clickhouse": "Int64", "valid": True}},
        )
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
        ]
        self.organization.save()
        membership = OrganizationMembership.objects.get(user=self.user, organization=self.organization)
        membership.level = OrganizationMembership.Level.MEMBER
        membership.save()
        AccessControl.objects.create(
            team=self.team,
            resource="warehouse_table",
            resource_id=str(table.id),
            access_level="none",
        )

        with patch(
            "posthog.hogql.database.database.feature_enabled_or_false",
            side_effect=lambda flag, *_args, **_kwargs: flag == "hogql-warehouse-access-control",
        ):
            sql, _context = HogQLQueryExecutor(
                query="SELECT value FROM managed_table",
                team=self.team,
                user=self.user,
                connection_id=str(source.id),
            ).generate_clickhouse_sql()

        self.assertIn("managed_table", sql)

    @patch("posthog.hogql.direct_sql.duckgres_adapter.make_duckgres_conninfo", return_value="fresh-conninfo")
    @patch("posthog.hogql.direct_sql.duckgres_adapter.psycopg.connect")
    @patch("posthog.hogql.query.raw_query_denied_by_table_access", side_effect=AssertionError)
    def test_managed_warehouse_raw_queries_skip_unconfigured_table_access(
        self, _denied, connect, _make_conninfo
    ) -> None:
        source = self._managed_source()
        connection, _cursor = self._connection_with_result([(1,)])
        connect.return_value.__enter__.return_value = connection

        response = HogQLQueryExecutor(
            query="SELECT 1", team=self.team, connection_id=str(source.id), send_raw_query=True
        ).execute()

        self.assertEqual(response.results, [(1,)])

    @patch("posthog.hogql.direct_sql.duckgres_adapter.make_duckgres_conninfo")
    @patch("posthog.hogql.direct_sql.duckgres_adapter.psycopg.connect")
    def test_hides_unavailable_warehouse_configuration(self, connect, make_conninfo) -> None:
        source = self._managed_source()
        make_conninfo.side_effect = ValueError("No DuckgresServer configured for organization secret-org")

        with self.assertRaisesMessage(ExposedHogQLError, "Managed warehouse is unavailable"):
            HogQLQueryExecutor(
                query="SELECT 1", team=self.team, connection_id=str(source.id), send_raw_query=True
            ).execute()

        connect.assert_not_called()

    @parameterized.expand(
        [
            ("raw", True),
            ("hogql", False),
        ]
    )
    @patch("posthog.hogql.direct_sql.postgres_adapter.psycopg.connect")
    @patch("posthog.hogql.direct_sql.duckgres_adapter.make_duckgres_conninfo")
    def test_missing_provision_marker_rejects_saved_connection_before_credentials(
        self, _name: str, send_raw_query: bool, make_conninfo, postgres_connect
    ) -> None:
        source = self._managed_source()
        DuckgresServer.objects.filter(organization=self.organization).delete()

        with self.assertRaisesMessage(ExposedHogQLError, "Invalid connectionId"):
            HogQLQueryExecutor(
                query="SELECT 1",
                team=self.team,
                connection_id=str(source.id),
                send_raw_query=send_raw_query,
            ).execute()

        make_conninfo.assert_not_called()
        postgres_connect.assert_not_called()

    @patch("posthog.hogql.direct_sql.duckgres_adapter.make_duckgres_conninfo", return_value="fresh-conninfo")
    @patch("posthog.hogql.direct_sql.duckgres_adapter.psycopg.connect")
    def test_hides_connection_details(self, connect, _make_conninfo) -> None:
        source = self._managed_source()
        connect.side_effect = psycopg.OperationalError(
            "could not connect to host=private.internal\nprivate driver detail"
        )

        with self.assertRaisesMessage(ExposedHogQLError, "Could not connect to the managed warehouse"):
            HogQLQueryExecutor(
                query="SELECT 1", team=self.team, connection_id=str(source.id), send_raw_query=True
            ).execute()

    @patch("posthog.hogql.direct_sql.duckgres_adapter.make_duckgres_conninfo", return_value="fresh-conninfo")
    @patch("posthog.hogql.direct_sql.duckgres_adapter.psycopg.connect")
    def test_maps_query_errors_to_a_single_message(self, connect, _make_conninfo) -> None:
        source = self._managed_source()
        connection, cursor = self._connection_with_result([])
        cursor.stream.side_effect = psycopg.ProgrammingError("query failed\nprivate driver detail")
        connect.return_value.__enter__.return_value = connection

        with self.assertRaisesMessage(ExposedHogQLError, "query failed"):
            HogQLQueryExecutor(
                query="SELECT 1", team=self.team, connection_id=str(source.id), send_raw_query=True
            ).execute()

    @patch("posthog.hogql.direct_sql.duckgres_adapter.DIRECT_DUCKGRES_MAX_ROWS", 3)
    @patch("posthog.hogql.direct_sql.duckgres_adapter.make_duckgres_conninfo", return_value="fresh-conninfo")
    @patch("posthog.hogql.direct_sql.duckgres_adapter.psycopg.connect")
    def test_rejects_raw_results_over_the_row_cap(self, connect, _make_conninfo) -> None:
        source = self._managed_source()
        connection, cursor = self._connection_with_result([(1,), (2,), (3,), (4,)])
        connect.return_value.__enter__.return_value = connection

        with self.assertRaisesMessage(ExposedHogQLError, "Add a LIMIT clause"):
            HogQLQueryExecutor(
                query="SELECT value FROM large_table", team=self.team, connection_id=str(source.id), send_raw_query=True
            ).execute()

        cursor.stream.assert_called_once_with("SELECT value FROM large_table", None)
        self.assertTrue(cursor.stream_closed)
        connection.commit.assert_not_called()
