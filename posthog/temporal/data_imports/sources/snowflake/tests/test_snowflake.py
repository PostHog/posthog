import pytest
from unittest.mock import MagicMock, patch

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from posthog.temporal.data_imports.sources.generated_configs import SnowflakeSourceConfig
from posthog.temporal.data_imports.sources.snowflake.snowflake import (
    SnowflakeImplementation,
    _build_query,
    _parse_clustering_key_leading_column,
    filter_snowflake_incremental_fields,
)

from products.data_warehouse.backend.types import IncrementalFieldType

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _generate_pem_key() -> str:
    """Generate a real PEM-encoded RSA key so `serialization.load_pem_private_key` succeeds."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048, backend=default_backend())
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")


def _make_config(auth_type: str = "password", **overrides) -> SnowflakeSourceConfig:
    auth: dict
    if auth_type == "password":
        auth = {"selection": "password", "user": "u", "password": "p"}
    else:
        auth = {
            "selection": "keypair",
            "user": "u",
            "private_key": _generate_pem_key(),
            "passphrase": "",
        }
    defaults: dict = {
        "account_id": "acc",
        "database": "DB",
        "warehouse": "WH",
        "schema": "PUBLIC",
        "role": "ROLE",
        "auth_type": auth,
    }
    defaults.update(overrides)
    return SnowflakeSourceConfig.from_dict(defaults)


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
# Module-level pure helpers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "clustering_key,expected",
    [
        # Snowflake stores clustering keys wrapped in LINEAR(...). Unquoted
        # identifiers are uppercased to match the form Snowflake returns from
        # INFORMATION_SCHEMA.COLUMNS — otherwise the source-level membership
        # check `field_name in indexed_cols` misses on every clustering key
        # that was written in lowercase.
        ("LINEAR(created_at)", "CREATED_AT"),
        ("LINEAR(created_at, user_id)", "CREATED_AT"),
        ("LINEAR(CreatedAt)", "CREATEDAT"),
        # Quoted identifiers preserve case sensitivity in Snowflake — strip the
        # quotes and keep the case as-written.
        ('LINEAR("CreatedAt", user_id)', "CreatedAt"),
        ('LINEAR("created_at")', "created_at"),
        # Older / non-LINEAR forms appear unwrapped in INFORMATION_SCHEMA.
        ("created_at", "CREATED_AT"),
        ("  created_at  ", "CREATED_AT"),
        # Function expressions don't accelerate WHERE col >= … on the column
        # they wrap, so we conservatively report no leading column.
        ("LINEAR(DATE_TRUNC('day', created_at))", None),
        # Empty / malformed inputs.
        ("", None),
        (None, None),
        ("LINEAR(", None),
    ],
)
def test_parse_clustering_key_leading_column(clustering_key, expected):
    assert _parse_clustering_key_leading_column(clustering_key) == expected


class TestFilterIncrementalFields:
    @pytest.mark.parametrize(
        "data_type,expected",
        [
            ("TIMESTAMP_NTZ", IncrementalFieldType.Timestamp),
            ("timestamp_ltz", IncrementalFieldType.Timestamp),
            ("date", IncrementalFieldType.Date),
            ("datetime", IncrementalFieldType.DateTime),
            ("NUMBER", IncrementalFieldType.Numeric),
            ("numeric", IncrementalFieldType.Numeric),
        ],
    )
    def test_picks_up_supported_types(self, data_type, expected):
        out = filter_snowflake_incremental_fields([("c", data_type, True)])
        assert out == [("c", expected, True)]

    def test_drops_unsupported(self):
        assert filter_snowflake_incremental_fields([("c", "varchar", True)]) == []


class TestBuildQuery:
    def test_incremental_requires_field(self):
        with pytest.raises(ValueError, match="incremental_field"):
            _build_query("DB", "PUBLIC", "t", True, None, None, None)

    def test_incremental_uses_operator_and_orders(self):
        sql, params = _build_query("DB", "PUBLIC", "t", True, "created_at", IncrementalFieldType.DateTime, "2025-01-01")
        assert "WHERE IDENTIFIER(%s)" in sql
        assert "ORDER BY IDENTIFIER(%s) ASC" in sql
        assert params == ("DB.PUBLIC.t", "created_at", "2025-01-01", "created_at")

    def test_incremental_seeds_initial_value_when_missing(self):
        # None last-value triggers fallback to incremental_type_to_initial_value
        _, params = _build_query("DB", "PUBLIC", "t", True, "created_at", IncrementalFieldType.DateTime, None)
        assert params[2] is not None


# ---------------------------------------------------------------------------
# Implementation fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def impl() -> SnowflakeImplementation:
    return SnowflakeImplementation()


@pytest.fixture
def logger() -> MagicMock:
    return MagicMock()


@pytest.fixture
def cursor() -> MagicMock:
    c = MagicMock()
    c.__enter__.return_value = c
    c.fetchall.return_value = []
    c.fetchone.return_value = None
    return c


# ---------------------------------------------------------------------------
# connect() — keypair auth passes DER bytes in-memory (no tempfile)
# ---------------------------------------------------------------------------


class TestConnect:
    def test_keypair_passes_der_bytes_in_memory(self, impl):
        # Regression guard: the pre-refactor streaming path never wrote the
        # private key to disk. Make sure `connect()` matches it — DER bytes
        # via `private_key=`, no `private_key_file` kwarg.
        with patch("snowflake.connector.connect") as mock_connect:
            mock_connect.return_value.__enter__.return_value = MagicMock()
            with impl.connect(_make_config("keypair")):
                pass
            kwargs = mock_connect.call_args.kwargs
            assert "private_key_file" not in kwargs
            assert isinstance(kwargs["private_key"], bytes)
            # Sanity-check it's a DER-encoded PKCS8 blob the connector can parse.
            serialization.load_der_private_key(kwargs["private_key"], password=None, backend=default_backend())


# ---------------------------------------------------------------------------
# Listing methods — they take a pre-opened connection
# ---------------------------------------------------------------------------


def _conn_with_cursor(cursor: MagicMock) -> MagicMock:
    conn = MagicMock()
    conn.cursor.return_value = cursor
    return conn


class TestGetColumns:
    def test_groups_columns_by_table(self, impl, cursor):
        cursor.fetchall.return_value = [
            ("users", "id", "NUMBER", "NO"),
            ("users", "email", "VARCHAR", "YES"),
            ("orders", "id", "NUMBER", "NO"),
        ]
        conn = _conn_with_cursor(cursor)
        result = impl.get_columns(conn, _make_config(), names=None)
        assert set(result.keys()) == {"users", "orders"}
        assert ("id", "NUMBER", False) in result["users"]
        assert ("email", "VARCHAR", True) in result["users"]

    def test_filters_by_names(self, impl, cursor):
        cursor.fetchall.return_value = [
            ("users", "id", "NUMBER", "NO"),
            ("orders", "id", "NUMBER", "NO"),
        ]
        conn = _conn_with_cursor(cursor)
        result = impl.get_columns(conn, _make_config(), names=["users"])
        assert list(result.keys()) == ["users"]


class TestGetPrimaryKeys:
    def test_extracts_pk_column_names(self, impl, cursor):
        cursor.description = [MagicMock(name="column_name")]
        cursor.description[0].name = "column_name"
        cursor.__iter__.return_value = iter([("id",)])
        conn = _conn_with_cursor(cursor)
        out = impl.get_primary_keys(conn, _make_config(), tables=["t"])
        assert out["t"] == ["id"]

    def test_swallows_per_table_failure(self, impl, cursor):
        # Per-table failure leaves the None placeholder so schema discovery keeps going
        cursor.execute.side_effect = Exception("permission denied")
        conn = _conn_with_cursor(cursor)
        out = impl.get_primary_keys(conn, _make_config(), tables=["t"])
        assert out == {"t": None}


class TestGetLeadingIndexColumns:
    def test_returns_leading_column_set_per_table(self, impl, cursor):
        cursor.__iter__.return_value = iter([("users", "LINEAR(created_at)"), ("orders", None)])
        conn = _conn_with_cursor(cursor)
        out = impl.get_leading_index_columns(conn, _make_config(), tables=["users", "orders"])
        assert out is not None
        assert out["users"] == {"CREATED_AT"}
        assert out["orders"] == set()

    def test_returns_none_on_failure(self, impl, cursor):
        # Discovery failure returns None so caller defaults to no warning
        cursor.execute.side_effect = Exception("perm")
        conn = _conn_with_cursor(cursor)
        assert impl.get_leading_index_columns(conn, _make_config(), tables=["t"]) is None


# ---------------------------------------------------------------------------
# Per-cursor metadata methods
# ---------------------------------------------------------------------------


class TestGetPrimaryKeysForTable:
    def test_returns_keys_when_present(self, impl, cursor):
        desc = MagicMock()
        desc.name = "column_name"
        cursor.description = [desc]
        cursor.__iter__.return_value = iter([("id",), ("email",)])
        assert impl.get_primary_keys_for_table(cursor, "DB", "PUBLIC", "t") == ["id", "email"]

    def test_raises_when_column_name_missing(self, impl, cursor):
        # Cursor description without `column_name` shouldn't silently return None — it's a Snowflake driver shape change worth surfacing.
        desc = MagicMock()
        desc.name = "something_else"
        cursor.description = [desc]
        with pytest.raises(ValueError, match="column_name"):
            impl.get_primary_keys_for_table(cursor, "DB", "PUBLIC", "t")


class TestGetRowsToSync:
    def test_returns_count(self, impl, cursor, logger):
        cursor.fetchone.return_value = (321,)
        assert impl.get_rows_to_sync(cursor, "SELECT 1", (), logger) == 321

    def test_returns_zero_on_exception(self, impl, cursor, logger):
        # Sync must never bail because the COUNT(*) probe failed
        cursor.execute.side_effect = RuntimeError("boom")
        assert impl.get_rows_to_sync(cursor, "SELECT 1", (), logger) == 0


# ---------------------------------------------------------------------------
# build_pipeline end-to-end (mocked driver)
# ---------------------------------------------------------------------------


class TestBuildPipeline:
    def test_builds_source_response_and_streams(self, impl):
        # Two separate cursors: one for metadata pass, one for streaming.
        metadata_cursor = MagicMock()
        metadata_cursor.__enter__.return_value = metadata_cursor
        desc = MagicMock()
        desc.name = "column_name"
        metadata_cursor.description = [desc]
        metadata_cursor.__iter__.return_value = iter([("id",)])
        metadata_cursor.fetchone.return_value = (5,)

        streaming_cursor = MagicMock()
        streaming_cursor.__enter__.return_value = streaming_cursor
        streaming_cursor.fetch_arrow_batches.return_value = iter([b"batch-1", b"batch-2"])

        cursors = iter([metadata_cursor, streaming_cursor])

        def cursor_factory():
            return next(cursors)

        mock_connection = MagicMock()
        mock_connection.__enter__.return_value = mock_connection
        mock_connection.cursor.side_effect = cursor_factory

        with patch("snowflake.connector.connect", return_value=mock_connection):
            response = impl.build_pipeline(_make_config(), _make_inputs(schema_name="messages"))
            assert response.primary_keys == ["id"]
            assert response.rows_to_sync == 5
            assert list(response.items()) == [b"batch-1", b"batch-2"]
