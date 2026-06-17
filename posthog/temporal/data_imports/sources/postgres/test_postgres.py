from collections.abc import Iterable
from contextlib import contextmanager
from datetime import UTC, date, datetime, time, timedelta, timezone
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

import posthog.temporal.data_imports.sources.postgres.partitioned_tables as partitioned_tables_pkg
from posthog.temporal.data_imports.pipelines.pipeline.consts import DEFAULT_CHUNK_SIZE
from posthog.temporal.data_imports.pipelines.pipeline.utils import (
    DEFAULT_NUMERIC_SCALE,
    MAX_NUMERIC_SCALE,
    QueryTimeoutException,
    TemporaryFileSizeExceedsLimitException,
)
from posthog.temporal.data_imports.sources.postgres.partitioned_tables import (
    WINDOW_MAX_QUERY_CANCELED_RETRIES,
    WINDOW_MAX_SERIALIZATION_RETRIES,
    ChildPartition,
    PartitionStrategy,
    build_partition_query,
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
    _MAX_SETUP_RECOVERY_CONFLICT_RETRIES,
    FORCE_UTF8_CLIENT_ENCODING,
    SSL_REQUIRED_AFTER_DATE,
    JsonAsStringLoader,
    PostgresDiscoveredSchema,
    PostgresImplementation,
    PostgreSQLColumn,
    RangeAsStringLoader,
    SafeDateLoader,
    SafeTimeLoader,
    SafeTimestampLoader,
    SafeTimestamptzLoader,
    SafeTimetzLoader,
    _build_count_query,
    _build_query,
    _connect_to_postgres,
    _connect_with_dropped_retry,
    _connect_with_options_fallback,
    _get_estimated_row_count_for_partitioned_table,
    _get_partition_settings,
    _get_partition_settings_for_partitioned_table,
    _get_primary_keys,
    _get_rows_to_sync,
    _get_sslmode,
    _get_table,
    _get_table_chunk_size,
    _has_duplicate_primary_keys,
    _is_connection_dropped_error,
    _is_options_startup_param_unsupported,
    _is_partitioned_table,
    _is_read_replica,
    _is_unsupported_function_error,
    _normalize_function_names,
    _raise_if_setup_connection_broken,
    _rls_active_from_conn,
    _role_subject_to_rls,
    _statement_timeout_as_non_retryable,
    filter_postgres_incremental_fields,
    get_foreign_keys,
    get_leading_index_columns,
    get_postgres_row_count,
    get_schemas,
    postgres_source,
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


class TestSafeTimestampLoader:
    @pytest.fixture
    def loader(self):
        return SafeTimestampLoader(oid=1114)

    @pytest.mark.parametrize(
        "input_data,expected",
        [
            (b"2024-01-15 10:30:00", datetime(2024, 1, 15, 10, 30, 0)),
            (b"2024-01-15 10:30:00.123456", datetime(2024, 1, 15, 10, 30, 0, 123456)),
            (b"0001-01-01 00:00:00", datetime(1, 1, 1, 0, 0, 0)),
            (b"9999-12-31 23:59:59", datetime(9999, 12, 31, 23, 59, 59)),
            (b"200082-12-31 18:30:00", datetime.max),
            (b"20424-11-14 10:30:00", datetime.max),
            (b"10000-01-01 00:00:00", datetime.max),
            (b"infinity", datetime.max),
            (b"-infinity", datetime.min),
            (b"0044-03-15 00:00:00 BC", datetime.min),
            (None, None),
        ],
    )
    def test_load_timestamps(self, loader, input_data, expected):
        assert loader.load(input_data) == expected

    def test_clamped_values_are_naive(self, loader):
        assert loader.load(b"200082-12-31 18:30:00").tzinfo is None


class TestSafeTimestamptzLoader:
    @pytest.fixture
    def loader(self):
        return SafeTimestamptzLoader(oid=1184)

    @pytest.mark.parametrize(
        "input_data,expected",
        [
            (b"2024-01-15 10:30:00+00", datetime(2024, 1, 15, 10, 30, 0, tzinfo=UTC)),
            (b"200082-12-31 18:30:00+00", datetime.max.replace(tzinfo=UTC)),
            (b"infinity", datetime.max.replace(tzinfo=UTC)),
            (b"-infinity", datetime.min.replace(tzinfo=UTC)),
            (None, None),
        ],
    )
    def test_load_timestamptz(self, loader, input_data, expected):
        assert loader.load(input_data) == expected

    def test_clamped_values_are_utc_aware(self, loader):
        # timestamptz columns map to a UTC-aware Arrow type, so clamps must stay aware
        # to avoid mixing naive and aware datetimes in the same column.
        assert loader.load(b"200082-12-31 18:30:00+00").tzinfo is UTC


class TestSafeTimeLoader:
    @pytest.fixture
    def loader(self):
        return SafeTimeLoader(oid=1083)

    @pytest.mark.parametrize(
        "input_data,expected",
        [
            # Postgres allows 24:00:00 (end-of-day) but Python's time caps at 23 — clamp to max.
            (b"24:00:00", time.max),
            (b"24:00:00.000000", time.max),
            # Normal values are parsed unchanged.
            (b"00:00:00", time(0, 0, 0)),
            (b"13:45:30", time(13, 45, 30)),
            (b"13:45:30.123456", time(13, 45, 30, 123456)),
            (b"23:59:59.999999", time(23, 59, 59, 999999)),
        ],
    )
    def test_load_times(self, loader, input_data, expected):
        assert loader.load(input_data) == expected

    def test_non_hour_24_errors_still_propagate(self, loader):
        with pytest.raises(psycopg.DataError):
            loader.load(b"99:99:99")


class TestSafeTimetzLoader:
    @pytest.fixture
    def loader(self):
        return SafeTimetzLoader(oid=1266)

    @pytest.mark.parametrize(
        "input_data,expected",
        [
            (b"24:00:00+00", time.max.replace(tzinfo=UTC)),
            (b"24:00:00.000000+00", time.max.replace(tzinfo=UTC)),
            (b"24:00:00+05:30", time.max.replace(tzinfo=timezone(timedelta(hours=5, minutes=30)))),
            (b"24:00:00-08", time.max.replace(tzinfo=timezone(timedelta(hours=-8)))),
            (b"13:45:30+02", time(13, 45, 30, tzinfo=timezone(timedelta(hours=2)))),
        ],
    )
    def test_load_timetz(self, loader, input_data, expected):
        assert loader.load(input_data) == expected


class TestPostgresImplementationWiring:
    def test_source_exposes_postgres_implementation_singleton(self):
        source = PostgresSource()
        assert isinstance(source.get_implementation, PostgresImplementation)
        # Same instance across two PostgresSource constructions — module-level singleton.
        assert source.get_implementation is PostgresSource().get_implementation

    def test_get_incremental_filter_returns_filter_postgres_incremental_fields(self):
        impl = PostgresSource().get_implementation
        assert impl.get_incremental_filter() is filter_postgres_incremental_fields


class TestPostgresSourceNonRetryableErrors:
    @pytest.fixture
    def source(self):
        return PostgresSource()

    @pytest.mark.parametrize(
        "error_msg",
        [
            'OperationalError: connection failed: connection to server at "10.0.0.1", port 5432 failed: FATAL: MaxClientsInSessionMode: max clients reached',
            # Newer Supabase/Supavisor session-mode pooler wording for the same client-slot
            # exhaustion as "MaxClientsInSessionMode: max clients reached". The pooler has
            # momentarily run out of client slots (pool_size reached); it recovers as connections
            # free up, so a fresh attempt succeeds — must stay retryable.
            'OperationalError: connection failed: connection to server at "44.216.29.125", port 5432 failed: FATAL:  (EMAXCONNSESSION) max clients reached in session mode - max clients are limited to pool_size: 15',
            'OperationalError: connection failed: connection to server at "10.0.0.1", port 5432 failed: FATAL: remaining connection slots are reserved for roles with the SUPERUSER attribute',
            'OperationalError: connection failed: connection to server at "10.0.0.1", port 5432 failed: FATAL: too many connections for role "user"',
            # Mid-stream SSL/connection drops during schema discovery — the pooler culled an idle
            # connection or the socket died. A fresh attempt reconnects, so these must stay retryable.
            "consuming input failed: SSL connection has been closed unexpectedly",
            "the connection is lost",
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
            "OperationalError: [Errno -5] No address associated with hostname",
            "BaseSSHTunnelForwarderError: Could not establish session to SSH gateway",
            # Newer Supabase/Supavisor pooler wording for a missing tenant/user. The older
            # "Tenant or user not found connection to server" / "FATAL: Tenant or user not found"
            # patterns don't substring-match this, so it needs its own key.
            'connection failed: connection to server at "52.45.94.125", port 6543 failed: FATAL:  (ENOTFOUND) tenant/user postgres.hksbxxtlcfeyyalgveif not found',
            "ProtocolViolation: server login has been failing, cached error: connect timeout (server_login_retry)",
            "server login has been failing, cached error: connection refused (server_login_retry)",
        ],
    )
    def test_permanent_connection_errors_are_non_retryable(self, source, error_msg):
        non_retryable = source.get_non_retryable_errors()
        is_non_retryable = any(pattern in error_msg for pattern in non_retryable.keys())
        assert is_non_retryable, f"Permanent error should be non-retryable: {error_msg}"

    @pytest.mark.parametrize(
        "error_msg",
        [
            # Raw psycopg message (what the activity-level check sees via str(e)) when require_ssl=False
            # leaves the OperationalError unwrapped. The host/port are volatile; the alert text is stable.
            'connection failed: connection to server at "37.16.27.102", port 6432 failed: SSL error: tlsv1 alert no application protocol',
            'connection failed: connection to server at "10.0.0.1", port 5432 failed: SSL error: tlsv1 alert no application protocol',
            # Temporal-wrapped message (what the workflow-level check sees) — carries the class name.
            'OperationalError: connection failed: connection to server at "37.16.27.102", port 6432 failed: SSL error: tlsv1 alert no application protocol',
        ],
    )
    def test_tls_no_application_protocol_errors_are_non_retryable(self, source, error_msg):
        non_retryable = source.get_non_retryable_errors()
        is_non_retryable = any(pattern in error_msg for pattern in non_retryable.keys())
        assert is_non_retryable, f"TLS ALPN rejection error should be non-retryable: {error_msg}"

    def test_tls_no_application_protocol_returns_friendly_message(self, source):
        non_retryable = source.get_non_retryable_errors()
        error_msg = (
            'connection failed: connection to server at "37.16.27.102", port 6432 failed: '
            "SSL error: tlsv1 alert no application protocol"
        )
        friendly = [reason for pattern, reason in non_retryable.items() if pattern in error_msg and reason]
        assert friendly, "TLS ALPN rejection error should surface an actionable message"
        assert "host and port" in friendly[0]

    def test_supavisor_enotfound_tenant_user_uses_new_key(self, source):
        # The older tenant/user patterns don't cover the newer "(ENOTFOUND) tenant/user" wording,
        # so confirm it's specifically the new key that recognises this message.
        error_msg = (
            'connection failed: connection to server at "52.45.94.125", port 6543 failed: '
            "FATAL:  (ENOTFOUND) tenant/user postgres.hksbxxtlcfeyyalgveif not found"
        )
        non_retryable = source.get_non_retryable_errors()
        assert "(ENOTFOUND) tenant/user" in non_retryable
        assert "Tenant or user not found connection to server" not in error_msg
        assert "FATAL: Tenant or user not found" not in error_msg
        assert any(pattern in error_msg for pattern in non_retryable.keys())

    @pytest.mark.parametrize(
        "error_msg",
        [
            # Supabase Supavisor pooler wording when the tenant/user is gone (project paused/deleted
            # or pooler username changed). The id between "tenant/user" and "not found" is volatile.
            'connection failed: connection to server at "13.238.183.126", port 5432 failed: FATAL:  (ENOTFOUND) tenant/user readonly_user.yvpaylojqoditoupicws not found',
            'connection failed: connection to server at "44.216.29.125", port 6543 failed: FATAL:  (ENOTFOUND) tenant/user postgres.xysbwpayipjbkimdauqr not found',
            # The real production message repeats the line (newlines are normalized to spaces upstream).
            'connection failed: connection to server at "13.200.110.68", port 6543 failed: FATAL:  (ENOTFOUND) tenant/user postgres.yszohtdqidnoqckysyff not found connection to server at "13.200.110.68", port 6543 failed: FATAL:  (ENOTFOUND) tenant/user postgres.yszohtdqidnoqckysyff not found',
        ],
    )
    def test_missing_pooler_tenant_or_user_is_non_retryable(self, source, error_msg):
        non_retryable = source.get_non_retryable_errors()
        is_non_retryable = any(pattern in error_msg for pattern in non_retryable.keys())
        assert is_non_retryable, f"Missing pooler tenant/user error should be non-retryable: {error_msg}"

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
            'invalid input syntax for type integer: "1.5"',
            'InvalidTextRepresentation: invalid input syntax for type integer: "1.5"',
        ],
    )
    def test_non_integer_incremental_cursor_errors_are_non_retryable(self, source, error_msg):
        non_retryable = source.get_non_retryable_errors()
        is_non_retryable = any(pattern in error_msg for pattern in non_retryable.keys())
        assert is_non_retryable, f"Non-integer incremental cursor error should be non-retryable: {error_msg}"

    @pytest.mark.parametrize(
        "error_msg",
        [
            "Hit 30 successive SerializationFailure errors. Aborting.",
            "Exception: Hit 30 successive SerializationFailure errors. Aborting.",
        ],
    )
    def test_exhausted_recovery_conflict_retries_are_non_retryable(self, source, error_msg):
        non_retryable = source.get_non_retryable_errors()
        is_non_retryable = any(pattern in error_msg for pattern in non_retryable.keys())
        assert is_non_retryable, f"Exhausted recovery-conflict error should be non-retryable: {error_msg}"

    @pytest.mark.parametrize(
        "error_msg",
        [
            # Raw psycopg message (what the activity-level check sees via str(e)) — no class name.
            "permission denied for table brand",
            "permission denied for view posthog_areas",
            "permission denied for materialized view posthog_notifications",
            # Temporal-wrapped message (what the workflow-level check sees) — carries the class name.
            "InsufficientPrivilege: permission denied for table brand",
        ],
    )
    def test_permission_denied_errors_are_non_retryable(self, source, error_msg):
        non_retryable = source.get_non_retryable_errors()
        is_non_retryable = any(pattern in error_msg for pattern in non_retryable.keys())
        assert is_non_retryable, f"Permission-denied error should be non-retryable: {error_msg}"

    def test_permission_denied_returns_friendly_message(self, source):
        non_retryable = source.get_non_retryable_errors()
        error_msg = "permission denied for table brand"
        friendly = [reason for pattern, reason in non_retryable.items() if pattern in error_msg and reason]
        assert friendly, "Permission-denied error should surface an actionable message"
        assert "SELECT" in friendly[0]

    @pytest.mark.parametrize(
        "error_msg",
        [
            # Raw psycopg message (what the activity-level check sees via str(e)).
            'materialized view "mv_dayplan_blocks" has not been populated\nHINT:  Use the REFRESH MATERIALIZED VIEW command.',
            # Temporal-wrapped message (what the workflow-level check sees) — carries the class name.
            'ObjectNotInPrerequisiteState: materialized view "mv_dayplan_blocks" has not been populated',
        ],
    )
    def test_unpopulated_materialized_view_errors_are_non_retryable(self, source, error_msg):
        non_retryable = source.get_non_retryable_errors()
        is_non_retryable = any(pattern in error_msg for pattern in non_retryable.keys())
        assert is_non_retryable, f"Unpopulated materialized view error should be non-retryable: {error_msg}"

    def test_unpopulated_materialized_view_returns_friendly_message(self, source):
        non_retryable = source.get_non_retryable_errors()
        error_msg = 'materialized view "mv_dayplan_blocks" has not been populated'
        friendly = [reason for pattern, reason in non_retryable.items() if pattern in error_msg and reason]
        assert friendly, "Unpopulated materialized view error should surface an actionable message"
        assert "REFRESH MATERIALIZED VIEW" in friendly[0]

    @pytest.mark.parametrize(
        "error_msg",
        [
            "cannot call jsonb_each on a non-object",
            "InvalidParameterValue: cannot call jsonb_each on a non-object",
            "cannot call jsonb_each_text on a non-object",
            "InvalidParameterValue: cannot call jsonb_each_text on a non-object",
        ],
    )
    def test_jsonb_each_on_non_object_is_non_retryable(self, source, error_msg):
        non_retryable = source.get_non_retryable_errors()
        is_non_retryable = any(pattern in error_msg for pattern in non_retryable.keys())
        assert is_non_retryable, f"jsonb_each on non-object error should be non-retryable: {error_msg}"

    @pytest.mark.parametrize(
        "error_msg",
        [
            # A single recovery conflict is retried in-process; on its own it must stay retryable.
            "canceling statement due to conflict with recovery",
            "could not serialize access due to conflict with recovery",
            # The connection-terminating variant is retried by the setup phase the same way.
            "terminating connection due to conflict with recovery",
            # The connection-dropped abort is a separate, genuinely transient condition.
            "Hit 10 successive connection-dropped errors. Aborting.",
        ],
    )
    def test_recovery_conflict_related_transients_stay_retryable(self, source, error_msg):
        non_retryable = source.get_non_retryable_errors()
        is_non_retryable = any(pattern in error_msg for pattern in non_retryable.keys())
        assert not is_non_retryable, f"Transient error should remain retryable: {error_msg}"


