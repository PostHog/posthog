from datetime import date

import pytest

from posthog.temporal.data_imports.sources.postgres.postgres import SafeDateLoader
from posthog.temporal.data_imports.sources.postgres.source import PostgresSource


class TestSafeDateLoader:
    @pytest.fixture
    def loader(self):
        return SafeDateLoader(oid=1082)  # 1082 is the PostgreSQL OID for date type

    @pytest.mark.parametrize(
        "input_data,expected",
        [
            (b"2024-01-15", date(2024, 1, 15)),
            (b"1999-12-31", date(1999, 12, 31)),
            (b"0001-01-01", date(1, 1, 1)),
            (b"9999-12-31", date(9999, 12, 31)),
            # Edge cases: dates beyond Python's date range should clamp
            (b"48113-11-21", date.max),
            (b"10000-01-01", date.max),
            (b"99999-12-31", date.max),
            # Infinity values
            (b"infinity", date.max),
            (b"-infinity", date.min),
            # Negative years / BC dates should clamp to date.min
            (b"-0001-01-01", date.min),
            (b"-0044-03-15", date.min),
            (b"0000-01-01", date.min),
            (b"0044-03-15 BC", date.min),
            # None should return None
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
