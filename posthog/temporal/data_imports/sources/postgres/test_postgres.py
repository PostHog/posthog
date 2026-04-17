from datetime import UTC, date, datetime
from typing import Any, cast

import pytest
from unittest.mock import patch

from django.db import connection as django_connection

import pyarrow as pa
import structlog
from psycopg import sql

from posthog.temporal.data_imports.pipelines.pipeline.utils import DEFAULT_NUMERIC_SCALE, MAX_NUMERIC_SCALE
from posthog.temporal.data_imports.sources.postgres.postgres import (
    SSL_REQUIRED_AFTER_DATE,
    JsonAsStringLoader,
    PostgreSQLColumn,
    RangeAsStringLoader,
    SafeDateLoader,
    _build_count_query,
    _build_query,
    _get_estimated_row_count_for_partitioned_table,
    _get_partition_settings,
    _get_partition_settings_for_partitioned_table,
    _get_primary_keys,
    _get_sslmode,
    _get_table,
    _has_duplicate_primary_keys,
    _is_partitioned_table,
    _is_read_replica,
    _normalize_function_names,
    filter_postgres_incremental_fields,
)
from posthog.temporal.data_imports.sources.postgres.source import PostgresSource

from products.data_warehouse.backend.types import IncrementalFieldType


class TestSafeDateLoader:
    @pytest.fixture
    def loader(self):
        return SafeDateLoader(oid=1082)

    @pytest.mark.parametrize(
        "input_data,expected",
        [
            (b"2024-01-15", date(2024, 1, 15)),
            (b"1999-12-31", date(1999, 12, 31)),
            (b"0001-01-01", date(1, 1, 1)),
            (b"9999-12-31", date(9999, 12, 31)),
            (b"48113-11-21", date.max),
            (b"10000-01-01", date.max),
            (b"99999-12-31", date.max),
            (b"infinity", date.max),
            (b"-infinity", date.min),
            (b"-0001-01-01", date.min),
            (b"-0044-03-15", date.min),
            (b"0000-01-01", date.min),
            (b"0044-03-15 BC", date.min),
            (None, None),
        ],
    )
    def test_load_dates(self, loader, input_data, expected):
        assert loader.load(input_data) == expected


class TestPostgresSourceNonRetryableErrors:
    @pytest.fixture
    def source(self):
        return PostgresSource()

    @pytest.mark.parametrize(
        "error_msg",
        [
            'OperationalError: connection failed: connection to server at "10.0.0.1", port 5432 failed: FATAL: MaxClientsInSessionMode: max clients reached',
            'OperationalError: connection failed: connection to server at "10.0.0.1", port 5432 failed: FATAL: remaining connection slots are reserved for roles with the SUPERUSER attribute',
            'OperationalError: connection failed: connection to server at "10.0.0.1", port 5432 failed: FATAL: too many connections for role "user"',
        ],
    )
    def test_transient_connection_errors_are_retryable(self, source, error_msg):
        non_retryable = source.get_non_retryable_errors()
        is_non_retryable = any(pattern in error_msg for pattern in non_retryable.keys())
        assert not is_non_retryable, f"Transient error should be retryable: {error_msg}"

    @pytest.mark.parametrize(
        "error_msg",
        [
            'psycopg2.OperationalError: could not connect to server: Connection refused\n\tIs the server running on host "10.0.0.1" and accepting TCP/IP connections on port 5432?',
            'psycopg2.OperationalError: could not connect to server: No route to host\n\tIs the server running on host "10.0.0.1"?',
            'could not translate host name "bad-hostname.example.com" to address: Name or service not known',
            'FATAL:  password authentication failed for user "myuser"',
            'FATAL: no such database "nonexistent_db"',
            "Name or service not known",
        ],
    )
    def test_permanent_connection_errors_are_non_retryable(self, source, error_msg):
        non_retryable = source.get_non_retryable_errors()
        is_non_retryable = any(pattern in error_msg for pattern in non_retryable.keys())
        assert is_non_retryable, f"Permanent error should be non-retryable: {error_msg}"


class TestGetSslmode:
    @pytest.mark.parametrize(
        "require_ssl,expected",
        [
            (True, "prefer"),
            (False, "prefer"),
        ],
    )
    def test_returns_prefer_in_test_mode(self, require_ssl, expected):
        """In TEST mode (our default for pytest), always returns 'prefer'."""
        assert _get_sslmode(require_ssl) == expected

    def test_returns_require_when_ssl_required_outside_test(self):
        with patch("posthog.temporal.data_imports.sources.postgres.postgres.settings") as mock_settings:
            mock_settings.TEST = False
            mock_settings.DEBUG = False
            mock_settings.E2E_TESTING = False
            assert _get_sslmode(True) == "require"

    def test_returns_prefer_when_ssl_not_required_outside_test(self):
        with patch("posthog.temporal.data_imports.sources.postgres.postgres.settings") as mock_settings:
            mock_settings.TEST = False
            mock_settings.DEBUG = False
            mock_settings.E2E_TESTING = False
            assert _get_sslmode(False) == "prefer"

    def test_returns_prefer_in_debug_mode(self):
        with patch("posthog.temporal.data_imports.sources.postgres.postgres.settings") as mock_settings:
            mock_settings.TEST = False
            mock_settings.DEBUG = True
            mock_settings.E2E_TESTING = False
            assert _get_sslmode(True) == "prefer"

    def test_returns_prefer_in_e2e_mode(self):
        with patch("posthog.temporal.data_imports.sources.postgres.postgres.settings") as mock_settings:
            mock_settings.TEST = False
            mock_settings.DEBUG = False
            mock_settings.E2E_TESTING = True
            assert _get_sslmode(True) == "prefer"