class TestPostgresSourceSetupRecoveryConflictRetry:
    @staticmethod
    @contextmanager
    def _tunnel():
        yield ("localhost", 5432)

    def _make_failing_connection(self, error: BaseException) -> mock.MagicMock:
        cursor = mock.MagicMock()
        cursor.execute.side_effect = error
        cursor_cm = mock.MagicMock()
        cursor_cm.__enter__.return_value = cursor
        cursor_cm.__exit__.return_value = False
        connection = mock.MagicMock()
        connection.closed = False
        connection.cursor.return_value = cursor_cm
        connection.__enter__.return_value = connection
        # Must return falsy so the raised error propagates out of the `with` block.
        connection.__exit__.return_value = False
        return connection

    def _call_postgres_source(self):
        return postgres_source(
            tunnel=self._tunnel,
            user="u",
            password="p",
            database="db",
            sslmode="prefer",
            schema="public",
            table_names=["t"],
            should_use_incremental_field=False,
            logger=structlog.get_logger(),
            db_incremental_field_last_value=None,
        )

    def test_sustained_recovery_conflict_during_setup_aborts_non_retryably(self):
        err = psycopg.errors.SerializationFailure("terminating connection due to conflict with recovery")
        connection = self._make_failing_connection(err)

        with patch(
            "posthog.temporal.data_imports.sources.postgres.postgres.psycopg.connect",
            return_value=connection,
        ) as connect_mock:
            with patch("posthog.temporal.data_imports.sources.postgres.postgres.time.sleep"):
                with pytest.raises(Exception) as exc_info:
                    self._call_postgres_source()

        # Exhausting the in-process retries surfaces the message wired into NonRetryableErrors.
        assert "successive SerializationFailure errors. Aborting." in str(exc_info.value)
        # Each retry reconnects, so connect is called once per attempt.
        assert connect_mock.call_count == _MAX_SETUP_RECOVERY_CONFLICT_RETRIES

    def test_non_recovery_serialization_failure_during_setup_is_not_retried(self):
        # A serialization failure unrelated to standby recovery must propagate immediately —
        # the retry is scoped strictly to "conflict with recovery".
        err = psycopg.errors.SerializationFailure("could not serialize access due to concurrent update")
        connection = self._make_failing_connection(err)

        with patch(
            "posthog.temporal.data_imports.sources.postgres.postgres.psycopg.connect",
            return_value=connection,
        ) as connect_mock:
            with pytest.raises(psycopg.errors.SerializationFailure):
                self._call_postgres_source()

        assert connect_mock.call_count == 1

    def test_connection_dropped_while_opening_setup_connection_is_retried(self):
        # A transient drop while opening the setup connection ("server closed the connection
        # unexpectedly") is the same class of error the read path already recovers from. The setup
        # connect must retry in-process with bounded backoff instead of failing on the first drop.
        err = psycopg.OperationalError(
            'connection failed: connection to server at "3.151.121.165", port 5432 failed: '
            "server closed the connection unexpectedly"
        )

        with patch(
            "posthog.temporal.data_imports.sources.postgres.postgres.psycopg.connect",
            side_effect=err,
        ) as connect_mock:
            with patch("posthog.temporal.data_imports.sources.postgres.postgres.time.sleep"):
                with pytest.raises(psycopg.OperationalError):
                    self._call_postgres_source()

        # `_connect_with_dropped_retry` defaults to 5 attempts; before the fix the drop escaped on
        # the first connect (call_count == 1).
        assert connect_mock.call_count == 5

    def test_permanent_error_while_opening_setup_connection_is_not_retried(self):
        # A permanent connect failure (bad password) must not be retried by the dropped-connection
        # handler — it should propagate on the first attempt.
        err = psycopg.OperationalError(
            'connection to server at "10.0.0.1" failed: FATAL: password authentication failed for user "u"'
        )

        with patch(
            "posthog.temporal.data_imports.sources.postgres.postgres.psycopg.connect",
            side_effect=err,
        ) as connect_mock:
            with patch("posthog.temporal.data_imports.sources.postgres.postgres.time.sleep"):
                with pytest.raises(psycopg.OperationalError):
                    self._call_postgres_source()

        assert connect_mock.call_count == 1


