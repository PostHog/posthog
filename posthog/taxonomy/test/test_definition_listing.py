from django.db import OperationalError
from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.taxonomy.definition_listing import is_query_canceled


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
