import datetime
from collections.abc import Generator
from typing import cast

import pytest
from unittest.mock import MagicMock

import pymysql

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from posthog.temporal.data_imports.sources.common.sql import Table, TableStats
from posthog.temporal.data_imports.sources.generated_configs import MySQLSourceConfig
from posthog.temporal.data_imports.sources.mysql.mysql import (
    STATEMENT_TIMEOUT_SECONDS,
    MySQLColumn,
    MySQLImplementation,
    _build_query,
    _is_bad_plan_error,
    _release_streaming_cursor,
    _safe_convert_date,
    _safe_convert_datetime,
    _sanitize_identifier,
)
from posthog.temporal.data_imports.sources.mysql.source import MySQLSource

from products.data_warehouse.backend.types import IncrementalFieldType

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(**overrides) -> MySQLSourceConfig:
    """Build a MySQLSourceConfig for tests that drive `build_pipeline`.

    pymysql.connect is mocked in every test that uses this, so the host/port
    never have to resolve. `ssh_tunnel` is left unset so the default `None`
    is preserved — the str-coercing `from_dict` turns explicit Nones into
    "None" strings otherwise.
    """
    defaults: dict = {
        "host": "localhost",
        "port": 3306,
        "database": "d",
        "user": "u",
        "password": "p",
        "schema": "mydb",
        "using_ssl": "false",
    }
    defaults.update(overrides)
    return MySQLSourceConfig.from_dict(defaults)


def _make_inputs(schema_name: str = "messages", **overrides) -> SourceInputs:
    defaults: dict = {
        "schema_name": schema_name,
        "schema_id": "schema-id",
        "source_id": "source-id",
        "team_id": 1,
        "should_use_incremental_field": False,
        "db_incremental_field_last_value": None,
        "db_incremental_field_earliest_value": None,
        "incremental_field": None,
        "incremental_field_type": None,
        "job_id": "job-id",
        "logger": MagicMock(),
        "reset_pipeline": False,
    }
    defaults.update(overrides)
    return SourceInputs(**defaults)


# ---------------------------------------------------------------------------
# Pure helper tests (unchanged — these are module-scope primitives)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "identifier,expected",
    [
        ("mydb", "`mydb`"),
        ("851", "`851`"),
        ("$col", "`$col`"),
        ("db@prod", "`db@prod`"),
    ],
)
def test_sanitize_identifier_valid(identifier, expected):
    assert _sanitize_identifier(identifier) == expected


@pytest.mark.parametrize(
    "identifier",
    [
        "bad;id",
        "$bad!",
    ],
)
def test_sanitize_identifier_invalid(identifier):
    with pytest.raises(ValueError, match="Invalid SQL identifier"):
        _sanitize_identifier(identifier)


class TestSafeConvertDate:
    @pytest.mark.parametrize(
        "input_val,expected",
        [
            ("2024-03-15", datetime.date(2024, 3, 15)),
            ("1970-01-01", datetime.date(1970, 1, 1)),
            ("9999-12-31", datetime.date(9999, 12, 31)),
            (b"2024-03-15", datetime.date(2024, 3, 15)),
        ],
    )
    def test_valid_dates(self, input_val, expected):
        assert _safe_convert_date(input_val) == expected

    @pytest.mark.parametrize(
        "input_val",
        [
            "0000-00-00",
            b"0000-00-00",
            "invalid",
            "",
        ],
    )
    def test_invalid_dates_return_none(self, input_val):
        assert _safe_convert_date(input_val) is None


class TestSafeConvertDatetime:
    @pytest.mark.parametrize(
        "input_val,expected",
        [
            ("2024-03-15 10:30:45", datetime.datetime(2024, 3, 15, 10, 30, 45)),
            ("2024-03-15 10:30:45.123456", datetime.datetime(2024, 3, 15, 10, 30, 45, 123456)),
            ("1970-01-01 00:00:00", datetime.datetime(1970, 1, 1, 0, 0, 0)),
            (b"2024-03-15 10:30:45", datetime.datetime(2024, 3, 15, 10, 30, 45)),
        ],
    )
    def test_valid_datetimes(self, input_val, expected):
        assert _safe_convert_datetime(input_val) == expected

    @pytest.mark.parametrize(
        "input_val",
        [
            "0000-00-00 00:00:00",
            b"0000-00-00 00:00:00",
            "invalid",
            "",
        ],
    )
    def test_invalid_datetimes_return_none(self, input_val):
        assert _safe_convert_datetime(input_val) is None