class TestIsConnectionDroppedError:
    @pytest.mark.parametrize(
        "error",
        [
            psycopg.errors.ProtocolViolation("server conn crashed?"),
            psycopg.OperationalError("server closed the connection unexpectedly"),
            psycopg.OperationalError("connection to server was lost"),
            psycopg.OperationalError("connection to server was closed unexpectedly"),
            psycopg.OperationalError("consuming input failed: EOF detected"),
            psycopg.OperationalError("terminating connection due to administrator command"),
            psycopg.errors.ProtocolViolation("SERVER CONN CRASHED?"),
            # SQLSTATE 25P03: the source's idle_in_transaction_session_timeout culled our
            # backend mid-stream. psycopg maps this to InternalError, not OperationalError,
            # so it's detected by type alone — even with no message to match on.
            psycopg.errors.IdleInTransactionSessionTimeout("terminating connection due to idle-in-transaction timeout"),
            psycopg.errors.IdleInTransactionSessionTimeout(),
        ],
    )
    def test_connection_dropped_errors_are_detected(self, error):
        assert _is_connection_dropped_error(error) is True

    @pytest.mark.parametrize(
        "error",
        [
            psycopg.errors.SerializationFailure("could not serialize access due to conflict with recovery"),
            psycopg.errors.QueryCanceled("statement timeout"),
            psycopg.OperationalError("password authentication failed for user"),
            # Initial-connect failures embed "connection to server …" but are
            # permanent — they must not be misclassified as a recoverable drop.
            psycopg.OperationalError(
                'connection to server at "10.0.0.1" failed: FATAL: password authentication failed'
            ),
            psycopg.errors.UniqueViolation("duplicate key value violates unique constraint"),
            ValueError("server conn crashed?"),
            Exception("server conn crashed?"),
        ],
    )
    def test_unrelated_errors_are_not_detected(self, error):
        assert _is_connection_dropped_error(error) is False


class TestRaiseIfSetupConnectionBroken:
    """A connection dropped mid-discovery must surface as a retryable error, not the masked
    `ProgrammingError: Explicit commit() forbidden within a Transaction context` that psycopg's
    implicit `with connection:` exit-commit raises when a savepoint teardown leaks the
    transaction-nesting counter on a no-longer-OK connection."""

    def test_broken_connection_raises_retryable_dropped_error(self):
        connection = mock.MagicMock()
        connection.broken = True

        with pytest.raises(psycopg.OperationalError) as exc_info:
            _raise_if_setup_connection_broken(cast(Any, connection))

        # Classified as a transient drop, so the activity keeps retrying...
        assert _is_connection_dropped_error(exc_info.value) is True
        # ...and the message is not matched by any NonRetryableErrors substring.
        message = str(exc_info.value)
        assert not any(key in message for key in PostgresSource().get_non_retryable_errors())

    def test_healthy_connection_is_a_noop(self):
        connection = mock.MagicMock()
        connection.broken = False

        # A healthy connection must not raise.
        _raise_if_setup_connection_broken(cast(Any, connection))


class TestConnectWithDroppedRetry:
    @pytest.fixture
    def logger(self):
        return structlog.get_logger()

    def test_retries_dropped_connection_then_succeeds(self, logger):
        good_conn = mock.MagicMock()
        connect = mock.MagicMock(
            side_effect=[
                # The exact error surfaced in production: a mid-stream SSL EOF on
                # the reconnect that bootstraps offset-chunking recovery.
                psycopg.OperationalError("consuming input failed: SSL SYSCALL error: EOF detected"),
                psycopg.OperationalError("server closed the connection unexpectedly"),
                good_conn,
            ]
        )

        with patch("posthog.temporal.data_imports.sources.postgres.postgres.time.sleep"):
            result = _connect_with_dropped_retry(connect, logger, max_attempts=5)

        assert result is good_conn
        assert connect.call_count == 3

    def test_permanent_error_is_not_retried(self, logger):
        connect = mock.MagicMock(
            side_effect=psycopg.OperationalError(
                'connection to server at "10.0.0.1" failed: FATAL: password authentication failed'
            )
        )

        with patch("posthog.temporal.data_imports.sources.postgres.postgres.time.sleep"):
            with pytest.raises(psycopg.OperationalError):
                _connect_with_dropped_retry(connect, logger, max_attempts=5)

        assert connect.call_count == 1

    def test_gives_up_after_max_attempts(self, logger):
        connect = mock.MagicMock(
            side_effect=psycopg.OperationalError("consuming input failed: SSL SYSCALL error: EOF detected")
        )

        with patch("posthog.temporal.data_imports.sources.postgres.postgres.time.sleep"):
            with pytest.raises(psycopg.OperationalError):
                _connect_with_dropped_retry(connect, logger, max_attempts=3)

        assert connect.call_count == 3


# Redshift (and other Postgres-wire engines) report `client_encoding` as the legacy alias
# `UNICODE`, which psycopg3 can't decode — it raises `NotSupportedError: codec not available in
# Python: 'UNICODE'`. We pin the client encoding to UTF8 on connect to avoid the crash.
class TestConnectForcesUtf8ClientEncoding:
    def test_connect_pins_client_encoding_to_utf8(self):
        with patch("posthog.temporal.data_imports.sources.postgres.postgres.psycopg.connect") as connect_mock:
            _connect_to_postgres(
                host="redshift-cluster.example.com",
                port=5439,
                database="dev",
                user="user",
                password="password",
            )

        assert connect_mock.call_args.kwargs["options"] == FORCE_UTF8_CLIENT_ENCODING

    def test_caller_supplied_options_are_appended_after_utf8(self):
        with patch("posthog.temporal.data_imports.sources.postgres.postgres.psycopg.connect") as connect_mock:
            _connect_to_postgres(
                host="db.example.com",
                port=5432,
                database="postgres",
                user="user",
                password="password",
                options="-c statement_timeout=5000",
            )

        assert connect_mock.call_args.kwargs["options"] == f"{FORCE_UTF8_CLIENT_ENCODING} -c statement_timeout=5000"


# Transaction-mode poolers (Supabase Supavisor on :6543, PgBouncer transaction mode, AWS RDS Proxy)
# reject the libpq `options` startup parameter we send to pin client_encoding=UTF8. When they do, we
# drop `options` and retry rather than failing the connection.
class TestConnectOptionsStartupParamFallback:
    @pytest.mark.parametrize(
        "message,expected",
        [
            (
                'connection to server at "1.2.3.4", port 6543 failed: FATAL:  unsupported startup parameter: options',
                True,
            ),
            (
                "connection failed: FATAL:  Feature not supported: RDS Proxy currently "
                "doesn’t support command-line options.",
                True,
            ),
            ("password authentication failed for user", False),
            ("server closed the connection unexpectedly", False),
        ],
    )
    def test_detects_options_unsupported_message(self, message, expected):
        assert _is_options_startup_param_unsupported(psycopg.OperationalError(message)) is expected

    def test_non_operational_error_is_not_matched(self):
        assert _is_options_startup_param_unsupported(ValueError("unsupported startup parameter: options")) is False

    def test_retries_without_options_when_pooler_rejects_it(self):
        good_conn = mock.MagicMock()
        connect_mock = mock.MagicMock(
            side_effect=[
                psycopg.OperationalError("FATAL:  unsupported startup parameter: options"),
                good_conn,
            ]
        )

        with patch("posthog.temporal.data_imports.sources.postgres.postgres.psycopg.connect", connect_mock):
            result = _connect_with_options_fallback(host="db", options=FORCE_UTF8_CLIENT_ENCODING)

        assert result is good_conn
        assert connect_mock.call_count == 2
        # First attempt carries options, retry drops it entirely.
        assert connect_mock.call_args_list[0].kwargs["options"] == FORCE_UTF8_CLIENT_ENCODING
        assert "options" not in connect_mock.call_args_list[1].kwargs

    def test_does_not_retry_when_no_options_were_sent(self):
        connect_mock = mock.MagicMock(
            side_effect=psycopg.OperationalError("FATAL:  unsupported startup parameter: options")
        )

        with patch("posthog.temporal.data_imports.sources.postgres.postgres.psycopg.connect", connect_mock):
            with pytest.raises(psycopg.OperationalError):
                _connect_with_options_fallback(host="db")

        assert connect_mock.call_count == 1

    def test_unrelated_operational_error_is_not_retried(self):
        connect_mock = mock.MagicMock(side_effect=psycopg.OperationalError("password authentication failed for user"))

        with patch("posthog.temporal.data_imports.sources.postgres.postgres.psycopg.connect", connect_mock):
            with pytest.raises(psycopg.OperationalError):
                _connect_with_options_fallback(host="db", options=FORCE_UTF8_CLIENT_ENCODING)

        assert connect_mock.call_count == 1


