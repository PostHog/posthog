import pytest
from unittest.mock import MagicMock

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from posthog.temporal.data_imports.sources.common.sql import Table, TableStats
from posthog.temporal.data_imports.sources.generated_configs import MSSQLSourceConfig
from posthog.temporal.data_imports.sources.mssql.mssql import (
    MSSQLColumn,
    MSSQLImplementation,
    _build_query,
    filter_mssql_incremental_fields,
)
from posthog.temporal.data_imports.sources.mssql.source import MSSQLSource

from products.data_warehouse.backend.types import IncrementalFieldType


def _make_config(**overrides) -> MSSQLSourceConfig:
    defaults: dict = {
        "host": "localhost",
        "port": 1433,
        "database": "d",
        "user": "u",
        "password": "p",
        "schema": "dbo",
    }
    defaults.update(overrides)
    return MSSQLSourceConfig.from_dict(defaults)


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
# Pure helper tests
# ---------------------------------------------------------------------------


class TestFilterMSSQLIncrementalFields:
    @pytest.mark.parametrize(
        "col_type,expected",
        [
            ("date", IncrementalFieldType.Date),
            ("datetime", IncrementalFieldType.DateTime),
            ("datetime2", IncrementalFieldType.DateTime),
            ("smalldatetime", IncrementalFieldType.DateTime),
            ("tinyint", IncrementalFieldType.Integer),
            ("smallint", IncrementalFieldType.Integer),
            ("int", IncrementalFieldType.Integer),
            ("bigint", IncrementalFieldType.Integer),
        ],
    )
    def test_recognized_types(self, col_type, expected):
        result = filter_mssql_incremental_fields([("col", col_type, True)])
        assert result == [("col", expected, True)]

    def test_drops_unsupported(self):
        result = filter_mssql_incremental_fields([("col", "varchar", False)])
        assert result == []


class TestMSSQLColumnToArrowField:
    def test_decimal_requires_precision(self):
        col = MSSQLColumn(name="x", data_type="decimal", nullable=True)
        with pytest.raises(TypeError, match="numeric_precision"):
            col.to_arrow_field()


class TestBuildQuery:
    def test_full_refresh_no_incremental(self):
        query, args = _build_query(
            schema="dbo",
            table_name="users",
            should_use_incremental_field=False,
            incremental_field=None,
            incremental_field_type=None,
            db_incremental_field_last_value=None,
        )
        assert "SELECT" in query
        assert "[dbo].[users]" in query
        assert "TOP" not in query
        assert args == {}

    def test_incremental_adds_where(self):
        query, args = _build_query(
            schema="dbo",
            table_name="users",
            should_use_incremental_field=True,
            incremental_field="created_at",
            incremental_field_type=IncrementalFieldType.DateTime,
            db_incremental_field_last_value="2025-01-01",
        )
        assert "WHERE [created_at]" in query
        assert "%(incremental_value)s" in query
        assert args == {"incremental_value": "2025-01-01"}

    def test_add_limit_uses_top_100(self):
        query, _ = _build_query(
            schema="dbo",
            table_name="users",
            should_use_incremental_field=False,
            incremental_field=None,
            incremental_field_type=None,
            db_incremental_field_last_value=None,
            add_limit=True,
        )
        assert "TOP 100" in query

    def test_incremental_requires_field(self):
        with pytest.raises(ValueError, match="incremental_field"):
            _build_query(
                schema="dbo",
                table_name="users",
                should_use_incremental_field=True,
                incremental_field=None,
                incremental_field_type=None,
                db_incremental_field_last_value=None,
            )

    @pytest.mark.parametrize(
        "schema,table_name",
        [
            ("dbo]; DROP TABLE foo; --", "users"),
            ("dbo", "users]; DROP TABLE foo; --"),
            ("dbo with space", "users"),
            ("dbo", "users'name"),
        ],
    )
    def test_rejects_unsafe_schema_or_table(self, schema, table_name):
        with pytest.raises(ValueError, match="Invalid SQL identifier"):
            _build_query(
                schema=schema,
                table_name=table_name,
                should_use_incremental_field=False,
                incremental_field=None,
                incremental_field_type=None,
                db_incremental_field_last_value=None,
            )

    def test_rejects_unsafe_incremental_field(self):
        with pytest.raises(ValueError, match="Invalid SQL identifier"):
            _build_query(
                schema="dbo",
                table_name="users",
                should_use_incremental_field=True,
                incremental_field="created_at]; DROP TABLE foo; --",
                incremental_field_type=IncrementalFieldType.DateTime,
                db_incremental_field_last_value="2025-01-01",
            )