class TestNormalizeFunctionNames:
    def test_valid_identifiers(self):
        result = _normalize_function_names(["foo", "bar_baz", "_private", "CamelCase"])
        assert result == ["_private", "bar_baz", "camelcase", "foo"]

    def test_filters_invalid_identifiers(self):
        result = _normalize_function_names(["valid", "123invalid", "has-dash", "also valid", "ok_name"])
        assert result == ["ok_name", "valid"]

    def test_filters_non_string_values(self):
        result = _normalize_function_names(["valid", 123, None, True, "another"])
        assert result == ["another", "valid"]

    def test_deduplicates_case_insensitive(self):
        result = _normalize_function_names(["Foo", "foo", "FOO"])
        assert result == ["foo"]

    def test_empty_list(self):
        assert _normalize_function_names([]) == []

    def test_all_invalid(self):
        assert _normalize_function_names([123, None, "1bad", "has space"]) == []

    def test_rejects_empty_string(self):
        assert _normalize_function_names([""]) == []


class TestFilterPostgresIncrementalFields:
    @pytest.mark.parametrize(
        "type_name,expected_type",
        [
            ("timestamp", IncrementalFieldType.Timestamp),
            ("timestamp without time zone", IncrementalFieldType.Timestamp),
            ("timestamp with time zone", IncrementalFieldType.Timestamp),
            ("timestamptz", IncrementalFieldType.Timestamp),
            ("TIMESTAMP", IncrementalFieldType.Timestamp),
            ("date", IncrementalFieldType.Date),
            ("DATE", IncrementalFieldType.Date),
            ("integer", IncrementalFieldType.Integer),
            ("smallint", IncrementalFieldType.Integer),
            ("bigint", IncrementalFieldType.Integer),
            ("INTEGER", IncrementalFieldType.Integer),
        ],
    )
    def test_supported_types(self, type_name, expected_type):
        result = filter_postgres_incremental_fields([("col", type_name, False)])
        assert result == [("col", expected_type, False)]

    @pytest.mark.parametrize(
        "type_name",
        ["text", "varchar", "boolean", "real", "numeric", "serial", "bigserial", "uuid", "json", "bytea"],
    )
    def test_unsupported_types_excluded(self, type_name):
        result = filter_postgres_incremental_fields([("col", type_name, False)])
        assert result == []

    def test_preserves_nullable_flag(self):
        result = filter_postgres_incremental_fields([("col", "integer", True)])
        assert result == [("col", IncrementalFieldType.Integer, True)]

    def test_multiple_columns(self):
        columns = [
            ("id", "integer", False),
            ("name", "text", False),
            ("created_at", "timestamp", True),
            ("is_active", "boolean", False),
            ("updated_at", "date", False),
        ]
        result = filter_postgres_incremental_fields(columns)
        assert result == [
            ("id", IncrementalFieldType.Integer, False),
            ("created_at", IncrementalFieldType.Timestamp, True),
            ("updated_at", IncrementalFieldType.Date, False),
        ]

    def test_empty_list(self):
        assert filter_postgres_incremental_fields([]) == []


class TestBuildQuery:
    def _render(self, composed: sql.Composed) -> str:
        """Render a psycopg sql.Composed to string without a connection."""
        return composed.as_string()

    def test_full_refresh(self):
        query = _build_query("public", "users", False, "table", None, None, None)
        rendered = self._render(query)
        assert '"public"."users"' in rendered
        assert "SELECT *" in rendered
        assert "WHERE" not in rendered

    def test_incremental(self):
        query = _build_query(
            "public", "events", True, "table", "created_at", IncrementalFieldType.Timestamp, "2024-01-01"
        )
        rendered = self._render(query)
        assert '"created_at"' in rendered
        assert "'2024-01-01'" in rendered
        assert "ORDER BY" in rendered

    def test_incremental_raises_without_field(self):
        with pytest.raises(ValueError, match="incremental_field and incremental_field_type can't be None"):
            _build_query("public", "events", True, "table", None, None, None)

    def test_incremental_raises_without_field_type(self):
        with pytest.raises(ValueError):
            _build_query("public", "events", True, "table", "id", None, None)

    def test_sampling_table(self):
        query = _build_query("public", "users", False, "table", None, None, None, add_sampling=True)
        rendered = self._render(query)
        assert "TABLESAMPLE SYSTEM (1)" in rendered
        assert "LIMIT 1000" in rendered

    def test_sampling_view(self):
        query = _build_query("public", "users", False, "view", None, None, None, add_sampling=True)
        rendered = self._render(query)
        assert "random() < 0.01" in rendered
        assert "LIMIT 1000" in rendered

    def test_incremental_with_sampling_table(self):
        query = _build_query(
            "myschema", "events", True, "table", "id", IncrementalFieldType.Integer, 100, add_sampling=True
        )
        rendered = self._render(query)
        assert "TABLESAMPLE SYSTEM (1)" in rendered
        assert '"id"' in rendered
        assert "LIMIT 1000" in rendered

    def test_incremental_with_sampling_view(self):
        query = _build_query(
            "myschema", "events", True, "view", "id", IncrementalFieldType.Integer, 100, add_sampling=True
        )
        rendered = self._render(query)
        assert "random() < 0.01" in rendered
        assert '"id"' in rendered
        assert "LIMIT 1000" in rendered


class TestBuildCountQuery:
    def _render(self, composed: sql.Composed) -> str:
        return composed.as_string()

    def test_full_refresh_count_query(self):
        query = _build_count_query("public", "users", False, None, None, None)
        rendered = self._render(query)
        assert "SELECT COUNT(*)" in rendered
        assert '"public"."users"' in rendered
        assert "WHERE" not in rendered
        assert "ORDER BY" not in rendered
        assert "FROM (" not in rendered

    def test_incremental_count_query(self):
        query = _build_count_query("public", "events", True, "created_at", IncrementalFieldType.Timestamp, "2024-01-01")
        rendered = self._render(query)
        assert "SELECT COUNT(*)" in rendered
        assert '"public"."events"' in rendered
        assert '"created_at"' in rendered
        assert "'2024-01-01'" in rendered
        assert "ORDER BY" not in rendered
        assert "FROM (" not in rendered


