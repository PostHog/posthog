import pytest
from unittest.mock import MagicMock

from psycopg import sql

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from posthog.temporal.data_imports.pipelines.pipeline.utils import TemporaryFileSizeExceedsLimitException
from posthog.temporal.data_imports.sources.common.sql import Table, TableStats
from posthog.temporal.data_imports.sources.generated_configs import RedshiftSourceConfig
from posthog.temporal.data_imports.sources.redshift.redshift import (
    RedshiftColumn,
    RedshiftImplementation,
    filter_redshift_incremental_fields,
)
from posthog.temporal.data_imports.sources.redshift.source import _REDSHIFT_IMPLEMENTATION, RedshiftSource

from products.data_warehouse.backend.types import IncrementalFieldType

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(**overrides) -> RedshiftSourceConfig:
    defaults: dict = {
        "host": "localhost",
        "port": 5439,
        "database": "dev",
        "user": "u",
        "password": "p",
        "schema": "public",
    }
    defaults.update(overrides)
    return RedshiftSourceConfig.from_dict(defaults)


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


class TestFilterIncrementalFields:
    @pytest.mark.parametrize(
        "data_type,expected_type",
        [
            ("timestamp", IncrementalFieldType.Timestamp),
            ("timestamp without time zone", IncrementalFieldType.Timestamp),
            ("timestamp with time zone", IncrementalFieldType.Timestamp),
            ("date", IncrementalFieldType.Date),
            ("integer", IncrementalFieldType.Integer),
            ("bigint", IncrementalFieldType.Integer),
            ("smallint", IncrementalFieldType.Integer),
            ("int4", IncrementalFieldType.Integer),
            ("int8", IncrementalFieldType.Integer),
        ],
    )
    def test_includes_incremental_types(self, data_type, expected_type):
        result = filter_redshift_incremental_fields([("col", data_type, True)])
        assert result == [("col", expected_type, True)]

    @pytest.mark.parametrize("data_type", ["varchar", "text", "json", "super", "real"])
    def test_excludes_non_incremental_types(self, data_type):
        result = filter_redshift_incremental_fields([("col", data_type, True)])
        assert result == []


class TestRedshiftColumnToArrowField:
    def test_decimal_requires_precision(self):
        col = RedshiftColumn(name="x", data_type="decimal", nullable=True)
        with pytest.raises(TypeError, match="numeric_precision"):
            col.to_arrow_field()

    def test_bigint_maps_to_int64(self):
        col = RedshiftColumn(name="x", data_type="bigint", nullable=False)
        field = col.to_arrow_field()
        assert "int64" in str(field.type)
        assert field.nullable is False

    def test_timestamptz_carries_utc_timezone(self):
        col = RedshiftColumn(name="x", data_type="timestamptz", nullable=True)
        field = col.to_arrow_field()
        assert "UTC" in str(field.type)


# ---------------------------------------------------------------------------
# Per-cursor metadata queries — exercise impl methods directly
# ---------------------------------------------------------------------------


@pytest.fixture
def impl() -> RedshiftImplementation:
    return RedshiftImplementation()


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
        assert impl.get_primary_keys_for_table(cursor, "public", "t") is None

    def test_returns_pk_column_names(self, impl, cursor):
        cursor.fetchall.return_value = [("id",), ("email",)]
        assert impl.get_primary_keys_for_table(cursor, "public", "t") == ["id", "email"]


class TestGetTableMetadata:
    def test_builds_table_with_columns(self, impl, cursor):
        cursor.execute.return_value = cursor
        # First fetchone for is-view check; iteration for columns
        cursor.fetchone.return_value = (False,)
        cursor.__iter__.return_value = iter(
            [
                ("id", "integer", "NO", None, None),
                ("email", "varchar", "YES", None, None),
            ]
        )
        table = impl.get_table_metadata(cursor, "public", "users")
        assert table.name == "users"
        assert table.parents == ("public",)
        assert len(table.columns) == 2
        assert table.type == "table"

    def test_marks_view_when_is_view_true(self, impl, cursor):
        cursor.execute.return_value = cursor
        cursor.fetchone.return_value = (True,)
        cursor.__iter__.return_value = iter([("id", "integer", "NO", None, None)])
        table = impl.get_table_metadata(cursor, "public", "myview")
        assert table.type == "view"

    def test_populates_numeric_precision_and_scale_for_decimals(self, impl, cursor):
        cursor.execute.return_value = cursor
        cursor.fetchone.return_value = (False,)
        cursor.__iter__.return_value = iter(
            [
                ("amount", "decimal", "NO", 10, 2),
            ]
        )
        table = impl.get_table_metadata(cursor, "public", "orders")
        assert table.columns[0].numeric_precision == 10
        assert table.columns[0].numeric_scale == 2


