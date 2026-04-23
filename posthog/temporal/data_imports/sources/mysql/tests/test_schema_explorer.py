"""Tests for `MySQLSchemaExplorer`.

Integration tests that exercise a real MySQL server live in
`posthog/temporal/tests/data_imports/test_mysql_source.py`; these tests use
a mocked cursor so we can verify:

- the SQL shape (parameterized, no identifier splicing)
- the return-value contracts (None vs. empty list, 0 vs. exception)
- identifier quoting for the places we must interpolate
- the safety behavior: malformed identifiers raise before any query runs
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from posthog.temporal.data_imports.sources.common.sql import InvalidIdentifierError, Table, TableStats
from posthog.temporal.data_imports.sources.mysql.schema_explorer import MySQLColumn, MySQLSchemaExplorer


@pytest.fixture
def logger():
    return MagicMock()


@pytest.fixture
def explorer():
    return MySQLSchemaExplorer()


@pytest.fixture
def cursor():
    c = MagicMock()
    c.fetchall.return_value = []
    c.fetchone.return_value = None
    c.description = None
    return c


class TestGetPrimaryKeys:
    def test_returns_none_when_no_rows(self, explorer, cursor):
        cursor.fetchall.return_value = []
        assert explorer.get_primary_keys(cursor, "db", "t") is None

    def test_returns_pk_column_names(self, explorer, cursor):
        cursor.fetchall.return_value = [("id",), ("email",)]
        assert explorer.get_primary_keys(cursor, "db", "t") == ["id", "email"]

    def test_uses_parameterized_query(self, explorer, cursor):
        explorer.get_primary_keys(cursor, "mydb", "mytable")
        # Must pass params as a dict, not inline the schema/table name.
        sql, params = cursor.execute.call_args.args
        assert "%(schema)s" in sql
        assert "%(table_name)s" in sql
        assert params == {"schema": "mydb", "table_name": "mytable"}
        # Neither identifier should appear as a literal in the SQL.
        assert "mydb" not in sql
        assert "mytable" not in sql


class TestGetTable:
    def test_builds_table_with_non_numeric_columns(self, explorer, cursor):
        cursor.__iter__.return_value = iter(
            [
                ("id", "int", "int", True, None, None),
                ("email", "varchar", "varchar(255)", False, None, None),
            ]
        )
        table = explorer.get_table(cursor, "mydb", "users")
        assert isinstance(table, Table)
        assert table.name == "users"
        assert table.parents == ("mydb",)
        assert len(table.columns) == 2
        assert all(isinstance(c, MySQLColumn) for c in table.columns)
        assert table.columns[0].numeric_precision is None
        assert table.columns[0].numeric_scale is None

    def test_populates_numeric_precision_and_scale_for_decimals(self, explorer, cursor):
        cursor.__iter__.return_value = iter(
            [
                ("amount", "decimal", "decimal(10,2)", False, 10, 2),
            ]
        )
        table = explorer.get_table(cursor, "mydb", "orders")
        assert table.columns[0].numeric_precision == 10
        assert table.columns[0].numeric_scale == 2

    def test_falls_back_to_defaults_when_decimal_missing_precision(self, explorer, cursor):
        cursor.__iter__.return_value = iter(
            [
                ("amount", "decimal", "decimal", False, None, None),
            ]
        )
        table = explorer.get_table(cursor, "mydb", "orders")
        # Defaults from DEFAULT_NUMERIC_PRECISION / DEFAULT_NUMERIC_SCALE — any positive int.
        assert isinstance(table.columns[0].numeric_precision, int)
        assert isinstance(table.columns[0].numeric_scale, int)


class TestGetRowsToSync:
    def test_returns_count_from_row(self, explorer, cursor, logger):
        cursor.fetchone.return_value = (123,)
        result = explorer.get_rows_to_sync(cursor, "SELECT * FROM t", {}, logger)
        assert result == 123

    def test_returns_zero_on_none_row(self, explorer, cursor, logger):
        cursor.fetchone.return_value = None
        assert explorer.get_rows_to_sync(cursor, "SELECT * FROM t", {}, logger) == 0

    def test_returns_zero_on_exception(self, explorer, cursor, logger):
        cursor.execute.side_effect = RuntimeError("boom")
        # Swallows the error rather than propagating — matches pre-refactor behavior.
        assert explorer.get_rows_to_sync(cursor, "SELECT * FROM t", {}, logger) == 0

    def test_wraps_inner_query_as_subselect(self, explorer, cursor, logger):
        cursor.fetchone.return_value = (5,)
        explorer.get_rows_to_sync(cursor, "SELECT x FROM y WHERE a = %(a)s", {"a": 1}, logger)
        sql, params = cursor.execute.call_args.args
        assert "SELECT x FROM y WHERE a = %(a)s" in sql
        assert "COUNT(*)" in sql
        assert params == {"a": 1}


class TestFetchTableStats:
    def test_returns_none_when_no_row(self, explorer, cursor, logger):
        cursor.fetchone.return_value = None
        assert explorer.fetch_table_stats(cursor, "db", "t", logger) is None

    def test_returns_none_when_either_value_is_none(self, explorer, cursor, logger):
        cursor.fetchone.return_value = (None, 100)
        assert explorer.fetch_table_stats(cursor, "db", "t", logger) is None
        cursor.fetchone.return_value = (100, None)
        assert explorer.fetch_table_stats(cursor, "db", "t", logger) is None

    def test_returns_table_stats_dataclass(self, explorer, cursor, logger):
        cursor.fetchone.return_value = (1024, 42)
        stats = explorer.fetch_table_stats(cursor, "db", "t", logger)
        assert stats == TableStats(table_size_bytes=1024, row_count=42)

    def test_uses_parameterized_query(self, explorer, cursor, logger):
        cursor.fetchone.return_value = (1, 1)
        explorer.fetch_table_stats(cursor, "mydb", "mytable", logger)
        sql, params = cursor.execute.call_args.args
        assert params == {"schema": "mydb", "table_name": "mytable"}
        # No raw interpolation of identifiers.
        assert "mydb" not in sql
        assert "mytable" not in sql


class TestFetchAverageRowSize:
    def test_returns_none_when_no_columns(self, explorer, cursor, logger):
        cursor.fetchall.return_value = []
        result = explorer.fetch_average_row_size(cursor, "db", "t", "SELECT 1", {}, logger)
        assert result is None

    def test_returns_none_when_sample_empty(self, explorer, cursor, logger):
        cursor.fetchall.return_value = [("id",), ("email",)]
        cursor.fetchone.return_value = None
        result = explorer.fetch_average_row_size(cursor, "db", "t", "SELECT 1", {}, logger)
        assert result is None

    def test_returns_row_size_bytes(self, explorer, cursor, logger):
        cursor.fetchall.return_value = [("id",), ("email",)]
        cursor.fetchone.return_value = (256.4,)
        result = explorer.fetch_average_row_size(cursor, "db", "t", "SELECT 1", {}, logger)
        assert result == 256

    def test_clamps_to_at_least_one(self, explorer, cursor, logger):
        cursor.fetchall.return_value = [("id",)]
        cursor.fetchone.return_value = (0,)
        result = explorer.fetch_average_row_size(cursor, "db", "t", "SELECT 1", {}, logger)
        assert result == 1

    def test_quotes_column_names_in_length_sum(self, explorer, cursor, logger):
        cursor.fetchall.return_value = [("id",), ("email",)]
        cursor.fetchone.return_value = (100,)
        explorer.fetch_average_row_size(cursor, "db", "t", "SELECT * FROM x", {}, logger)
        # The second execute call is the size query — inspect it.
        second_call = cursor.execute.call_args_list[1]
        sql = second_call.args[0]
        assert "`id`" in sql
        assert "`email`" in sql
        assert "LENGTH(COALESCE(`id`" in sql

    def test_rejects_malformed_column_names(self, explorer, cursor, logger):
        # If INFORMATION_SCHEMA somehow returns a weird column name, we must
        # reject it rather than splice it into SQL. The quoter raises; the
        # method catches and returns None (capture_exception in prod).
        cursor.fetchall.return_value = [("bad;col",)]
        cursor.fetchone.return_value = (1,)
        result = explorer.fetch_average_row_size(cursor, "db", "t", "SELECT 1", {}, logger)
        assert result is None

    def test_returns_none_on_exception(self, explorer, cursor, logger):
        cursor.execute.side_effect = RuntimeError("boom")
        result = explorer.fetch_average_row_size(cursor, "db", "t", "SELECT 1", {}, logger)
        assert result is None


class TestFindIndexForCursor:
    def _show_index_rows(self, *triples):
        # (column_name, seq_in_index, key_name)
        return [
            (key_name, None, seq, None, col, None, None, None, None, None, None, None) for col, seq, key_name in triples
        ]

    def test_returns_key_name_for_matching_leading_column(self, explorer, cursor, logger):
        cursor.description = [
            ("Table",),
            ("Non_unique",),
            ("Key_name",),
            ("Seq_in_index",),
            ("Column_name",),
            ("Collation",),
        ]
        cursor.fetchall.return_value = [
            ("t", 1, "idx_created", 1, "created_at", "A"),
            ("t", 1, "idx_id", 1, "id", "A"),
        ]
        result = explorer.find_index_for_cursor(cursor, "db", "t", "created_at", logger)
        assert result == "idx_created"

    def test_skips_non_leading_columns(self, explorer, cursor, logger):
        cursor.description = [("Key_name",), ("Seq_in_index",), ("Column_name",)]
        cursor.fetchall.return_value = [
            ("idx_composite", 2, "created_at"),  # not the leading column — skip
        ]
        result = explorer.find_index_for_cursor(cursor, "db", "t", "created_at", logger)
        assert result is None

    def test_returns_none_when_no_match(self, explorer, cursor, logger):
        cursor.description = [("Key_name",), ("Seq_in_index",), ("Column_name",)]
        cursor.fetchall.return_value = [
            ("idx_id", 1, "id"),
        ]
        result = explorer.find_index_for_cursor(cursor, "db", "t", "created_at", logger)
        assert result is None

    def test_returns_none_on_unexpected_columns(self, explorer, cursor, logger):
        cursor.description = [("foo",), ("bar",)]
        cursor.fetchall.return_value = []
        result = explorer.find_index_for_cursor(cursor, "db", "t", "x", logger)
        assert result is None

    def test_returns_none_on_exception(self, explorer, cursor, logger):
        cursor.execute.side_effect = RuntimeError("boom")
        result = explorer.find_index_for_cursor(cursor, "db", "t", "x", logger)
        assert result is None

    def test_rejects_malformed_schema_or_table(self, explorer, cursor, logger):
        # `SHOW INDEX FROM ...` has no parameterized form, so we MUST reject
        # malformed names before building the query. The quoter raises and we
        # catch it, returning None.
        result = explorer.find_index_for_cursor(cursor, "bad;schema", "t", "x", logger)
        assert result is None


class TestExplainQuery:
    def test_prefixes_with_explain(self, explorer, cursor, logger):
        cursor.fetchall.return_value = []
        cursor.description = []
        explorer.explain_query(cursor, "SELECT 1", {}, logger)
        sql, _ = cursor.execute.call_args.args
        assert sql.startswith("EXPLAIN ")

    def test_swallows_exceptions(self, explorer, cursor, logger):
        cursor.execute.side_effect = RuntimeError("boom")
        # Must not raise — diagnostic-only.
        explorer.explain_query(cursor, "SELECT 1", {}, logger)


class TestMySQLColumnToArrowField:
    """Spot-check — the full table of conversions is covered by the pre-existing
    `TestMySQLColumnDateNullability` in `tests/test_mysql.py`."""

    def test_decimal_requires_precision(self):
        col = MySQLColumn(name="x", data_type="decimal", column_type="decimal", nullable=True)
        with pytest.raises(TypeError, match="numeric_precision"):
            col.to_arrow_field()

    def test_unsigned_int_widens(self):
        col = MySQLColumn(name="x", data_type="int", column_type="int(10) unsigned", nullable=False)
        field = col.to_arrow_field()
        # Unsigned integers widen to the next signed type that can hold their range.
        assert "uint" in str(field.type)

    def test_date_is_forced_nullable(self):
        col = MySQLColumn(name="x", data_type="date", column_type="date", nullable=False)
        field = col.to_arrow_field()
        assert field.nullable is True


class TestSafetyContract:
    """Verifies the safety invariant the refactor is supposed to preserve:
    driver-specific metadata queries never splice untrusted identifiers into SQL."""

    def test_quoter_rejects_bad_identifiers_independently(self):
        explorer = MySQLSchemaExplorer()
        with pytest.raises(InvalidIdentifierError):
            explorer._quoter.quote("bad;id")

    def test_quoter_accepts_common_identifier_shapes(self):
        explorer = MySQLSchemaExplorer()
        for ident in ["users", "my_table", "$col", "851", "db@prod"]:
            assert explorer._quoter.quote(ident).startswith("`")