class TestIsPartitionedTable:
    @pytest.mark.parametrize(
        "setup_ddl, table_name, expected",
        [
            (
                [
                    "CREATE TABLE test_is_part (id INTEGER, created_at DATE NOT NULL, PRIMARY KEY (id, created_at)) PARTITION BY RANGE (created_at)",
                    "CREATE TABLE test_is_part_2026 PARTITION OF test_is_part FOR VALUES FROM ('2026-01-01') TO ('2027-01-01')",
                ],
                "test_is_part",
                True,
            ),
            (
                ["CREATE TABLE test_is_regular (id SERIAL PRIMARY KEY, data TEXT)"],
                "test_is_regular",
                False,
            ),
            ([], "does_not_exist_xyz", False),
        ],
    )
    @pytest.mark.django_db
    def test_is_partitioned_table(self, setup_ddl, table_name, expected):
        with django_connection.cursor() as dj_cursor:
            for stmt in setup_ddl:
                dj_cursor.execute(stmt)
            assert _is_partitioned_table(cast(Any, dj_cursor), "public", table_name) is expected


class TestGetEstimatedRowCountForPartitionedTable:
    @pytest.mark.django_db
    def test_returns_estimate_for_partitioned_table(self):
        logger = structlog.get_logger()

        with django_connection.cursor() as dj_cursor:
            dj_cursor.execute("""
                CREATE TABLE test_est_count_partitioned (
                    id BIGSERIAL,
                    created_at DATE NOT NULL,
                    PRIMARY KEY (id, created_at)
                ) PARTITION BY RANGE (created_at)
            """)
            dj_cursor.execute("""
                CREATE TABLE test_est_count_partitioned_q1
                PARTITION OF test_est_count_partitioned
                FOR VALUES FROM ('2026-01-01') TO ('2026-04-01')
            """)
            dj_cursor.execute("""
                CREATE TABLE test_est_count_partitioned_q2
                PARTITION OF test_est_count_partitioned
                FOR VALUES FROM ('2026-04-01') TO ('2026-07-01')
            """)
            dj_cursor.execute("""
                INSERT INTO test_est_count_partitioned (created_at)
                SELECT '2026-01-15'::date + (g % 2) * interval '3 months'
                FROM generate_series(1, 200) g
            """)
            dj_cursor.execute("ANALYZE test_est_count_partitioned")

            result = _get_estimated_row_count_for_partitioned_table(
                cast(Any, dj_cursor), "public", "test_est_count_partitioned", logger
            )
            assert result is not None
            # reltuples is approximate; 200 rows should be close
            assert 150 <= result <= 250

    @pytest.mark.django_db
    def test_returns_none_for_non_partitioned_table(self):
        logger = structlog.get_logger()

        with django_connection.cursor() as dj_cursor:
            dj_cursor.execute("CREATE TABLE test_est_count_regular (id SERIAL PRIMARY KEY, data TEXT)")
            dj_cursor.execute("INSERT INTO test_est_count_regular (data) SELECT 'x' FROM generate_series(1, 50)")
            dj_cursor.execute("ANALYZE test_est_count_regular")

            result = _get_estimated_row_count_for_partitioned_table(
                cast(Any, dj_cursor), "public", "test_est_count_regular", logger
            )
            # No child partitions → partition_count == 0 → function returns None
            assert result is None

    @pytest.mark.django_db
    def test_returns_none_when_partitions_partially_analyzed(self):
        """Mixed analyzed + unanalyzed partitions must not sum reltuples naively.

        reltuples = -1 on never-analyzed partitions would under-count if summed.
        We require all partitions analyzed before trusting reltuples.
        """
        logger = structlog.get_logger()

        with django_connection.cursor() as dj_cursor:
            dj_cursor.execute("""
                CREATE TABLE test_est_count_partial (
                    id BIGSERIAL,
                    created_at DATE NOT NULL,
                    PRIMARY KEY (id, created_at)
                ) PARTITION BY RANGE (created_at)
            """)
            dj_cursor.execute("""
                CREATE TABLE test_est_count_partial_q1
                PARTITION OF test_est_count_partial
                FOR VALUES FROM ('2026-01-01') TO ('2026-04-01')
            """)
            dj_cursor.execute("""
                CREATE TABLE test_est_count_partial_q2
                PARTITION OF test_est_count_partial
                FOR VALUES FROM ('2026-04-01') TO ('2026-07-01')
            """)
            dj_cursor.execute("""
                INSERT INTO test_est_count_partial (created_at)
                SELECT '2026-01-15'::date + (g % 2) * interval '3 months'
                FROM generate_series(1, 200) g
            """)
            # Analyze only the first partition — second remains reltuples=-1.
            dj_cursor.execute("ANALYZE test_est_count_partial_q1")

            # reltuples unreliable; n_live_tup is 0 inside test transaction →
            # function returns None, forcing exact COUNT(*) fallback.
            result = _get_estimated_row_count_for_partitioned_table(
                cast(Any, dj_cursor), "public", "test_est_count_partial", logger
            )
            assert result is None

    @pytest.mark.django_db
    def test_returns_none_without_analyze(self):
        logger = structlog.get_logger()

        with django_connection.cursor() as dj_cursor:
            dj_cursor.execute("""
                CREATE TABLE test_est_count_no_analyze (
                    id BIGSERIAL,
                    created_at DATE NOT NULL,
                    PRIMARY KEY (id, created_at)
                ) PARTITION BY RANGE (created_at)
            """)
            dj_cursor.execute("""
                CREATE TABLE test_est_count_no_analyze_p1
                PARTITION OF test_est_count_no_analyze
                FOR VALUES FROM ('2026-01-01') TO ('2026-07-01')
            """)
            dj_cursor.execute("""
                INSERT INTO test_est_count_no_analyze (created_at)
                SELECT '2026-03-01'::date FROM generate_series(1, 300)
            """)
            # Without ANALYZE, reltuples is -1 (PG14+). The stats collector
            # n_live_tup fallback also can't see rows inside a test transaction.
            # In production, committed inserts would be visible via n_live_tup.
            # Here the function returns None, causing a fallback to exact COUNT(*).
            result = _get_estimated_row_count_for_partitioned_table(
                cast(Any, dj_cursor), "public", "test_est_count_no_analyze", logger
            )
            assert result is None

    @pytest.mark.django_db
    def test_returns_none_for_empty_partitioned_table(self):
        logger = structlog.get_logger()

        with django_connection.cursor() as dj_cursor:
            dj_cursor.execute("""
                CREATE TABLE test_est_count_empty (
                    id INTEGER,
                    created_at DATE NOT NULL,
                    PRIMARY KEY (id, created_at)
                ) PARTITION BY RANGE (created_at)
            """)
            dj_cursor.execute("""
                CREATE TABLE test_est_count_empty_p1
                PARTITION OF test_est_count_empty
                FOR VALUES FROM ('2026-01-01') TO ('2026-07-01')
            """)
            dj_cursor.execute("ANALYZE test_est_count_empty")

            # Both reltuples and n_live_tup are 0 — falls back to exact COUNT(*)
            result = _get_estimated_row_count_for_partitioned_table(
                cast(Any, dj_cursor), "public", "test_est_count_empty", logger
            )
            assert result is None