class TestGetRowsToSync:
    def _inner(self):
        return sql.SQL("SELECT 1").format()

    def test_returns_count_from_row(self, impl, cursor, logger):
        cursor.fetchone.return_value = (123,)
        result = impl.get_rows_to_sync(cursor, self._inner(), None, logger)
        assert result == 123

    def test_returns_zero_on_none_row(self, impl, cursor, logger):
        cursor.fetchone.return_value = None
        assert impl.get_rows_to_sync(cursor, self._inner(), None, logger) == 0

    def test_returns_zero_on_generic_exception(self, impl, cursor, logger):
        cursor.execute.side_effect = RuntimeError("boom")
        assert impl.get_rows_to_sync(cursor, self._inner(), None, logger) == 0

    def test_raises_on_temp_file_limit(self, impl, cursor, logger):
        cursor.execute.side_effect = RuntimeError("temporary file size exceeds temp_file_limit")
        with pytest.raises(TemporaryFileSizeExceedsLimitException):
            impl.get_rows_to_sync(cursor, self._inner(), None, logger)


class TestFetchTableStats:
    def test_returns_none_when_no_row(self, impl, cursor, logger):
        cursor.fetchone.return_value = None
        assert impl.fetch_table_stats(cursor, "public", "t", logger) is None

    def test_returns_none_when_size_zero(self, impl, cursor, logger):
        cursor.fetchone.return_value = (0, 100)
        assert impl.fetch_table_stats(cursor, "public", "t", logger) is None

    def test_returns_none_when_rows_zero(self, impl, cursor, logger):
        cursor.fetchone.return_value = (10, 0)
        assert impl.fetch_table_stats(cursor, "public", "t", logger) is None

    def test_converts_size_mb_to_bytes(self, impl, cursor, logger):
        cursor.fetchone.return_value = (2, 100)  # 2 MB, 100 rows
        stats = impl.fetch_table_stats(cursor, "public", "t", logger)
        assert stats == TableStats(table_size_bytes=2 * 1024 * 1024, row_count=100)

    def test_returns_none_on_exception(self, impl, cursor, logger):
        cursor.execute.side_effect = RuntimeError("boom")
        assert impl.fetch_table_stats(cursor, "public", "t", logger) is None


class TestFetchAverageRowSize:
    def _inner(self):
        return sql.SQL("SELECT 1").format()

    def test_returns_none_when_no_row(self, impl, cursor, logger):
        cursor.fetchone.return_value = None
        assert impl.fetch_average_row_size(cursor, "public", "t", self._inner(), None, logger) is None

    def test_returns_none_when_row_value_is_none(self, impl, cursor, logger):
        cursor.fetchone.return_value = (None,)
        assert impl.fetch_average_row_size(cursor, "public", "t", self._inner(), None, logger) is None

    def test_returns_row_size_bytes(self, impl, cursor, logger):
        cursor.fetchone.return_value = (256.4,)
        result = impl.fetch_average_row_size(cursor, "public", "t", self._inner(), None, logger)
        assert result == 256

    def test_returns_none_on_exception(self, impl, cursor, logger):
        cursor.execute.side_effect = [None, RuntimeError("boom")]
        assert impl.fetch_average_row_size(cursor, "public", "t", self._inner(), None, logger) is None


class TestHasDuplicatePrimaryKeys:
    def test_returns_false_when_no_pks(self, impl, cursor, logger):
        assert impl.has_duplicate_primary_keys(cursor, "public", "t", None, logger) is False
        assert impl.has_duplicate_primary_keys(cursor, "public", "t", [], logger) is False

    def test_returns_true_when_row_found(self, impl, cursor, logger):
        cursor.fetchone.return_value = (1,)
        assert impl.has_duplicate_primary_keys(cursor, "public", "t", ["id"], logger) is True

    def test_returns_false_when_no_row(self, impl, cursor, logger):
        cursor.fetchone.return_value = None
        assert impl.has_duplicate_primary_keys(cursor, "public", "t", ["id"], logger) is False

    def test_returns_false_on_exception(self, impl, cursor, logger):
        cursor.execute.side_effect = RuntimeError("boom")
        assert impl.has_duplicate_primary_keys(cursor, "public", "t", ["id"], logger) is False


