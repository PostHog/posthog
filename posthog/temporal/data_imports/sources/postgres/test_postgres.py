from datetime import UTC, date, datetime, timedelta
from typing import Any, cast

import pytest
from freezegun import freeze_time
from unittest import mock
from unittest.mock import patch

from django.db import connection as django_connection

import psycopg
import pyarrow as pa
import structlog
from psycopg import sql

from posthog.temporal.data_imports.pipelines.pipeline.utils import (
    DEFAULT_NUMERIC_SCALE,
    MAX_NUMERIC_SCALE,
    QueryTimeoutException,
)
from posthog.temporal.data_imports.sources.postgres.partitioned_tables import (
    WINDOW_MAX_QUERY_CANCELED_RETRIES,
    WINDOW_MAX_SERIALIZATION_RETRIES,
    ChildPartition,
    PartitionStrategy,
    derive_upper_bound,
    get_partition_strategy,
    is_supported_incremental_type_for_window,
    iterate_date_windows,
    iterate_partitions,
    list_child_partitions,
    partition_bounds_for_range,
    should_preserve_asc_sort,
)
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
    get_foreign_keys,
    get_postgres_row_count,
    get_schemas,
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

    def test_validate_credentials_for_access_method_requires_schema_for_warehouse_imports(self, source):
        config = source.parse_config(
            {
                "host": "localhost",
                "port": 5432,
                "database": "postgres",
                "user": "postgres",
                "password": "postgres",
                "schema": "",
            }
        )

        valid, error = source.validate_credentials_for_access_method(config, team_id=1, access_method="warehouse")

        assert valid is False
        assert error == "Schema is required for warehouse imports."

    def test_validate_credentials_for_access_method_allows_blank_schema_for_direct_queries(self, source):
        config = source.parse_config(
            {
                "host": "localhost",
                "port": 5432,
                "database": "postgres",
                "user": "postgres",
                "password": "postgres",
                "schema": "",
            }
        )

        with mock.patch.object(source, "validate_credentials", return_value=(True, None)) as validate_credentials:
            valid, error = source.validate_credentials_for_access_method(config, team_id=1, access_method="direct")

        assert valid is True
        assert error is None
        validate_credentials.assert_called_once_with(config, 1, schema_name=None)