class TestGetPartitionSettings:
    @pytest.mark.django_db
    def test_partitioned_table_uses_catalog_fast_path(self):
        """On a partitioned parent, settings come from pg_inherits/reltuples,
        not a COUNT(*) + pg_table_size on the parent.
        """
        logger = structlog.get_logger()

        with django_connection.cursor() as dj_cursor:
            dj_cursor.execute("""
                CREATE TABLE test_ps_partitioned (
                    id BIGSERIAL,
                    created_at DATE NOT NULL,
                    payload TEXT,
                    PRIMARY KEY (id, created_at)
                ) PARTITION BY RANGE (created_at)
            """)
            dj_cursor.execute("""
                CREATE TABLE test_ps_partitioned_q1
                PARTITION OF test_ps_partitioned
                FOR VALUES FROM ('2026-01-01') TO ('2026-04-01')
            """)
            dj_cursor.execute("""
                CREATE TABLE test_ps_partitioned_q2
                PARTITION OF test_ps_partitioned
                FOR VALUES FROM ('2026-04-01') TO ('2026-07-01')
            """)
            dj_cursor.execute("""
                INSERT INTO test_ps_partitioned (created_at, payload)
                SELECT '2026-01-15'::date + (g % 2) * interval '3 months',
                       repeat('x', 256)
                FROM generate_series(1, 500) g
            """)
            dj_cursor.execute("ANALYZE test_ps_partitioned")

            result = _get_partition_settings(cast(Any, dj_cursor), "public", "test_ps_partitioned", logger)
            assert result is not None
            assert result.partition_count >= 1
            assert result.partition_size > 0

    @pytest.mark.django_db
    def test_partitioned_table_returns_none_when_any_partition_unanalyzed(self):
        """Mixed analyzed + unanalyzed partitions must not produce a setting —
        the catalog numbers are stale, so fall through to exact scan.
        """
        logger = structlog.get_logger()

        with django_connection.cursor() as dj_cursor:
            dj_cursor.execute("""
                CREATE TABLE test_ps_partial (
                    id BIGSERIAL,
                    created_at DATE NOT NULL,
                    PRIMARY KEY (id, created_at)
                ) PARTITION BY RANGE (created_at)
            """)
            dj_cursor.execute("""
                CREATE TABLE test_ps_partial_q1
                PARTITION OF test_ps_partial
                FOR VALUES FROM ('2026-01-01') TO ('2026-04-01')
            """)
            dj_cursor.execute("""
                CREATE TABLE test_ps_partial_q2
                PARTITION OF test_ps_partial
                FOR VALUES FROM ('2026-04-01') TO ('2026-07-01')
            """)
            dj_cursor.execute("""
                INSERT INTO test_ps_partial (created_at)
                SELECT '2026-01-15'::date + (g % 2) * interval '3 months'
                FROM generate_series(1, 200) g
            """)
            dj_cursor.execute("ANALYZE test_ps_partial_q1")

            result = _get_partition_settings_for_partitioned_table(
                cast(Any, dj_cursor), "public", "test_ps_partial", logger
            )
            assert result is None

    @pytest.mark.django_db
    def test_non_partitioned_table_still_uses_legacy_query(self):
        """Regular tables must skip the catalog fast path and go through the
        original COUNT(*) + pg_table_size query.
        """
        logger = structlog.get_logger()

        with django_connection.cursor() as dj_cursor:
            dj_cursor.execute("CREATE TABLE test_ps_regular (id SERIAL PRIMARY KEY, data TEXT)")
            dj_cursor.execute("INSERT INTO test_ps_regular (data) SELECT repeat('x', 128) FROM generate_series(1, 200)")
            dj_cursor.execute("ANALYZE test_ps_regular")

            result = _get_partition_settings(cast(Any, dj_cursor), "public", "test_ps_regular", logger)
            assert result is not None
            assert result.partition_size > 0