# ---------------------------------------------------------------------------
# Listing — exercise impl methods that take a real cursor mock
# ---------------------------------------------------------------------------


class TestGetColumns:
    def test_returns_columns_grouped_by_table(self, impl):
        conn = MagicMock()
        cur = MagicMock()
        cur.__enter__.return_value = cur
        cur.fetchall.return_value = [
            ("users", "id", "integer", "NO"),
            ("users", "email", "varchar", "YES"),
            ("orders", "id", "bigint", "NO"),
        ]
        conn.cursor.return_value = cur

        result = impl.get_columns(conn, _make_config(), names=None)

        assert result == {
            "users": [("id", "integer", False), ("email", "varchar", True)],
            "orders": [("id", "bigint", False)],
        }

    def test_returns_empty_when_no_rows(self, impl):
        conn = MagicMock()
        cur = MagicMock()
        cur.__enter__.return_value = cur
        cur.fetchall.return_value = []
        conn.cursor.return_value = cur

        assert impl.get_columns(conn, _make_config(), names=["foo"]) == {}


class TestGetPrimaryKeys:
    def test_returns_empty_for_no_tables(self, impl):
        result = impl.get_primary_keys(MagicMock(), _make_config(), [])
        assert result == {}

    def test_returns_pk_columns_grouped_by_table(self, impl):
        conn = MagicMock()
        cur = MagicMock()
        cur.__enter__.return_value = cur
        cur.fetchall.return_value = [("users", "id"), ("users", "tenant_id"), ("orders", "id")]
        conn.cursor.return_value = cur

        result = impl.get_primary_keys(conn, _make_config(), ["users", "orders", "items"])
        assert result == {"users": ["id", "tenant_id"], "orders": ["id"], "items": None}

    def test_swallows_errors_and_returns_none_per_table(self, impl):
        conn = MagicMock()
        cur = MagicMock()
        cur.__enter__.return_value = cur
        cur.execute.side_effect = Exception("denied")
        conn.cursor.return_value = cur

        result = impl.get_primary_keys(conn, _make_config(), ["users"])
        assert result == {"users": None}


class TestGetLeadingIndexColumns:
    def _make_conn(self, rows):
        conn = MagicMock()
        cur = MagicMock()
        cur.__enter__.return_value = cur
        cur.fetchall.return_value = rows
        conn.cursor.return_value = cur
        return conn

    def test_returns_empty_for_no_tables(self, impl):
        assert impl.get_leading_index_columns(MagicMock(), _make_config(), []) == {}

    def test_returns_leading_compound_sortkey(self, impl):
        # tablename, column, sortkey
        conn = self._make_conn(
            [
                ("messages", "created_at", 1),
                ("messages", "user_id", 2),
            ]
        )
        result = impl.get_leading_index_columns(conn, _make_config(), ["messages"])
        assert result == {"messages": {"created_at"}}

    def test_treats_interleaved_sortkey_as_indexed(self, impl):
        conn = self._make_conn(
            [
                ("messages", "a", -1),
                ("messages", "b", 2),
                ("messages", "c", -3),
            ]
        )
        result = impl.get_leading_index_columns(conn, _make_config(), ["messages"])
        assert result == {"messages": {"a", "b", "c"}}

    def test_tables_with_no_sortkey_are_empty(self, impl):
        conn = self._make_conn([])
        result = impl.get_leading_index_columns(conn, _make_config(), ["messages", "logs"])
        assert result == {"messages": set(), "logs": set()}

    def test_returns_none_on_exception(self, impl):
        conn = MagicMock()
        cur = MagicMock()
        cur.__enter__.return_value = cur
        cur.execute.side_effect = Exception("denied")
        conn.cursor.return_value = cur
        assert impl.get_leading_index_columns(conn, _make_config(), ["t"]) is None


# ---------------------------------------------------------------------------
# Source wiring — singleton + get_implementation + non-retryable errors
# ---------------------------------------------------------------------------


class TestRedshiftSourceWiring:
    def test_get_implementation_returns_singleton(self):
        source = RedshiftSource()
        assert source.get_implementation is _REDSHIFT_IMPLEMENTATION