class TestMySQLColumnDateNullability:
    @pytest.mark.parametrize(
        "data_type",
        [
            "date",
            "datetime",
            "timestamp",
        ],
    )
    def test_date_columns_always_nullable(self, data_type):
        column = MySQLColumn(
            name="test_col",
            data_type=data_type,
            column_type=data_type,
            nullable=False,
        )
        field = column.to_arrow_field()
        assert field.nullable is True

    def test_non_date_column_respects_nullable_flag(self):
        column = MySQLColumn(
            name="test_col",
            data_type="int",
            column_type="int",
            nullable=False,
        )
        field = column.to_arrow_field()
        assert field.nullable is False


class TestMySQLColumnToArrowField:
    def test_decimal_requires_precision(self):
        col = MySQLColumn(name="x", data_type="decimal", column_type="decimal", nullable=True)
        with pytest.raises(TypeError, match="numeric_precision"):
            col.to_arrow_field()

    def test_unsigned_int_widens(self):
        col = MySQLColumn(name="x", data_type="int", column_type="int(10) unsigned", nullable=False)
        field = col.to_arrow_field()
        # Unsigned integers widen to the next signed type that can hold their range.
        assert "uint" in str(field.type)


# ---------------------------------------------------------------------------
# Per-cursor metadata queries — test MySQLImplementation methods directly
# ---------------------------------------------------------------------------


@pytest.fixture
def impl() -> MySQLImplementation:
    return MySQLImplementation()


@pytest.fixture
def logger() -> MagicMock:
    return MagicMock()


@pytest.fixture
def cursor() -> MagicMock:
    c = MagicMock()
    c.fetchall.return_value = []
    c.fetchone.return_value = None
    c.description = None
    return c


class TestGetPrimaryKeysForTable:
    def test_returns_none_when_no_rows(self, impl, cursor):
        cursor.fetchall.return_value = []
        assert impl.get_primary_keys_for_table(cursor, "db", "t") is None

    def test_returns_pk_column_names(self, impl, cursor):
        cursor.fetchall.return_value = [("id",), ("email",)]
        assert impl.get_primary_keys_for_table(cursor, "db", "t") == ["id", "email"]

    def test_uses_parameterized_query(self, impl, cursor):
        impl.get_primary_keys_for_table(cursor, "mydb", "mytable")
        # Must pass params as a dict, not inline the schema/table name.
        sql, params = cursor.execute.call_args.args
        assert "%(schema)s" in sql
        assert "%(table_name)s" in sql
        assert params == {"schema": "mydb", "table_name": "mytable"}
        assert "mydb" not in sql
        assert "mytable" not in sql


class TestGetTableMetadata:
    def test_builds_table_with_non_numeric_columns(self, impl, cursor):
        cursor.__iter__.return_value = iter(
            [
                ("id", "int", "int", True, None, None),
                ("email", "varchar", "varchar(255)", False, None, None),
            ]
        )
        table = impl.get_table_metadata(cursor, "mydb", "users")
        assert isinstance(table, Table)
        assert table.name == "users"
        assert table.parents == ("mydb",)
        assert len(table.columns) == 2
        assert all(isinstance(c, MySQLColumn) for c in table.columns)
        assert table.columns[0].numeric_precision is None

    def test_populates_numeric_precision_and_scale_for_decimals(self, impl, cursor):
        cursor.__iter__.return_value = iter(
            [
                ("amount", "decimal", "decimal(10,2)", False, 10, 2),
            ]
        )
        table = impl.get_table_metadata(cursor, "mydb", "orders")
        assert table.columns[0].numeric_precision == 10
        assert table.columns[0].numeric_scale == 2

    def test_falls_back_to_defaults_when_decimal_missing_precision(self, impl, cursor):
        cursor.__iter__.return_value = iter(
            [
                ("amount", "decimal", "decimal", False, None, None),
            ]
        )
        table = impl.get_table_metadata(cursor, "mydb", "orders")
        assert isinstance(table.columns[0].numeric_precision, int)
        assert isinstance(table.columns[0].numeric_scale, int)