class TestPostgreSQLColumnToArrowField:
    @pytest.mark.parametrize(
        "data_type,expected_arrow_type",
        [
            ("bigint", pa.int64()),
            ("integer", pa.int32()),
            ("smallint", pa.int16()),
            ("real", pa.float32()),
            ("double precision", pa.float64()),
            ("text", pa.string()),
            ("varchar", pa.string()),
            ("character varying", pa.string()),
            ("date", pa.date32()),
            ("time", pa.time64("us")),
            ("time without time zone", pa.time64("us")),
            ("timestamp", pa.timestamp("us")),
            ("timestamp without time zone", pa.timestamp("us")),
            ("timestamptz", pa.timestamp("us", tz="UTC")),
            ("timestamp with time zone", pa.timestamp("us", tz="UTC")),
            ("interval", pa.duration("us")),
            ("boolean", pa.bool_()),
            ("bytea", pa.binary()),
            ("uuid", pa.string()),
            ("json", pa.string()),
            ("jsonb", pa.string()),
        ],
    )
    def test_type_mappings(self, data_type, expected_arrow_type):
        col = PostgreSQLColumn("test_col", data_type, nullable=True)
        field = col.to_arrow_field()
        assert field.type == expected_arrow_type
        assert field.name == "test_col"
        assert field.nullable is True

    def test_numeric_with_precision_and_scale(self):
        col = PostgreSQLColumn("price", "numeric", nullable=False, numeric_precision=10, numeric_scale=2)
        field = col.to_arrow_field()
        assert isinstance(field.type, pa.Decimal128Type)
        assert field.nullable is False

    def test_decimal_alias(self):
        col = PostgreSQLColumn("amount", "decimal", nullable=True, numeric_precision=18, numeric_scale=4)
        field = col.to_arrow_field()
        assert isinstance(field.type, pa.Decimal128Type)

    def test_numeric_raises_without_precision(self):
        col = PostgreSQLColumn("val", "numeric", nullable=True, numeric_precision=None, numeric_scale=None)
        with pytest.raises(TypeError, match="expected `numeric_precision` and `numeric_scale` to be `int`"):
            col.to_arrow_field()

    def test_numeric_raises_with_zero_precision(self):
        col = PostgreSQLColumn("val", "numeric", nullable=True, numeric_precision=0, numeric_scale=2)
        with pytest.raises(TypeError):
            col.to_arrow_field()

    def test_array_types_map_to_string(self):
        col = PostgreSQLColumn("tags", "text[]", nullable=True)
        field = col.to_arrow_field()
        assert field.type == pa.string()

    def test_integer_array(self):
        col = PostgreSQLColumn("ids", "integer[]", nullable=False)
        field = col.to_arrow_field()
        assert field.type == pa.string()

    def test_unknown_type_maps_to_string(self):
        col = PostgreSQLColumn("mystery", "citext", nullable=True)
        field = col.to_arrow_field()
        assert field.type == pa.string()

    def test_nullable_false(self):
        col = PostgreSQLColumn("id", "integer", nullable=False)
        field = col.to_arrow_field()
        assert field.nullable is False


class TestJsonAsStringLoader:
    @pytest.fixture
    def loader(self):
        return JsonAsStringLoader(oid=114)

    def test_loads_json_bytes(self, loader):
        assert loader.load(b'{"key": "value"}') == '{"key": "value"}'

    def test_loads_empty_object(self, loader):
        assert loader.load(b"{}") == "{}"

    def test_loads_array(self, loader):
        assert loader.load(b"[1, 2, 3]") == "[1, 2, 3]"

    def test_none_returns_none(self, loader):
        assert loader.load(None) is None

    def test_loads_unicode(self, loader):
        result = loader.load("héllo".encode())
        assert result == "héllo"


class TestRangeAsStringLoader:
    @pytest.fixture
    def loader(self):
        return RangeAsStringLoader(oid=3904)

    def test_loads_range_bytes(self, loader):
        assert loader.load(b"[4,6)") == "[4,6)"

    def test_loads_empty_range(self, loader):
        assert loader.load(b"empty") == "empty"

    def test_none_returns_none(self, loader):
        assert loader.load(None) is None

    def test_loads_unbounded_range(self, loader):
        assert loader.load(b"[,10)") == "[,10)"


class TestSSLRequiredAfterDate:
    def test_date_value(self):
        assert SSL_REQUIRED_AFTER_DATE == datetime(2026, 2, 18, tzinfo=UTC)

    def test_timezone_aware(self):
        assert SSL_REQUIRED_AFTER_DATE.tzinfo is not None


