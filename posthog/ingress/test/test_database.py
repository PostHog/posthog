from unittest.mock import patch

from django.conf import settings
from django.db import InterfaceError, OperationalError, connections
from django.test import SimpleTestCase, TestCase, TransactionTestCase

from parameterized import parameterized

from posthog.ingress.dispatch.database import (
    bounded_statement_timeout,
    is_connection_failure,
    is_statement_timeout,
    read_aliases,
    read_with_reconnect,
)
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


class TestIsConnectionFailure(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "a_socket_that_went_away_under_the_statement",
                OperationalError("server closed the connection unexpectedly"),
                True,
            ),
            ("a_driver_that_reports_the_connection_gone", InterfaceError("connection already closed"), True),
            (
                "a_socket_reset_while_the_read_opened_its_connection",
                OperationalError(
                    "connection failed: connection to server at 127.0.0.1 failed: Connection reset by peer"
                ),
                True,
            ),
            (
                "a_tls_drop_reported_at_the_socket",
                OperationalError("connection failed: SSL SYSCALL error: EOF detected"),
                True,
            ),
            ("the_cap_firing", OperationalError("canceling statement due to statement timeout"), False),
            ("an_unrelated_database_failure", OperationalError("deadlock detected"), False),
            ("an_error_from_somewhere_else", ValueError("not a database error"), False),
        ]
    )
    def test_tells_a_lost_connection_from_a_failed_statement(self, _name, error, expected) -> None:
        # The two cannot be one predicate: a cancelled statement ran and a lost connection
        # did not, so retrying a timeout would spend the delivery's budget twice. The connect-time
        # forms carry no SQLSTATE, so the message is all the predicate gets to read.
        self.assertEqual(is_connection_failure(error), expected)

    def test_reads_the_connection_exception_class_off_the_cause(self) -> None:
        # A driver that keeps the SQLSTATE says 08006 rather than any particular wording.
        error = OperationalError("the driver said little")
        error.__cause__ = type("Cause", (Exception,), {"sqlstate": "08006"})()

        self.assertTrue(is_connection_failure(error))


class TestReadWithReconnect(TransactionTestCase):
    def test_a_read_that_lost_its_connection_runs_once_more(self) -> None:
        # Autocommit on purpose: the retry replaces the connection, which a TestCase's own
        # transaction would hide. The delivery this guards is lost without the second attempt.
        attempts: list[str] = []

        def read() -> int:
            attempts.append("called")
            if len(attempts) == 1:
                raise OperationalError("server closed the connection unexpectedly")
            with bounded_statement_timeout(50, models=[Team]):
                return Team.objects.count()

        self.assertEqual(read_with_reconnect(read, models=[Team]), Team.objects.count())
        self.assertEqual(len(attempts), 2)


class TestReadWithReconnectInsideACallersTransaction(TestCase):
    def test_a_caller_owned_transaction_gets_the_error_rather_than_a_new_connection(self) -> None:
        # A Django TestCase wraps every test in a transaction, which is the joining case:
        # replacing the connection would throw the caller's transaction away with it.
        attempts: list[str] = []

        def read() -> None:
            attempts.append("called")
            raise OperationalError("server closed the connection unexpectedly")

        with self.assertRaises(OperationalError):
            read_with_reconnect(read, models=[Team])

        self.assertEqual(len(attempts), 1)


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