class TestGetRowsToSync:
    def test_returns_count_from_row(self, impl, cursor, logger):
        cursor.fetchone.return_value = (123,)
        result = impl.get_rows_to_sync(cursor, "SELECT * FROM t", {}, logger)
        assert result == 123

    def test_returns_zero_on_none_row(self, impl, cursor, logger):
        cursor.fetchone.return_value = None
        assert impl.get_rows_to_sync(cursor, "SELECT * FROM t", {}, logger) == 0

    def test_returns_zero_on_exception(self, impl, cursor, logger):
        cursor.execute.side_effect = RuntimeError("boom")
        # Swallows the error rather than propagating — matches pre-refactor behavior.
        assert impl.get_rows_to_sync(cursor, "SELECT * FROM t", {}, logger) == 0

    def test_wraps_inner_query_as_subselect(self, impl, cursor, logger):
        cursor.fetchone.return_value = (5,)
        impl.get_rows_to_sync(cursor, "SELECT x FROM y WHERE a = %(a)s", {"a": 1}, logger)
        sql, params = cursor.execute.call_args.args
        assert "SELECT x FROM y WHERE a = %(a)s" in sql
        assert "COUNT(*)" in sql
        assert params == {"a": 1}


class TestFetchTableStats:
    def test_returns_none_when_no_row(self, impl, cursor, logger):
        cursor.fetchone.return_value = None
        assert impl.fetch_table_stats(cursor, "db", "t", logger) is None

    def test_returns_none_when_either_value_is_none(self, impl, cursor, logger):
        cursor.fetchone.return_value = (None, 100)
        assert impl.fetch_table_stats(cursor, "db", "t", logger) is None
        cursor.fetchone.return_value = (100, None)
        assert impl.fetch_table_stats(cursor, "db", "t", logger) is None

    def test_returns_table_stats_dataclass(self, impl, cursor, logger):
        cursor.fetchone.return_value = (1024, 42)
        stats = impl.fetch_table_stats(cursor, "db", "t", logger)
        assert stats == TableStats(table_size_bytes=1024, row_count=42)

    def test_uses_parameterized_query(self, impl, cursor, logger):
        cursor.fetchone.return_value = (1, 1)
        impl.fetch_table_stats(cursor, "mydb", "mytable", logger)
        sql, params = cursor.execute.call_args.args
        assert params == {"schema": "mydb", "table_name": "mytable"}
        assert "mydb" not in sql
        assert "mytable" not in sql


class TestFetchAverageRowSize:
    def test_returns_none_when_no_columns(self, impl, cursor, logger):
        cursor.fetchall.return_value = []
        result = impl.fetch_average_row_size(cursor, "db", "t", "SELECT 1", {}, logger)
        assert result is None

    def test_returns_none_when_sample_empty(self, impl, cursor, logger):
        cursor.fetchall.return_value = [("id",), ("email",)]
        cursor.fetchone.return_value = None
        result = impl.fetch_average_row_size(cursor, "db", "t", "SELECT 1", {}, logger)
        assert result is None

    def test_returns_row_size_bytes(self, impl, cursor, logger):
        cursor.fetchall.return_value = [("id",), ("email",)]
        cursor.fetchone.return_value = (256.4,)
        result = impl.fetch_average_row_size(cursor, "db", "t", "SELECT 1", {}, logger)
        assert result == 256

    def test_clamps_to_at_least_one(self, impl, cursor, logger):
        cursor.fetchall.return_value = [("id",)]
        cursor.fetchone.return_value = (0,)
        result = impl.fetch_average_row_size(cursor, "db", "t", "SELECT 1", {}, logger)
        assert result == 1

    def test_quotes_column_names_in_length_sum(self, impl, cursor, logger):
        cursor.fetchall.return_value = [("id",), ("email",)]
        cursor.fetchone.return_value = (100,)
        impl.fetch_average_row_size(cursor, "db", "t", "SELECT * FROM x", {}, logger)
        # The second execute call is the size query — inspect it.
        second_call = cursor.execute.call_args_list[1]
        sql = second_call.args[0]
        assert "`id`" in sql
        assert "`email`" in sql
        assert "LENGTH(COALESCE(`id`" in sql

    def test_rejects_malformed_column_names(self, impl, cursor, logger):
        # If INFORMATION_SCHEMA somehow returns a weird column name, we must
        # reject it rather than splice it into SQL. The quoter raises; the
        # method catches and returns None.
        cursor.fetchall.return_value = [("bad;col",)]
        cursor.fetchone.return_value = (1,)
        result = impl.fetch_average_row_size(cursor, "db", "t", "SELECT 1", {}, logger)
        assert result is None

    def test_returns_none_on_exception(self, impl, cursor, logger):
        cursor.execute.side_effect = RuntimeError("boom")
        result = impl.fetch_average_row_size(cursor, "db", "t", "SELECT 1", {}, logger)
        assert result is None