# ---------------------------------------------------------------------------
# Per-cursor metadata queries
# ---------------------------------------------------------------------------


@pytest.fixture
def impl() -> MSSQLImplementation:
    return MSSQLImplementation()


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
        assert impl.get_primary_keys_for_table(cursor, "dbo", "t") is None

    def test_returns_pk_column_names(self, impl, cursor):
        cursor.fetchall.return_value = [("id",), ("email",)]
        assert impl.get_primary_keys_for_table(cursor, "dbo", "t") == ["id", "email"]

    def test_uses_parameterized_query(self, impl, cursor):
        impl.get_primary_keys_for_table(cursor, "dbo", "mytable")
        sql, params = cursor.execute.call_args.args
        assert "%(schema)s" in sql
        assert "%(table_name)s" in sql
        assert params == {"schema": "dbo", "table_name": "mytable"}


class TestGetTableMetadata:
    def test_builds_table_with_non_numeric_columns(self, impl, cursor):
        cursor.__iter__.return_value = iter(
            [
                ("id", "int", True, None, None),
                ("email", "varchar", False, None, None),
            ]
        )
        table = impl.get_table_metadata(cursor, "dbo", "users")
        assert isinstance(table, Table)
        assert table.name == "users"
        assert table.parents == ("dbo",)
        assert len(table.columns) == 2
        assert all(isinstance(c, MSSQLColumn) for c in table.columns)
        assert table.columns[0].numeric_precision is None

    def test_populates_numeric_precision_and_scale_for_decimals(self, impl, cursor):
        cursor.__iter__.return_value = iter(
            [
                ("amount", "decimal", False, 10, 2),
            ]
        )
        table = impl.get_table_metadata(cursor, "dbo", "orders")
        assert table.columns[0].numeric_precision == 10
        assert table.columns[0].numeric_scale == 2

    def test_falls_back_to_defaults_when_decimal_missing_precision(self, impl, cursor):
        cursor.__iter__.return_value = iter(
            [
                ("amount", "decimal", False, None, None),
            ]
        )
        table = impl.get_table_metadata(cursor, "dbo", "orders")
        assert isinstance(table.columns[0].numeric_precision, int)
        assert isinstance(table.columns[0].numeric_scale, int)

    def test_raises_when_no_columns(self, impl, cursor):
        cursor.__iter__.return_value = iter([])
        with pytest.raises(ValueError, match="not found"):
            impl.get_table_metadata(cursor, "dbo", "missing")


class TestFetchTableStats:
    def test_returns_none_when_no_row(self, impl, cursor, logger):
        cursor.fetchone.return_value = None
        assert impl.fetch_table_stats(cursor, "dbo", "t", logger) is None

    def test_returns_table_stats_dataclass(self, impl, cursor, logger):
        # sp_spaceused result shape: name, rows, reserved, data, index_size, unused
        cursor.fetchone.return_value = ("t", "1000", "40 KB", "32 KB", "8 KB", "0 KB")
        stats = impl.fetch_table_stats(cursor, "dbo", "t", logger)
        assert stats == TableStats(table_size_bytes=32 * 1024, row_count=1000)

    def test_returns_none_on_unknown_unit(self, impl, cursor, logger):
        cursor.fetchone.return_value = ("t", "1000", "40 ZB", "32 ZB", "8 ZB", "0 ZB")
        assert impl.fetch_table_stats(cursor, "dbo", "t", logger) is None

    def test_returns_none_on_exception(self, impl, cursor, logger):
        cursor.execute.side_effect = RuntimeError("boom")
        assert impl.fetch_table_stats(cursor, "dbo", "t", logger) is None


