from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

import pytest

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase

import psycopg
from parameterized import parameterized

from posthog.management.commands.apply_persons_migrations import TRACKING_TABLE, _runs_outside_transaction
from posthog.persons_db import persons_db_connection


def _persons_fetchall(query: str, params: list | None = None) -> list[tuple]:
    with persons_db_connection(writer=True, autocommit=True) as conn, conn.cursor() as cursor:
        cursor.execute(query, params)
        return cursor.fetchall()


def _persons_execute(statements: list[str]) -> None:
    with persons_db_connection(writer=True, autocommit=True) as conn, conn.cursor() as cursor:
        for statement in statements:
            cursor.execute(statement)


class TestNoTransactionMarker(SimpleTestCase):
    @parameterized.expand(
        [
            ("first_line", "-- no-transaction\nCREATE INDEX CONCURRENTLY a ON t (c);", True),
            ("first_line_with_suffix", "-- no-transaction (concurrent)\nCREATE INDEX CONCURRENTLY a ON t (c);", True),
            ("after_other_comments", "-- why\n\n-- no-transaction\nCREATE INDEX CONCURRENTLY a ON t (c);", False),
            ("after_a_blank_line", "\n-- no-transaction\nCREATE INDEX CONCURRENTLY a ON t (c);", False),
            ("absent", "-- why\nCREATE INDEX a ON t (c);", False),
            ("only_after_a_statement", "CREATE INDEX a ON t (c);\n-- no-transaction\n", False),
        ]
    )
    def test_marker_detection(self, _name: str, sql_content: str, expected: bool) -> None:
        assert _runs_outside_transaction(sql_content) is expected


class TestApplyPersonsMigrations(TestCase):
    def setUp(self) -> None:
        super().setUp()
        self.suffix = uuid4().hex[:8]
        self.table = f"no_tx_test_{self.suffix}"
        self.index = f"no_tx_test_{self.suffix}_idx"
        self._migrations_tmp = TemporaryDirectory()
        self.migrations_dir = Path(self._migrations_tmp.name)

    def tearDown(self) -> None:
        _persons_execute(
            [
                f"DROP INDEX CONCURRENTLY IF EXISTS {self.index}",
                f"DROP TABLE IF EXISTS {self.table}",
                f"DELETE FROM {TRACKING_TABLE} WHERE filename LIKE '%{self.suffix}%'",
            ]
        )
        self._migrations_tmp.cleanup()
        super().tearDown()

    def _write_migration(self, version: str, name: str, body: str) -> None:
        (self.migrations_dir / f"{version}_{self.suffix}_{name}.sql").write_text(body)

    def _apply(self) -> None:
        call_command("apply_persons_migrations", "--migrations-dir", str(self.migrations_dir))

    def _recorded_migrations(self) -> list[str]:
        rows = _persons_fetchall(
            f"SELECT filename FROM {TRACKING_TABLE} WHERE filename LIKE %s ORDER BY filename",
            [f"%{self.suffix}%"],
        )
        return [row[0] for row in rows]

    def test_applies_a_concurrent_index_build_marked_no_transaction(self) -> None:
        self._write_migration("20990101000001", "create_table", f"CREATE TABLE {self.table} (id INT);")
        self._write_migration(
            "20990101000002",
            "add_index",
            f"-- no-transaction\nCREATE INDEX CONCURRENTLY IF NOT EXISTS {self.index} ON {self.table} (id);",
        )

        self._apply()

        assert _persons_fetchall("SELECT indisvalid FROM pg_index WHERE indexrelid = %s::regclass", [self.index]) == [
            (True,)
        ]
        assert len(self._recorded_migrations()) == 2

    def test_rejects_a_no_transaction_file_holding_more_than_one_statement(self) -> None:
        self._write_migration(
            "20990101000001",
            "two_statements",
            f"-- no-transaction\nCREATE TABLE {self.table} (id INT);\n"
            f"CREATE INDEX CONCURRENTLY {self.index} ON {self.table} (id);",
        )

        with pytest.raises(CommandError, match="more than one statement"):
            self._apply()

        assert self._recorded_migrations() == []

    def test_refuses_to_continue_when_a_failed_build_left_an_invalid_index(self) -> None:
        self._write_migration(
            "20990101000001",
            "create_table",
            f"CREATE TABLE {self.table} (id INT); INSERT INTO {self.table} (id) VALUES (1), (1);",
        )
        self._write_migration(
            "20990101000002",
            "add_unique_index",
            f"-- no-transaction\nCREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS {self.index} ON {self.table} (id);",
        )

        with pytest.raises(psycopg.Error):
            self._apply()

        with pytest.raises(CommandError, match=f"DROP INDEX CONCURRENTLY public.{self.index}") as error:
            self._apply()

        assert "INVALID" in str(error.value)
        assert len(self._recorded_migrations()) == 1
