from datetime import UTC, datetime, timedelta

from freezegun import freeze_time

from django.test import SimpleTestCase

from clickhouse_driver.errors import ServerException
from parameterized import parameterized
from rest_framework.exceptions import ValidationError

from posthog.hogql.constants import LimitContext

from posthog.clickhouse.client.limit import ConcurrencyLimitExceeded
from posthog.errors import wrap_clickhouse_query_error
from posthog.exceptions import (
    ClickHouseAtCapacity,
    ClickHouseEstimatedQueryExecutionTimeTooLong,
    ClickHouseQueryMemoryLimitExceeded,
    ClickHouseQuerySizeExceeded,
    ClickHouseQueryTimeOut,
)
from posthog.hogql_queries.query_failure_handling import (
    build_failure_exception,
    classify_failure,
    scope_for_limit_context,
)
from posthog.query_cache.failures import SCOPE_ASYNC, SCOPE_SYNC, QueryFailureRecord


def _memory_error(message: str):
    return wrap_clickhouse_query_error(ServerException(message, code=241))


def _record(kind, consecutive_failures, detail, open_until=None):
    return QueryFailureRecord(
        kind=kind,
        detail=detail,
        consecutive_failures=consecutive_failures,
        last_failed_at=datetime.now(UTC),
        open_until=open_until,
        scope=SCOPE_SYNC,
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
            ("at_capacity", ClickHouseAtCapacity(), None),
            ("concurrency_limit", ConcurrencyLimitExceeded("busy"), None),
            ("too_many_simultaneous", wrap_clickhouse_query_error(ServerException("busy", code=202)), None),
            ("user_error", ValidationError("bad"), None),
        ]
    )
    def test_classify_failure(self, _name, error, expected):
        assert classify_failure(error) == expected

    @parameterized.expand(
        [
            ("interactive", None, SCOPE_SYNC),
            ("query", LimitContext.QUERY, SCOPE_SYNC),
            ("worker", LimitContext.QUERY_ASYNC, SCOPE_ASYNC),
            ("export", LimitContext.EXPORT, SCOPE_ASYNC),
        ]
    )
    def test_scope_for_limit_context(self, _name, limit_context, expected):
        assert scope_for_limit_context(limit_context) == expected

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