class TestStatementTimeoutAsNonRetryable:
    @pytest.mark.parametrize(
        "should_use_incremental_field,incremental_field,expected_substr",
        [
            # Incremental syncs map the timeout to a non-retryable QueryTimeoutException.
            (True, "updated_at", "updated_at"),
            # Full-table syncs must re-raise the raw QueryCanceled so a fresh re-sync can
            # reorder rows; we only short-circuit incremental reads.
            (False, None, None),
        ],
    )
    def test_statement_timeout_mapping(self, should_use_incremental_field, incremental_field, expected_substr):
        result = _statement_timeout_as_non_retryable(
            psycopg.errors.QueryCanceled("canceling statement due to statement timeout"),
            should_use_incremental_field=should_use_incremental_field,
            incremental_field=incremental_field,
        )
        if expected_substr is None:
            assert result is None
        else:
            assert isinstance(result, QueryTimeoutException)
            assert expected_substr in str(result)

    @pytest.mark.parametrize(
        "error",
        [
            psycopg.errors.ProtocolViolation("server conn crashed?"),
            psycopg.OperationalError("server closed the connection unexpectedly"),
            psycopg.errors.SerializationFailure("due to conflict with recovery"),
            Exception("canceling statement due to statement timeout"),
        ],
    )
    def test_non_statement_timeout_errors_are_not_mapped(self, error):
        assert (
            _statement_timeout_as_non_retryable(
                error,
                should_use_incremental_field=True,
                incremental_field="updated_at",
            )
            is None
        )


class TestPostgresSourceForPipelineSchemaResolution:
    @pytest.fixture
    def source(self):
        return PostgresSource()

    def _make_inputs(self, schema_name: str):
        return mock.MagicMock(
            schema_id="00000000-0000-0000-0000-000000000000",
            schema_name=schema_name,
            should_use_incremental_field=False,
            incremental_field=None,
            incremental_field_type=None,
            db_incremental_field_last_value=None,
            team_id=1,
            logger=mock.MagicMock(),
        )

    def _make_config(self, schema: str | None = None):
        return mock.MagicMock(
            user="u",
            password="p",
            database="db",
            schema=schema,
        )

    def _make_schema_model(
        self,
        name: str,
        schema_metadata: dict | None = None,
        source_model=None,
        sync_type_config: dict | None = None,
        s3_folder_name: str | None = None,
    ):
        schema = mock.MagicMock()
        schema.name = name
        schema.id = "00000000-0000-0000-0000-000000000000"
        schema.is_cdc = False
        schema.cdc_mode = None
        schema.initial_sync_complete = True
        schema.enabled_columns = None
        schema.chunk_size_override = None
        schema.schema_metadata = schema_metadata
        schema.sync_type_config = sync_type_config or {}
        schema.s3_folder_name = s3_folder_name
        # MagicMock auto-attrs are truthy; pin the property to what the real model would resolve
        # (resolution itself is covered by warehouse_sources test_models).
        schema.resolved_s3_folder_name = s3_folder_name
        schema.source = source_model or mock.MagicMock()
        return schema

    def test_dotted_schema_name_without_metadata_routes_to_correct_source_schema(self, source):
        # Repro: row created before this PR has name="poblic.example_table" and no schema_metadata.
        # source_for_pipeline must not fall through to config.schema or "public" — that produces
        # `SELECT FROM "public"."poblic.example_table"`, an undefined relation.
        schema_model = self._make_schema_model("poblic.example_table", schema_metadata=None)
        inputs = self._make_inputs("poblic.example_table")
        config = self._make_config(schema=None)

        with (
            mock.patch(
                "products.warehouse_sources.backend.models.external_data_schema.ExternalDataSchema.objects"
            ) as objects_mock,
            mock.patch("posthog.temporal.data_imports.sources.postgres.source.postgres_source") as postgres_source_mock,
            mock.patch("posthog.temporal.data_imports.sources.postgres.source.source_requires_ssl", return_value=False),
            mock.patch.object(source, "make_ssh_tunnel_func", return_value=lambda: None),
        ):
            objects_mock.select_related.return_value.get.return_value = schema_model
            postgres_source_mock.return_value = mock.MagicMock()

            source.source_for_pipeline(config, inputs)

            assert postgres_source_mock.called, "postgres_source was not invoked"
            kwargs = postgres_source_mock.call_args.kwargs
            assert kwargs["schema"] == "poblic", f"expected schema='poblic', got {kwargs['schema']!r}"
            assert kwargs["table_names"] == ["example_table"], (
                f"expected table_names=['example_table'], got {kwargs['table_names']!r}"
            )

    def test_schema_metadata_wins_over_dotted_name_inference(self, source):
        # Metadata is the source of truth — explicit pin always beats name-splitting.
        schema_model = self._make_schema_model(
            "weird.name",
            schema_metadata={"source_schema": "real_schema", "source_table_name": "real_table"},
        )
        inputs = self._make_inputs("weird.name")
        config = self._make_config(schema=None)

        with (
            mock.patch(
                "products.warehouse_sources.backend.models.external_data_schema.ExternalDataSchema.objects"
            ) as objects_mock,
            mock.patch("posthog.temporal.data_imports.sources.postgres.source.postgres_source") as postgres_source_mock,
            mock.patch("posthog.temporal.data_imports.sources.postgres.source.source_requires_ssl", return_value=False),
            mock.patch.object(source, "make_ssh_tunnel_func", return_value=lambda: None),
        ):
            objects_mock.select_related.return_value.get.return_value = schema_model
            postgres_source_mock.return_value = mock.MagicMock()

            source.source_for_pipeline(config, inputs)
            kwargs = postgres_source_mock.call_args.kwargs
            assert kwargs["schema"] == "real_schema"
            assert kwargs["table_names"] == ["real_table"]

    def test_s3_folder_name_drives_response_name_so_delta_writes_to_legacy_path(self, source):
        # After `consolidate_postgres_legacy_rows` renames `example_table` → `public.example_table`,
        # the row carries `s3_folder_name="example_table"`. `validate_schema_and_update_table` uses
        # that key for `url_pattern`, so `SourceResponse.name` MUST also derive from the storage key
        # — otherwise Delta files land at `.../public__example_table/` while `DataWarehouseTable.url_pattern`
        # points at `.../example_table/` and HogQL reads from an empty location.
        from posthog.temporal.data_imports.naming_convention import NamingConvention

        schema_model = self._make_schema_model(
            "public.example_table",
            schema_metadata={"source_schema": "public", "source_table_name": "example_table"},
            s3_folder_name="example_table",
        )
        inputs = self._make_inputs("public.example_table")
        config = self._make_config(schema=None)

        with (
            mock.patch(
                "products.warehouse_sources.backend.models.external_data_schema.ExternalDataSchema.objects"
            ) as objects_mock,
            mock.patch("posthog.temporal.data_imports.sources.postgres.source.postgres_source") as postgres_source_mock,
            mock.patch("posthog.temporal.data_imports.sources.postgres.source.source_requires_ssl", return_value=False),
            mock.patch.object(source, "make_ssh_tunnel_func", return_value=lambda: None),
        ):
            response = mock.MagicMock()
            objects_mock.select_related.return_value.get.return_value = schema_model
            postgres_source_mock.return_value = response

            source.source_for_pipeline(config, inputs)

            assert response.name == NamingConvention.normalize_identifier("example_table"), (
                f"response.name must derive from s3_folder_name to keep Delta writes anchored to the "
                f"legacy folder; got {response.name!r}"
            )

    def test_response_name_uses_schema_name_when_no_storage_key(self, source):
        # New (non-migrated) rows have no s3_folder_name — response.name falls back to the row's
        # current name so the Delta path matches `url_pattern` (also derived from the row's name).
        from posthog.temporal.data_imports.naming_convention import NamingConvention

        schema_model = self._make_schema_model(
            "poblic.new_table",
            schema_metadata={"source_schema": "poblic", "source_table_name": "new_table"},
            sync_type_config={},
        )
        inputs = self._make_inputs("poblic.new_table")
        config = self._make_config(schema=None)

        with (
            mock.patch(
                "products.warehouse_sources.backend.models.external_data_schema.ExternalDataSchema.objects"
            ) as objects_mock,
            mock.patch("posthog.temporal.data_imports.sources.postgres.source.postgres_source") as postgres_source_mock,
            mock.patch("posthog.temporal.data_imports.sources.postgres.source.source_requires_ssl", return_value=False),
            mock.patch.object(source, "make_ssh_tunnel_func", return_value=lambda: None),
        ):
            response = mock.MagicMock()
            objects_mock.select_related.return_value.get.return_value = schema_model
            postgres_source_mock.return_value = response

            source.source_for_pipeline(config, inputs)

            assert response.name == NamingConvention.normalize_identifier("poblic.new_table")

    def test_unqualified_name_falls_back_to_config_schema(self, source):
        # Legacy row "example_table" with no metadata + config.schema="public" → ("public", "example_table").
        schema_model = self._make_schema_model("example_table", schema_metadata=None)
        inputs = self._make_inputs("example_table")
        config = self._make_config(schema="public")

        with (
            mock.patch(
                "products.warehouse_sources.backend.models.external_data_schema.ExternalDataSchema.objects"
            ) as objects_mock,
            mock.patch("posthog.temporal.data_imports.sources.postgres.source.postgres_source") as postgres_source_mock,
            mock.patch("posthog.temporal.data_imports.sources.postgres.source.source_requires_ssl", return_value=False),
            mock.patch.object(source, "make_ssh_tunnel_func", return_value=lambda: None),
        ):
            objects_mock.select_related.return_value.get.return_value = schema_model
            postgres_source_mock.return_value = mock.MagicMock()

            source.source_for_pipeline(config, inputs)
            kwargs = postgres_source_mock.call_args.kwargs
            assert kwargs["schema"] == "public"
            assert kwargs["table_names"] == ["example_table"]

    def test_validate_credentials_for_access_method_allows_blank_schema_for_warehouse_imports(self, source):
        # Multi-schema parity: warehouse mode now accepts blank `schema` (browse-all) just like
        # direct mode. Each `ExternalDataSchema` row pins its own `(schema, table)` in metadata.
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
            valid, error = source.validate_credentials_for_access_method(config, team_id=1, access_method="warehouse")

        assert valid is True
        assert error is None
        validate_credentials.assert_called_once_with(config, 1, schema_name=None)

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


