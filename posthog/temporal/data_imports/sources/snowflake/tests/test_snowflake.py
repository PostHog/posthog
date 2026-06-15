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
    _split_display_name,
    filter_snowflake_incremental_fields,
)
from posthog.temporal.data_imports.sources.snowflake.source import SnowflakeSource

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


@pytest.mark.parametrize(
    "display_name,default_schema,expected",
    [
        # Bare name uses the configured schema (single-schema source).
        ("users", "PUBLIC", ("PUBLIC", "users")),
        ("users", None, (None, "users")),
        # Qualified name splits; the dotted schema wins over the default.
        ("analytics.users", "PUBLIC", ("analytics", "users")),
        ("analytics.users", None, ("analytics", "users")),
        # Whitespace-only dotted prefix normalizes away and falls back to the default.
        ("   .users", "PUBLIC", ("PUBLIC", "users")),
    ],
)
def test_split_display_name(display_name, default_schema, expected):
    assert _split_display_name(display_name, default_schema) == expected


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
        assert 'WHERE "created_at"' in sql
        assert 'ORDER BY "created_at" ASC' in sql
        assert params == ("DB.PUBLIC.t", "2025-01-01")

    def test_incremental_seeds_initial_value_when_missing(self):
        # None last-value triggers fallback to incremental_type_to_initial_value
        _, params = _build_query("DB", "PUBLIC", "t", True, "created_at", IncrementalFieldType.DateTime, None)
        assert params[1] is not None


class TestBuildQueryEnabledColumns:
    def test_full_refresh_none_uses_select_star(self):
        sql, _ = _build_query("DB", "PUBLIC", "t", False, None, None, None, enabled_columns=None, primary_keys=["id"])
        assert sql.startswith("SELECT * FROM IDENTIFIER(%s)")

    def test_full_refresh_subset_projects_pk_retained(self):
        sql, _ = _build_query(
            "DB", "PUBLIC", "t", False, None, None, None, enabled_columns=["EMAIL"], primary_keys=["ID"]
        )
        assert sql.startswith('SELECT "EMAIL", "ID" FROM IDENTIFIER(%s)')

    def test_full_refresh_subset_keeps_incremental_field(self):
        sql, _ = _build_query(
            "DB",
            "PUBLIC",
            "t",
            False,
            None,
            None,
            None,
            enabled_columns=["EMAIL"],
            primary_keys=["ID"],
        )
        assert '"EMAIL"' in sql
        assert '"ID"' in sql

    def test_incremental_subset_retains_incremental_field(self):
        sql, params = _build_query(
            "DB",
            "PUBLIC",
            "t",
            True,
            "CREATED_AT",
            IncrementalFieldType.DateTime,
            "2025-01-01",
            enabled_columns=["EMAIL"],
            primary_keys=["ID"],
        )
        assert sql.startswith('SELECT "EMAIL", "ID", "CREATED_AT" FROM IDENTIFIER(%s)')
        assert 'WHERE "CREATED_AT"' in sql
        assert 'ORDER BY "CREATED_AT" ASC' in sql
        assert params == ("DB.PUBLIC.t", "2025-01-01")


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

    @pytest.mark.parametrize("blank", ["", "   ", None])
    def test_blank_schema_reaches_connector_as_none(self, impl, blank):
        # `schema=""` would make the connector try `USE SCHEMA ""` (invalid) — normalize to None.
        with patch("snowflake.connector.connect") as mock_connect:
            mock_connect.return_value.__enter__.return_value = MagicMock()
            with impl.connect(_make_config(schema=blank)):
                pass
            assert mock_connect.call_args.kwargs["schema"] is None

    def test_set_schema_reaches_connector(self, impl):
        with patch("snowflake.connector.connect") as mock_connect:
            mock_connect.return_value.__enter__.return_value = MagicMock()
            with impl.connect(_make_config(schema="SALES")):
                pass
            assert mock_connect.call_args.kwargs["schema"] == "SALES"


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
            ("PUBLIC", "users", "id", "NUMBER", "NO"),
            ("PUBLIC", "users", "email", "VARCHAR", "YES"),
            ("PUBLIC", "orders", "id", "NUMBER", "NO"),
        ]
        conn = _conn_with_cursor(cursor)
        result = impl.get_columns(conn, _make_config(), names=None)
        # Single-schema source keeps bare table names.
        assert set(result.keys()) == {"users", "orders"}
        assert ("id", "NUMBER", False) in result["users"]
        assert ("email", "VARCHAR", True) in result["users"]

    def test_filters_by_names(self, impl, cursor):
        cursor.fetchall.return_value = [
            ("PUBLIC", "users", "id", "NUMBER", "NO"),
            ("PUBLIC", "orders", "id", "NUMBER", "NO"),
        ]
        conn = _conn_with_cursor(cursor)
        result = impl.get_columns(conn, _make_config(), names=["users"])
        assert list(result.keys()) == ["users"]

    def test_single_schema_filters_by_configured_schema(self, impl, cursor):
        cursor.fetchall.return_value = []
        conn = _conn_with_cursor(cursor)
        impl.get_columns(conn, _make_config(schema="SALES"), names=None)
        sql = cursor.execute.call_args.args[0]
        params = cursor.execute.call_args.args[1]
        assert "table_schema = %(schema)s" in sql
        assert params == {"schema": "SALES"}

    @pytest.mark.parametrize("blank", ["", "   ", None])
    def test_blank_schema_discovers_all_namespaces_qualified(self, impl, cursor, blank):
        cursor.fetchall.return_value = [
            ("analytics", "users", "id", "NUMBER", "NO"),
            ("sales", "users", "id", "NUMBER", "NO"),
            ("sales", "orders", "id", "NUMBER", "NO"),
        ]
        conn = _conn_with_cursor(cursor)
        result = impl.get_columns(conn, _make_config(schema=blank), names=None)
        # Same table name in two schemas must stay distinct and qualified.
        assert set(result.keys()) == {"analytics.users", "sales.users", "sales.orders"}
        sql = cursor.execute.call_args.args[0]
        assert "table_schema != %(system_schema)s" in sql
        assert cursor.execute.call_args.args[1] == {"system_schema": "INFORMATION_SCHEMA"}

    def test_blank_schema_filters_by_qualified_names(self, impl, cursor):
        cursor.fetchall.return_value = [
            ("analytics", "users", "id", "NUMBER", "NO"),
            ("sales", "users", "id", "NUMBER", "NO"),
        ]
        conn = _conn_with_cursor(cursor)
        result = impl.get_columns(conn, _make_config(schema=""), names=["sales.users"])
        assert list(result.keys()) == ["sales.users"]

    def test_qualified_name_falls_back_to_bare_discovery_key(self, impl, cursor):
        # Mid-migration a row may be requested qualified while a configured-schema source still
        # discovers it bare — keep the requested (qualified) key, mapped to the bare columns.
        cursor.fetchall.return_value = [("PUBLIC", "users", "id", "NUMBER", "NO")]
        conn = _conn_with_cursor(cursor)
        result = impl.get_columns(conn, _make_config(schema="PUBLIC"), names=["PUBLIC.users"])
        assert result == {"PUBLIC.users": [("id", "NUMBER", False)]}


