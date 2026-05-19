import datetime
from contextlib import contextmanager

import pytest
from unittest.mock import MagicMock

import pymysql

from posthog.temporal.data_imports.sources.common.sql import Table
from posthog.temporal.data_imports.sources.mysql.mysql import (
    STATEMENT_TIMEOUT_SECONDS,
    MySQLColumn,
    _build_query,
    _find_index_for_cursor,
    _is_bad_plan_timeout,
    _safe_convert_date,
    _safe_convert_datetime,
    _sanitize_identifier,
    mysql_source,
)
from posthog.temporal.data_imports.sources.mysql.source import MySQLSource

from products.data_warehouse.backend.types import IncrementalFieldType


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


@contextmanager
def _fake_tunnel():
    yield "localhost", 3306


@pytest.fixture
def mysql_mocks(mocker):
    """Patch pymysql.connect and metadata helpers so mysql_source can run end-to-end
    without a real MySQL server. Returns (mock_connect, setup_cursor, ss_cursor).

    pymysql.connect is called twice: once for the metadata pass in mysql_source(),
    and once inside get_rows() for the streaming connection we care about testing.
    """
    fake_table = Table(
        name="messages",
        parents=("mydb",),
        columns=[MySQLColumn(name="id", data_type="int", column_type="int", nullable=False)],
    )
    mocker.patch("posthog.temporal.data_imports.sources.mysql.mysql._get_table", return_value=fake_table)
    mocker.patch("posthog.temporal.data_imports.sources.mysql.mysql._get_primary_keys", return_value=["id"])
    mocker.patch("posthog.temporal.data_imports.sources.mysql.mysql._get_rows_to_sync", return_value=0)
    mocker.patch("posthog.temporal.data_imports.sources.mysql.mysql._get_table_chunk_size", return_value=1000)
    mocker.patch("posthog.temporal.data_imports.sources.mysql.mysql._get_partition_settings", return_value=None)

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
    source = mysql_source(
        tunnel=_fake_tunnel,
        user="u",
        password="p",
        database="d",
        using_ssl=False,
        schema="mydb",
        table_names=["messages"],
        should_use_incremental_field=False,
        logger=MagicMock(),
        db_incremental_field_last_value=None,
    )
    list(source.items())  # type: ignore[arg-type]  # MySQL source is always sync


class TestStreamingConnectionTimeouts:
    def test_read_timeout_is_passed_to_streaming_connection(self, mysql_mocks):
        mock_connect, _, _ = mysql_mocks
        _drain_source()
        streaming_kwargs = mock_connect.call_args_list[1].kwargs
        assert streaming_kwargs["read_timeout"] == STATEMENT_TIMEOUT_SECONDS

    def test_set_session_timeouts_are_executed(self, mysql_mocks):
        _, setup_cursor, _ = mysql_mocks
        _drain_source()
        executed = [c.args[0] for c in setup_cursor.execute.call_args_list if c.args]
        set_session = next((sql for sql in executed if "SET SESSION" in sql), None)
        assert set_session is not None
        assert f"net_write_timeout = {STATEMENT_TIMEOUT_SECONDS}" in set_session
        assert f"net_read_timeout = {STATEMENT_TIMEOUT_SECONDS}" in set_session

    def test_sync_continues_when_set_session_raises(self, mysql_mocks):
        _, setup_cursor, ss_cursor = mysql_mocks
        setup_cursor.execute.side_effect = Exception("SET SESSION denied")

        _drain_source()

        assert ss_cursor.execute.called


def _show_index_rows(*triples: tuple[str, str, int]) -> list[tuple]:
    """Build fake SHOW INDEX rows from (key_name, column_name, seq_in_index) triples.

    Column order must match the cursor.description returned by the mock.
    """
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
        cursor = MagicMock()
        cursor.description = _SHOW_INDEX_COLUMNS
        cursor.fetchall.return_value = rows
        return cursor

    def test_returns_index_name_when_cursor_is_leading_column(self):
        cursor = self._make_cursor(_show_index_rows(("idx_created_at", "created_at", 1)))
        result = _find_index_for_cursor(cursor, "mydb", "message", "created_at", MagicMock())
        assert result == "idx_created_at"

    def test_returns_none_when_cursor_is_not_leading_column(self):
        # Composite index (user_id, created_at) — can't use for WHERE on created_at alone
        cursor = self._make_cursor(
            _show_index_rows(
                ("idx_composite", "user_id", 1),
                ("idx_composite", "created_at", 2),
            )
        )
        result = _find_index_for_cursor(cursor, "mydb", "message", "created_at", MagicMock())
        assert result is None

    def test_returns_none_when_no_index_mentions_cursor(self):
        cursor = self._make_cursor(_show_index_rows(("PRIMARY", "id", 1)))
        result = _find_index_for_cursor(cursor, "mydb", "message", "created_at", MagicMock())
        assert result is None

    def test_returns_first_matching_index_among_several(self):
        cursor = self._make_cursor(
            _show_index_rows(
                ("idx_a", "created_at", 1),
                ("idx_b", "created_at", 1),
            )
        )
        result = _find_index_for_cursor(cursor, "mydb", "message", "created_at", MagicMock())
        assert result == "idx_a"

    def test_returns_none_on_query_failure(self):
        cursor = MagicMock()
        cursor.execute.side_effect = Exception("SHOW INDEX failed")
        result = _find_index_for_cursor(cursor, "mydb", "message", "created_at", MagicMock())
        assert result is None


class TestIsBadPlanTimeout:
    def test_matches_error_2013(self):
        assert _is_bad_plan_timeout(pymysql.err.OperationalError(2013, "Lost connection to MySQL server during query"))

    @pytest.mark.parametrize(
        "code,message",
        [
            (2003, "Can't connect to MySQL server"),
            (1045, "Access denied for user"),
        ],
    )
    def test_does_not_match_other_error_codes(self, code, message):
        assert not _is_bad_plan_timeout(pymysql.err.OperationalError(code, message))

    def test_does_not_match_error_without_args(self):
        assert not _is_bad_plan_timeout(pymysql.err.OperationalError())


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