class TestPostgresSchemaDiscovery:
    def _mock_connection(self, *fetchall_results: list[tuple[object, ...]]):
        cursor = mock.MagicMock()
        cursor.fetchall.side_effect = list(fetchall_results)
        cursor.fetchone.return_value = ("PostgreSQL 15.0",)

        cursor_context = mock.MagicMock()
        cursor_context.__enter__.return_value = cursor
        cursor_context.__exit__.return_value = None

        connection = mock.MagicMock()
        connection.cursor.return_value = cursor_context
        return connection

    def test_get_schemas_qualifies_table_names_when_schema_is_blank(self):
        connection = self._mock_connection(
            [("public", "users"), ("analytics", "events")],
            [
                ("analytics", "events", "id", "integer", "NO", 1),
                ("public", "users", "id", "integer", "NO", 1),
            ],
        )

        with mock.patch(
            "posthog.temporal.data_imports.sources.postgres.postgres._connect_to_postgres",
            return_value=connection,
        ):
            schemas = get_schemas(
                host="localhost",
                port=5432,
                database="postgres",
                user="postgres",
                password="postgres",
                schema="",
            )

        cursor = connection.cursor.return_value.__enter__.return_value
        executed_queries = [
            call.args[0] for call in cursor.execute.call_args_list if "SELECT version()" not in str(call.args[0])
        ]
        first_query = executed_queries[0]
        second_query = executed_queries[1]

        assert "NOT IN" in first_query
        assert "ALL(" not in first_query
        assert " IN (" in second_query
        assert "ANY(" not in second_query
        assert set(schemas.keys()) == {"public.users", "analytics.events"}
        assert schemas["public.users"].source_schema == "public"
        assert schemas["public.users"].source_table_name == "users"
        assert schemas["analytics.events"].source_schema == "analytics"
        assert schemas["analytics.events"].source_table_name == "events"

    def test_get_foreign_keys_qualifies_target_table_names_when_schema_is_blank(self):
        connection = self._mock_connection(
            [("public", "users"), ("analytics", "events")],
            [("analytics", "events", "user_id", "public", "users", "id")],
        )

        with mock.patch(
            "posthog.temporal.data_imports.sources.postgres.postgres._connect_to_postgres",
            return_value=connection,
        ):
            foreign_keys = get_foreign_keys(
                host="localhost",
                port=5432,
                database="postgres",
                user="postgres",
                password="postgres",
                schema="",
            )

        cursor = connection.cursor.return_value.__enter__.return_value
        executed_queries = [
            call.args[0] for call in cursor.execute.call_args_list if "SELECT version()" not in str(call.args[0])
        ]
        first_query = executed_queries[0]
        second_query = executed_queries[1]

        assert "NOT IN" in first_query
        assert "ALL(" not in first_query
        assert " IN (" in second_query
        assert "ANY(" not in second_query
        assert foreign_keys == {"analytics.events": [("user_id", "public.users", "id")]}

    def test_get_schemas_for_duckdb_uses_current_catalog_only(self):
        connection = self._mock_connection(
            [("ducklake", "system", "query_log")],
            [
                ("system", "query_log", "query_id", "varchar", "NO", 1),
            ],
        )
        connection.cursor.return_value.__enter__.return_value.fetchone.side_effect = [
            ("DuckDB 1.4 (Duckgres)",),
            ("ducklake",),
        ]

        with mock.patch(
            "posthog.temporal.data_imports.sources.postgres.postgres._connect_to_postgres",
            return_value=connection,
        ):
            schemas = get_schemas(
                host="localhost",
                port=5432,
                database="postgres",
                user="postgres",
                password="postgres",
                schema="",
            )

        cursor = connection.cursor.return_value.__enter__.return_value
        information_schema_call = next(
            call for call in cursor.execute.call_args_list if "FROM information_schema.tables" in str(call.args[0])
        )
        information_schema_query = str(information_schema_call.args[0])
        information_schema_params = information_schema_call.args[1]

        assert "table_catalog = %(current_database)s" in information_schema_query
        assert information_schema_params["current_database"] == "ducklake"
        assert schemas["system.query_log"].source_catalog == "ducklake"
        assert "public.ducklake_view" not in schemas

    def test_get_postgres_row_count_skips_blank_schema_browse(self):
        with mock.patch(
            "posthog.temporal.data_imports.sources.postgres.postgres._connect_to_postgres"
        ) as patch_connect_to_postgres:
            row_counts = get_postgres_row_count(
                host="localhost",
                port=5432,
                database="postgres",
                user="postgres",
                password="postgres",
                schema="   ",
            )

        assert row_counts == {}
        patch_connect_to_postgres.assert_not_called()


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


class TestBuildQueryUpperBound:
    def test_includes_inclusive_upper_bound(self):
        q = _build_query(
            "public",
            "t",
            should_use_incremental_field=True,
            table_type="table",
            incremental_field="created_at",
            incremental_field_type=IncrementalFieldType.DateTime,
            db_incremental_field_last_value=datetime(2026, 1, 1),
            upper_bound_inclusive=datetime(2026, 1, 2),
        )
        rendered = q.as_string()
        assert '"created_at" > ' in rendered
        assert '"created_at" <= ' in rendered
        assert 'ORDER BY "created_at" ASC' in rendered

    def test_skips_upper_bound_when_not_provided(self):
        q = _build_query(
            "public",
            "t",
            should_use_incremental_field=True,
            table_type="table",
            incremental_field="created_at",
            incremental_field_type=IncrementalFieldType.DateTime,
            db_incremental_field_last_value=datetime(2026, 1, 1),
        )
        rendered = q.as_string()
        assert '"created_at" <= ' not in rendered
        assert 'ORDER BY "created_at" ASC' in rendered