def _show_index_rows(*triples: tuple[str, str, int]) -> list[tuple]:
    """Build fake SHOW INDEX rows from (key_name, column_name, seq_in_index) triples."""
    return [
        (
            "message",  # Table
            1,  # Non_unique
            key_name,  # Key_name
            seq,  # Seq_in_index
            column,  # Column_name
            "A",  # Collation
            1000,  # Cardinality
            None,  # Sub_part
            None,  # Packed
            "",  # Null
            "BTREE",  # Index_type
            "",  # Comment
            "",  # Index_comment
            "YES",  # Visible
            None,  # Expression
        )
        for key_name, column, seq in triples
    ]


_SHOW_INDEX_COLUMNS = [
    ("Table",),
    ("Non_unique",),
    ("Key_name",),
    ("Seq_in_index",),
    ("Column_name",),
    ("Collation",),
    ("Cardinality",),
    ("Sub_part",),
    ("Packed",),
    ("Null",),
    ("Index_type",),
    ("Comment",),
    ("Index_comment",),
    ("Visible",),
    ("Expression",),
]


class TestFindIndexForCursor:
    def _make_cursor(self, rows):
        c = MagicMock()
        c.description = _SHOW_INDEX_COLUMNS
        c.fetchall.return_value = rows
        return c

    def test_returns_index_name_when_cursor_is_leading_column(self, impl, logger):
        c = self._make_cursor(_show_index_rows(("idx_created_at", "created_at", 1)))
        assert impl.find_index_for_cursor(c, "mydb", "message", "created_at", logger) == "idx_created_at"

    def test_returns_none_when_cursor_is_not_leading_column(self, impl, logger):
        # Composite index (user_id, created_at) — can't use for WHERE on created_at alone
        c = self._make_cursor(
            _show_index_rows(
                ("idx_composite", "user_id", 1),
                ("idx_composite", "created_at", 2),
            )
        )
        assert impl.find_index_for_cursor(c, "mydb", "message", "created_at", logger) is None

    def test_returns_none_when_no_index_mentions_cursor(self, impl, logger):
        c = self._make_cursor(_show_index_rows(("PRIMARY", "id", 1)))
        assert impl.find_index_for_cursor(c, "mydb", "message", "created_at", logger) is None

    def test_returns_first_matching_index_among_several(self, impl, logger):
        c = self._make_cursor(
            _show_index_rows(
                ("idx_a", "created_at", 1),
                ("idx_b", "created_at", 1),
            )
        )
        assert impl.find_index_for_cursor(c, "mydb", "message", "created_at", logger) == "idx_a"

    def test_returns_none_on_query_failure(self, impl, logger):
        c = MagicMock()
        c.execute.side_effect = Exception("SHOW INDEX failed")
        assert impl.find_index_for_cursor(c, "mydb", "message", "created_at", logger) is None

    def test_returns_none_on_unexpected_columns(self, impl, cursor, logger):
        cursor.description = [("foo",), ("bar",)]
        cursor.fetchall.return_value = []
        assert impl.find_index_for_cursor(cursor, "db", "t", "x", logger) is None

    def test_rejects_malformed_schema_or_table(self, impl, cursor, logger):
        # `SHOW INDEX FROM ...` has no parameterized form, so we MUST reject
        # malformed names before building the query.
        assert impl.find_index_for_cursor(cursor, "bad;schema", "t", "x", logger) is None


