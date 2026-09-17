from contextlib import ExitStack

from unittest.mock import patch

from django.conf import settings
from django.db import OperationalError, connections
from django.test import SimpleTestCase, TestCase, TransactionTestCase

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


class TestBoundedStatementTimeoutReconnects(TransactionTestCase):
    def test_a_read_survives_a_connection_the_server_dropped(self) -> None:
        # Installing the cap is the first thing that touches a connection, and the pooler drops
        # connections. Before the retry, that lost the whole webhook delivery.
        alias = read_aliases([Team])[0]
        connection = connections[alias]
        connection.ensure_connection()
        with self.assertRaises(OperationalError):
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_terminate_backend(pg_backend_pid())")

        with bounded_statement_timeout(500, models=[Team]):
            self.assertEqual(Team.objects.filter(pk=-1).count(), 0)


class TestCappedAliasRetry(SimpleTestCase):
    @parameterized.expand(
        [
            ("a_dropped_connection_is_opened_again", "server closed the connection unexpectedly", 2),
            # libpq keeps the OS string's own case, and reports a drop on an encrypted connection
            # through the TLS layer, so neither of these reaches the plain lowercase wording.
            ("a_reset_the_os_capitalized_is_too", "could not receive data from server: Connection reset by peer", 2),
            ("a_tls_drop_is_too", "SSL connection has been closed unexpectedly", 2),
            ("a_tls_socket_drop_is_too", "consuming input failed: SSL SYSCALL error: EOF detected", 2),
            # No backoff sits behind this retry, so a failure that needs one must not be repeated
            # into the delivery's wall clock. The pooler quotes the backend failure it cached, so
            # the cooldown has to outrank a marker that appears inside that quote.
            ("a_saturated_pool_is_not", "query_wait_timeout", 1),
            (
                "a_cached_pooler_login_failure_is_not",
                "server login has been failing, cached error: server closed the connection unexpectedly",
                1,
            ),
        ]
    )
    def test_only_a_dropped_connection_is_opened_again(self, _name: str, message: str, expected_opens: int) -> None:
        opens = []

        def open_alias(alias: str, timeout_ms: int) -> ExitStack:
            opens.append(alias)
            raise OperationalError(message)

        with patch("posthog.ingress.dispatch.database._open_capped_alias", side_effect=open_alias):
            with self.assertRaises(OperationalError):
                with bounded_statement_timeout(500, models=[Team]):
                    pass

        self.assertEqual(len(opens), expected_opens)
