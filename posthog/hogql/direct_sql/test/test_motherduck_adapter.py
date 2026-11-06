from posthog.test.base import BaseTest
from unittest.mock import patch

from django.test import SimpleTestCase

import duckdb
from parameterized import parameterized

from posthog.hogql.constants import HogQLDialect
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.database.direct_motherduck_table import DirectMotherDuckTable
from posthog.hogql.database.models import StringDatabaseField, TableNode
from posthog.hogql.direct_sql.motherduck_adapter import (
    _fetch_capped_motherduck_rows,
    convert_pyformat_placeholders,
    duckdb_type_to_clickhouse_type,
    ensure_read_only_raw_motherduck_statement,
)
from posthog.hogql.errors import ExposedHogQLError, QueryError
from posthog.hogql.parser import parse_select
from posthog.hogql.printer.utils import prepare_and_print_ast


def _table(**overrides) -> DirectMotherDuckTable:
    kwargs = {
        "name": "taxi",
        "fields": {},
        "motherduck_database": "sample_data",
        "motherduck_schema": "nyc",
        "motherduck_table_name": "taxi",
        "external_data_source_id": "src",
        **overrides,
    }
    return DirectMotherDuckTable(**kwargs)


class TestDirectMotherDuckTable(SimpleTestCase):
    def test_renders_quoted_three_part_name(self):
        # Safe lowercase identifiers stay bare (the escaper quotes only when needed).
        self.assertEqual(_table().to_printed_duckdb(None), "sample_data.nyc.taxi")

    def test_escapes_special_identifiers(self):
        table = _table(motherduck_database='my"db', motherduck_table_name="weird.name")
        self.assertEqual(table.to_printed_duckdb(None), '"my""db".nyc."weird.name"')

    def test_requires_database_and_schema(self):
        with self.assertRaises(QueryError):
            _table(motherduck_database=" ").to_printed_duckdb(None)
        with self.assertRaises(QueryError):
            _table(motherduck_schema="").to_printed_duckdb(None)

    def test_refuses_other_dialects(self):
        with self.assertRaises(QueryError):
            _table().to_printed_postgres(None)
        with self.assertRaises(QueryError):
            _table().to_printed_clickhouse(None)

    def test_resolves_fields_case_insensitively(self):
        # DuckDB resolves identifiers case-insensitively while preserving stored case; a HogQL
        # query typing `VendorID` as `vendorid` must resolve to the stored column.
        table = _table(fields={"VendorID": StringDatabaseField(name="VendorID")})
        self.assertTrue(table.has_field("vendorid"))
        field = table.get_field("VENDORID")
        assert isinstance(field, StringDatabaseField)
        self.assertEqual(field.name, "VendorID")


class TestDirectMotherDuckPrinting(BaseTest):
    def _print(self, *, is_direct_query: bool, dialect: HogQLDialect = "duckdb") -> str:
        table = _table(fields={"fare_amount": StringDatabaseField(name="fare_amount")})
        database = Database()
        root = TableNode()
        root.add_child(TableNode(name="taxi", table=table))
        database._add_warehouse_tables(root)
        context = HogQLContext(
            team_id=self.team.pk,
            enable_select_queries=True,
            database=database,
            is_direct_query=is_direct_query,
        )
        return prepare_and_print_ast(parse_select("SELECT fare_amount FROM taxi"), context, dialect)[0]

    def test_direct_query_prints_qualified_table_in_duckdb_dialect(self):
        printed = self._print(is_direct_query=True)
        self.assertIn("sample_data.nyc.taxi", printed)
        self.assertNotIn("team_id", printed)

    def test_refuses_external_table_in_clickhouse_dialect(self):
        # Our own cluster must never be asked to resolve a customer's MotherDuck table.
        with self.assertRaises(QueryError):
            self._print(is_direct_query=False, dialect="clickhouse")