class TestExplainQuery:
    def test_prefixes_with_explain(self, impl, cursor, logger):
        cursor.fetchall.return_value = []
        cursor.description = []
        impl.explain_query(cursor, "SELECT 1", {}, logger)
        sql, _ = cursor.execute.call_args.args
        assert sql.startswith("EXPLAIN ")

    def test_swallows_exceptions(self, impl, cursor, logger):
        cursor.execute.side_effect = RuntimeError("boom")
        # Must not raise — diagnostic-only.
        impl.explain_query(cursor, "SELECT 1", {}, logger)

    def test_does_not_capture_exceptions(self, impl, cursor, logger, mocker):
        # EXPLAIN is best-effort diagnostics — a failure (e.g. MySQL 1345 when
        # EXPLAINing a view whose underlying tables the user can't SHOW VIEW on)
        # never affects the sync, so it must not be reported to error tracking.
        capture = mocker.patch("posthog.temporal.data_imports.sources.mysql.mysql.capture_exception")
        cursor.execute.side_effect = pymysql.err.OperationalError(
            1345, "EXPLAIN/SHOW can not be issued; lacking privileges for underlying table"
        )
        impl.explain_query(cursor, "SELECT 1", {}, logger)
        capture.assert_not_called()


class TestSafetyContract:
    """Verifies that driver-specific metadata queries never splice untrusted identifiers into SQL."""

    def test_quoter_rejects_bad_identifiers(self):
        # _sanitize_identifier wraps InvalidIdentifierError → ValueError for
        # back-compat with semgrep rules keyed on the legacy message shape.
        with pytest.raises(ValueError, match="Invalid SQL identifier"):
            _sanitize_identifier("bad;id")

    @pytest.mark.parametrize("ident", ["users", "my_table", "$col", "851", "db@prod"])
    def test_quoter_accepts_common_identifier_shapes(self, ident):
        assert _sanitize_identifier(ident).startswith("`")


# ---------------------------------------------------------------------------
# End-to-end build_pipeline — wired through MySQLImplementation
# ---------------------------------------------------------------------------


@pytest.fixture
def build_pipeline_mocks(mocker):
    """Patch pymysql.connect + per-cursor metadata methods on MySQLImplementation
    so `build_pipeline` can run end-to-end without a real MySQL server.

    pymysql.connect is called twice: once for the metadata pass inside
    `build_pipeline`, and once inside `get_rows()` for the streaming
    connection we care about testing.
    """
    fake_table = Table(
        name="messages",
        parents=("mydb",),
        columns=[MySQLColumn(name="id", data_type="int", column_type="int", nullable=False)],
    )
    mocker.patch.object(MySQLImplementation, "get_table_metadata", return_value=fake_table)
    mocker.patch.object(MySQLImplementation, "get_primary_keys_for_table", return_value=["id"])
    mocker.patch.object(MySQLImplementation, "get_rows_to_sync", return_value=0)
    mocker.patch.object(MySQLImplementation, "get_chunk_size", return_value=1000)
    mocker.patch.object(MySQLImplementation, "get_partition_settings", return_value=None)
    mocker.patch.object(MySQLImplementation, "explain_query")

    setup_cursor = MagicMock()
    setup_cursor.__enter__.return_value = setup_cursor

    ss_cursor = MagicMock()
    ss_cursor.__enter__.return_value = ss_cursor
    ss_cursor.description = [("id",)]
    ss_cursor.fetchmany.return_value = []

    metadata_cursor = MagicMock()
    metadata_cursor.__enter__.return_value = metadata_cursor

    # connection.cursor() is called 3 times total: once for metadata (no args),
    # once for the SET SESSION setup on the streaming connection (no args),
    # and once with SSCursor for the streaming query.
    state = {"metadata_done": False}

    def cursor_factory(*args, **kwargs):
        if args or kwargs:
            return ss_cursor
        if not state["metadata_done"]:
            state["metadata_done"] = True
            return metadata_cursor
        return setup_cursor

    mock_connection = MagicMock()
    mock_connection.__enter__.return_value = mock_connection
    mock_connection.cursor.side_effect = cursor_factory

    mock_connect = mocker.patch(
        "posthog.temporal.data_imports.sources.mysql.mysql.pymysql.connect",
        return_value=mock_connection,
    )
    return mock_connect, setup_cursor, ss_cursor