class TestValidateCredentialsErrorMapping:
    @pytest.fixture
    def source(self):
        return PostgresSource()

    @pytest.fixture
    def config(self, source):
        return source.parse_config(
            {
                "host": "db.example.com",
                "port": 5432,
                "database": "postgres",
                "user": "postgres",
                "password": "postgres",
                "schema": "public",
            }
        )

    @pytest.mark.parametrize(
        "error_msg, expected",
        [
            (
                'connection failed: connection to server at "1.2.3.4", port 5432 failed: '
                "error received from server in SCRAM exchange: Wrong password",
                "Invalid user or password",
            ),
            (
                'connection failed: connection to server at "1.2.3.4", port 5432 failed: '
                "FATAL:  the database system is starting up",
                "Your database is starting up or recovering. Wait a moment and try again.",
            ),
            (
                'connection failed: connection to server at "1.2.3.4", port 5432 failed: '
                "server does not support SSL, but SSL was required",
                "SSL/TLS connection is required but your database does not support it. "
                "Please enable SSL/TLS on your PostgreSQL server.",
            ),
            (
                "consuming input failed: SSL connection has been closed unexpectedly",
                "The SSL/TLS connection to your database was closed unexpectedly. "
                "Check your database's SSL configuration and that the port is correct.",
            ),
            (
                'connection failed: connection to server at "127.0.0.1", port 43185 failed: '
                "server closed the connection unexpectedly\n\tThis probably means the server terminated abnormally\n"
                "\tbefore or while processing the request.",
                "Your database closed the connection unexpectedly while connecting. This usually means the host "
                "or port is wrong, the server requires SSL/TLS, or a connection pooler, firewall, or SSH tunnel "
                "dropped the connection. Check your host, port, and SSL settings.",
            ),
            # Unmapped errors fall back to the generic message.
            (
                "some brand new failure",
                "Could not connect to Postgres. Please check all connection details are valid.",
            ),
        ],
    )
    def test_operational_errors_map_to_friendly_messages(self, source, config, error_msg, expected):
        with (
            mock.patch.object(source, "ssh_tunnel_is_valid", return_value=(True, None)),
            mock.patch.object(source, "is_database_host_valid", return_value=(True, None)),
            mock.patch.object(source, "get_schemas", side_effect=psycopg.OperationalError(error_msg)),
        ):
            valid, error = source.validate_credentials(config, team_id=1)

        assert valid is False
        assert error == expected


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

    @pytest.mark.parametrize(
        "selected_schema,requested_name,fetchall_results,expected_keys",
        [
            # Qualified lookup against a schema that's keyed unqualified (config.schema set).
            # This is the multi-schema migration scenario: row name was rewritten to
            # `public.tracking_link` while the source still has `schema="public"` configured.
            (
                "public",
                "public.tracking_link",
                (
                    [("public", "tracking_link")],
                    [("public", "tracking_link", "id", "integer", "NO", 1)],
                ),
                {"public.tracking_link"},
            ),
            # Unqualified lookup against an unqualified keyspace — the legacy path.
            (
                "public",
                "tracking_link",
                (
                    [("public", "tracking_link")],
                    [("public", "tracking_link", "id", "integer", "NO", 1)],
                ),
                {"tracking_link"},
            ),
            # Qualified lookup against a qualified keyspace (no config.schema, multi-schema mode).
            (
                "",
                "public.tracking_link",
                (
                    [("public", "tracking_link")],
                    [("public", "tracking_link", "id", "integer", "NO", 1)],
                ),
                {"public.tracking_link"},
            ),
        ],
    )
    def test_get_schemas_accepts_qualified_and_unqualified_names(
        self, selected_schema, requested_name, fetchall_results, expected_keys
    ):
        connection = self._mock_connection(*fetchall_results)

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
                schema=selected_schema,
                names=[requested_name],
            )

        assert set(schemas.keys()) == expected_keys

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


