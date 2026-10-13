from unittest.mock import patch

from django.conf import settings
from django.db import OperationalError, connections
from django.test import SimpleTestCase, TestCase

from parameterized import parameterized

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

    @parameterized.expand(
        [
            ("a_configured_replica_the_router_never_reads_is_not_dialled", lambda model: "default", ["default"]),
            ("a_fully_replica_opted_read_does_not_wait_on_the_primary", lambda model: "replica", ["replica"]),
            (
                "an_alias_only_some_models_read_from_is_still_capped",
                lambda model: "replica" if model is User else "default",
                ["default", "replica"],
            ),
        ]
    )
    def test_takes_the_alias_set_from_the_router(self, _name, db_for_read, expected) -> None:
        # Bounding an alias means opening it, and connection setup is itself unbounded (these
        # aliases carry no connect_timeout), so an alias the read never uses must not be dialled
        # just to install a cap on it. That cuts both ways, hence the first two cases.
        with self.settings(DATABASES={**settings.DATABASES, "replica": settings.DATABASES["default"]}):
            with patch("posthog.ingress.dispatch.database.router.db_for_read", side_effect=db_for_read):
                self.assertEqual(sorted(read_aliases([Team, User])), expected)


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