def _drain_source():
    source = MySQLImplementation().build_pipeline(_make_config(), _make_inputs())
    list(source.items())  # type: ignore[arg-type]  # MySQL source is always sync


class TestStreamingConnectionTimeouts:
    def test_read_timeout_is_passed_to_streaming_connection(self, build_pipeline_mocks):
        mock_connect, _, _ = build_pipeline_mocks
        _drain_source()
        streaming_kwargs = mock_connect.call_args_list[1].kwargs
        assert streaming_kwargs["read_timeout"] == STATEMENT_TIMEOUT_SECONDS

    def test_set_session_timeouts_are_executed(self, build_pipeline_mocks):
        _, setup_cursor, _ = build_pipeline_mocks
        _drain_source()
        executed = [c.args[0] for c in setup_cursor.execute.call_args_list if c.args]
        set_session = next((sql for sql in executed if "SET SESSION" in sql), None)
        assert set_session is not None
        assert f"net_write_timeout = {STATEMENT_TIMEOUT_SECONDS}" in set_session
        assert f"net_read_timeout = {STATEMENT_TIMEOUT_SECONDS}" in set_session

    def test_sync_continues_when_set_session_raises(self, build_pipeline_mocks):
        _, setup_cursor, ss_cursor = build_pipeline_mocks
        setup_cursor.execute.side_effect = Exception("SET SESSION denied")

        _drain_source()

        assert ss_cursor.execute.called


class TestReleaseStreamingCursor:
    def test_detaches_cursor_without_closing(self):
        cursor = MagicMock()
        _release_streaming_cursor(cursor)
        assert cursor.connection is None
        cursor.close.assert_not_called()


class TestStreamingCursorTeardown:
    """The streaming SSCursor must be torn down without draining its unbuffered
    result set, so an early exit can't resurface a lost-connection error over
    the real reason iteration stopped."""

    def test_early_close_does_not_drain_or_raise(self, build_pipeline_mocks):
        _, _, ss_cursor = build_pipeline_mocks
        # Every fetch returns a row, so the generator stays suspended at a yield
        # until we close it — mimicking a sync cancelled mid-stream.
        ss_cursor.fetchmany.return_value = [(1,)]
        ss_cursor.close.side_effect = pymysql.err.OperationalError(2013, "Lost connection to MySQL server during query")

        source = MySQLImplementation().build_pipeline(_make_config(), _make_inputs())
        # MySQL source is always sync, so items() yields a plain generator.
        rows = cast(Generator, source.items())
        next(rows)  # pull the first batch, suspend at the yield

        # A cancelled activity closes the generator early — this must not raise.
        rows.close()

        ss_cursor.close.assert_not_called()
        assert ss_cursor.connection is None

    def test_midstream_error_propagates_without_draining(self, build_pipeline_mocks):
        _, _, ss_cursor = build_pipeline_mocks
        # First fetch yields a batch, the second loses the connection mid-stream.
        ss_cursor.fetchmany.side_effect = [
            [(1,)],
            pymysql.err.OperationalError(2013, "Lost connection to MySQL server during query"),
        ]
        ss_cursor.close.side_effect = AssertionError("cursor must not be drained on teardown")

        source = MySQLImplementation().build_pipeline(_make_config(), _make_inputs())
        with pytest.raises(pymysql.err.OperationalError):
            list(source.items())  # type: ignore[arg-type]  # MySQL source is always sync

        ss_cursor.close.assert_not_called()
        assert ss_cursor.connection is None


