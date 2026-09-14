from django.db import OperationalError, connections
from django.test import SimpleTestCase, TestCase

from posthog.ingress.dispatch.database import bounded_statement_timeout, is_statement_timeout, read_aliases
from posthog.models import Team, User


def _current_statement_timeout(alias: str) -> str:
    with connections[alias].cursor() as cursor:
        cursor.execute("SHOW statement_timeout")
        row = cursor.fetchone()
    return row[0]


class TestReadAliases(SimpleTestCase):
    def test_models_that_route_to_one_alias_are_capped_once(self) -> None:
        self.assertEqual(read_aliases([Team, User]), read_aliases([Team]))


class TestIsStatementTimeout(SimpleTestCase):
    def test_an_unrelated_database_failure_is_not_the_cap_firing(self) -> None:
        self.assertFalse(is_statement_timeout(OperationalError("server closed the connection unexpectedly")))
        self.assertFalse(is_statement_timeout(ValueError("not a database error")))


class TestBoundedStatementTimeout(TestCase):
    def test_a_statement_over_the_cap_is_cancelled_and_reported_as_a_timeout(self) -> None:
        alias = read_aliases([Team])[0]

        with self.assertRaises(OperationalError) as raised:
            with bounded_statement_timeout(50, models=[Team]):
                with connections[alias].cursor() as cursor:
                    cursor.execute("SELECT pg_sleep(5)")

        self.assertTrue(is_statement_timeout(raised.exception))

    def test_the_previous_cap_comes_back_when_the_caller_owns_the_transaction(self) -> None:
        alias = read_aliases([Team])[0]
        # A Django TestCase wraps every test in a transaction, so this is the joining case:
        # SET LOCAL outlives the block and has to be put back by hand.
        before = _current_statement_timeout(alias)

        with bounded_statement_timeout(50, models=[Team]):
            self.assertEqual(_current_statement_timeout(alias), "50ms")

        self.assertEqual(_current_statement_timeout(alias), before)