def _pk_description() -> list[MagicMock]:
    """`SHOW PRIMARY KEYS IN SCHEMA` description: table_name, column_name, key_sequence at 0,1,2."""
    cols = []
    for col_name in ("table_name", "column_name", "key_sequence"):
        desc = MagicMock()
        desc.name = col_name
        cols.append(desc)
    return cols


class TestGetPrimaryKeys:
    def test_extracts_pk_column_names(self, impl, cursor):
        cursor.description = _pk_description()
        cursor.__iter__.return_value = iter([("t", "id", 1)])
        conn = _conn_with_cursor(cursor)
        out = impl.get_primary_keys(conn, _make_config(), tables=["t"])
        assert out["t"] == ["id"]
        # Batched per schema, not per table.
        sql = cursor.execute.call_args.args[0]
        assert "SHOW PRIMARY KEYS IN SCHEMA" in sql
        assert '"DB"."PUBLIC"' in sql

    def test_orders_composite_key_by_sequence(self, impl, cursor):
        cursor.description = _pk_description()
        cursor.__iter__.return_value = iter([("t", "b", 2), ("t", "a", 1)])
        conn = _conn_with_cursor(cursor)
        out = impl.get_primary_keys(conn, _make_config(), tables=["t"])
        assert out["t"] == ["a", "b"]

    def test_swallows_per_schema_failure(self, impl, cursor):
        # Per-schema failure leaves the None placeholder so schema discovery keeps going
        cursor.execute.side_effect = Exception("permission denied")
        conn = _conn_with_cursor(cursor)
        out = impl.get_primary_keys(conn, _make_config(), tables=["t"])
        assert out == {"t": None}

    def test_multi_schema_routes_keys_to_qualified_display_names(self, impl, cursor):
        cursor.description = _pk_description()
        # One SHOW per distinct schema, in sorted order: analytics, then sales.
        cursor.__iter__.side_effect = [
            iter([("users", "id", 1)]),
            iter([("users", "uuid", 1), ("orders", "id", 1)]),
        ]
        conn = _conn_with_cursor(cursor)
        out = impl.get_primary_keys(
            conn, _make_config(schema=""), tables=["analytics.users", "sales.users", "sales.orders"]
        )
        assert out == {"analytics.users": ["id"], "sales.users": ["uuid"], "sales.orders": ["id"]}
        assert cursor.execute.call_count == 2


class TestGetLeadingIndexColumns:
    def test_returns_leading_column_set_per_table(self, impl, cursor):
        cursor.__iter__.return_value = iter([("PUBLIC", "users", "LINEAR(created_at)"), ("PUBLIC", "orders", None)])
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

    def test_multi_schema_maps_clustering_keys_to_qualified_names(self, impl, cursor):
        # Same table name across schemas must not cross-contaminate clustering keys.
        cursor.__iter__.return_value = iter(
            [
                ("analytics", "users", "LINEAR(created_at)"),
                ("sales", "users", "LINEAR(signed_up)"),
            ]
        )
        conn = _conn_with_cursor(cursor)
        out = impl.get_leading_index_columns(conn, _make_config(schema=""), tables=["analytics.users", "sales.users"])
        assert out is not None
        assert out["analytics.users"] == {"CREATED_AT"}
        assert out["sales.users"] == {"SIGNED_UP"}