class TestIsBadPlanError:
    def test_matches_error_2013(self):
        assert _is_bad_plan_error(pymysql.err.OperationalError(2013, "Lost connection to MySQL server during query"))

    def test_matches_error_1038_out_of_sort_memory(self):
        # Out of sort memory is the same bad plan (filesort over the incremental
        # field) seen from the other side — the FORCE INDEX fallback resolves it.
        assert _is_bad_plan_error(
            pymysql.err.OperationalError(1038, "Out of sort memory, consider increasing server sort buffer size")
        )

    @pytest.mark.parametrize(
        "code,message",
        [
            (2003, "Can't connect to MySQL server"),
            (1045, "Access denied for user"),
        ],
    )
    def test_does_not_match_other_error_codes(self, code, message):
        assert not _is_bad_plan_error(pymysql.err.OperationalError(code, message))

    def test_does_not_match_error_without_args(self):
        assert not _is_bad_plan_error(pymysql.err.OperationalError())


class TestBuildQueryForceIndex:
    def test_force_index_hint_omitted_by_default(self):
        query, _ = _build_query(
            schema="mydb",
            table_name="message",
            should_use_incremental_field=True,
            incremental_field="created_at",
            incremental_field_type=IncrementalFieldType.DateTime,
            db_incremental_field_last_value="2025-01-01",
        )
        assert "FORCE INDEX" not in query

    def test_force_index_hint_added_when_provided(self):
        query, _ = _build_query(
            schema="mydb",
            table_name="message",
            should_use_incremental_field=True,
            incremental_field="created_at",
            incremental_field_type=IncrementalFieldType.DateTime,
            db_incremental_field_last_value="2025-01-01",
            force_index_name="idx_created_at",
        )
        assert "FORCE INDEX (`idx_created_at`)" in query
        # Hint goes between the table and the WHERE clause
        assert query.index("FORCE INDEX") < query.index("WHERE")

    def test_force_index_hint_applied_for_non_incremental_query_too(self):
        # Full refresh mode — the hint still attaches so callers can force a
        # specific scan order if they choose (no ORDER BY, but hint is still valid).
        query, _ = _build_query(
            schema="mydb",
            table_name="message",
            should_use_incremental_field=False,
            incremental_field=None,
            incremental_field_type=None,
            db_incremental_field_last_value=None,
            force_index_name="PRIMARY",
        )
        assert "FORCE INDEX (`PRIMARY`)" in query

    def test_force_index_identifier_is_sanitized(self):
        # Rejects invalid SQL identifiers to prevent injection via index name.
        with pytest.raises(ValueError, match="Invalid SQL identifier"):
            _build_query(
                schema="mydb",
                table_name="message",
                should_use_incremental_field=True,
                incremental_field="created_at",
                incremental_field_type=IncrementalFieldType.DateTime,
                db_incremental_field_last_value="2025-01-01",
                force_index_name="bad;injection",
            )


class TestBuildQueryEnabledColumns:
    @pytest.mark.parametrize(
        "enabled_columns,primary_keys,expected_prefix",
        [
            (None, ["id"], "SELECT * FROM"),
            (["email"], ["id"], "SELECT `email`, `id` FROM"),
            ([], None, "SELECT * FROM"),
            ([], ["id"], "SELECT `id` FROM"),
        ],
    )
    def test_full_refresh_projection(
        self,
        enabled_columns: list[str] | None,
        primary_keys: list[str] | None,
        expected_prefix: str,
    ):
        query, _ = _build_query(
            schema="mydb",
            table_name="message",
            should_use_incremental_field=False,
            incremental_field=None,
            incremental_field_type=None,
            db_incremental_field_last_value=None,
            enabled_columns=enabled_columns,
            primary_keys=primary_keys,
        )
        assert query.startswith(expected_prefix)

    def test_incremental_projection_retains_incremental_field(self):
        query, _ = _build_query(
            schema="mydb",
            table_name="message",
            should_use_incremental_field=True,
            incremental_field="created_at",
            incremental_field_type=IncrementalFieldType.DateTime,
            db_incremental_field_last_value="2025-01-01",
            enabled_columns=["email"],
            primary_keys=["id"],
        )
        assert query.startswith("SELECT `email`, `id`, `created_at` FROM")
        assert "WHERE `created_at` > %(incremental_value)s" in query


