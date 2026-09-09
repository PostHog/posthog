from uuid import uuid4

import unittest
from posthog.test.base import APIBaseTest
from unittest.mock import patch

import duckdb
from parameterized import parameterized

from posthog.hogql.errors import ExposedHogQLError
from posthog.hogql.motherduck_connection_cache import (
    cached_motherduck_connection,
    clear_thread_local_motherduck_connections,
)
from posthog.hogql.query import HogQLQueryExecutor

from products.data_warehouse.backend.facade.api import DIRECT_MOTHERDUCK_URL_PATTERN
from products.data_warehouse.backend.facade.sources import (
    DIRECT_MOTHERDUCK_CATALOG_OPTION,
    DIRECT_MOTHERDUCK_SCHEMA_OPTION,
    DIRECT_MOTHERDUCK_TABLE_OPTION,
)
from products.warehouse_sources.backend.facade.models import DataWarehouseTable, ExternalDataSource
from products.warehouse_sources.backend.facade.source_management import SourceRegistry
from products.warehouse_sources.backend.facade.types import ExternalDataSourceType

# Patched where it is used: the direct-query path reaches the driver through the name
# `source.py` binds, so patching the transport module it came from would not intercept.
_TRANSPORT_CONNECT = "products.warehouse_sources.backend.temporal.data_imports.sources.motherduck.source.connect"


def _source_and_config(token: str = "token", database: str = "db"):
    """The (source, config) pair the adapter hands the cache, built the same way it does."""
    source = SourceRegistry.get_source(ExternalDataSourceType.MOTHERDUCK)
    return source, source.parse_config({"access_token": token, "database": database})


def _local_duckdb(*_args, **_kwargs) -> duckdb.DuckDBPyConnection:
    connection = duckdb.connect(":memory:")
    connection.execute("CREATE SCHEMA nyc")
    connection.execute("CREATE TABLE nyc.taxi (trip_id BIGINT, fare DOUBLE, city VARCHAR)")
    connection.execute("INSERT INTO nyc.taxi VALUES (1, 10.5, 'ny'), (2, 20.0, 'sf'), (3, 30.0, 'ny')")
    return connection


class TestDirectMotherDuckQuery(APIBaseTest):
    def setUp(self):
        super().setUp()
        # The connection cache is thread-local module state; isolate each test.
        clear_thread_local_motherduck_connections()
        self.addCleanup(clear_thread_local_motherduck_connections)

    def _create_source(self) -> ExternalDataSource:
        return ExternalDataSource.objects.create(
            team=self.team,
            source_id=str(uuid4()),
            connection_id=str(uuid4()),
            status=ExternalDataSource.Status.COMPLETED,
            source_type="Motherduck",
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            prefix="md",
            connection_metadata={"engine": "motherduck", "database": "memory"},
            job_inputs={"access_token": "test-token", "database": "memory"},
        )

    def _create_direct_table(self, source: ExternalDataSource) -> DataWarehouseTable:
        return DataWarehouseTable.objects.create(
            name="nyc.taxi",
            team=self.team,
            format=DataWarehouseTable.TableFormat.Parquet,
            url_pattern=DIRECT_MOTHERDUCK_URL_PATTERN,
            external_data_source=source,
            columns={
                "trip_id": {"clickhouse": "Int64", "hogql": "IntegerDatabaseField", "valid": True},
                "fare": {"clickhouse": "Float64", "hogql": "FloatDatabaseField", "valid": True},
                "city": {"clickhouse": "String", "hogql": "StringDatabaseField", "valid": True},
            },
            options={
                DIRECT_MOTHERDUCK_CATALOG_OPTION: "memory",
                DIRECT_MOTHERDUCK_SCHEMA_OPTION: "nyc",
                DIRECT_MOTHERDUCK_TABLE_OPTION: "taxi",
            },
        )

    def test_hogql_query_compiles_to_duckdb_and_executes(self):
        source = self._create_source()
        self._create_direct_table(source)

        executor = HogQLQueryExecutor(
            query="SELECT trip_id, fare FROM `nyc.taxi` WHERE city = 'ny' ORDER BY trip_id",
            team=self.team,
            connection_id=str(source.id),
        )
        with patch(_TRANSPORT_CONNECT, side_effect=_local_duckdb):
            response = executor.execute()

        self.assertEqual(executor.direct_dialect, "duckdb")
        # The compiled SQL targets the physical three-part location, with the constant bound
        # as a converted `$name` parameter rather than inlined.
        self.assertIn("nyc.taxi", executor.direct_sql or "")
        self.assertEqual(response.results, [(1, 10.5), (3, 30.0)])
        self.assertEqual(response.types, [("trip_id", "Int64"), ("fare", "Float64")])

    def test_raw_query_executes_against_duckdb(self):
        source = self._create_source()

        executor = HogQLQueryExecutor(
            query="SELECT count(*) AS n, min(city) AS c FROM memory.nyc.taxi",
            team=self.team,
            connection_id=str(source.id),
            send_raw_query=True,
        )
        with patch(_TRANSPORT_CONNECT, side_effect=_local_duckdb):
            response = executor.execute()

        self.assertEqual(response.results, [(3, "ny")])
        self.assertEqual(response.types, [("n", "Int64"), ("c", "String")])

    @parameterized.expand(
        [
            ("insert", "INSERT INTO nyc.taxi VALUES (9, 1.0, 'x')"),
            ("attach", "ATTACH 'md:other_db'"),
            ("read_csv", "SELECT * FROM read_csv('/etc/passwd')"),
            ("multi_statement", "SELECT 1; DROP TABLE nyc.taxi"),
        ]
    )
    def test_raw_query_rejects_unsafe_statements_before_connecting(self, _name: str, query: str):
        source = self._create_source()

        executor = HogQLQueryExecutor(
            query=query,
            team=self.team,
            connection_id=str(source.id),
            send_raw_query=True,
        )

        with patch(
            "posthog.hogql.direct_sql.motherduck_adapter.MotherDuckAdapter.validate_source_config"
        ) as mock_validate:
            with self.assertRaises(ExposedHogQLError):
                executor.execute()

        # The statement is rejected before any connection is opened.
        mock_validate.assert_not_called()
        self.assertIsNone(executor.direct_sql)