class TestGetPrimaryKeys:
    @pytest.mark.django_db
    def test_returns_primary_keys_for_table(self):
        logger = structlog.get_logger()

        with django_connection.cursor() as dj_cursor:
            dj_cursor.execute("""
                CREATE TABLE test_pk_table (
                    id INTEGER PRIMARY KEY,
                    name TEXT
                )
            """)
            result = _get_primary_keys(cast(Any, dj_cursor), "public", "test_pk_table", logger)
            assert result is not None
            assert "id" in result

    @pytest.mark.django_db
    def test_returns_none_for_table_without_primary_key(self):
        logger = structlog.get_logger()

        with django_connection.cursor() as dj_cursor:
            dj_cursor.execute("""
                CREATE TABLE test_no_pk_table (
                    id INTEGER,
                    name TEXT
                )
            """)
            result = _get_primary_keys(cast(Any, dj_cursor), "public", "test_no_pk_table", logger)
            assert result is None

    @pytest.mark.django_db
    def test_returns_composite_primary_keys(self):
        logger = structlog.get_logger()

        with django_connection.cursor() as dj_cursor:
            dj_cursor.execute("""
                CREATE TABLE test_composite_pk_table (
                    org_id INTEGER,
                    user_id INTEGER,
                    name TEXT,
                    PRIMARY KEY (org_id, user_id)
                )
            """)
            result = _get_primary_keys(cast(Any, dj_cursor), "public", "test_composite_pk_table", logger)
            assert result is not None
            assert len(result) == 2
            assert "org_id" in result
            assert "user_id" in result

    @pytest.mark.django_db
    def test_returns_primary_keys_for_partitioned_parent_table(self):
        logger = structlog.get_logger()

        with django_connection.cursor() as dj_cursor:
            dj_cursor.execute("""
                CREATE TABLE test_partitioned_parent_pk (
                    id INTEGER,
                    created_at DATE,
                    name TEXT,
                    PRIMARY KEY (id, created_at)
                ) PARTITION BY RANGE (created_at)
            """)
            dj_cursor.execute("""
                CREATE TABLE test_partitioned_parent_pk_2026
                PARTITION OF test_partitioned_parent_pk
                FOR VALUES FROM ('2026-01-01') TO ('2027-01-01')
            """)

            result = _get_primary_keys(cast(Any, dj_cursor), "public", "test_partitioned_parent_pk", logger)
            assert result is not None
            assert result == ["id", "created_at"]

    @pytest.mark.django_db
    def test_returns_primary_keys_for_partitioned_parent_when_only_children_have_pk(self):
        logger = structlog.get_logger()

        with django_connection.cursor() as dj_cursor:
            dj_cursor.execute("""
                CREATE TABLE test_partitioned_parent_no_pk (
                    order_id INTEGER NOT NULL,
                    created_at DATE NOT NULL,
                    updated_at DATE NOT NULL
                ) PARTITION BY RANGE (created_at)
            """)
            dj_cursor.execute("""
                CREATE TABLE test_partitioned_parent_no_pk_2026_q1
                PARTITION OF test_partitioned_parent_no_pk
                FOR VALUES FROM ('2026-01-01') TO ('2026-04-01')
            """)
            dj_cursor.execute("""
                CREATE TABLE test_partitioned_parent_no_pk_2026_q2
                PARTITION OF test_partitioned_parent_no_pk
                FOR VALUES FROM ('2026-04-01') TO ('2026-07-01')
            """)

            dj_cursor.execute("""
                ALTER TABLE ONLY test_partitioned_parent_no_pk_2026_q1
                ADD CONSTRAINT test_partitioned_parent_no_pk_2026_q1_pkey PRIMARY KEY (order_id)
            """)
            dj_cursor.execute("""
                ALTER TABLE ONLY test_partitioned_parent_no_pk_2026_q2
                ADD CONSTRAINT test_partitioned_parent_no_pk_2026_q2_pkey PRIMARY KEY (order_id)
            """)

            result = _get_primary_keys(cast(Any, dj_cursor), "public", "test_partitioned_parent_no_pk", logger)
            assert result is not None
            assert result == ["order_id"]

    @pytest.mark.django_db
    def test_returns_none_for_partitioned_parent_with_inconsistent_child_pks(self):
        logger = structlog.get_logger()

        with django_connection.cursor() as dj_cursor:
            dj_cursor.execute("""
                CREATE TABLE test_partitioned_inconsistent_pk (
                    col_a INTEGER NOT NULL,
                    col_b INTEGER NOT NULL,
                    created_at DATE NOT NULL
                ) PARTITION BY RANGE (created_at)
            """)
            dj_cursor.execute("""
                CREATE TABLE test_partitioned_inconsistent_pk_q1
                PARTITION OF test_partitioned_inconsistent_pk
                FOR VALUES FROM ('2026-01-01') TO ('2026-04-01')
            """)
            dj_cursor.execute("""
                CREATE TABLE test_partitioned_inconsistent_pk_q2
                PARTITION OF test_partitioned_inconsistent_pk
                FOR VALUES FROM ('2026-04-01') TO ('2026-07-01')
            """)
            dj_cursor.execute("""
                ALTER TABLE ONLY test_partitioned_inconsistent_pk_q1
                ADD CONSTRAINT test_partitioned_inconsistent_pk_q1_pkey PRIMARY KEY (col_a)
            """)
            dj_cursor.execute("""
                ALTER TABLE ONLY test_partitioned_inconsistent_pk_q2
                ADD CONSTRAINT test_partitioned_inconsistent_pk_q2_pkey PRIMARY KEY (col_b)
            """)

            result = _get_primary_keys(cast(Any, dj_cursor), "public", "test_partitioned_inconsistent_pk", logger)
            assert result is None


class TestHasDuplicatePrimaryKeys:
    @pytest.mark.django_db
    def test_returns_false_when_no_primary_keys(self):
        logger = structlog.get_logger()

        with django_connection.cursor() as dj_cursor:
            assert _has_duplicate_primary_keys(cast(Any, dj_cursor), "public", "any_table", None, logger) is False
            assert _has_duplicate_primary_keys(cast(Any, dj_cursor), "public", "any_table", [], logger) is False

    @pytest.mark.django_db
    def test_returns_false_when_no_duplicates(self):
        logger = structlog.get_logger()

        with django_connection.cursor() as dj_cursor:
            dj_cursor.execute("""
                CREATE TABLE test_no_dup_table (
                    id INTEGER,
                    name TEXT
                )
            """)
            dj_cursor.execute("INSERT INTO test_no_dup_table VALUES (1, 'a'), (2, 'b'), (3, 'c')")
            result = _has_duplicate_primary_keys(cast(Any, dj_cursor), "public", "test_no_dup_table", ["id"], logger)
            assert result is False

    @pytest.mark.django_db
    def test_returns_true_when_duplicates_exist(self):
        logger = structlog.get_logger()

        with django_connection.cursor() as dj_cursor:
            dj_cursor.execute("""
                CREATE TABLE test_dup_table (
                    id INTEGER,
                    name TEXT
                )
            """)
            dj_cursor.execute("INSERT INTO test_dup_table VALUES (1, 'a'), (1, 'b'), (2, 'c')")
            result = _has_duplicate_primary_keys(cast(Any, dj_cursor), "public", "test_dup_table", ["id"], logger)
            assert result is True


class TestIsReadReplica:
    @pytest.mark.django_db
    def test_primary_is_not_read_replica(self):
        with django_connection.cursor() as dj_cursor:
            result = _is_read_replica(cast(Any, dj_cursor))
            assert result is False