class TestMySQLSourceNonRetryableErrors:
    @pytest.fixture
    def source(self):
        return MySQLSource()

    @pytest.mark.parametrize(
        "error_msg",
        [
            "Cannot build decimal array from values",
            "ValueError: Cannot build decimal array from values",
        ],
    )
    def test_unrepresentable_decimal_values_are_non_retryable(self, source, error_msg):
        non_retryable = source.get_non_retryable_errors()
        is_non_retryable = any(pattern in error_msg for pattern in non_retryable.keys())
        assert is_non_retryable, f"Unrepresentable decimal error should be non-retryable: {error_msg}"

    @pytest.mark.parametrize(
        "error_msg",
        [
            "Source column type changed",
            "SchemaColumnTypeChangedException: Source column type changed: 'id' has values that no longer fit",
        ],
    )
    def test_widened_integer_column_errors_are_non_retryable(self, source, error_msg):
        non_retryable = source.get_non_retryable_errors()
        is_non_retryable = any(pattern in error_msg for pattern in non_retryable.keys())
        assert is_non_retryable, f"Widened integer column error should be non-retryable: {error_msg}"

    @pytest.mark.parametrize(
        "error_msg",
        [
            "[SSL: WRONG_VERSION_NUMBER] wrong version number (_ssl.c:2657)",
            # The signature also arrives wrapped in pymysql's OperationalError(2013) — we must
            # still catch it without making the bare 2013/"Lost connection" text non-retryable.
            "OperationalError: (2013, 'Lost connection to MySQL server during query "
            "([SSL: WRONG_VERSION_NUMBER] wrong version number (_ssl.c:2657))')",
        ],
    )
    def test_ssl_wrong_version_number_is_non_retryable(self, source, error_msg):
        non_retryable = source.get_non_retryable_errors()
        is_non_retryable = any(pattern in error_msg for pattern in non_retryable.keys())
        assert is_non_retryable, f"SSL version mismatch should be non-retryable: {error_msg}"

    @pytest.mark.parametrize(
        "error_msg",
        [
            "is blocked because of many connection errors",
            # MariaDB phrasing (suggests mariadb-admin) — what we actually observed in the wild.
            "OperationalError: (1129, \"Host '172.31.4.130' is blocked because of many connection "
            "errors; unblock with 'mariadb-admin flush-hosts'\")",
            # MySQL phrasing (suggests mysqladmin) — same root cause, different unblock hint.
            "OperationalError: (1129, \"Host '10.0.1.5' is blocked because of many connection "
            "errors; unblock with 'mysqladmin flush-hosts'\")",
        ],
    )
    def test_host_blocked_is_non_retryable(self, source, error_msg):
        non_retryable = source.get_non_retryable_errors()
        is_non_retryable = any(pattern in error_msg for pattern in non_retryable.keys())
        assert is_non_retryable, f"Host-blocked error should be non-retryable: {error_msg}"

    @pytest.mark.parametrize(
        "error_msg",
        [
            # A genuine transient connection drop (no SSL signature) must stay retryable.
            "OperationalError: (2013, 'Lost connection to MySQL server during query')",
            "Lost connection to MySQL server during query",
        ],
    )
    def test_transient_lost_connection_stays_retryable(self, source, error_msg):
        non_retryable = source.get_non_retryable_errors()
        is_non_retryable = any(pattern in error_msg for pattern in non_retryable.keys())
        assert not is_non_retryable, f"Transient lost-connection error should remain retryable: {error_msg}"

    @pytest.mark.parametrize(
        "error_msg",
        [
            # MySQL error 1135: the server reached the connection but couldn't spawn an OS thread
            # to service it (errno 11 EAGAIN). This is a transient, server-side resource exhaustion
            # — it clears as concurrent connections close — so it must keep retrying, just like
            # Postgres's "too many connections" / "max clients reached" capacity errors.
            "OperationalError: (1135, 'Can't create a new thread (errno 11 \"Resource temporarily "
            'unavailable"); if you are not out of available memory, you can consult the manual for '
            "a possible OS-dependent bug')",
            'Can\'t create a new thread (errno 11 "Resource temporarily unavailable")',
        ],
    )
    def test_cant_create_new_thread_stays_retryable(self, source, error_msg):
        non_retryable = source.get_non_retryable_errors()
        is_non_retryable = any(pattern in error_msg for pattern in non_retryable.keys())
        assert not is_non_retryable, f"Transient thread-exhaustion error should remain retryable: {error_msg}"