class TestFetchAverageRowSize:
    """MSSQL's `fetch_average_row_size` samples a separate `TOP 100` query
    rather than the live inner_query, so the `inner_query` / `inner_query_args`
    arguments are accepted for API parity but unused."""

    def test_returns_none_when_no_columns(self, impl, cursor, logger):
        cursor.fetchall.return_value = []
        result = impl.fetch_average_row_size(cursor, "dbo", "t", "SELECT 1", {}, logger)
        assert result is None

    def test_returns_none_when_sample_empty(self, impl, cursor, logger):
        cursor.fetchall.return_value = [("id",), ("email",)]
        cursor.fetchone.return_value = None
        result = impl.fetch_average_row_size(cursor, "dbo", "t", "SELECT 1", {}, logger)
        assert result is None

    def test_returns_row_size_bytes(self, impl, cursor, logger):
        cursor.fetchall.return_value = [("id",), ("email",)]
        cursor.fetchone.return_value = (256.4,)
        result = impl.fetch_average_row_size(cursor, "dbo", "t", "SELECT 1", {}, logger)
        assert result == 256

    def test_clamps_to_at_least_one(self, impl, cursor, logger):
        cursor.fetchall.return_value = [("id",)]
        cursor.fetchone.return_value = (0,)
        result = impl.fetch_average_row_size(cursor, "dbo", "t", "SELECT 1", {}, logger)
        assert result == 1

    def test_uses_separate_top_100_sample(self, impl, cursor, logger):
        cursor.fetchall.return_value = [("id",)]
        cursor.fetchone.return_value = (10,)
        impl.fetch_average_row_size(cursor, "dbo", "t", "SELECT 1", {}, logger)
        size_query = cursor.execute.call_args_list[1].args[0]
        assert "TOP 100" in size_query
        assert "DATALENGTH([id])" in size_query

    def test_rejects_malformed_column_names(self, impl, cursor, logger):
        # If INFORMATION_SCHEMA returns a weird column name, the quoter
        # must reject it rather than splice it into SQL. Method catches
        # and returns None.
        cursor.fetchall.return_value = [("bad;col",)]
        cursor.fetchone.return_value = (1,)
        result = impl.fetch_average_row_size(cursor, "dbo", "t", "SELECT 1", {}, logger)
        assert result is None

    def test_returns_none_on_exception(self, impl, cursor, logger):
        cursor.execute.side_effect = RuntimeError("boom")
        result = impl.fetch_average_row_size(cursor, "dbo", "t", "SELECT 1", {}, logger)
        assert result is None


# ---------------------------------------------------------------------------
# End-to-end build_pipeline — wired through MSSQLImplementation
# ---------------------------------------------------------------------------


@pytest.fixture
def build_pipeline_mocks(mocker):
    """Patch pymssql.connect + per-cursor metadata methods on MSSQLImplementation
    so `build_pipeline` can run end-to-end without a real MSSQL server."""
    fake_table = Table(
        name="messages",
        parents=("dbo",),
        columns=[MSSQLColumn(name="id", data_type="int", nullable=False)],
    )
    mocker.patch.object(MSSQLImplementation, "get_table_metadata", return_value=fake_table)
    mocker.patch.object(MSSQLImplementation, "get_primary_keys_for_table", return_value=["id"])
    mocker.patch.object(MSSQLImplementation, "get_rows_to_sync", return_value=0)
    mocker.patch.object(MSSQLImplementation, "get_chunk_size", return_value=1000)
    mocker.patch.object(MSSQLImplementation, "get_partition_settings", return_value=None)

    streaming_cursor = MagicMock()
    streaming_cursor.__enter__.return_value = streaming_cursor
    streaming_cursor.description = [("id",)]
    streaming_cursor.fetchmany.return_value = []

    metadata_cursor = MagicMock()
    metadata_cursor.__enter__.return_value = metadata_cursor

    state = {"metadata_done": False}

    def cursor_factory(*args, **kwargs):
        if not state["metadata_done"]:
            state["metadata_done"] = True
            return metadata_cursor
        return streaming_cursor

    mock_connection = MagicMock()
    mock_connection.__enter__.return_value = mock_connection
    mock_connection.cursor.side_effect = cursor_factory

    mock_connect = mocker.patch(
        "posthog.temporal.data_imports.sources.mssql.mssql.pymssql.connect",
        return_value=mock_connection,
    )
    return mock_connect, streaming_cursor


def _drain_source():
    source = MSSQLImplementation().build_pipeline(_make_config(), _make_inputs())
    list(source.items())  # type: ignore[arg-type]


class TestBuildPipeline:
    def test_streams_through_separate_connection(self, build_pipeline_mocks):
        mock_connect, streaming_cursor = build_pipeline_mocks
        _drain_source()
        # Two connect calls: one for metadata, one for streaming.
        assert mock_connect.call_count == 2
        assert streaming_cursor.execute.called


class TestMSSQLSourceNonRetryableErrors:
    @pytest.mark.parametrize(
        "error_msg",
        [
            "Cannot build decimal array from values",
            "ValueError: Cannot build decimal array from values",
            "Source column type changed",
            "SchemaColumnTypeChangedException: Source column type changed: 'id' no longer fits",
        ],
    )
    def test_data_shape_errors_are_non_retryable(self, error_msg):
        non_retryable = MSSQLSource().get_non_retryable_errors()
        assert any(pattern in error_msg for pattern in non_retryable.keys()), error_msg
