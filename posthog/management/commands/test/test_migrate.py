from unittest.mock import MagicMock

from django.core.management.base import CommandError
from django.db import NotSupportedError, OperationalError
from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.management.commands.migrate import (
    UNSUPPORTED_DATABASE_EXIT_CODE,
    check_database_version,
    find_unsafe_fallback,
    resolve_replaced,
    resolve_target,
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


class TestFindUnsafeFallback(SimpleTestCase):
    # Two squash generations. The newer one nests the older one by name, and the squash
    # tool removed a dependency entry from 0002, from the older squash's addons tail, and from 0004.
    REPLACED = resolve_replaced(
        {
            ("a", "0001_squash_2026_09_07_initial"): [("a", "0001_x"), ("a", "0002_edited")],
            ("a", "0001_squash_2026_11_02_initial"): [
                ("a", "0001_squash_2026_09_07_initial"),
                ("a", "0003_squash_2026_09_07_schema_addons"),
                ("a", "0004_edited"),
                ("a", "0005_y"),
            ],
        }
    )
    DEPENDENTS = [("a", "0002_edited"), ("a", "0003_squash_2026_09_07_schema_addons"), ("a", "0004_edited")]
    EVERYTHING = {
        ("a", "0001_x"),
        ("a", "0002_edited"),
        ("a", "0003_squash_2026_09_07_schema_addons"),
        ("a", "0004_edited"),
        ("a", "0005_y"),
    }

    @parameterized.expand(
        [
            ("fresh", set(), None, []),
            ("fully_migrated", EVERYTHING, None, []),
            ("a_few_days_behind", EVERYTHING - {("a", "0005_y")}, None, []),
            (
                "before_an_edited_file_in_the_new_range",
                EVERYTHING - {("a", "0004_edited"), ("a", "0005_y")},
                None,
                ["a.0004_edited"],
            ),
            (
                "inside_the_older_squash",
                {("a", "0001_x")},
                None,
                ["a.0002_edited", "a.0003_squash_2026_09_07_schema_addons", "a.0004_edited"],
            ),
            (
                "fresh_with_a_replaced_target",
                set(),
                ("a", "0001_x"),
                ["a.0002_edited", "a.0003_squash_2026_09_07_schema_addons", "a.0004_edited"],
            ),
        ]
    )
    def test_flags_only_edited_files_that_would_run(self, _name, applied, target, expected):
        assert find_unsafe_fallback(self.REPLACED, self.DEPENDENTS, applied, target) == expected


class TestResolveTarget(SimpleTestCase):
    DISK = [("a", "0001_x"), ("a", "0002_y"), ("a", "0002_y_more"), ("b", "0001_x")]

    @parameterized.expand(
        [
            ("unique_prefix", "a", "0001", ("a", "0001_x")),
            ("exact_name_beats_a_longer_match", "a", "0002_y", ("a", "0002_y")),
            ("ambiguous_prefix", "a", "0002", None),
            ("zero", "a", "zero", None),
            ("app_only", "a", None, None),
        ]
    )
    def test_matches_a_target_like_django(self, _name, app_label, migration_name, expected):
        assert resolve_target(self.DISK, app_label, migration_name) == expected