class TestMotherDuckReadOnlyGuard(SimpleTestCase):
    @parameterized.expand(
        [
            ("select", "SELECT * FROM sample_data.nyc.taxi"),
            ("with_cte", "WITH x AS (SELECT 1) SELECT * FROM x"),
            ("lowercase", "select count(*) from taxi"),
            ("leading_comment", "-- hi\nSELECT 1"),
            # A column named like a blocked function is an identifier in quotes — allowed.
            ("quoted_column_named_glob", 'SELECT "glob" FROM taxi'),
            ("string_literal", "SELECT 'read_csv' AS label"),
            # Blocked names are only rejected in call position, so these stay usable as columns.
            ("column_named_query", "SELECT query FROM request_log"),
            ("qualified_column_named_query", "SELECT t.query, t.duration FROM request_log t"),
        ]
    )
    def test_allows_read_only(self, _name, sql):
        self.assertEqual(ensure_read_only_raw_motherduck_statement(sql), sql)

    @parameterized.expand(
        [
            ("insert", "INSERT INTO taxi VALUES (1)"),
            ("update", "UPDATE taxi SET fare_amount = 0"),
            ("delete", "DELETE FROM taxi"),
            ("drop", "DROP TABLE taxi"),
            ("create", "CREATE TABLE t (x INT)"),
            ("attach", "ATTACH 'md:other_db'"),
            ("copy", "COPY taxi TO 'out.parquet'"),
            ("install", "INSTALL httpfs"),
            ("pragma", "PRAGMA database_list"),
            ("multi_statement", "SELECT 1; DROP TABLE taxi"),
            ("with_prefixed_insert", "WITH x AS (SELECT 1) INSERT INTO taxi SELECT * FROM x"),
        ]
    )
    def test_rejects_writes_and_non_selects(self, _name, sql):
        with self.assertRaises(ExposedHogQLError):
            ensure_read_only_raw_motherduck_statement(sql)

    @parameterized.expand(
        [
            ("read_csv", "SELECT * FROM read_csv('/etc/passwd')"),
            ("read_parquet", "SELECT * FROM read_parquet('secrets.parquet')"),
            ("read_text", "SELECT * FROM read_text('/etc/hosts')"),
            ("glob", "SELECT * FROM glob('/*')"),
            ("getenv", "SELECT getenv('AWS_SECRET_ACCESS_KEY')"),
            ("uppercase", "SELECT * FROM READ_CSV('/etc/passwd')"),
            ("nested", "SELECT * FROM (SELECT * FROM read_json_auto('x.json'))"),
            # DuckDB resolves a quoted identifier to the same function.
            ("quoted_call", "SELECT * FROM \"read_csv\"('/etc/passwd')"),
        ]
    )
    def test_rejects_environment_reading_functions(self, _name, sql):
        with self.assertRaises(ExposedHogQLError):
            ensure_read_only_raw_motherduck_statement(sql)

    @parameterized.expand(
        [
            # `query()` runs its string argument as a statement, so the outer SELECT gate alone
            # would let `PRAGMA PRINT_MD_TOKEN` return the source's MotherDuck token.
            ("query_pragma_token", "SELECT * FROM query('PRAGMA PRINT_MD_TOKEN')"),
            ("query_table", "SELECT * FROM query_table('taxi')"),
            # The token travels in the DSN and lands as a readable DuckDB setting.
            ("current_setting", "SELECT current_setting('motherduck_token')"),
            ("duckdb_settings", "SELECT value FROM duckdb_settings() WHERE name = 'motherduck_token'"),
            ("duckdb_secrets", "SELECT * FROM duckdb_secrets()"),
        ]
    )
    def test_rejects_credential_revealing_functions(self, _name, sql):
        with self.assertRaises(ExposedHogQLError):
            ensure_read_only_raw_motherduck_statement(sql)


class TestPlaceholderConversion(SimpleTestCase):
    def test_converts_named_placeholders(self):
        sql, values = convert_pyformat_placeholders(
            "SELECT * FROM t WHERE a = %(hogql_val_0)s AND b = %(hogql_val_1)s",
            {"hogql_val_0": "x", "hogql_val_1": 2},
        )
        self.assertEqual(sql, "SELECT * FROM t WHERE a = $hogql_val_0 AND b = $hogql_val_1")
        self.assertEqual(values, {"hogql_val_0": "x", "hogql_val_1": 2})

    def test_leaves_sql_untouched_without_values(self):
        # Raw passthrough SQL runs with no bound values; a literal `%(` in a string constant
        # must survive verbatim.
        sql, values = convert_pyformat_placeholders("SELECT '%(not_a_param)s'", None)
        self.assertEqual(sql, "SELECT '%(not_a_param)s'")
        self.assertEqual(values, {})


