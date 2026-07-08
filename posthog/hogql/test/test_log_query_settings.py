import pytest
from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from django.test import SimpleTestCase

from clickhouse_driver.errors import ServerException
from parameterized import parameterized

from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.errors import QueryError
from posthog.hogql.query import HogQLQueryExecutor

from posthog.errors import (
    CHQueryErrorLogsClusterUnavailable,
    CHQueryErrorTooManyBytes,
    CHQueryErrorUnknownIdentifier,
    ExposedCHQueryError,
    wrap_clickhouse_query_error,
)


class TestLogQuerySettings(ClickhouseTestMixin, APIBaseTest):
    """Tests that user HogQL queries on log tables get max_bytes_to_read settings applied."""

    def _get_clickhouse_sql_for(self, query: str, query_type: str = "HogQLQuery") -> str:
        executor = HogQLQueryExecutor(
            query=query,
            team=self.team,
            query_type=query_type,
        )
        sql, _context = executor.generate_clickhouse_sql()
        return sql

    # --- User HogQL queries on log tables ---
    def test_user_query_on_logs_table_has_max_bytes_to_read(self):
        sql = self._get_clickhouse_sql_for("SELECT * FROM logs LIMIT 10")
        assert f"max_bytes_to_read=" in sql.replace(" ", "")

    def test_user_query_on_logs_table_has_throw_overflow_mode(self):
        sql = self._get_clickhouse_sql_for("SELECT * FROM logs LIMIT 10")
        assert "read_overflow_mode" in sql
        assert "throw" in sql

    def test_user_query_on_log_attributes_table_has_max_bytes_to_read(self):
        sql = self._get_clickhouse_sql_for("SELECT * FROM log_attributes LIMIT 10")
        assert f"max_bytes_to_read=" in sql.replace(" ", "")

    def test_user_query_on_logs_kafka_metrics_table_has_max_bytes_to_read(self):
        sql = self._get_clickhouse_sql_for("SELECT * FROM logs_kafka_metrics LIMIT 10")
        assert f"max_bytes_to_read=" in sql.replace(" ", "")

    # --- Non-log user queries should NOT have log settings ---
    def test_user_query_on_events_table_has_no_max_bytes_to_read(self):
        sql = self._get_clickhouse_sql_for("SELECT * FROM events LIMIT 10")
        assert "max_bytes_to_read" not in sql

    def test_user_query_on_persons_table_has_no_max_bytes_to_read(self):
        sql = self._get_clickhouse_sql_for("SELECT * FROM persons LIMIT 10")
        assert "max_bytes_to_read" not in sql

    def test_user_query_on_sessions_table_has_no_max_bytes_to_read(self):
        sql = self._get_clickhouse_sql_for("SELECT * FROM sessions LIMIT 10")
        assert "max_bytes_to_read" not in sql

    # --- Internal query runners should NOT get log settings ---
    def test_internal_logs_query_type_has_no_max_bytes_to_read(self):
        sql = self._get_clickhouse_sql_for(
            "SELECT * FROM logs LIMIT 10",
            query_type="LogsQuery",
        )
        assert "max_bytes_to_read" not in sql

    def test_internal_has_logs_query_type_has_no_max_bytes_to_read(self):
        sql = self._get_clickhouse_sql_for(
            "SELECT * FROM logs LIMIT 10",
            query_type="HasLogsQuery",
        )
        assert "max_bytes_to_read" not in sql

    def test_user_query_on_logs_applies_settings_even_with_custom_settings(self):
        executor = HogQLQueryExecutor(
            query="SELECT * FROM logs LIMIT 10",
            team=self.team,
            query_type="HogQLQuery",
            settings=HogQLGlobalSettings(max_execution_time=30),
        )
        sql, _context = executor.generate_clickhouse_sql()
        assert f"max_bytes_to_read=" in sql.replace(" ", "")
        # The user's other settings should still be preserved
        assert "max_execution_time" in sql

    def test_mixed_events_and_logs_join_raises_workload_error(self):
        with pytest.raises(QueryError):
            self._get_clickhouse_sql_for("SELECT * FROM events e JOIN logs l ON e.uuid = l.uuid LIMIT 10")


class TestTooManyBytesError(ClickhouseTestMixin, APIBaseTest):
    """Tests that TOO_MANY_BYTES error is exposed to users."""

    def test_wrap_clickhouse_query_error_returns_exposed_error_for_too_many_bytes(self):
        server_error = ServerException(
            "DB::Exception: Limit for result exceeded, max bytes: 5000000000. Stack trace: ...",
            code=307,
        )
        wrapped = wrap_clickhouse_query_error(server_error)
        assert isinstance(wrapped, CHQueryErrorTooManyBytes)
        assert isinstance(wrapped, ExposedCHQueryError)

    def test_wrap_clickhouse_query_error_too_many_bytes_has_friendly_message(self):
        server_error = ServerException(
            "DB::Exception: Limit for result exceeded, max bytes: 5000000000. Stack trace: ...",
            code=307,
        )
        wrapped = wrap_clickhouse_query_error(server_error)
        message = str(wrapped)
        # Should NOT contain raw ClickHouse internals
        assert "DB::Exception" not in message
        assert "Stack trace" not in message

        assert "limit for result exceeded" in message.lower()

    def test_wrap_clickhouse_query_error_too_many_bytes_has_code_name(self):
        server_error = ServerException(
            "DB::Exception: Limit for result exceeded, max bytes: 5000000000.",
            code=307,
        )
        wrapped = wrap_clickhouse_query_error(server_error)
        assert getattr(wrapped, "code_name", None) == "too_many_bytes"


class TestLogsClusterUnavailableError(SimpleTestCase):
    """A `FROM logs` query in an environment without the LOGS cluster must yield an actionable
    message, not the raw `Unknown table expression identifier 'logs_distributed'` internal error."""

    @parameterized.expand(
        [
            "logs_distributed",
            "log_attributes_distributed",
            "logs_kafka_metrics_distributed",
            "trace_spans_distributed",
            "trace_attributes_distributed",
        ]
    )
    def test_missing_logs_cluster_table_is_exposed_with_friendly_message(self, table: str):
        server_error = ServerException(
            f"DB::Exception: Unknown table expression identifier '{table}' in scope "
            f"SELECT count() AS c FROM {table}. Stack trace: ...",
            code=47,
        )
        wrapped = wrap_clickhouse_query_error(server_error)
        assert isinstance(wrapped, CHQueryErrorLogsClusterUnavailable)
        assert isinstance(wrapped, ExposedCHQueryError)
        message = str(wrapped)
        assert table in message
        assert "logs product" in message
        # The raw ClickHouse internals must not leak through.
        assert "DB::Exception" not in message
        assert "Stack trace" not in message

    def test_unrelated_unknown_identifier_is_not_treated_as_logs_cluster(self):
        server_error = ServerException(
            "DB::Exception: Unknown table expression identifier 'events' in scope SELECT * FROM events.",
            code=47,
        )
        wrapped = wrap_clickhouse_query_error(server_error)
        assert isinstance(wrapped, CHQueryErrorUnknownIdentifier)
        assert not isinstance(wrapped, CHQueryErrorLogsClusterUnavailable)
