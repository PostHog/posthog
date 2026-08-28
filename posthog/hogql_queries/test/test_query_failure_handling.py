from datetime import UTC, datetime, timedelta

from freezegun import freeze_time
from unittest.mock import patch

from django.test import SimpleTestCase

from clickhouse_driver.errors import ServerException
from parameterized import parameterized
from rest_framework.exceptions import ValidationError

from posthog.hogql.constants import LimitContext

from posthog.clickhouse.client.execute import KillSwitchLevel
from posthog.clickhouse.client.limit import ConcurrencyLimitExceeded
from posthog.errors import wrap_clickhouse_query_error
from posthog.exceptions import (
    ClickHouseAtCapacity,
    ClickHouseBytesLimitExceeded,
    ClickHouseEstimatedQueryExecutionTimeTooLong,
    ClickHouseQueryMemoryLimitExceeded,
    ClickHouseQuerySizeExceeded,
    ClickHouseQueryTimeOut,
)
from posthog.hogql_queries.query_failure_handling import (
    budget_for_limit_context,
    build_failure_exception,
    classify_failure,
)
from posthog.query_cache.failures import BUDGET_EXTENDED, BUDGET_INTERACTIVE, QueryFailureRecord


def _memory_error(message: str):
    return wrap_clickhouse_query_error(ServerException(message, code=241))


def _record(kind, consecutive_failures, detail, open_until=None):
    return QueryFailureRecord(
        kind=kind,
        detail=detail,
        consecutive_failures=consecutive_failures,
        last_failed_at=datetime.now(UTC),
        open_until=open_until,
        budget=BUDGET_INTERACTIVE,
    )


class TestQueryFailureHandling(SimpleTestCase):
    @parameterized.expand(
        [
            ("memory_per_query_26x", _memory_error("Query memory limit exceeded: would use 42.03 GiB"), "memory_limit"),
            (
                "memory_per_query_legacy",
                _memory_error("Memory limit (for query) exceeded: would use 30.1 GiB"),
                "memory_limit",
            ),
            ("memory_total", _memory_error("Memory limit (total) exceeded: would use 100 GiB"), None),
            ("memory_for_user", _memory_error("Memory limit (for user) exceeded: would use 80 GiB"), None),
            ("memory_unknown_phrasing", _memory_error("Some future memory message"), None),
            ("timeout", ClickHouseQueryTimeOut(), "timeout"),
            ("too_slow", ClickHouseEstimatedQueryExecutionTimeTooLong(), "too_slow"),
            ("query_size", ClickHouseQuerySizeExceeded(), "query_size"),
            (
                "too_many_bytes",
                wrap_clickhouse_query_error(ServerException("Limit for bytes to read exceeded", code=307)),
                "too_many_bytes",
            ),
            ("at_capacity", ClickHouseAtCapacity(), None),
            ("concurrency_limit", ConcurrencyLimitExceeded("busy"), None),
            ("too_many_simultaneous", wrap_clickhouse_query_error(ServerException("busy", code=202)), None),
            ("user_error", ValidationError("bad"), None),
        ]
    )
    def test_classify_failure(self, _name, error, expected):
        assert classify_failure(error) == expected

    @parameterized.expand([("light", KillSwitchLevel.LIGHT), ("full", KillSwitchLevel.FULL)])
    def test_too_many_bytes_not_classified_under_kill_switch(self, _name, level):
        error = wrap_clickhouse_query_error(ServerException("Limit for bytes to read exceeded", code=307))
        with patch("posthog.hogql_queries.query_failure_handling.get_kill_switch_level", return_value=level):
            assert classify_failure(error) is None

    @parameterized.expand([("light", KillSwitchLevel.LIGHT), ("full", KillSwitchLevel.FULL)])
    def test_too_many_bytes_not_classified_under_team_kill_switch(self, _name, level):
        error = wrap_clickhouse_query_error(ServerException("Limit for bytes to read exceeded", code=307))
        with patch("posthog.hogql_queries.query_failure_handling.get_team_kill_switch_level", return_value=level):
            assert classify_failure(error, team_id=42) is None

    def test_too_many_bytes_classified_when_no_switch_covers_team(self):
        error = wrap_clickhouse_query_error(ServerException("Limit for bytes to read exceeded", code=307))
        with patch(
            "posthog.hogql_queries.query_failure_handling.get_team_kill_switch_level",
            return_value=KillSwitchLevel.OFF,
        ):
            assert classify_failure(error, team_id=42) == "too_many_bytes"

    @parameterized.expand(
        [
            ("interactive", None, BUDGET_INTERACTIVE),
            ("query", LimitContext.QUERY, BUDGET_INTERACTIVE),
            ("worker", LimitContext.QUERY_ASYNC, BUDGET_EXTENDED),
            ("export", LimitContext.EXPORT, BUDGET_EXTENDED),
        ]
    )
    def test_budget_for_limit_context(self, _name, limit_context, expected):
        assert budget_for_limit_context(limit_context) == expected

    def test_build_failure_exception_preserves_class_and_status(self):
        with freeze_time("2026-01-01T00:00:00Z"):
            original_detail = str(ClickHouseQueryTimeOut().detail)
            record = _record("timeout", 3, original_detail, open_until=datetime.now(UTC) + timedelta(minutes=2))

            error = build_failure_exception(record)
            assert isinstance(error, ClickHouseQueryTimeOut)
            assert error.status_code == 504
            assert getattr(error, "served_from_query_failure_cache", False)
            detail = str(error.detail)
            assert detail.startswith(original_detail)
            assert "This query failed the same way 3 times in a row" in detail
            assert detail.endswith("It can run again in about 2 minutes.")

    def test_build_failure_exception_matches_fresh_too_many_bytes_shape(self):
        record = _record("too_many_bytes", 1, "Limit for bytes to read exceeded: 1.10 TB, maximum: 1.00 TB")

        error = build_failure_exception(record)
        assert isinstance(error, ClickHouseBytesLimitExceeded)
        assert error.status_code == 400
        assert error.get_codes() == ["too_many_bytes"]
        assert "was not run again" in str(error.detail)

    def test_build_failure_exception_first_failure_wording(self):
        with freeze_time("2026-01-01T00:00:00Z"):
            original_detail = str(ClickHouseQueryMemoryLimitExceeded().detail)
            record = _record("memory_limit", 1, original_detail, open_until=datetime.now(UTC) + timedelta(minutes=2))

            error = build_failure_exception(record)
            assert isinstance(error, ClickHouseQueryMemoryLimitExceeded)
            assert error.status_code == 513
            detail = str(error.detail)
            assert detail.startswith(original_detail)
            assert "This query failed in a way that will repeat" in detail
            assert detail.endswith("It can run again in about 2 minutes.")