class TestMotherDuckConnectionCache(unittest.TestCase):
    def setUp(self):
        clear_thread_local_motherduck_connections()
        self.addCleanup(clear_thread_local_motherduck_connections)

    def test_reuses_connection_across_calls(self):
        with patch(_TRANSPORT_CONNECT, side_effect=lambda *a, **k: duckdb.connect(":memory:")) as mock_connect:
            with cached_motherduck_connection(*_source_and_config()) as first:
                pass
            with cached_motherduck_connection(*_source_and_config()) as second:
                pass
        self.assertIs(first, second)
        mock_connect.assert_called_once()

    def test_reopens_after_ttl(self):
        with patch(_TRANSPORT_CONNECT, side_effect=lambda *a, **k: duckdb.connect(":memory:")) as mock_connect:
            with patch("posthog.hogql.motherduck_connection_cache.MOTHERDUCK_CONNECTION_CACHE_TTL_SECONDS", 0):
                with cached_motherduck_connection(*_source_and_config()):
                    pass
                with cached_motherduck_connection(*_source_and_config()):
                    pass
        self.assertEqual(mock_connect.call_count, 2)

    def test_reopens_when_connection_found_dead(self):
        with patch(_TRANSPORT_CONNECT, side_effect=lambda *a, **k: duckdb.connect(":memory:")) as mock_connect:
            with cached_motherduck_connection(*_source_and_config()) as connection:
                pass
            connection.close()
            with cached_motherduck_connection(*_source_and_config()):
                pass
        self.assertEqual(mock_connect.call_count, 2)

    def test_evicts_on_transport_error_keeps_on_sql_error(self):
        with patch(_TRANSPORT_CONNECT, side_effect=lambda *a, **k: duckdb.connect(":memory:")) as mock_connect:
            # A SQL-level error (bad table) leaves the connection cached...
            with self.assertRaises(duckdb.Error):
                with cached_motherduck_connection(*_source_and_config()) as connection:
                    connection.execute("SELECT * FROM missing_table")
            with cached_motherduck_connection(*_source_and_config()):
                pass
            self.assertEqual(mock_connect.call_count, 1)
            # ...while a transport-shaped error evicts it.
            with self.assertRaises(duckdb.IOException):
                with cached_motherduck_connection(*_source_and_config()):
                    raise duckdb.IOException("socket closed")
            with cached_motherduck_connection(*_source_and_config()):
                pass
            self.assertEqual(mock_connect.call_count, 2)

    def test_different_tokens_use_separate_connections(self):
        with patch(_TRANSPORT_CONNECT, side_effect=lambda *a, **k: duckdb.connect(":memory:")) as mock_connect:
            with cached_motherduck_connection(*_source_and_config("token-a")):
                pass
            with cached_motherduck_connection(*_source_and_config("token-b")):
                pass
        self.assertEqual(mock_connect.call_count, 2)
