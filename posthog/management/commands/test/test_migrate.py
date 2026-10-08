from unittest.mock import MagicMock

from django.core.management.base import CommandError
from django.db import NotSupportedError, OperationalError
from django.test import SimpleTestCase

from posthog.management.commands.migrate import UNSUPPORTED_DATABASE_EXIT_CODE, check_database_version


def fake_connection(error: Exception) -> MagicMock:
    connection = MagicMock()
    connection.ensure_connection.side_effect = error
    return connection


class TestCheckDatabaseVersion(SimpleTestCase):
    def test_stops_with_recovery_steps_on_an_unsupported_server(self):
        error = NotSupportedError("PostgreSQL 14 or later is required (found 11.22).")

        with self.assertRaises(CommandError) as raised:
            check_database_version(fake_connection(error))

        assert raised.exception.returncode == UNSUPPORTED_DATABASE_EXIT_CODE
        assert "found 11.22" in str(raised.exception)
        assert "pg_dumpall" in str(raised.exception)

    def test_lets_a_transient_connection_failure_through(self):
        error = OperationalError("could not connect to server")

        with self.assertRaises(OperationalError):
            check_database_version(fake_connection(error))