class TestGetSourceMetadata:
    def test_single_schema_pins_configured_namespace(self, impl):
        meta = impl.get_source_metadata(MagicMock(), _make_config(schema="PUBLIC"), tables=["users"])
        assert meta.catalog_by_table == {"users": "DB"}
        assert meta.schema_by_table == {"users": "PUBLIC"}
        assert meta.table_name_by_table == {"users": "users"}

    def test_multi_schema_splits_qualified_display_names(self, impl):
        meta = impl.get_source_metadata(MagicMock(), _make_config(schema=""), tables=["analytics.users", "sales.users"])
        assert meta.catalog_by_table == {"analytics.users": "DB", "sales.users": "DB"}
        assert meta.schema_by_table == {"analytics.users": "analytics", "sales.users": "sales"}
        assert meta.table_name_by_table == {"analytics.users": "users", "sales.users": "users"}


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
            assert response.name == "messages"
            assert response.primary_keys == ["id"]
            assert response.rows_to_sync == 5
            assert list(response.items()) == [b"batch-1", b"batch-2"]
            # Pin a single timestamp unit so mixed ns/us batches don't break pyarrow assembly.
            streaming_cursor.fetch_arrow_batches.assert_called_once_with(force_microsecond_precision=True)

    def test_multi_schema_row_routes_to_qualified_namespace(self, impl):
        # A blank-namespace source pins each row's schema via the dotted schema_name.
        metadata_cursor = MagicMock()
        metadata_cursor.__enter__.return_value = metadata_cursor
        desc = MagicMock()
        desc.name = "column_name"
        metadata_cursor.description = [desc]
        metadata_cursor.__iter__.return_value = iter([("id",)])
        metadata_cursor.fetchone.return_value = (3,)

        streaming_cursor = MagicMock()
        streaming_cursor.__enter__.return_value = streaming_cursor
        streaming_cursor.fetch_arrow_batches.return_value = iter([b"batch-1"])

        cursors = iter([metadata_cursor, streaming_cursor])
        mock_connection = MagicMock()
        mock_connection.__enter__.return_value = mock_connection
        mock_connection.cursor.side_effect = lambda: next(cursors)

        with patch("snowflake.connector.connect", return_value=mock_connection):
            response = impl.build_pipeline(_make_config(schema=""), _make_inputs(schema_name="analytics.users"))
            # Delta subdir keeps the qualified, normalized name so cross-schema duplicates stay distinct.
            assert response.name == "analytics_users"
            assert list(response.items()) == [b"batch-1"]

        # PK probe and streaming query both target DB.analytics.users (resolved schema, unqualified table).
        pk_param = metadata_cursor.execute.call_args_list[0].args[1]
        assert pk_param == ("DB.analytics.users",)
        stream_param = streaming_cursor.execute.call_args.args[1]
        assert stream_param == ("DB.analytics.users",)


class TestSnowflakeSourceNonRetryableErrors:
    @pytest.fixture
    def source(self):
        return SnowflakeSource()

    @pytest.mark.parametrize(
        "error_msg",
        [
            "250001 (08001): None: Failed to connect to DB: acme-xy123.snowflakecomputing.com:443. User access disabled. Contact your local system administrator.",
            "User access disabled. Contact your local system administrator.",
        ],
    )
    def test_disabled_user_is_non_retryable(self, source, error_msg):
        non_retryable = source.get_non_retryable_errors()
        is_non_retryable = any(pattern in error_msg for pattern in non_retryable.keys())
        assert is_non_retryable, f"Disabled-user error should be non-retryable: {error_msg}"

    @pytest.mark.parametrize(
        "error_msg",
        [
            "Duo Security authentication is denied",
            # The real shape from production: codes + host vary, but the Duo substring is stable.
            "250001 (08001): None: Failed to connect to DB: wv65496-re80354.snowflakecomputing.com:443. "
            "Duo Security authentication is denied.",
        ],
    )
    def test_duo_security_denied_is_non_retryable(self, source, error_msg):
        non_retryable = source.get_non_retryable_errors()
        is_non_retryable = any(pattern in error_msg for pattern in non_retryable.keys())
        assert is_non_retryable, f"Duo-denied error should be non-retryable: {error_msg}"

    @pytest.mark.parametrize(
        "error_msg",
        [
            "250003 (08001): Failed to connect to DB: acme-xy123.snowflakecomputing.com:443. Connection timed out",
            "Operation timed out while waiting for the warehouse to resume",
        ],
    )
    def test_transient_errors_are_retryable(self, source, error_msg):
        non_retryable = source.get_non_retryable_errors()
        is_non_retryable = any(pattern in error_msg for pattern in non_retryable.keys())
        assert not is_non_retryable, f"Error should remain retryable: {error_msg}"