class TestPostgresSourceGetSchemasDegradesGracefully:
    @pytest.fixture
    def source(self):
        return PostgresSource()

    def _config(self):
        return mock.MagicMock(user="u", password="p", database="db", schema="", ssh_tunnel=None)

    @pytest.mark.parametrize(
        "exc",
        [
            psycopg.errors.OutOfMemory(
                'out of memory\nDETAIL:  Failed on request of size 2048 in memory context "ExecutorState".'
            ),
            psycopg.OperationalError("connection refused"),
            Exception("unexpected error"),
        ],
    )
    def test_foreign_key_discovery_failure_does_not_break_schema_listing(self, source, exc):
        # A failing foreign-key lookup (e.g. the source DB OOMs on the information_schema join)
        # must degrade to empty foreign keys, not take down the whole schema listing.
        discovered = {
            "public.users": PostgresDiscoveredSchema(
                source_catalog=None,
                source_schema="public",
                source_table_name="users",
                columns=[("id", "integer", False)],
            )
        }

        tunnel_cm = mock.MagicMock()
        tunnel_cm.__enter__.return_value = ("localhost", 5432)
        tunnel_cm.__exit__.return_value = None

        with (
            mock.patch.object(source, "with_ssh_tunnel", return_value=tunnel_cm),
            mock.patch(
                "posthog.temporal.data_imports.sources.postgres.source.get_postgres_schemas",
                return_value=discovered,
            ),
            mock.patch(
                "posthog.temporal.data_imports.sources.postgres.source.get_postgres_foreign_keys",
                side_effect=exc,
            ),
            # PK/index discovery opens its own connection; let it fail so the test needs no real DB.
            # That path is already guarded and defaults gracefully.
            mock.patch(
                "posthog.temporal.data_imports.sources.postgres.source.pg_connection",
                side_effect=psycopg.OperationalError("no db in test"),
            ),
        ):
            schemas = source.get_schemas(self._config(), team_id=1)

        assert len(schemas) == 1
        assert schemas[0].name == "public.users"
        assert schemas[0].foreign_keys == []

    def test_metadata_connection_failure_degrades_quietly_without_capturing(self, source):
        # The PK/index/RLS metadata connection is opened separately from schema discovery and is
        # prone to transient drops (commonly an SSH-tunnel hiccup raising "server closed the
        # connection unexpectedly"). Schema discovery already succeeded, so this must degrade quietly:
        # surface the schema listing and DON'T flood error tracking with a captured exception.
        discovered = {
            "public.users": PostgresDiscoveredSchema(
                source_catalog=None,
                source_schema="public",
                source_table_name="users",
                columns=[("id", "integer", False)],
            )
        }

        tunnel_cm = mock.MagicMock()
        tunnel_cm.__enter__.return_value = ("localhost", 5432)
        tunnel_cm.__exit__.return_value = None

        connection_dropped = psycopg.OperationalError(
            'connection failed: connection to server at "127.0.0.1", port 37761 failed: '
            "server closed the connection unexpectedly\n\tThis probably means the server terminated "
            "abnormally\n\tbefore or while processing the request."
        )

        with (
            mock.patch.object(source, "with_ssh_tunnel", return_value=tunnel_cm),
            mock.patch(
                "posthog.temporal.data_imports.sources.postgres.source.get_postgres_schemas",
                return_value=discovered,
            ),
            mock.patch(
                "posthog.temporal.data_imports.sources.postgres.source.get_postgres_foreign_keys",
                return_value={},
            ),
            mock.patch(
                "posthog.temporal.data_imports.sources.postgres.source.pg_connection",
                side_effect=connection_dropped,
            ),
            mock.patch("posthog.temporal.data_imports.sources.postgres.source.capture_exception") as mock_capture,
        ):
            schemas = source.get_schemas(self._config(), team_id=1)

        assert len(schemas) == 1
        assert schemas[0].name == "public.users"
        # Best-effort metadata is dropped, but the listing survives and nothing is captured.
        assert schemas[0].supports_cdc is False
        mock_capture.assert_not_called()

    def test_primary_key_discovery_failure_degrades_without_capturing_exception(self, source):
        # Some Postgres-wire-compatible engines reject our pg_catalog PK query (e.g. a
        # DuckDB/DuckLake backend can't bind `ANY(indkey)` and raises the binder error
        # below). PK discovery is best-effort and already falls back to no-CDC, so the
        # failure must be logged, not flooded into error tracking as a captured exception.
        discovered = {
            "public.users": PostgresDiscoveredSchema(
                source_catalog=None,
                source_schema="public",
                source_table_name="users",
                columns=[("id", "integer", False)],
            )
        }

        tunnel_cm = mock.MagicMock()
        tunnel_cm.__enter__.return_value = ("localhost", 5432)
        tunnel_cm.__exit__.return_value = None

        conn_cm = mock.MagicMock()
        conn_cm.__enter__.return_value = mock.MagicMock()
        conn_cm.__exit__.return_value = None

        unnest_error = psycopg.errors.InternalError_(
            "flight execute: rpc error: code = InvalidArgument desc = failed to prepare query: "
            "Binder Error: UNNEST not supported here"
        )

        with (
            mock.patch.object(source, "with_ssh_tunnel", return_value=tunnel_cm),
            mock.patch(
                "posthog.temporal.data_imports.sources.postgres.source.get_postgres_schemas",
                return_value=discovered,
            ),
            mock.patch(
                "posthog.temporal.data_imports.sources.postgres.source.get_postgres_foreign_keys",
                return_value={},
            ),
            mock.patch(
                "posthog.temporal.data_imports.sources.postgres.source.pg_connection",
                return_value=conn_cm,
            ),
            mock.patch(
                "posthog.temporal.data_imports.sources.postgres.source.get_primary_key_columns",
                side_effect=unnest_error,
            ),
            mock.patch(
                "posthog.temporal.data_imports.sources.postgres.source.get_leading_index_columns",
                return_value={"users": set()},
            ),
            mock.patch(
                "posthog.temporal.data_imports.sources.postgres.source._rls_active_from_conn",
                return_value={},
            ),
            mock.patch("posthog.temporal.data_imports.sources.postgres.source.capture_exception") as mock_capture,
        ):
            schemas = source.get_schemas(self._config(), team_id=1)

        assert len(schemas) == 1
        assert schemas[0].name == "public.users"
        # PK discovery failed, so CDC must not be advertised — but the listing still succeeds.
        assert schemas[0].supports_cdc is False
        # The handled, best-effort failure must not be captured as an exception.
        mock_capture.assert_not_called()


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

    @pytest.mark.parametrize(
        "case_name,enabled_columns,primary_keys,should_use_incremental,incremental_field,incremental_type,last_value,must_contain,must_not_contain,ordered",
        [
            (
                "explicit_list_includes_pk",
                ["email", "name"],
                ["id"],
                False,
                None,
                None,
                None,
                ['"email"', '"name"', '"id"'],
                ["SELECT *"],
                None,
            ),
            (
                "preserves_user_order_pk_appended",
                ["zeta", "alpha"],
                ["id"],
                False,
                None,
                None,
                None,
                [],
                None,
                ['"zeta"', '"alpha"', '"id"'],
            ),
            (
                "includes_incremental_field",
                ["payload"],
                ["id"],
                True,
                "updated_at",
                IncrementalFieldType.Timestamp,
                "2024-01-01",
                ['"payload"', '"updated_at"', '"id"'],
                None,
                None,
            ),
            (
                "none_is_select_star",
                None,
                ["id"],
                False,
                None,
                None,
                None,
                ["SELECT *"],
                None,
                None,
            ),
            (
                "empty_keeps_only_pks_and_incremental",
                [],
                ["id"],
                False,
                None,
                None,
                None,
                ['"id"'],
                ["SELECT *"],
                None,
            ),
            # Guard against an invalid `SELECT  FROM` when no columns can be retained.
            (
                "empty_with_no_pks_or_incremental_falls_back_to_star",
                [],
                None,
                False,
                None,
                None,
                None,
                ["SELECT *"],
                None,
                None,
            ),
        ],
    )
    def test_enabled_columns_projection(
        self,
        case_name,
        enabled_columns,
        primary_keys,
        should_use_incremental,
        incremental_field,
        incremental_type,
        last_value,
        must_contain,
        must_not_contain,
        ordered,
    ):
        query = _build_query(
            "public",
            "events" if should_use_incremental else "users",
            should_use_incremental,
            "table",
            incremental_field,
            incremental_type,
            last_value,
            enabled_columns=enabled_columns,
            primary_keys=primary_keys,
        )
        rendered = self._render(query)
        for substring in must_contain or []:
            assert substring in rendered, f"[{case_name}] expected {substring!r} in {rendered!r}"
        for substring in must_not_contain or []:
            assert substring not in rendered, f"[{case_name}] expected {substring!r} NOT in {rendered!r}"
        if ordered:
            positions = [rendered.index(s) for s in ordered]
            assert positions == sorted(positions), f"[{case_name}] expected {ordered} in order in {rendered!r}"

    @pytest.mark.parametrize(
        "field_type,last_value,expected_operator",
        [
            # Date cursors must be inclusive — saving cursor='2026-05-13' and re-querying with
            # `>` skips every row that lands on 2026-05-13 after the cursor advanced.
            (IncrementalFieldType.Date, date(2026, 5, 13), ">="),
            (IncrementalFieldType.DateTime, datetime(2026, 5, 13, 1, 36, tzinfo=UTC), ">"),
            (IncrementalFieldType.Timestamp, datetime(2026, 5, 13, 1, 36, tzinfo=UTC), ">"),
            (IncrementalFieldType.Integer, 100, ">"),
        ],
    )
    def test_operator_matches_field_type(self, field_type, last_value, expected_operator):
        query = _build_query("public", "events", True, "table", "cursor", field_type, last_value)
        rendered = self._render(query)
        assert f'"cursor" {expected_operator} ' in rendered
        # The other operator never appears for the cursor column.
        wrong = ">" if expected_operator == ">=" else ">="
        assert f'"cursor" {wrong} ' not in rendered

    @pytest.mark.parametrize(
        "field_type,last_value,expected_operator",
        [
            (IncrementalFieldType.Date, date(2026, 5, 13), ">="),
            (IncrementalFieldType.DateTime, datetime(2026, 5, 13, 1, 36, tzinfo=UTC), ">"),
            (IncrementalFieldType.Integer, 100, ">"),
        ],
    )
    def test_count_query_operator_matches_field_type(self, field_type, last_value, expected_operator):
        query = _build_count_query("public", "events", True, "cursor", field_type, last_value)
        rendered = self._render(query)
        assert f'"cursor" {expected_operator} ' in rendered

    def test_windowed_mode_keeps_exclusive_lower_bound_for_date(self):
        # iterate_date_windows feeds previous_hi as next_lo; `>=` would re-fetch every
        # boundary date inside one run, so the upper_bound_inclusive path must stay `>`.
        query = _build_query(
            "public",
            "events",
            True,
            "table",
            "cursor",
            IncrementalFieldType.Date,
            date(2026, 5, 13),
            upper_bound_inclusive=date(2026, 5, 14),
        )
        rendered = self._render(query)
        assert '"cursor" > ' in rendered
        assert '"cursor" >= ' not in rendered


class TestBuildPartitionQuery:
    def _render(self, composed: sql.Composed) -> str:
        return composed.as_string()

    def test_full_refresh_targets_child_relation(self):
        query = build_partition_query(
            "public",
            "events_2026_01",
            should_use_incremental_field=False,
            incremental_field=None,
            incremental_field_type=None,
            db_incremental_field_last_value=None,
        )
        rendered = self._render(query)
        assert '"public"."events_2026_01"' in rendered
        assert "WHERE" not in rendered

    def test_incremental_applies_cursor_filter(self):
        query = build_partition_query(
            "public",
            "events_2026_01",
            should_use_incremental_field=True,
            incremental_field="created_at",
            incremental_field_type=IncrementalFieldType.Timestamp,
            db_incremental_field_last_value="2026-01-15",
        )
        rendered = self._render(query)
        assert '"public"."events_2026_01"' in rendered
        assert '"created_at" > ' in rendered
        assert "'2026-01-15'" in rendered
        assert "ORDER BY" in rendered

    def test_incremental_raises_without_field(self):
        with pytest.raises(ValueError, match="incremental_field and incremental_field_type can't be None"):
            build_partition_query(
                "public",
                "events_2026_01",
                should_use_incremental_field=True,
                incremental_field=None,
                incremental_field_type=None,
                db_incremental_field_last_value=None,
            )

    @pytest.mark.parametrize(
        "field_type,last_value,expected_operator",
        [
            (IncrementalFieldType.Date, date(2026, 5, 13), ">="),
            (IncrementalFieldType.DateTime, datetime(2026, 5, 13, 1, 36, tzinfo=UTC), ">"),
            (IncrementalFieldType.Integer, 100, ">"),
        ],
    )
    def test_operator_matches_field_type(self, field_type, last_value, expected_operator):
        query = build_partition_query(
            "public",
            "events_2026_01",
            should_use_incremental_field=True,
            incremental_field="cursor",
            incremental_field_type=field_type,
            db_incremental_field_last_value=last_value,
        )
        rendered = self._render(query)
        assert f'"cursor" {expected_operator} ' in rendered


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


@pytest.fixture
def autocommit_pg_connection():
    # Raw autocommit connection to the test DB — mirrors how discovery connects in production
    # (no shared transaction). The default django_db cursor runs inside a transaction and can't
    # exercise the isolation path.
    sd = django_connection.settings_dict
    conn = psycopg.connect(
        host=sd["HOST"] or None,
        port=sd["PORT"] or None,
        dbname=sd["NAME"],
        user=sd["USER"] or None,
        password=sd["PASSWORD"] or None,
        autocommit=True,
    )
    try:
        yield conn
    finally:
        conn.close()


class TestGetTableChunkSize:
    @pytest.mark.django_db
    def test_failing_probe_isolated_by_autocommit(self, autocommit_pg_connection):
        # A failing probe falls back to DEFAULT_CHUNK_SIZE and, under autocommit, doesn't poison
        # the connection for later probes.
        logger = structlog.get_logger()
        with autocommit_pg_connection.cursor() as cursor:
            inner_query = sql.SQL("SELECT * FROM does_not_exist_chunk_probe").format()

            chunk_size = _get_table_chunk_size(cast(Any, cursor), inner_query, logger)
            assert chunk_size == DEFAULT_CHUNK_SIZE

            cursor.execute("SELECT 1")
            assert cursor.fetchone()[0] == 1

    @pytest.mark.django_db
    def test_statement_timeout_falls_back_without_poisoning_transaction(self):
        # The estimation query wraps the sample in octet_length(t::text), which can exceed the
        # source's statement_timeout on tables whose rows trigger slow validator functions. A
        # cancelled probe must degrade to DEFAULT_CHUNK_SIZE, not crash the whole import — the
        # streaming read loop has its own dedicated QueryCanceled handling.
        logger = structlog.get_logger()

        with django_connection.cursor() as dj_cursor:
            # Tight timeout + a deliberately slow probe reproduces a real QueryCanceled.
            dj_cursor.execute("SET LOCAL statement_timeout = '100ms'")
            inner_query = sql.SQL("SELECT pg_sleep(3) AS c").format()

            chunk_size = _get_table_chunk_size(cast(Any, dj_cursor), inner_query, logger)
            assert chunk_size == DEFAULT_CHUNK_SIZE

            # Savepoint rollback leaves the connection usable for the rest of setup.
            dj_cursor.execute("SELECT 1")
            assert dj_cursor.fetchone()[0] == 1


