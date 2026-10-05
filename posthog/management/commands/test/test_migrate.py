from unittest.mock import MagicMock

from django.core.management.base import CommandError
from django.db import NotSupportedError, OperationalError
from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.management.commands.migrate import (
    UNSUPPORTED_DATABASE_EXIT_CODE,
    check_database_version,
    find_apps_without_a_baseline,
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


ROOTS = [("posthog", "0000_squash_stub"), ("ee", "0001_squash_initial"), ("auth", "0001_initial")]


class TestFindAppsWithoutABaseline(SimpleTestCase):
    @parameterized.expand(
        [
            ("fresh_database", [], []),
            (
                "migrated_past_the_squash",
                [("posthog", "0000_squash_stub"), ("posthog", "1391_x"), ("ee", "0001_squash_initial")],
                [],
            ),
            (
                "stopped_before_the_squash",
                [("posthog", "0001_initial"), ("posthog", "0800_x"), ("auth", "0001_initial")],
                ["posthog"],
            ),
            ("every_app_stopped_before_the_squash", [("posthog", "0800_x"), ("ee", "0010_x")], ["ee", "posthog"]),
            ("rows_of_an_app_the_code_no_longer_has", [("retired_app", "0001_initial"), ("auth", "0001_initial")], []),
        ]
    )
    def test_finds_apps_whose_history_the_code_no_longer_has(
        self, _name: str, applied: list[tuple[str, str]], expected: list[str]
    ) -> None:
        assert find_apps_without_a_baseline(set(applied), ROOTS) == expected