class TestGetTable:
    @pytest.mark.django_db
    def test_regular_table(self):
        logger = structlog.get_logger()

        with django_connection.cursor() as dj_cursor:
            dj_cursor.execute("""
                CREATE TABLE test_get_table_regular (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    score DOUBLE PRECISION
                )
            """)
            table = _get_table(cast(Any, dj_cursor), "public", "test_get_table_regular", logger)
            assert table.type == "table"
            col_names = [c.name for c in table.columns]
            assert "id" in col_names
            assert "name" in col_names
            assert "score" in col_names

    @pytest.mark.django_db
    def test_view(self):
        logger = structlog.get_logger()

        with django_connection.cursor() as dj_cursor:
            dj_cursor.execute("CREATE TABLE test_get_table_view_base (id INTEGER, name TEXT)")
            dj_cursor.execute("CREATE VIEW test_get_table_view AS SELECT * FROM test_get_table_view_base")
            table = _get_table(cast(Any, dj_cursor), "public", "test_get_table_view", logger)
            assert table.type == "view"

    @pytest.mark.django_db
    def test_materialized_view(self):
        logger = structlog.get_logger()

        with django_connection.cursor() as dj_cursor:
            dj_cursor.execute("CREATE TABLE test_get_table_matview_base (id INTEGER, val NUMERIC(10,2))")
            dj_cursor.execute(
                "CREATE MATERIALIZED VIEW test_get_table_matview AS SELECT * FROM test_get_table_matview_base"
            )
            table = _get_table(cast(Any, dj_cursor), "public", "test_get_table_matview", logger)
            assert table.type == "materialized_view"

    @pytest.mark.django_db
    def test_unconstrained_numeric_probe_gated_off_uses_default_scale(self):
        """When the caller doesn't request probing (the default), an unconstrained `numeric`
        column falls back to `DEFAULT_NUMERIC_SCALE` regardless of the actual data. This is the
        path used by incremental syncs where the delta column type is already set and probing
        would be a wasted full-table aggregation."""
        logger = structlog.get_logger()

        with django_connection.cursor() as dj_cursor:
            dj_cursor.execute("CREATE TABLE test_get_table_probe_gated_off (id INTEGER PRIMARY KEY, val NUMERIC)")
            dj_cursor.execute("INSERT INTO test_get_table_probe_gated_off VALUES (1, 0.84497449830783164117::numeric)")
            # Explicitly omit `probe_unconstrained_numeric_scale` to exercise the default.
            table = _get_table(dj_cursor, "public", "test_get_table_probe_gated_off", logger)  # type: ignore[arg-type]
            val_col = next(c for c in table.columns if c.name == "val")
            assert val_col.numeric_scale == DEFAULT_NUMERIC_SCALE

    @pytest.mark.django_db
    @pytest.mark.parametrize(
        "inserts,expected_precision,expected_scale,expected_arrow_type",
        [
            pytest.param(
                [
                    "INSERT INTO test_probe_scale VALUES (1, 0.84497449830783164117::numeric)",
                    "INSERT INTO test_probe_scale VALUES (2, 0::numeric)",
                ],
                38,
                20,
                pa.decimal128(38, 20),
                id="fractional_fits_in_decimal128",
            ),
            pytest.param(
                [],
                38,
                DEFAULT_NUMERIC_SCALE,
                pa.decimal128(38, DEFAULT_NUMERIC_SCALE),
                id="empty_table_falls_back_to_default",
            ),
            pytest.param(
                [
                    "INSERT INTO test_probe_scale VALUES (1, 0.1234567890123456789012345678901234567890::numeric)",
                ],
                38,
                MAX_NUMERIC_SCALE,
                pa.decimal128(38, MAX_NUMERIC_SCALE),
                id="scale_past_max_clamped_with_small_int_still_fits",
            ),
            # Pins the intentional conservative behavior: all-integer data means MAX(scale(val))
            # returns 0, but we fall back to DEFAULT_NUMERIC_SCALE rather than freezing the delta
            # column at scale=0 — because the source column is unconstrained and a future sync
            # could legitimately carry fractional digits the delta column wouldn't be able to
            # hold. See the matching comment in postgres.py:_get_table.
            pytest.param(
                [
                    "INSERT INTO test_probe_scale VALUES (1, 42::numeric)",
                    "INSERT INTO test_probe_scale VALUES (2, 1000::numeric)",
                ],
                38,
                DEFAULT_NUMERIC_SCALE,
                pa.decimal128(38, DEFAULT_NUMERIC_SCALE),
                id="integer_only_data_falls_back_to_default",
            ),
            # 8 integer digits + 30 fractional digits = 38 total, which is the `decimal128`
            # precision budget. Must fit without escalating.
            pytest.param(
                [
                    "INSERT INTO test_probe_scale VALUES (1, 12345678.012345678901234567890123456789::numeric)",
                ],
                38,
                30,
                pa.decimal128(38, 30),
                id="total_exactly_at_decimal128_budget_fits",
            ),
            # 9 integer digits + 30 fractional digits = 39 total, one digit past the `decimal128`
            # budget. The column must escalate precision past 38 so `build_pyarrow_decimal_type`
            # promotes to `decimal256`; staying at (38, 30) would silently lose the leading integer
            # digit when the data is later cast to arrow.
            pytest.param(
                [
                    "INSERT INTO test_probe_scale VALUES (1, 123456789.012345678901234567890123456789::numeric)",
                ],
                39,
                30,
                pa.decimal256(39, 30),
                id="integer_overflow_escalates_precision_past_38",
            ),
            # 10 integer digits + 32 fractional digits = 42 total. Scale is at MAX_NUMERIC_SCALE,
            # integer side is over budget. Must escalate precision to cover both dimensions.
            pytest.param(
                [
                    "INSERT INTO test_probe_scale VALUES (1, 1234567890.12345678901234567890123456789012::numeric)",
                ],
                42,
                MAX_NUMERIC_SCALE,
                pa.decimal256(42, MAX_NUMERIC_SCALE),
                id="both_dimensions_exceed_budget_escalates_precision",
            ),
        ],
    )
    def test_unconstrained_numeric_probe_dimensions(
        self,
        inserts: list[str],
        expected_precision: int,
        expected_scale: int,
        expected_arrow_type: pa.DataType,
    ):
        """Unconstrained `numeric` columns probe both fractional scale and integer digits so the
        resulting decimal type has enough precision to hold the observed data. When total digits
        exceed `decimal128`'s 38-digit budget, precision must escalate past 38 so
        `build_pyarrow_decimal_type` promotes the column to `decimal256` (which delta-rs will then
        collapse to `string` at write). Freezing at `decimal128(38, scale)` silently truncates
        either fractional digits (original bug pre-PR) or integer digits (regression introduced by
        the single-dimension probe)."""
        logger = structlog.get_logger()

        with django_connection.cursor() as dj_cursor:
            dj_cursor.execute("CREATE TABLE test_probe_scale (id INTEGER PRIMARY KEY, val NUMERIC)")
            for insert_sql in inserts:
                dj_cursor.execute(insert_sql)

            table = _get_table(
                dj_cursor,  # type: ignore[arg-type]
                "public",
                "test_probe_scale",
                logger,
                probe_unconstrained_numeric_scale=True,
            )
            val_col = next(c for c in table.columns if c.name == "val")
            assert val_col.numeric_precision == expected_precision
            assert val_col.numeric_scale == expected_scale
            # Guard the full schema conversion too — catches regressions where precision/scale
            # look right on the PostgreSQLColumn but the arrow type flips (e.g. decimal128 vs
            # decimal256). The expected type is explicit per case rather than derived from
            # `build_pyarrow_decimal_type(precision, scale)` so each case locks in its intended
            # arrow width at the parameter level.
            assert val_col.to_arrow_field().type == expected_arrow_type

    @pytest.mark.django_db
    def test_constrained_numeric_skips_probe(self):
        """Columns declared with explicit precision/scale use those values directly, no data probe."""
        logger = structlog.get_logger()

        with django_connection.cursor() as dj_cursor:
            dj_cursor.execute(
                "CREATE TABLE test_get_table_constrained_numeric (id INTEGER PRIMARY KEY, val NUMERIC(10, 2))"
            )
            # Even though there's no data, the declared scale is used — no probe attempted.
            table = _get_table(dj_cursor, "public", "test_get_table_constrained_numeric", logger)  # type: ignore[arg-type]
            val_col = next(c for c in table.columns if c.name == "val")
            assert val_col.numeric_precision == 10
            assert val_col.numeric_scale == 2

    @pytest.mark.django_db
    def test_constrained_numeric_zero_scale_survives_schema_conversion(self):
        """Declared `NUMERIC(X, 0)` columns must be convertible to an arrow schema without tripping
        the legacy truthy-check guard in `PostgreSQLColumn.to_arrow_field`."""
        logger = structlog.get_logger()

        with django_connection.cursor() as dj_cursor:
            dj_cursor.execute("CREATE TABLE test_get_table_zero_scale (id INTEGER PRIMARY KEY, val NUMERIC(10, 0))")
            table = _get_table(dj_cursor, "public", "test_get_table_zero_scale", logger)  # type: ignore[arg-type]
            val_col = next(c for c in table.columns if c.name == "val")
            assert val_col.numeric_precision == 10
            assert val_col.numeric_scale == 0
            # Must not raise — the full schema conversion is the actual regression surface.
            arrow_schema = table.to_arrow_schema()
            assert pa.types.is_decimal(arrow_schema.field("val").type)

    @pytest.mark.django_db
    def test_unconstrained_numeric_on_view_skips_probe(self):
        """`MAX(scale(col))` on a regular view forces the view definition to execute, which
        can be arbitrarily expensive for join/aggregate views. The probe is skipped for views
        regardless of the caller's probe flag, and falls back to DEFAULT_NUMERIC_SCALE.
        The downstream `_process_batch` fallback chain handles scale inference at row time."""
        logger = structlog.get_logger()

        with django_connection.cursor() as dj_cursor:
            dj_cursor.execute(
                "CREATE TABLE test_get_table_view_unconstrained_base (id INTEGER PRIMARY KEY, val NUMERIC)"
            )
            dj_cursor.execute(
                "INSERT INTO test_get_table_view_unconstrained_base VALUES (1, 0.84497449830783164117::numeric)"
            )
            dj_cursor.execute(
                "CREATE VIEW test_get_table_view_unconstrained AS SELECT * FROM test_get_table_view_unconstrained_base"
            )
            table = _get_table(
                dj_cursor,  # type: ignore[arg-type]
                "public",
                "test_get_table_view_unconstrained",
                logger,
                probe_unconstrained_numeric_scale=True,
            )
            assert table.type == "view"
            val_col = next(c for c in table.columns if c.name == "val")
            # Probe was skipped for the view → default scale, even though the base table has
            # scale-20 data that a probe would have found.
            assert val_col.numeric_scale == DEFAULT_NUMERIC_SCALE

    @pytest.mark.django_db
    def test_unconstrained_numeric_multiple_columns_probed_together(self):
        """Multiple unconstrained numeric columns are probed in a single aggregation query."""
        logger = structlog.get_logger()

        with django_connection.cursor() as dj_cursor:
            dj_cursor.execute(
                "CREATE TABLE test_get_table_multi_numeric "
                "(id INTEGER PRIMARY KEY, a NUMERIC, b NUMERIC, c NUMERIC(5, 2))"
            )
            dj_cursor.execute(
                "INSERT INTO test_get_table_multi_numeric VALUES "
                "(1, 0.12345::numeric, 0.1234567890::numeric, 1.23::numeric(5,2))"
            )
            table = _get_table(
                dj_cursor,  # type: ignore[arg-type]
                "public",
                "test_get_table_multi_numeric",
                logger,
                probe_unconstrained_numeric_scale=True,
            )
            cols_by_name = {c.name: c for c in table.columns}
            assert cols_by_name["a"].numeric_scale == 5
            assert cols_by_name["b"].numeric_scale == 10
            # Constrained column is untouched.
            assert cols_by_name["c"].numeric_precision == 5
            assert cols_by_name["c"].numeric_scale == 2