class TestDuckDBTypeMapping(SimpleTestCase):
    @parameterized.expand(
        [
            ("BIGINT", "Int64"),
            ("INTEGER", "Int32"),
            ("UBIGINT", "UInt64"),
            ("DOUBLE", "Float64"),
            ("DECIMAL(10,2)", "Decimal"),
            ("VARCHAR", "String"),
            ("BOOLEAN", "Bool"),
            ("DATE", "Date32"),
            ("TIMESTAMP", "DateTime64(6)"),
            ("TIMESTAMP WITH TIME ZONE", "DateTime64(6, 'UTC')"),
            ("UUID", "UUID"),
            # Nested / exotic types round-trip as strings, including arrays whose element
            # type would otherwise match the scalar decimal/timestamp fallbacks.
            ("STRUCT(a INTEGER)", "String"),
            ("INTEGER[]", "String"),
            ("DECIMAL(18,3)[]", "String"),
            ("TIMESTAMP[]", "String"),
            ("JSON", "String"),
            (None, "String"),
        ]
    )
    def test_maps_duckdb_types(self, duckdb_type, expected):
        self.assertEqual(duckdb_type_to_clickhouse_type(duckdb_type), expected)


class TestMotherDuckRowCap(SimpleTestCase):
    def test_returns_rows_under_cap(self):
        connection = duckdb.connect(":memory:")
        connection.execute("SELECT * FROM range(3)")
        self.assertEqual(_fetch_capped_motherduck_rows(connection), [(0,), (1,), (2,)])

    def test_raises_when_result_exceeds_cap(self):
        connection = duckdb.connect(":memory:")
        connection.execute("SELECT * FROM range(10)")
        with patch("posthog.hogql.direct_sql.motherduck_adapter.DIRECT_MOTHERDUCK_MAX_ROWS", 3):
            with self.assertRaisesRegex(ExposedHogQLError, "Add a LIMIT clause"):
                _fetch_capped_motherduck_rows(connection)


class TestMotherDuckAdapterExecute(BaseTest):
    def _request(self, sql: str, values: dict | None = None):
        from posthog.hogql.constants import HogQLGlobalSettings
        from posthog.hogql.direct_sql.adapter import DirectQueryRequest
        from posthog.hogql.timings import HogQLTimings

        from products.warehouse_sources.backend.facade.models import ExternalDataSource

        source = ExternalDataSource.objects.create(
            team=self.team,
            source_type="Motherduck",
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            job_inputs={"access_token": "test-token", "database": "memory"},
            source_id="motherduck-test",
            connection_id="motherduck-test",
        )
        return DirectQueryRequest(
            source=source,
            team=self.team,
            sql=sql,
            values=values,
            settings=HogQLGlobalSettings(max_execution_time=60),
            timings=HogQLTimings(),
            query_type="HogQLQuery",
            debug=False,
        )

    def test_executes_with_placeholder_conversion_and_typed_results(self):
        from contextlib import contextmanager

        from posthog.hogql.direct_sql.motherduck_adapter import MotherDuckAdapter

        connection = duckdb.connect(":memory:")
        connection.execute("CREATE TABLE t (n BIGINT, label VARCHAR, created TIMESTAMP)")
        connection.execute("INSERT INTO t VALUES (1, 'a', '2026-01-01'), (2, 'b', '2026-01-02')")

        @contextmanager
        def fake_cache(token, database):
            yield connection

        request = self._request("SELECT n, label, created FROM t WHERE label = %(hogql_val_0)s", {"hogql_val_0": "b"})
        with patch("posthog.hogql.direct_sql.motherduck_adapter.cached_motherduck_connection", fake_cache):
            result = MotherDuckAdapter().execute(request)

        self.assertEqual(len(result.results), 1)
        self.assertEqual(result.results[0][0], 2)
        self.assertEqual(result.print_columns, ["n", "label", "created"])
        self.assertEqual(result.types, [("n", "Int64"), ("label", "String"), ("created", "DateTime64(6)")])

    def test_sql_errors_surface_as_exposed_errors(self):
        from contextlib import contextmanager

        from posthog.hogql.direct_sql.motherduck_adapter import MotherDuckAdapter

        connection = duckdb.connect(":memory:")

        @contextmanager
        def fake_cache(token, database):
            yield connection

        request = self._request("SELECT * FROM missing_table")
        with patch("posthog.hogql.direct_sql.motherduck_adapter.cached_motherduck_connection", fake_cache):
            with self.assertRaises(ExposedHogQLError):
                MotherDuckAdapter().execute(request)

    def test_failed_connect_surfaces_its_translated_message(self):
        from posthog.hogql.direct_sql.motherduck_adapter import MotherDuckAdapter

        from products.warehouse_sources.backend.facade.source_management import MotherDuckConnectionError

        request = self._request("SELECT 1")
        with patch(
            "posthog.hogql.direct_sql.motherduck_adapter.cached_motherduck_connection",
            side_effect=MotherDuckConnectionError("Invalid MotherDuck token."),
        ):
            with self.assertRaisesRegex(ExposedHogQLError, "Invalid MotherDuck token."):
                MotherDuckAdapter().execute(request)
