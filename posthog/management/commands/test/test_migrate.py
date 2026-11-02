from types import SimpleNamespace

from unittest.mock import MagicMock

from django.core.management.base import CommandError
from django.db import NotSupportedError, OperationalError
from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.management.commands.migrate import (
    UNSUPPORTED_DATABASE_EXIT_CODE,
    check_database_version,
    find_partly_applied_squashes,
    replaced_by_squash,
)


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


class TestFindPartlyAppliedSquashes(SimpleTestCase):
    LOADER = SimpleNamespace(
        disk_migrations={
            ("app", "0001_a"): SimpleNamespace(replaces=[]),
            ("app", "0002_b"): SimpleNamespace(replaces=[]),
            ("app", "0003_c"): SimpleNamespace(replaces=[]),
            ("app", "0001_squash_2026_09_07_initial"): SimpleNamespace(replaces=[("app", "0001_a"), ("app", "0002_b")]),
            ("app", "0001_squash_2026_11_02_initial"): SimpleNamespace(
                replaces=[("app", "0001_squash_2026_09_07_initial"), ("app", "0003_c")]
            ),
        }
    )

    @parameterized.expand(
        [
            ("fresh", set(), []),
            ("at_the_floor", {("app", "0001_a"), ("app", "0002_b"), ("app", "0003_c")}, []),
            (
                "inside_the_new_range",
                {("app", "0001_a"), ("app", "0002_b")},
                ["app.0001_squash_2026_11_02_initial"],
            ),
            (
                "inside_the_old_range",
                {("app", "0001_a")},
                ["app.0001_squash_2026_09_07_initial", "app.0001_squash_2026_11_02_initial"],
            ),
        ]
    )
    def test_flags_only_databases_that_stopped_inside_a_squash(self, _name, applied, expected):
        assert find_partly_applied_squashes(replaced_by_squash(self.LOADER), applied) == expected