class TestPartitionBoundsForRange:
    @pytest.mark.parametrize(
        "partbound,field_type,expected",
        [
            (
                "FOR VALUES FROM ('2026-01-01') TO ('2026-02-01')",
                IncrementalFieldType.Date,
                (date(2026, 1, 1), date(2026, 2, 1)),
            ),
            (
                "FOR VALUES FROM ('2026-01-01 00:00:00') TO ('2026-02-01 00:00:00')",
                IncrementalFieldType.DateTime,
                (datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 2, 1, tzinfo=UTC)),
            ),
            ("FOR VALUES FROM (100) TO (200)", IncrementalFieldType.Integer, (100, 200)),
            ("FOR VALUES FROM (MINVALUE) TO ('2026-01-01')", IncrementalFieldType.Date, None),
            ("FOR VALUES FROM ('2026-01-01') TO (MAXVALUE)", IncrementalFieldType.Date, None),
            ("DEFAULT", IncrementalFieldType.Date, None),
            ("FOR VALUES IN ('a', 'b')", IncrementalFieldType.Date, None),
            ("FOR VALUES WITH (modulus 4, remainder 0)", IncrementalFieldType.Integer, None),
        ],
    )
    def test_parses(self, partbound, field_type, expected):
        child = ChildPartition(oid=1, schema="public", name="p", partbound=partbound)
        assert partition_bounds_for_range(child, field_type) == expected


class TestDeriveUpperBound:
    def test_prefers_range_hi_when_available(self):
        bounds = [(date(2026, 1, 1), date(2026, 2, 1)), (date(2026, 2, 1), date(2026, 3, 1))]
        assert derive_upper_bound(IncrementalFieldType.Date, bounds) == date(2026, 3, 1)

    @freeze_time("2026-04-20T12:00:00Z")
    def test_uses_now_for_datetime_without_bounds(self):
        out = derive_upper_bound(IncrementalFieldType.DateTime, [])
        assert out == datetime(2026, 4, 20, 12, 0, 0, tzinfo=UTC)

    def test_returns_none_for_numeric_without_bounds(self):
        assert derive_upper_bound(IncrementalFieldType.Integer, []) is None
        assert derive_upper_bound(IncrementalFieldType.Numeric, []) is None


class TestShouldPreserveAscSort:
    def test_true_for_range_on_incremental_field(self):
        strat = PartitionStrategy(strategy="r", key_columns=("created_at",))
        assert should_preserve_asc_sort(strat, "created_at") is True

    def test_false_for_range_on_different_field(self):
        strat = PartitionStrategy(strategy="r", key_columns=("region",))
        assert should_preserve_asc_sort(strat, "created_at") is False

    def test_false_for_hash_partitioning(self):
        strat = PartitionStrategy(strategy="h", key_columns=("id",))
        assert should_preserve_asc_sort(strat, "id") is False

    def test_true_without_strategy_info(self):
        assert should_preserve_asc_sort(None, "created_at") is True


class TestIsSupportedIncrementalTypeForWindow:
    @pytest.mark.parametrize(
        "field_type,expected",
        [
            (IncrementalFieldType.Date, True),
            (IncrementalFieldType.DateTime, True),
            (IncrementalFieldType.Timestamp, True),
            (IncrementalFieldType.Integer, True),
            (IncrementalFieldType.Numeric, True),
            (IncrementalFieldType.ObjectID, False),
            (None, False),
        ],
    )
    def test_matrix(self, field_type, expected):
        assert is_supported_incremental_type_for_window(field_type) is expected


