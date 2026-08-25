import socket
import threading
from collections.abc import Generator

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

import psycopg
from parameterized import parameterized
from psycopg import pq

from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.database.database import Database
from posthog.hogql.direct_sql import DuckgresRawAdapter, PostgresAdapter, get_adapter, get_raw_adapter_for_source
from posthog.hogql.direct_sql.adapter import DirectQueryPrincipal
from posthog.hogql.direct_sql.duckgres_adapter import _DuckgresStreamingClientCursor
from posthog.hogql.errors import ExposedHogQLError, QueryError, TableAccessDeniedError
from posthog.hogql.query import HogQLQueryExecutor

from posthog.constants import AvailableFeature
from posthog.models import OrganizationMembership

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
            team_id=123,
            source_type=ExternalDataSourceType.POSTGRES,
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            direct_query_enabled=True,
            prefix=MANAGED_WAREHOUSE_SOURCE_PREFIX,
            job_inputs={
                "host": "managed.example.com",
                "port": 5432,
                "database": "ducklake",
                "user": "posthog_team_123",
                "password": "reader-password",
            },
            connection_metadata={
                "engine": "duckdb",
                "system_managed": True,
                "credential_kind": "project_reader",
                "reader_configured": True,
            },
        )
        for field, value in overrides.items():
            setattr(source, field, value)
        return source

    def test_selects_native_adapter_only_for_complete_managed_markers(self) -> None:
        self.assertIsInstance(get_raw_adapter_for_source(self._source()), DuckgresRawAdapter)
        self.assertIsInstance(
            get_raw_adapter_for_source(
                self._source(
                    connection_metadata={
                        "engine": "duckdb",
                        "system_managed": True,
                        "credential_kind": "org_root",
                    }
                )
            ),
            PostgresAdapter,
        )

    def test_selects_native_adapter_for_secretless_service_credentials(self) -> None:
        source = self._source(
            job_inputs={},
            connection_metadata={
                "engine": "duckdb",
                "system_managed": True,
                "credential_kind": "duckgres_service",
                "lifecycle_generation": 1,
            },
        )

        self.assertIsInstance(get_raw_adapter_for_source(source), DuckgresRawAdapter)
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
            (
                "pending_reader",
                {
                    "connection_metadata": {
                        "engine": "duckdb",
                        "system_managed": True,
                        "credential_kind": "project_reader",
                        "reader_configured": False,
                    }
                },
            ),
            (
                "unknown_credential_kind",
                {
                    "connection_metadata": {
                        "engine": "duckdb",
                        "system_managed": True,
                        "credential_kind": "unknown",
                    }
                },
            ),
        ]
    )
    def test_incomplete_managed_markers_do_not_select_native_adapter(
        self, _name: str, overrides: dict[str, object]
    ) -> None:
        adapter = get_raw_adapter_for_source(self._source(**overrides))
        if overrides.get("prefix") == "ducklake":
            self.assertIsInstance(adapter, PostgresAdapter)
        else:
            self.assertIsNone(adapter)


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
            yield from ()
            return next(results)

        cursor = MagicMock()
        with patch("posthog.hogql.direct_sql.duckgres_adapter.fetch", side_effect=fake_fetch):
            self.assertEqual(list(_DuckgresStreamingClientCursor._stream_fetchone_gen(cursor, first=True)), [])

        cursor._set_results.assert_called_once_with([terminal_result])

    def test_streams_with_the_simple_query_protocol(self) -> None:
        postgres_query = object()

        def empty_generator(*_args: object, **_kwargs: object) -> Generator[None]:
            yield from ()

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
        resolver_patcher = patch(
            "posthog.hogql.direct_sql.duckgres_adapter.resolve_psycopg_hostaddr_with_timeout",
            return_value=["203.0.113.10"],
        )
        self.resolve_hostaddr = resolver_patcher.start()
        self.addCleanup(resolver_patcher.stop)

    def _managed_source(
        self,
        *,
        source_id: str = "managed-source",
        user: str | None = None,
        direct_query_enabled: bool = True,
        connection_metadata: dict[str, object] | None = None,
    ) -> ExternalDataSource:
        return ExternalDataSource.objects.create(
            team=self.team,
            source_id=source_id,
            connection_id=f"{source_id}-connection",
            status=ExternalDataSource.Status.COMPLETED,
            source_type=ExternalDataSourceType.POSTGRES,
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            direct_query_enabled=direct_query_enabled,
            prefix=MANAGED_WAREHOUSE_SOURCE_PREFIX,
            job_inputs={
                "host": f"{source_id}.example.com",
                "port": 5432,
                "database": "ducklake",
                "user": user if user is not None else f"posthog_team_{self.team.pk}",
                "password": f"{source_id}-password",
            },
            connection_metadata=(
                connection_metadata
                if connection_metadata is not None
                else {
                    "engine": "duckdb",
                    "system_managed": True,
                    "credential_kind": "project_reader",
                    "reader_configured": True,
                }
            ),
        )

    def _dynamic_managed_source(self, *, source_id: str = "managed-service-source") -> ExternalDataSource:
        return self._managed_source(
            source_id=source_id,
            connection_metadata={
                "engine": "duckdb",
                "system_managed": True,
                "credential_kind": "duckgres_service",
                "lifecycle_generation": 1,
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

    def _managed_source_with_denied_table(
        self,
        *,
        user: str | None = None,
        connection_metadata: dict[str, object] | None = None,
    ) -> ExternalDataSource:
        source = self._managed_source(user=user, connection_metadata=connection_metadata)
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
        return source

    @patch("posthog.hogql.direct_sql.duckgres_adapter._connect_duckgres_address")
    def test_executes_with_the_selected_sources_project_reader(self, connect) -> None:
        self._managed_source(source_id="decoy-source")
        source = self._managed_source(source_id="selected-source")
        connection, cursor = self._connection_with_result([(1,)])
        connect.return_value.__enter__.return_value = connection

        with (
            patch("posthog.hogql.direct_connection.Database.create_for", side_effect=AssertionError),
            patch.object(HogQLQueryExecutor, "_prepare_execution", side_effect=AssertionError),
            patch(
                "products.warehouse_sources.backend.facade.source_management.SourceRegistry.get_source",
                side_effect=AssertionError,
            ),
        ):
            response = HogQLQueryExecutor(
                query="SELECT 1 AS value", team=self.team, connection_id=str(source.id), send_raw_query=True
            ).execute()

        self.assertEqual(response.results, [(1,)])
        self.assertEqual(response.columns, ["value"])
        self.assertEqual(response.types, [("value", "Int32")])
        connect.assert_called_once()
        source_config, hostaddr, deadline, abort_check = connect.call_args.args
        self.assertEqual(source_config.host, "selected-source.example.com")
        self.assertEqual(source_config.port, 5432)
        self.assertEqual(source_config.database, "ducklake")
        self.assertEqual(source_config.user, f"posthog_team_{self.team.pk}")
        self.assertEqual(source_config.password, "selected-source-password")
        self.assertEqual(hostaddr, "203.0.113.10")
        self.assertGreater(deadline, 0)
        self.assertTrue(callable(abort_check))
        self.resolve_hostaddr.assert_called_once()
        resolver_args = self.resolve_hostaddr.call_args.args
        resolver_kwargs = self.resolve_hostaddr.call_args.kwargs
        self.assertEqual(resolver_args[:2], ("selected-source.example.com", 5432))
        self.assertGreater(resolver_args[2], 0)
        self.assertLessEqual(resolver_args[2], 15)
        self.assertTrue(resolver_kwargs["fail_on_resolution_error"])
        self.assertTrue(callable(resolver_kwargs["abort_check"]))
        connection.execute.assert_called_once_with("USE ducklake")
        cursor.stream.assert_called_once_with("SELECT 1 AS value", None)

    @patch("posthog.hogql.direct_sql.duckgres_adapter._connect_duckgres_address")
    @patch("posthog.hogql.direct_sql.duckgres_adapter.resolve_managed_warehouse_postgres_connection")
    def test_dynamic_source_mints_for_the_stable_user_identity_and_uses_tls(self, resolve_connection, connect) -> None:
        source = self._dynamic_managed_source()
        source.job_inputs = {}
        source.save(update_fields=["job_inputs"])
        resolve_connection.return_value = MagicMock(
            host="managed.example.com",
            port=5432,
            database="ducklake",
            username="svc_generated",
            password="service-secret",
            sslmode="require",
        )
        connection, _cursor = self._connection_with_result([(1,)])
        connect.return_value.__enter__.return_value = connection

        HogQLQueryExecutor(
            query="SELECT 1 AS value",
            team=self.team,
            user=self.user,
            connection_id=str(source.id),
            send_raw_query=True,
        ).execute()

        resolve_connection.assert_called_once()
        self.assertEqual(
            resolve_connection.call_args.kwargs["principal"],
            f"posthog:sql-editor:team:{self.team.pk}:user:{self.user.pk}",
        )
        self.assertNotIn(self.user.email, resolve_connection.call_args.kwargs["principal"])
        source_config = connect.call_args.args[0]
        self.assertEqual(source_config.user, "svc_generated")
        self.assertEqual(source_config.password, "service-secret")

    @patch("posthog.hogql.direct_sql.duckgres_adapter._connect_duckgres_address")
    def test_dynamic_source_without_a_real_user_fails_closed(self, connect) -> None:
        source = self._dynamic_managed_source()
        source.job_inputs = {}
        source.save(update_fields=["job_inputs"])

        with self.assertRaisesMessage(ExposedHogQLError, "Managed warehouse is unavailable"):
            HogQLQueryExecutor(
                query="SELECT 1",
                team=self.team,
                connection_id=str(source.id),
                send_raw_query=True,
            ).execute()

        connect.assert_not_called()

    def test_request_principal_is_a_narrow_immutable_contract(self) -> None:
        principal = DirectQueryPrincipal(value="posthog:sql-editor:team:1:user:2")

        with self.assertRaises(AttributeError):
            principal.__setattr__("value", "changed")

    @patch("posthog.hogql.direct_sql.duckgres_adapter._connect_duckgres_address")
    def test_rejects_multiple_statements_before_connecting(self, connect) -> None:
        source = self._managed_source()

        with self.assertRaisesMessage(ExposedHogQLError, "Raw queries must contain a single statement"):
            HogQLQueryExecutor(
                query="SELECT 1; SELECT 2",
                team=self.team,
                connection_id=str(source.id),
                send_raw_query=True,
            ).execute()

        connect.assert_not_called()

    @patch("posthog.hogql.direct_sql.duckgres_adapter._connect_duckgres_address")
    @patch("posthog.hogql.direct_sql.duckgres_adapter.threading.Timer")
    def test_schedules_cancellation_and_preserves_empty_utility_results(self, timer, connect) -> None:
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

    @patch("posthog.hogql.direct_sql.duckgres_adapter._connect_duckgres_address")
    def test_preserves_columns_for_an_empty_select(self, connect) -> None:
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

    @patch("posthog.hogql.direct_sql.duckgres_adapter._connect_duckgres_address")
    @patch("posthog.hogql.direct_sql.duckgres_adapter.threading.Timer")
    @patch("posthog.hogql.direct_sql.duckgres_adapter.socket.socket")
    def test_cancels_queries_at_the_execution_deadline(self, socket_factory, timer, connect) -> None:
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

    @patch("posthog.hogql.direct_sql.duckgres_adapter._connect_duckgres_address")
    def test_cancels_a_running_query_when_the_async_request_is_canceled(self, connect) -> None:
        source = self._managed_source()
        connection, cursor = self._connection_with_result([])
        cancellation_observed = threading.Event()

        def blocked_rows() -> Generator[tuple[object, ...]]:
            if not cancellation_observed.wait(2):
                raise AssertionError("The managed warehouse query was not canceled")
            yield from ()
            raise psycopg.OperationalError("query canceled")

        cursor.stream.return_value = blocked_rows()
        connection.cancel_safe.side_effect = lambda **_kwargs: cancellation_observed.set()
        connect.return_value.__enter__.return_value = connection
        query_tags = MagicMock(client_query_id="query-id", celery_task_id="2f3350d0-e641-4c33-bc9c-66898bf22317")

        with (
            patch("posthog.hogql.query.get_query_tags", return_value=query_tags),
            patch(
                "posthog.hogql.direct_sql.duckgres_adapter.is_direct_query_cancellation_requested",
                side_effect=[False, False, True],
            ),
            self.assertRaises(ExposedHogQLError) as error,
        ):
            HogQLQueryExecutor(
                query="SELECT slow_value",
                team=self.team,
                connection_id=str(source.id),
                send_raw_query=True,
            ).execute()

        self.assertEqual(str(error.exception), "Managed warehouse query was canceled.")
        connection.cancel_safe.assert_called()
        connection.commit.assert_not_called()

    @patch("posthog.hogql.direct_sql.duckgres_adapter._connect_duckgres_address")
    def test_cancels_before_opening_a_connection(self, connect) -> None:
        source = self._managed_source()
        query_tags = MagicMock(client_query_id="query-id", celery_task_id="2f3350d0-e641-4c33-bc9c-66898bf22317")

        with (
            patch("posthog.hogql.query.get_query_tags", return_value=query_tags),
            patch(
                "posthog.hogql.direct_sql.duckgres_adapter.is_direct_query_cancellation_requested",
                return_value=True,
            ),
            self.assertRaises(ExposedHogQLError) as error,
        ):
            HogQLQueryExecutor(
                query="SELECT slow_value",
                team=self.team,
                connection_id=str(source.id),
                send_raw_query=True,
            ).execute()

        self.assertEqual(str(error.exception), "Managed warehouse query was canceled.")
        connect.assert_not_called()

    def test_non_raw_managed_query_ignores_warehouse_object_access_control(self) -> None:
        source = self._managed_source_with_denied_table()

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

    def test_non_raw_legacy_managed_source_enforces_warehouse_object_access_control(self) -> None:
        source = self._managed_source_with_denied_table(
            user="org-root",
            connection_metadata={
                "engine": "duckdb",
                "system_managed": True,
                "credential_kind": "org_root",
            },
        )
        with (
            patch(
                "posthog.hogql.database.database.feature_enabled_or_false",
                side_effect=lambda flag, *_args, **_kwargs: flag == "hogql-warehouse-access-control",
            ),
            self.assertRaises(TableAccessDeniedError),
        ):
            HogQLQueryExecutor(
                query="SELECT value FROM managed_table",
                team=self.team,
                user=self.user,
                connection_id=str(source.id),
            ).generate_clickhouse_sql()

    @patch("posthog.hogql.direct_sql.postgres_adapter.psycopg.connect")
    def test_non_raw_managed_connection_errors_hide_connection_details(self, connect) -> None:
        source = self._managed_source()
        DataWarehouseTable.objects.create(
            name="managed_table",
            format="Parquet",
            team=self.team,
            external_data_source=source,
            url_pattern="",
            columns={"value": {"hogql": "IntegerDatabaseField", "clickhouse": "Int64", "valid": True}},
        )
        connect.side_effect = psycopg.OperationalError(
            "could not connect to host=private.internal\nprivate driver detail"
        )

        with self.assertRaises(ExposedHogQLError) as context:
            HogQLQueryExecutor(
                query="SELECT value FROM managed_table",
                team=self.team,
                connection_id=str(source.id),
            ).execute()

        self.assertEqual(
            str(context.exception),
            "Could not connect to the managed warehouse. Try again, and contact support if the problem persists.",
        )
        self.assertNotIn("private.internal", str(context.exception))
        self.assertNotIn("private driver detail", str(context.exception))

    @patch("posthog.hogql.direct_sql.duckgres_adapter._connect_duckgres_address")
    @patch("posthog.hogql.query.raw_query_denied_by_table_access", side_effect=AssertionError)
    def test_managed_warehouse_raw_queries_skip_unconfigured_table_access(self, _denied, connect) -> None:
        source = self._managed_source()
        connection, _cursor = self._connection_with_result([(1,)])
        connect.return_value.__enter__.return_value = connection

        response = HogQLQueryExecutor(
            query="SELECT 1", team=self.team, connection_id=str(source.id), send_raw_query=True
        ).execute()

        self.assertEqual(response.results, [(1,)])

    @parameterized.expand(
        [
            ("empty_password", {"password": ""}),
            ("root_username", {"user": "root"}),
        ]
    )
    @patch("posthog.hogql.direct_sql.duckgres_adapter._connect_duckgres_address")
    def test_rejects_malformed_reader_credentials(
        self, _name: str, credential_overrides: dict[str, object], connect
    ) -> None:
        source = self._managed_source()
        source.job_inputs = {**source.job_inputs, **credential_overrides}
        source.save(update_fields=["job_inputs"])

        with self.assertRaisesMessage(ExposedHogQLError, "Invalid connectionId"):
            HogQLQueryExecutor(
                query="SELECT 1", team=self.team, connection_id=str(source.id), send_raw_query=True
            ).execute()

        connect.assert_not_called()

    @patch("posthog.hogql.direct_sql.duckgres_adapter._connect_duckgres_address")
    @patch("posthog.hogql.direct_sql.postgres_adapter.psycopg.connect")
    @patch("posthog.hogql.query.raw_query_denied_by_table_access", return_value=True)
    def test_legacy_managed_raw_query_preserves_external_table_access_control(
        self, denied: MagicMock, postgres_connect: MagicMock, duckgres_connect: MagicMock
    ) -> None:
        source = self._managed_source(
            user="org-root",
            connection_metadata={
                "engine": "duckdb",
                "system_managed": True,
                "credential_kind": "org_root",
            },
        )
        with self.assertRaisesMessage(ExposedHogQLError, "raw SQL is not allowed"):
            HogQLQueryExecutor(
                query="SELECT 1",
                team=self.team,
                user=self.user,
                connection_id=str(source.id),
                send_raw_query=True,
            ).execute()

        denied.assert_called_once()
        postgres_connect.assert_not_called()
        duckgres_connect.assert_not_called()

    @parameterized.expand(
        [
            (
                "pending_reader",
                {
                    "engine": "duckdb",
                    "system_managed": True,
                    "credential_kind": "project_reader",
                    "reader_configured": False,
                },
                True,
            ),
            (
                "unknown_credential_kind",
                {
                    "engine": "duckdb",
                    "system_managed": True,
                    "credential_kind": "unknown",
                    "reader_configured": True,
                },
                True,
            ),
            (
                "direct_query_disabled",
                {
                    "engine": "duckdb",
                    "system_managed": True,
                    "credential_kind": "project_reader",
                    "reader_configured": True,
                },
                False,
            ),
        ]
    )
    @patch("posthog.hogql.direct_sql.duckgres_adapter._connect_duckgres_address")
    def test_rejects_unready_project_readers_before_connecting(
        self,
        _name: str,
        connection_metadata: dict[str, object],
        direct_query_enabled: bool,
        connect,
    ) -> None:
        source = self._managed_source(
            connection_metadata=connection_metadata,
            direct_query_enabled=direct_query_enabled,
        )

        with self.assertRaises(ExposedHogQLError):
            HogQLQueryExecutor(
                query="SELECT 1",
                team=self.team,
                connection_id=str(source.id),
                send_raw_query=True,
            ).execute()

        connect.assert_not_called()

    def test_database_fails_closed_for_an_unavailable_reserved_source(self) -> None:
        source = self._managed_source(
            connection_metadata={
                "engine": "duckdb",
                "system_managed": True,
                "credential_kind": "project_reader",
                "reader_configured": False,
            }
        )

        with self.assertRaisesMessage(QueryError, "This managed warehouse connection isn't available"):
            Database.create_for(team=self.team, connection_id=str(source.id))

    @patch("posthog.hogql.direct_sql.duckgres_adapter._connect_duckgres_address")
    def test_hides_connection_details(self, connect) -> None:
        source = self._managed_source()
        connect.side_effect = psycopg.OperationalError(
            "could not connect to host=private.internal\nprivate driver detail"
        )

        with self.assertRaises(ExposedHogQLError) as context:
            HogQLQueryExecutor(
                query="SELECT 1", team=self.team, connection_id=str(source.id), send_raw_query=True
            ).execute()

        self.assertEqual(
            str(context.exception),
            "Could not connect to the managed warehouse. Try again, and contact support if the problem persists.",
        )
        self.assertNotIn("private.internal", str(context.exception))
        self.assertNotIn("private driver detail", str(context.exception))

    @patch("posthog.hogql.direct_sql.duckgres_adapter._connect_duckgres_address")
    @patch("posthog.hogql.direct_sql.duckgres_adapter.monotonic")
    def test_connect_deadline_is_shared_across_resolved_addresses(self, monotonic, connect) -> None:
        source = self._managed_source()
        clock = [100.0]
        monotonic.side_effect = lambda: clock[0]
        self.resolve_hostaddr.return_value = ["203.0.113.10", "203.0.113.11"]

        def fail_after_deadline(*_args: object) -> None:
            clock[0] = 116.0
            raise psycopg.OperationalError("first address failed")

        connect.side_effect = fail_after_deadline
        with self.assertRaises(ExposedHogQLError) as context:
            HogQLQueryExecutor(
                query="SELECT 1", team=self.team, connection_id=str(source.id), send_raw_query=True
            ).execute()

        self.assertEqual(
            str(context.exception),
            "Could not connect to the managed warehouse. Try again, and contact support if the problem persists.",
        )
        connect.assert_called_once()
        self.assertEqual(connect.call_args.args[1], "203.0.113.10")

    @patch("posthog.hogql.direct_sql.duckgres_adapter._connect_duckgres_address")
    def test_maps_query_errors_to_a_single_message(self, connect) -> None:
        source = self._managed_source()
        connection, cursor = self._connection_with_result([])
        cursor.stream.side_effect = psycopg.ProgrammingError("query failed\nprivate driver detail")
        connect.return_value.__enter__.return_value = connection

        with self.assertRaises(ExposedHogQLError) as context:
            HogQLQueryExecutor(
                query="SELECT 1", team=self.team, connection_id=str(source.id), send_raw_query=True
            ).execute()

        self.assertEqual(str(context.exception), "query failed")
        self.assertNotIn("private driver detail", str(context.exception))

    @patch("posthog.hogql.direct_sql.duckgres_adapter._connect_duckgres_address")
    def test_hides_post_connect_operational_error_details(self, connect) -> None:
        source = self._managed_source()
        connection, cursor = self._connection_with_result([])
        cursor.stream.side_effect = psycopg.OperationalError(
            "server closed the connection to host=private.internal\nprivate driver detail"
        )
        connect.return_value.__enter__.return_value = connection

        with self.assertRaises(ExposedHogQLError) as context:
            HogQLQueryExecutor(
                query="SELECT 1", team=self.team, connection_id=str(source.id), send_raw_query=True
            ).execute()

        self.assertEqual(
            str(context.exception),
            "Could not connect to the managed warehouse. Try again, and contact support if the problem persists.",
        )
        self.assertNotIn("private.internal", str(context.exception))
        self.assertNotIn("private driver detail", str(context.exception))

    @patch("posthog.hogql.direct_sql.duckgres_adapter.DIRECT_DUCKGRES_MAX_ROWS", 3)
    @patch("posthog.hogql.direct_sql.duckgres_adapter._connect_duckgres_address")
    def test_accepts_raw_results_at_the_row_cap(self, connect) -> None:
        source = self._managed_source()
        connection, cursor = self._connection_with_result([(1,), (2,), (3,)])
        connect.return_value.__enter__.return_value = connection

        response = HogQLQueryExecutor(
            query="SELECT value FROM bounded_table", team=self.team, connection_id=str(source.id), send_raw_query=True
        ).execute()

        self.assertEqual(response.results, [(1,), (2,), (3,)])
        self.assertTrue(cursor.stream_closed)
        connection.commit.assert_called_once_with()

    @patch("posthog.hogql.direct_sql.duckgres_adapter._connect_duckgres_address")
    def test_rejects_raw_results_over_the_row_cap(self, connect) -> None:
        source = self._managed_source()
        connection, cursor = self._connection_with_result([(1,)] * 50_001)
        connect.return_value.__enter__.return_value = connection

        with self.assertRaises(ExposedHogQLError) as context:
            HogQLQueryExecutor(
                query="SELECT value FROM large_table", team=self.team, connection_id=str(source.id), send_raw_query=True
            ).execute()

        self.assertEqual(
            str(context.exception),
            "Managed warehouse query returned more than 50,000 rows. Add a LIMIT clause.",
        )
        cursor.stream.assert_called_once_with("SELECT value FROM large_table", None)
        self.assertTrue(cursor.stream_closed)
        connection.commit.assert_not_called()