class TestGetRowsToSync:
    # Mirrors a misconfigured incremental field: COUNT(*) over a column that doesn't exist.
    _FAILING_COUNT_QUERY = sql.SQL("SELECT COUNT(*) FROM {table} WHERE {col} > 0").format(
        table=sql.Identifier("information_schema", "tables"),
        col=sql.Identifier("does_not_exist_count_col"),
    )

    @pytest.mark.django_db
    def test_failing_count_query_falls_back_to_zero_without_capturing(self):
        logger = structlog.get_logger()

        with django_connection.cursor() as dj_cursor:
            with patch("posthog.temporal.data_imports.sources.postgres.postgres.capture_exception") as mock_capture:
                rows = _get_rows_to_sync(cast(Any, dj_cursor), self._FAILING_COUNT_QUERY, logger)

        # Best-effort estimate falls back to 0 and never reports the handled failure.
        assert rows == 0
        mock_capture.assert_not_called()

    @pytest.mark.django_db
    def test_failing_count_isolated_by_autocommit(self, autocommit_pg_connection):
        # Regression for the reported incident: a read-replica recovery conflict cancels the
        # rows-to-sync COUNT(*). Under autocommit the failure stays contained — returns 0 and
        # leaves the connection usable — instead of poisoning a shared transaction.
        logger = structlog.get_logger()
        with autocommit_pg_connection.cursor() as cursor:
            assert _get_rows_to_sync(cast(Any, cursor), self._FAILING_COUNT_QUERY, logger) == 0

            cursor.execute("SELECT 1")
            assert cursor.fetchone()[0] == 1

    def test_temp_file_limit_error_still_raises(self):
        logger = structlog.get_logger()

        cursor = mock.MagicMock()
        cursor.execute.side_effect = Exception("temporary file size exceeds temp_file_limit (1048576kB)")
        count_query = _build_count_query("public", "users", False, None, None, None)

        with patch("posthog.temporal.data_imports.sources.postgres.postgres.capture_exception") as mock_capture:
            with pytest.raises(TemporaryFileSizeExceedsLimitException):
                _get_rows_to_sync(cast(Any, cursor), count_query, logger)

        # The temp-file signal is actionable, so it propagates rather than being swallowed.
        mock_capture.assert_not_called()


class TestPartitionedTableChunkSizing:
    """Incremental reads use per-child partition queries; no parent FETCH chunk cap."""

    def test_no_partitioned_fetch_cap_exported(self) -> None:
        assert not hasattr(partitioned_tables_pkg, "PARTITIONED_TABLE_MAX_CHUNK_SIZE")
        assert "PARTITIONED_TABLE_MAX_CHUNK_SIZE" not in partitioned_tables_pkg.__all__


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

    def test_missing_table_falls_back_to_none_without_capturing(self):
        # The selected table was dropped/renamed before this best-effort probe, so psycopg raises
        # UndefinedTable (42P01). The real extraction query surfaces "does not exist" through the
        # non-retryable path, so this helper must degrade quietly (None) instead of flooding error
        # tracking with a handled duplicate.
        logger = structlog.get_logger()

        cursor = mock.MagicMock()
        cursor.execute.side_effect = psycopg.errors.UndefinedTable('relation "public.store_source" does not exist')

        with patch("posthog.temporal.data_imports.sources.postgres.postgres.capture_exception") as mock_capture:
            result = _get_partition_settings(cast(Any, cursor), "public", "store_source", logger, is_partitioned=False)

        assert result is None
        mock_capture.assert_not_called()

    def test_reuses_passed_is_partitioned_flag(self):
        # When the caller already knows the table is partitioned, skip re-detecting it.
        logger = structlog.get_logger()
        cursor = mock.MagicMock()
        sentinel = object()

        with (
            patch("posthog.temporal.data_imports.sources.postgres.postgres._is_partitioned_table") as mock_detect,
            patch(
                "posthog.temporal.data_imports.sources.postgres.postgres._get_partition_settings_for_partitioned_table",
                return_value=sentinel,
            ) as mock_partitioned,
        ):
            result = _get_partition_settings(cast(Any, cursor), "public", "t", logger, is_partitioned=True)

        mock_detect.assert_not_called()
        mock_partitioned.assert_called_once()
        assert result is sentinel

    def test_recovery_conflict_returns_none_without_capturing(self):
        # Regression: a read-replica recovery conflict cancels the best-effort sizing query.
        # It's transient and the row-streaming reader retries it in-process, so degrade to None
        # without flooding error tracking with a handled condition.
        logger = structlog.get_logger()
        cursor = mock.MagicMock()
        cursor.execute.side_effect = psycopg.errors.SerializationFailure(
            "canceling statement due to conflict with recovery"
        )

        with patch("posthog.temporal.data_imports.sources.postgres.postgres.capture_exception") as capture_mock:
            result = _get_partition_settings(cast(Any, cursor), "public", "t", logger, is_partitioned=False)

        assert result is None
        capture_mock.assert_not_called()

    @pytest.mark.django_db
    def test_failing_sizing_query_falls_back_to_none_without_capturing(self):
        logger = structlog.get_logger()

        # The sizing query runs against a table that doesn't exist — stands in for an
        # upstream/source-side failure (e.g. a misbehaving extension index on the source DB)
        # that is already tolerated by falling back to default partition settings.
        with django_connection.cursor() as dj_cursor:
            with patch("posthog.temporal.data_imports.sources.postgres.postgres.capture_exception") as mock_capture:
                result = _get_partition_settings(cast(Any, dj_cursor), "public", "does_not_exist_ps_table", logger)

        # Best-effort sizing falls back to None and never reports the handled failure.
        assert result is None
        mock_capture.assert_not_called()

    @pytest.mark.parametrize(
        "exc",
        [
            # Direct read-replica recovery conflict on the sizing query.
            psycopg.errors.SerializationFailure("canceling statement due to conflict with recovery"),
            # Downstream symptom: an earlier best-effort query in this transaction hit the transient
            # condition above and left it in INERROR, so the sizing query fails with this instead.
            psycopg.errors.InFailedSqlTransaction(
                "current transaction is aborted, commands ignored until end of transaction block"
            ),
        ],
    )
    def test_handled_transient_errors_return_none_without_capturing(self, exc):
        # Both are handled, transient conditions that resurface (and are classified) via the real
        # extraction query, so partition sizing must degrade to None without flooding error tracking.
        logger = structlog.get_logger()
        cursor = mock.MagicMock()
        cursor.execute.side_effect = exc

        with patch("posthog.temporal.data_imports.sources.postgres.postgres.capture_exception") as capture_mock:
            result = _get_partition_settings(cast(Any, cursor), "public", "t", logger, is_partitioned=False)

        assert result is None
        capture_mock.assert_not_called()

    def test_temp_file_limit_error_still_raises(self):
        logger = structlog.get_logger()

        cursor = mock.MagicMock()
        cursor.execute.side_effect = Exception("temporary file size exceeds temp_file_limit (1048576kB)")

        with patch("posthog.temporal.data_imports.sources.postgres.postgres.capture_exception") as mock_capture:
            with pytest.raises(TemporaryFileSizeExceedsLimitException):
                _get_partition_settings(cast(Any, cursor), "public", "users", logger)

        # The temp-file signal is actionable, so it propagates rather than being swallowed.
        mock_capture.assert_not_called()


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


class TestGetLeadingIndexColumns:
    """Unit tests for the leading-index-column helper used to flag unindexed
    incremental fields in the source-setup wizard. The helper queries
    ``pg_index``/``pg_attribute``; we mock the cursor to verify that:
    - rows are bucketed by table
    - tables in the input list with no rows return empty sets (so the UI
      warning fires for tables without any indexes)
    - empty input is short-circuited
    """

    def _mock_connection(self, fetched_rows: list[tuple[str, str]]):
        cursor = mock.MagicMock()
        cursor.__iter__.return_value = iter(fetched_rows)

        cursor_context = mock.MagicMock()
        cursor_context.__enter__.return_value = cursor
        cursor_context.__exit__.return_value = None

        connection = mock.MagicMock()
        connection.cursor.return_value = cursor_context
        return connection, cursor

    def test_groups_columns_by_table(self):
        connection, _ = self._mock_connection(
            [
                ("orders", "created_at"),
                ("orders", "id"),
                ("users", "id"),
            ]
        )
        result = get_leading_index_columns(connection, "public", ["orders", "users", "logs"])
        assert result == {
            "orders": {"created_at", "id"},
            "users": {"id"},
        }
        assert "logs" not in result  # caller distinguishes "no index" via missing key

    def test_returns_empty_dict_for_empty_input(self):
        # No connection cursor should be opened when there are no tables.
        connection = mock.MagicMock()
        result = get_leading_index_columns(connection, "public", [])
        assert result == {}
        connection.cursor.assert_not_called()

    def test_returns_none_when_query_raises(self):
        # Permission errors on system catalogs (rare, but possible with
        # restricted roles) must not leak out — the caller defaults to
        # `is_indexed=True` and skips the warning when discovery fails.
        connection = mock.MagicMock()
        cursor = mock.MagicMock()
        cursor.execute.side_effect = Exception("permission denied for table pg_index")

        cursor_context = mock.MagicMock()
        cursor_context.__enter__.return_value = cursor
        cursor_context.__exit__.return_value = None
        connection.cursor.return_value = cursor_context

        result = get_leading_index_columns(connection, "public", ["orders"])
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

    def test_handles_naive_cursor_against_aware_partition_bounds(self):
        # Pipeline can persist the incremental cursor as a naive datetime, but
        # partition bounds parsed from the catalog are always UTC-aware. The
        # walker must coerce naive->aware before comparing or Python raises
        # `can't compare offset-naive and offset-aware datetimes`.
        child = ChildPartition(
            oid=1,
            schema="public",
            name="p",
            partbound="FOR VALUES FROM ('2026-01-01 00:00:00') TO ('2026-01-02 00:00:00')",
        )
        factory = _FakeConnectionFactory([[(1, 10)]])
        tables = list(
            iterate_date_windows(
                get_connection=cast(Any, factory),
                build_windowed_query=_build_fake_query,
                schema="public",
                table_name="t",
                incremental_field="x",
                incremental_field_type=IncrementalFieldType.DateTime,
                db_incremental_field_last_value=datetime(2025, 12, 31, 23, 59, 59),  # naive!
                child_partitions=[child],
                chunk_size=1000,
                arrow_schema=_arrow_schema(),
                logger=structlog.get_logger(),
                initial_window=timedelta(days=1),
                clock=_FakeClock(),
                sleeper=lambda _s: None,
            )
        )
        assert sum(t.num_rows for t in tables) == 1

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