class TestListChildPartitionsAndStrategy:
    @pytest.mark.django_db
    def test_lists_children_and_strategy(self):
        with django_connection.cursor() as dj_cursor:
            dj_cursor.execute("""
                CREATE TABLE test_lcp_parent (
                    id BIGSERIAL,
                    created_at DATE NOT NULL,
                    PRIMARY KEY (id, created_at)
                ) PARTITION BY RANGE (created_at)
            """)
            dj_cursor.execute(
                "CREATE TABLE test_lcp_2026_01 PARTITION OF test_lcp_parent "
                "FOR VALUES FROM ('2026-01-01') TO ('2026-02-01')"
            )
            dj_cursor.execute(
                "CREATE TABLE test_lcp_2026_02 PARTITION OF test_lcp_parent "
                "FOR VALUES FROM ('2026-02-01') TO ('2026-03-01')"
            )

            children = list_child_partitions(cast(Any, dj_cursor), "public", "test_lcp_parent")
            names = {c.name for c in children}
            assert names == {"test_lcp_2026_01", "test_lcp_2026_02"}
            # All children have parseable range bounds
            for c in children:
                assert partition_bounds_for_range(c, IncrementalFieldType.Date) is not None

            strat = get_partition_strategy(cast(Any, dj_cursor), "public", "test_lcp_parent")
            assert strat is not None
            assert strat.strategy == "r"
            assert strat.key_columns == ("created_at",)

    @pytest.mark.django_db
    def test_returns_none_for_non_partitioned(self):
        with django_connection.cursor() as dj_cursor:
            dj_cursor.execute("CREATE TABLE test_lcp_regular (id SERIAL PRIMARY KEY, data TEXT)")
            assert get_partition_strategy(cast(Any, dj_cursor), "public", "test_lcp_regular") is None
            assert list_child_partitions(cast(Any, dj_cursor), "public", "test_lcp_regular") == []


# ---- Fake connection infrastructure for deterministic iterate_date_windows tests ----


class _FakeClock:
    def __init__(self, start: float = 0.0):
        self.t = start

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


class _FakeCursor:
    """Minimal psycopg cursor stand-in.

    Each invocation of iterate_date_windows opens a fresh cursor; `script` is a
    list of per-cursor behaviors. A behavior is one of:
      - list[tuple]  → rows returned from fetchmany, then []
      - Exception instance → raised from execute()
    """

    def __init__(self, owner: "_FakeConnection", behaviour):
        self.owner = owner
        self.behaviour = behaviour
        self.description = [mock.Mock(name="col1"), mock.Mock(name="col2")]
        self.description[0].name = "id"
        self.description[1].name = "val"
        self._rows_remaining: list = []
        self._executed = False

    def execute(self, query):
        self.owner.executed_queries.append(query)
        if isinstance(self.behaviour, Exception):
            raise self.behaviour
        self._rows_remaining = list(self.behaviour)
        self._executed = True

    def fetchmany(self, n: int):
        if not self._executed:
            return []
        batch, self._rows_remaining = self._rows_remaining[:n], self._rows_remaining[n:]
        return batch

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class _FakeConnection:
    def __init__(self, owner: "_FakeConnectionFactory"):
        self.owner = owner
        self.executed_queries: list = []

    def cursor(self, *args, **kwargs):
        # Pop the next behaviour off the factory's script
        behaviour = self.owner.script.pop(0) if self.owner.script else []
        cur = _FakeCursor(self, behaviour)
        return cur

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    @property
    def closed(self):
        return False


class _FakeConnectionFactory:
    def __init__(self, script: list):
        self.script = script
        self.connections_opened = 0
        self.connections: list[_FakeConnection] = []

    def __call__(self) -> _FakeConnection:
        self.connections_opened += 1
        conn = _FakeConnection(self)
        self.connections.append(conn)
        return conn

    def all_executed_queries(self) -> list[str]:
        return [
            q.as_string() if hasattr(q, "as_string") else str(q) for c in self.connections for q in c.executed_queries
        ]


def _arrow_schema() -> pa.Schema:
    fields: list[pa.Field] = [pa.field("id", pa.int64()), pa.field("val", pa.int64())]
    return pa.schema(fields)


def _build_fake_query(lo, hi):
    return sql.SQL("SELECT * FROM t WHERE x > {lo} AND x <= {hi}").format(lo=sql.Literal(lo), hi=sql.Literal(hi))


