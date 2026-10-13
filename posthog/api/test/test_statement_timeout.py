from posthog.test.base import BaseTest

from django.db import DEFAULT_DB_ALIAS, OperationalError, connection
from django.test import SimpleTestCase

from parameterized import parameterized
from prometheus_client import Counter
from rest_framework.exceptions import APIException

from posthog.api.statement_timeout import is_query_canceled, statement_timeout

TEST_TIMED_OUT_COUNTER = Counter("test_statement_timeout_total", "Test only.")


def current_statement_timeout() -> str:
    with connection.cursor() as cursor:
        cursor.execute("SHOW statement_timeout")
        return cursor.fetchone()[0]


class TestStatementTimeoutInsideAnOuterTransaction(BaseTest):
    # BaseTest wraps each test in a transaction, so the helper runs as a savepoint here, which is
    # the case where a SET LOCAL would otherwise outlive the block.
    @parameterized.expand([["an explicit cap", "7s"], ["no cap", "0"]])
    def test_puts_the_outer_timeout_back_when_the_block_succeeds(self, _name: str, outer_value: str) -> None:
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL statement_timeout = %s", [outer_value])

        with statement_timeout(DEFAULT_DB_ALIAS, 250, APIException, TEST_TIMED_OUT_COUNTER):
            assert current_statement_timeout() == "250ms"

        assert current_statement_timeout() == outer_value


class TestIsQueryCanceled(SimpleTestCase):
    @staticmethod
    def _wrapped_error(**attrs: str) -> OperationalError:
        # Django surfaces the driver's error as its own OperationalError with the original attached
        # as __cause__, which is where the SQLSTATE lives.
        cause = Exception("canceling statement due to statement timeout")
        for name, value in attrs.items():
            setattr(cause, name, value)
        error = OperationalError("canceling statement due to statement timeout")
        error.__cause__ = cause
        return error

    @parameterized.expand(
        [
            ["psycopg3 exposes sqlstate", {"sqlstate": "57014"}, True],
            ["psycopg2 exposes pgcode", {"pgcode": "57014"}, True],
            ["a dropped connection is not a cancellation", {"sqlstate": "08006"}, False],
            ["a driver error carrying no sqlstate", {}, False],
        ]
    )
    def test_recognises_only_a_cancelled_statement(self, _name: str, attrs: dict[str, str], expected: bool) -> None:
        assert is_query_canceled(self._wrapped_error(**attrs)) is expected

    def test_recognises_the_code_on_the_error_itself(self) -> None:
        error = OperationalError("canceling statement due to statement timeout")
        error.sqlstate = "57014"  # type: ignore[attr-defined]

        assert is_query_canceled(error) is True