class TestRlsDetectionRealDb:
    def _create_table(self, cursor, *, rls_active: bool) -> None:
        cursor.execute("CREATE TABLE test_rls_param (id SERIAL PRIMARY KEY, user_id INTEGER)")
        if not rls_active:
            return
        cursor.execute("ALTER TABLE test_rls_param ENABLE ROW LEVEL SECURITY")
        cursor.execute("ALTER TABLE test_rls_param FORCE ROW LEVEL SECURITY")
        cursor.execute("CREATE POLICY test_rls_param_policy ON test_rls_param USING (false)")
        # FORCE subjects a non-superuser owner directly; a superuser bypasses even FORCE, so observe
        # via a freshly created unprivileged role (a superuser can always create one).
        cursor.execute("SELECT rolsuper FROM pg_roles WHERE rolname = current_user")
        if cursor.fetchone()[0]:
            cursor.execute("CREATE ROLE test_rls_param_role NOLOGIN")
            cursor.execute("GRANT SELECT ON test_rls_param TO test_rls_param_role")
            cursor.execute("SET LOCAL ROLE test_rls_param_role")

    @pytest.mark.parametrize("rls_active,expected", [(False, False), (True, True)])
    @pytest.mark.django_db
    def test_role_subject_to_rls(self, rls_active, expected):
        logger = structlog.get_logger()
        with django_connection.cursor() as dj_cursor:
            self._create_table(dj_cursor, rls_active=rls_active)
            try:
                assert _role_subject_to_rls(cast(Any, dj_cursor), "public", "test_rls_param", logger) is expected
            finally:
                dj_cursor.execute("RESET ROLE")

    @pytest.mark.parametrize("rls_active,expected", [(False, False), (True, True)])
    @pytest.mark.django_db
    def test_rls_active_from_conn(self, rls_active, expected):
        with django_connection.cursor() as dj_cursor:
            self._create_table(dj_cursor, rls_active=rls_active)
            try:
                result = _rls_active_from_conn(
                    cast(Any, _DjangoBackedConnection(dj_cursor)), "public", ["test_rls_param"]
                )
                assert result == {"test_rls_param": expected}
            finally:
                dj_cursor.execute("RESET ROLE")

    @pytest.mark.django_db
    def test_rls_active_from_conn_runs_without_schema_or_names(self):
        # Regression: an early-return guard used to bail when no schema and no names were given,
        # silently dropping every RLS warning in multi-schema discovery. The full table list must
        # still be checked, so the table appears in the result (keyed by its qualified name).
        with django_connection.cursor() as dj_cursor:
            dj_cursor.execute("CREATE TABLE test_rls_noschema (id SERIAL PRIMARY KEY)")
            result = _rls_active_from_conn(cast(Any, _DjangoBackedConnection(dj_cursor)), "", None)
            assert "public.test_rls_noschema" in result


# Message a DuckDB/Flight-SQL-backed Postgres-wire engine returns when `row_security_active` is
# absent — the engine accepts the connection but lacks the Postgres-only catalog function.
_FLIGHT_MISSING_FUNCTION_MSG = (
    "flight execute: rpc error: code = InvalidArgument desc = failed to prepare query: "
    "Catalog Error: Scalar Function with name row_security_active does not exist!"
)


class TestIsUnsupportedFunctionError:
    @pytest.mark.parametrize(
        "error,expected",
        [
            (psycopg.errors.InternalError(_FLIGHT_MISSING_FUNCTION_MSG), True),
            (Exception('function "row_security_active" does not exist'), True),
            (Exception("Unknown function: row_security_active"), True),
            # Real Postgres raises UndefinedFunction (SQLSTATE 42883) — recognised by type alone.
            (psycopg.errors.UndefinedFunction("function row_security_active(oid) does not exist"), True),
            # Different function missing -> not our concern, should still be captured.
            (Exception("function some_other_func does not exist"), False),
            # A genuine permission error mentioning the function must NOT be swallowed.
            (Exception("permission denied for function row_security_active"), False),
            (Exception("connection reset by peer"), False),
        ],
    )
    def test_recognises_missing_function(self, error, expected):
        assert _is_unsupported_function_error(error, "row_security_active") is expected


class TestRlsActiveFromConnErrorHandling:
    @staticmethod
    def _conn_raising(exc: Exception):
        conn = mock.MagicMock()
        conn.cursor.return_value.__enter__.return_value.execute.side_effect = exc
        return conn

    def test_unsupported_function_error_is_not_captured(self):
        # A Postgres-wire engine without `row_security_active` is an expected shape: degrade to no
        # RLS warnings without flooding error tracking.
        conn = self._conn_raising(psycopg.errors.InternalError(_FLIGHT_MISSING_FUNCTION_MSG))
        with patch("posthog.temporal.data_imports.sources.postgres.postgres.capture_exception") as capture_mock:
            result = _rls_active_from_conn(cast(Any, conn), "public", ["t"])
        assert result == {}
        capture_mock.assert_not_called()

    def test_unexpected_error_is_still_captured(self):
        conn = self._conn_raising(Exception("connection reset by peer"))
        with patch("posthog.temporal.data_imports.sources.postgres.postgres.capture_exception") as capture_mock:
            result = _rls_active_from_conn(cast(Any, conn), "public", ["t"])
        assert result == {}
        capture_mock.assert_called_once()

    def test_failed_sql_transaction_is_not_captured(self):
        # This lookup shares a connection with earlier best-effort metadata queries (PK + index
        # discovery). When one of those fails on a non-Postgres engine (e.g. Redshift) its exception
        # is caught upstream but leaves the transaction aborted, so our first statement here raises
        # InFailedSqlTransaction as a downstream symptom. That's already handled, not a bug — don't
        # flood error tracking with it.
        conn = self._conn_raising(
            psycopg.errors.InFailedSqlTransaction(
                "current transaction is aborted, commands ignored until end of transaction block"
            )
        )
        with patch("posthog.temporal.data_imports.sources.postgres.postgres.capture_exception") as capture_mock:
            result = _rls_active_from_conn(cast(Any, conn), "public", ["t"])
        assert result == {}
        capture_mock.assert_not_called()


class TestGetRowsInitialConnectRetry:
    # Regression: the main server-cursor read path opened its initial connection with a bare
    # get_connection(), so a transient "server closed the connection unexpectedly" while
    # establishing that connection escaped and failed the whole sync — even though every other
    # read path already recovers in-process via _connect_with_dropped_retry. Wrapping the initial
    # connect in the same helper makes a transient drop retry instead of aborting.
    @pytest.mark.django_db(transaction=True)
    def test_initial_connect_retries_transient_drop(self):
        table_name = "test_initial_connect_retry"
        sd = django_connection.settings_dict

        with django_connection.cursor() as dj_cursor:
            dj_cursor.execute(f"DROP TABLE IF EXISTS {table_name}")
            dj_cursor.execute(f"CREATE TABLE {table_name} (id BIGSERIAL PRIMARY KEY, val TEXT)")
            dj_cursor.execute(f"INSERT INTO {table_name} (val) SELECT 'v' || g FROM generate_series(1, 5) g")

        @contextmanager
        def tunnel():
            yield (sd["HOST"] or "localhost", int(sd["PORT"]) if sd["PORT"] else 5432)

        real_connect = psycopg.connect

        def plain_connect(*args, **kwargs):
            # The production connect passes dummy SSL cert paths ("/tmp/no.txt"); strip the SSL
            # kwargs so the read path can reach the local test DB while we exercise the retry.
            for key in ("sslmode", "sslrootcert", "sslcert", "sslkey"):
                kwargs.pop(key, None)
            return real_connect(*args, **kwargs)

        logger = structlog.get_logger()

        try:
            with patch(
                "posthog.temporal.data_imports.sources.postgres.postgres.psycopg.connect",
                side_effect=plain_connect,
            ):
                response = postgres_source(
                    tunnel=tunnel,
                    user=sd["USER"] or "",
                    password=sd["PASSWORD"] or "",
                    database=sd["NAME"],
                    sslmode="prefer",
                    schema="public",
                    table_names=[table_name],
                    should_use_incremental_field=False,
                    logger=logger,
                    db_incremental_field_last_value=None,
                    team_id=1,
                )

            connect_calls = {"n": 0}

            def flaky_connect(*args, **kwargs):
                connect_calls["n"] += 1
                if connect_calls["n"] == 1:
                    # The exact production failure: a transient drop while establishing the read
                    # connection (here, the local 127.0.0.1 tunnel endpoint).
                    raise psycopg.OperationalError(
                        'connection failed: connection to server at "127.0.0.1", port 5432 failed: '
                        "server closed the connection unexpectedly"
                    )
                return plain_connect(*args, **kwargs)

            with (
                patch("posthog.temporal.data_imports.sources.postgres.postgres.time.sleep"),
                patch(
                    "posthog.temporal.data_imports.sources.postgres.postgres.psycopg.connect",
                    side_effect=flaky_connect,
                ),
            ):
                tables = list(cast(Iterable[Any], response.items()))

            assert connect_calls["n"] >= 2, "initial connect should have been retried after the transient drop"
            assert sum(table.num_rows for table in tables) == 5
        finally:
            with django_connection.cursor() as dj_cursor:
                dj_cursor.execute(f"DROP TABLE IF EXISTS {table_name}")