def _run_windows(script, **overrides):
    factory = _FakeConnectionFactory(script)
    kwargs: dict[str, Any] = {
        "get_connection": cast(Any, factory),
        "build_windowed_query": _build_fake_query,
        "schema": "public",
        "table_name": "t",
        "incremental_field": "x",
        "incremental_field_type": IncrementalFieldType.Date,
        "db_incremental_field_last_value": date(2026, 1, 1),
        "child_partitions": [],
        "chunk_size": 1000,
        "arrow_schema": _arrow_schema(),
        "logger": structlog.get_logger(),
        "initial_window": timedelta(days=1),
        "clock": _FakeClock(),
        "sleeper": lambda _s: None,
    }
    kwargs.update(overrides)
    # Give the test a deterministic finite range by forcing upper via a time-based field
    # + partition bounds argument. Tests that need an explicit upper pass child_partitions.
    return list(iterate_date_windows(**kwargs)), factory


class TestIterateDateWindowsFake:
    def test_single_window_yields_rows(self):
        # One partition covering one day → one window, 3 rows
        child = ChildPartition(
            oid=1,
            schema="public",
            name="p",
            partbound="FOR VALUES FROM ('2026-01-01') TO ('2026-01-02')",
        )
        tables, factory = _run_windows(
            script=[[(1, 10), (2, 20), (3, 30)]],
            child_partitions=[child],
        )
        assert factory.connections_opened == 1
        total = sum(t.num_rows for t in tables)
        assert total == 3

    def test_walks_multiple_windows(self):
        # Two partitions, each 1 day; with initial_window=1 day, expect two windows.
        children = [
            ChildPartition(
                oid=1,
                schema="public",
                name="p1",
                partbound="FOR VALUES FROM ('2026-01-01') TO ('2026-01-02')",
            ),
            ChildPartition(
                oid=2,
                schema="public",
                name="p2",
                partbound="FOR VALUES FROM ('2026-01-02') TO ('2026-01-03')",
            ),
        ]
        tables, factory = _run_windows(
            script=[[(1, 10)], [(2, 20)]],
            child_partitions=children,
            db_incremental_field_last_value=date(2026, 1, 1),
        )
        assert factory.connections_opened == 2
        assert sum(t.num_rows for t in tables) == 2

    def test_shrinks_and_retries_on_query_canceled(self):
        child = ChildPartition(
            oid=1,
            schema="public",
            name="p",
            partbound="FOR VALUES FROM ('2026-01-01') TO ('2026-01-02')",
        )
        # QueryCanceled once -> shrink + retry -> succeeds -> walker may continue
        # through the remaining range. We only care that retries happened and rows came back.
        script = [psycopg.errors.QueryCanceled("timeout"), [(1, 10)], [], []]
        tables, factory = _run_windows(script=script, child_partitions=[child])
        assert factory.connections_opened >= 2
        assert sum(t.num_rows for t in tables) == 1

    def test_raises_query_timeout_after_budget_exhausted(self):
        child = ChildPartition(
            oid=1,
            schema="public",
            name="p",
            partbound="FOR VALUES FROM ('2026-01-01') TO ('2026-01-02')",
        )
        # Fail every attempt; iterator must raise QueryTimeoutException.
        script = [psycopg.errors.QueryCanceled("timeout")] * (WINDOW_MAX_QUERY_CANCELED_RETRIES + 2)
        with pytest.raises(QueryTimeoutException):
            list(
                iterate_date_windows(
                    get_connection=cast(Any, _FakeConnectionFactory(script)),
                    build_windowed_query=_build_fake_query,
                    schema="public",
                    table_name="t",
                    incremental_field="x",
                    incremental_field_type=IncrementalFieldType.Date,
                    db_incremental_field_last_value=date(2026, 1, 1),
                    child_partitions=[child],
                    chunk_size=1000,
                    arrow_schema=_arrow_schema(),
                    logger=structlog.get_logger(),
                    initial_window=timedelta(days=1),
                    clock=_FakeClock(),
                    sleeper=lambda _s: None,
                )
            )

    def test_raises_after_max_serialization_retries_on_replica(self):
        child = ChildPartition(
            oid=1,
            schema="public",
            name="p",
            partbound="FOR VALUES FROM ('2026-01-01') TO ('2026-01-02')",
        )
        conflict_err = psycopg.errors.SerializationFailure("due to conflict with recovery")
        script = [conflict_err] * (WINDOW_MAX_SERIALIZATION_RETRIES + 2)

        with pytest.raises(psycopg.errors.SerializationFailure):
            list(
                iterate_date_windows(
                    get_connection=cast(Any, _FakeConnectionFactory(script)),
                    build_windowed_query=_build_fake_query,
                    schema="public",
                    table_name="t",
                    incremental_field="x",
                    incremental_field_type=IncrementalFieldType.Date,
                    db_incremental_field_last_value=date(2026, 1, 1),
                    child_partitions=[child],
                    chunk_size=1000,
                    arrow_schema=_arrow_schema(),
                    logger=structlog.get_logger(),
                    initial_window=timedelta(days=1),
                    clock=_FakeClock(),
                    sleeper=lambda _s: None,
                    using_read_replica=True,
                )
            )

    def test_does_not_set_per_window_statement_timeout(self):
        """Critical: this is the user's explicit requirement — no tightened timeout."""
        child = ChildPartition(
            oid=1,
            schema="public",
            name="p",
            partbound="FOR VALUES FROM ('2026-01-01') TO ('2026-01-02')",
        )
        script = [[(1, 10)]]
        factory = _FakeConnectionFactory(script)
        list(
            iterate_date_windows(
                get_connection=cast(Any, factory),
                build_windowed_query=_build_fake_query,
                schema="public",
                table_name="t",
                incremental_field="x",
                incremental_field_type=IncrementalFieldType.Date,
                db_incremental_field_last_value=date(2026, 1, 1),
                child_partitions=[child],
                chunk_size=1000,
                arrow_schema=_arrow_schema(),
                logger=structlog.get_logger(),
                initial_window=timedelta(days=1),
                clock=_FakeClock(),
                sleeper=lambda _s: None,
            )
        )
        # Inspect every query issued across all opened connections — none must
        # be a `SET statement_timeout` statement. The connection-level 10-min
        # backstop set in postgres_source.get_connection is the only timeout.
        all_queries = factory.all_executed_queries()
        assert all_queries, "expected at least one query to be executed"
        assert not any("statement_timeout" in q.lower() for q in all_queries), (
            f"iterate_date_windows must not tighten statement_timeout per window; queries: {all_queries}"
        )