class TestRedshiftSourceNonRetryableErrors:
    @pytest.mark.parametrize(
        "error_msg",
        [
            "Source column type changed",
            "SchemaColumnTypeChangedException: Source column type changed: 'id' has values that no longer fit",
        ],
    )
    def test_widened_integer_column_errors_are_non_retryable(self, error_msg):
        non_retryable = RedshiftSource().get_non_retryable_errors()
        is_non_retryable = any(pattern in error_msg for pattern in non_retryable.keys())
        assert is_non_retryable


class TestRedshiftSourceForPipeline:
    def test_forwards_chunk_size_override_from_external_data_schema(self, mocker):
        schema_row = MagicMock()
        schema_row.chunk_size_override = 9999
        mocker.patch(
            "posthog.temporal.data_imports.sources.redshift.source.ExternalDataSchema.objects.get",
            return_value=schema_row,
        )
        build_pipeline = mocker.patch.object(RedshiftImplementation, "build_pipeline", return_value=MagicMock())

        source = RedshiftSource()
        config = _make_config()
        inputs = _make_inputs()
        source.source_for_pipeline(config, inputs)

        build_pipeline.assert_called_once_with(config, inputs, chunk_size_override=9999)


# ---------------------------------------------------------------------------
# End-to-end build_pipeline — wired through RedshiftImplementation
# ---------------------------------------------------------------------------


@pytest.fixture
def build_pipeline_mocks(mocker):
    """Patch psycopg.connect + per-cursor metadata methods on RedshiftImplementation
    so `build_pipeline` can run end-to-end without a real Redshift server.
    """
    fake_table = Table(
        name="messages",
        parents=("public",),
        columns=[RedshiftColumn(name="id", data_type="integer", nullable=False)],
        type="table",
    )

    mocker.patch.object(RedshiftImplementation, "get_table_metadata", return_value=fake_table)
    mocker.patch.object(RedshiftImplementation, "get_primary_keys_for_table", return_value=["id"])
    mocker.patch.object(RedshiftImplementation, "get_rows_to_sync", return_value=0)
    mocker.patch.object(RedshiftImplementation, "get_chunk_size", return_value=1000)
    mocker.patch.object(RedshiftImplementation, "get_partition_settings", return_value=None)
    mocker.patch.object(RedshiftImplementation, "has_duplicate_primary_keys", return_value=False)

    streaming_cursor = MagicMock()
    streaming_cursor.__enter__.return_value = streaming_cursor
    streaming_cursor.description = [MagicMock(name="id")]
    streaming_cursor.description[0].name = "id"
    streaming_cursor.fetchmany.return_value = []

    # The metadata pass uses the patched `RedshiftImplementation`
    # methods, so a single cursor mock can serve both connections —
    # only the streaming connection requires `conn.adapters` to be set.
    state = {"first_conn": True}

    def connect_side_effect(*args, **kwargs):
        conn = MagicMock()
        conn.__enter__.return_value = conn
        conn.cursor.return_value = streaming_cursor
        if not state["first_conn"]:
            conn.adapters = MagicMock()
        state["first_conn"] = False
        return conn

    mock_connect = mocker.patch(
        "posthog.temporal.data_imports.sources.redshift.redshift.psycopg.connect",
        side_effect=connect_side_effect,
    )
    return mock_connect, streaming_cursor


class TestBuildPipeline:
    def test_returns_source_response(self, build_pipeline_mocks):
        mock_connect, _ = build_pipeline_mocks
        impl = RedshiftImplementation()
        response = impl.build_pipeline(_make_config(), _make_inputs())
        assert response.name == "messages"
        assert response.primary_keys == ["id"]
        # psycopg.connect was called at least once for the metadata pass
        assert mock_connect.called

    def test_streaming_drains_without_error(self, build_pipeline_mocks):
        _, streaming_cursor = build_pipeline_mocks
        impl = RedshiftImplementation()
        response = impl.build_pipeline(_make_config(), _make_inputs())
        list(response.items())  # type: ignore[arg-type]
        # streaming cursor.execute should have been invoked for the streaming query
        assert streaming_cursor.execute.called

    def test_chunk_size_override_skips_probe(self, build_pipeline_mocks, mocker):
        mocked_chunk_size = mocker.patch.object(RedshiftImplementation, "get_chunk_size")
        impl = RedshiftImplementation()
        impl.build_pipeline(_make_config(), _make_inputs(), chunk_size_override=4242)
        mocked_chunk_size.assert_not_called()