class TestIterateDateWindowsRealDb:
    @pytest.mark.django_db
    def test_yields_all_rows_over_partitioned_table(self):
        logger = structlog.get_logger()
        with django_connection.cursor() as dj_cursor:
            dj_cursor.execute("""
                CREATE TABLE test_idw_parent (
                    id BIGSERIAL,
                    created_at DATE NOT NULL,
                    val INTEGER,
                    PRIMARY KEY (id, created_at)
                ) PARTITION BY RANGE (created_at)
            """)
            dj_cursor.execute(
                "CREATE TABLE test_idw_p1 PARTITION OF test_idw_parent FOR VALUES FROM ('2026-01-01') TO ('2026-01-04')"
            )
            dj_cursor.execute(
                "CREATE TABLE test_idw_p2 PARTITION OF test_idw_parent FOR VALUES FROM ('2026-01-04') TO ('2026-01-07')"
            )
            dj_cursor.execute(
                "INSERT INTO test_idw_parent (created_at, val) "
                "SELECT '2026-01-01'::date + (g % 6) * interval '1 day', g "
                "FROM generate_series(1, 60) g"
            )

            children = list_child_partitions(cast(Any, dj_cursor), "public", "test_idw_parent")
            idw_fields: list[pa.Field] = [
                pa.field("id", pa.int64()),
                pa.field("created_at", pa.date32()),
                pa.field("val", pa.int64()),
            ]
            schema = pa.schema(idw_fields)

            def get_connection():
                # Hand out the Django-bound psycopg connection. The tests run in a
                # single transaction so a fresh psycopg.connect would not see the
                # CREATE/INSERT above. Wrap Django's connection in a shim that
                # returns the same raw cursor each time and no-ops __exit__.
                return _DjangoBackedConnection(dj_cursor)

            def build_q(lo, hi):
                return _build_query(
                    "public",
                    "test_idw_parent",
                    should_use_incremental_field=True,
                    table_type="table",
                    incremental_field="created_at",
                    incremental_field_type=IncrementalFieldType.Date,
                    db_incremental_field_last_value=lo,
                    upper_bound_inclusive=hi,
                )

            tables = list(
                iterate_date_windows(
                    get_connection=get_connection,
                    build_windowed_query=build_q,
                    schema="public",
                    table_name="test_idw_parent",
                    incremental_field="created_at",
                    incremental_field_type=IncrementalFieldType.Date,
                    db_incremental_field_last_value=date(2025, 12, 31),
                    child_partitions=children,
                    chunk_size=100,
                    arrow_schema=schema,
                    logger=logger,
                    initial_window=timedelta(days=1),
                )
            )
            total = sum(t.num_rows for t in tables)
            assert total == 60


class _DjangoBackedConnection:
    """Shim wrapping a Django cursor for tests that must see uncommitted rows.

    Named cursors go through the same raw psycopg cursor, so we just alias it.
    """

    def __init__(self, dj_cursor):
        self._dj_cursor = dj_cursor
        self.closed = False

    def cursor(self, *args, **kwargs):
        return _DjangoBackedCursorCtx(self._dj_cursor)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class _DjangoBackedCursorCtx:
    def __init__(self, dj_cursor):
        self._dj_cursor = dj_cursor

    def __enter__(self):
        return self._dj_cursor

    def __exit__(self, *args):
        return False


class TestIteratePartitionsRealDb:
    @pytest.mark.django_db
    def test_yields_all_rows(self):
        logger = structlog.get_logger()
        with django_connection.cursor() as dj_cursor:
            dj_cursor.execute("""
                CREATE TABLE test_ip_parent (
                    id BIGSERIAL,
                    created_at DATE NOT NULL,
                    val INTEGER,
                    PRIMARY KEY (id, created_at)
                ) PARTITION BY RANGE (created_at)
            """)
            dj_cursor.execute(
                "CREATE TABLE test_ip_p1 PARTITION OF test_ip_parent FOR VALUES FROM ('2026-01-01') TO ('2026-02-01')"
            )
            dj_cursor.execute(
                "CREATE TABLE test_ip_p2 PARTITION OF test_ip_parent FOR VALUES FROM ('2026-02-01') TO ('2026-03-01')"
            )
            dj_cursor.execute(
                "INSERT INTO test_ip_parent (created_at, val) "
                "SELECT '2026-01-01'::date + (g % 40) * interval '1 day', g "
                "FROM generate_series(1, 80) g"
            )

            children = list_child_partitions(cast(Any, dj_cursor), "public", "test_ip_parent")
            ip_fields: list[pa.Field] = [
                pa.field("id", pa.int64()),
                pa.field("created_at", pa.date32()),
                pa.field("val", pa.int64()),
            ]
            arrow_schema = pa.schema(ip_fields)

            def build_q(child_schema, child_name):
                return sql.SQL("SELECT id, created_at, val FROM {s}.{t} ORDER BY id ASC").format(
                    s=sql.Identifier(child_schema), t=sql.Identifier(child_name)
                )

            def get_connection():
                return _DjangoBackedConnection(dj_cursor)

            tables = list(
                iterate_partitions(
                    get_connection=get_connection,
                    build_partition_query=build_q,
                    schema="public",
                    table_name="test_ip_parent",
                    child_partitions=children,
                    chunk_size=100,
                    arrow_schema=arrow_schema,
                    logger=logger,
                )
            )
            assert sum(t.num_rows for t in tables) == 80
