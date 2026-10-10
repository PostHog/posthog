from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

import pytest

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase

import psycopg
from parameterized import parameterized

from posthog.management.commands.apply_persons_migrations import (
    HOBBY_ONLY_MIGRATIONS_DIR,
    TRACKING_TABLE,
    _concurrent_index_target,
    _holds_multiple_statements,
    _runs_outside_transaction,
)
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


class TestMultipleStatementDetection(SimpleTestCase):
    @parameterized.expand(
        [
            ("single_statement", "CREATE INDEX CONCURRENTLY i ON t (c);", False),
            ("semicolon_in_a_string_literal", "CREATE INDEX CONCURRENTLY i ON t (c) WHERE v = ';';", False),
            ("trailing_comment", "CREATE INDEX CONCURRENTLY i ON t (c);\n-- recovery note\n", False),
            (
                "comment_marker_in_a_string_literal",
                "CREATE INDEX CONCURRENTLY i ON t (c) WHERE v = '--x'; CREATE INDEX j ON t (d);",
                True,
            ),
            ("two_statements", "CREATE TABLE t (id INT);\nCREATE INDEX CONCURRENTLY i ON t (id);", True),
        ]
    )
    def test_statement_counting(self, _name: str, sql_content: str, expected: bool) -> None:
        assert _holds_multiple_statements(sql_content) is expected


class TestConcurrentIndexTarget(SimpleTestCase):
    @parameterized.expand(
        [
            ("create", "CREATE INDEX CONCURRENTLY IF NOT EXISTS i ON t (c);", "i"),
            ("create_below_a_comment_block", "-- no-transaction\n-- why\nCREATE INDEX CONCURRENTLY i ON t (c);", "i"),
            ("create_unique_over_two_lines", "CREATE UNIQUE INDEX CONCURRENTLY Mixed\n    ON t (c);", "mixed"),
            ("create_with_a_quoted_name", 'CREATE INDEX CONCURRENTLY "Mixed" ON t (c);', "Mixed"),
            (
                "create_with_a_doubled_quote_in_the_quoted_name",
                'CREATE UNIQUE INDEX CONCURRENTLY "Mixed""unique" ON t (c);',
                'Mixed"unique',
            ),
            ("create_without_a_name", "CREATE INDEX CONCURRENTLY ON t (c);", None),
            ("drop", "DROP INDEX CONCURRENTLY IF EXISTS i;", None),
        ]
    )
    def test_target_parsing(self, _name: str, sql_content: str, expected: str | None) -> None:
        assert _concurrent_index_target(sql_content) == expected


class TestApplyPersonsMigrations(TestCase):
    def setUp(self) -> None:
        super().setUp()
        self.suffix = uuid4().hex[:8]
        self.table = f"no_tx_test_{self.suffix}"
        self.index = f"no_tx_test_{self.suffix}_idx"
        self.other_table = f"no_tx_test_{self.suffix}_other"
        self.other_index = f"no_tx_test_{self.suffix}_other_idx"
        self._migrations_tmp = TemporaryDirectory()
        self.migrations_dir = Path(self._migrations_tmp.name)

    def tearDown(self) -> None:
        _persons_execute(
            [
                f"DROP INDEX CONCURRENTLY IF EXISTS {self.index}",
                f"DROP INDEX CONCURRENTLY IF EXISTS {self.other_index}",
                f"DROP TABLE IF EXISTS {self.table}",
                f"DROP TABLE IF EXISTS {self.other_table}",
                f"DELETE FROM {TRACKING_TABLE} WHERE filename LIKE '%{self.suffix}%'",
            ]
        )
        self._migrations_tmp.cleanup()
        super().tearDown()

    def _write_migration(self, version: str, name: str, body: str, subdir: str = "") -> None:
        directory = self.migrations_dir / subdir
        directory.mkdir(exist_ok=True)
        (directory / f"{version}_{self.suffix}_{name}.sql").write_text(body)

    def _copy_hobby_migrations_onto_test_table(self) -> None:
        source = Path(settings.BASE_DIR) / "rust" / "persons_migrations" / HOBBY_ONLY_MIGRATIONS_DIR
        for sql_file in sorted(source.glob("*.sql")):
            version, name = sql_file.stem.split("_", 1)
            body = sql_file.read_text().replace("posthog_person", self.table)
            self._write_migration(version, name, body, subdir=HOBBY_ONLY_MIGRATIONS_DIR)

    def _apply(self, *args: str) -> None:
        call_command("apply_persons_migrations", "--migrations-dir", str(self.migrations_dir), *args)

    def _leave_an_invalid_index(self, table: str, index: str) -> None:
        _persons_execute([f"CREATE TABLE {table} (id INT)", f"INSERT INTO {table} (id) VALUES (1), (1)"])
        with pytest.raises(psycopg.Error):
            _persons_execute([f"CREATE UNIQUE INDEX CONCURRENTLY {index} ON {table} (id)"])

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

    def test_applies_a_marked_migration_while_an_unrelated_index_is_invalid(self) -> None:
        self._leave_an_invalid_index(self.other_table, self.other_index)
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

    def test_applies_a_concurrent_drop_of_an_invalid_index(self) -> None:
        self._leave_an_invalid_index(self.table, self.index)
        self._write_migration(
            "20990101000001",
            "drop_index",
            f"-- no-transaction\nDROP INDEX CONCURRENTLY IF EXISTS {self.index};",
        )

        self._apply()

        assert _persons_fetchall("SELECT to_regclass(%s) IS NULL", [self.index]) == [(True,)]
        assert self._recorded_migrations() == [f"20990101000001_{self.suffix}_drop_index.sql"]

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

    @parameterized.expand([("hobby", ["--hobby"], 2), ("not_hobby", [], 1)])
    def test_applies_hobby_only_migrations_only_on_hobby(self, _name: str, args: list[str], expected: int) -> None:
        self._write_migration("20990101000001", "create_table", f"CREATE TABLE {self.table} (id INT);")
        self._write_migration(
            "20990101000002",
            "add_column",
            f"ALTER TABLE {self.table} ADD COLUMN extra INT;",
            subdir=HOBBY_ONLY_MIGRATIONS_DIR,
        )

        self._apply(*args)

        assert len(self._recorded_migrations()) == expected

    def test_hobby_migrations_give_an_unpartitioned_person_table_the_upsert_arbiter(self) -> None:
        self._write_migration(
            "20000101000001",
            "create_table",
            f"CREATE TABLE {self.table} (id SERIAL PRIMARY KEY, team_id INT NOT NULL, uuid UUID NOT NULL);",
        )
        self._copy_hobby_migrations_onto_test_table()

        self._apply("--hobby")

        person_uuid = str(uuid4())
        upsert = f"INSERT INTO {self.table} (team_id, uuid) VALUES (1, %s) ON CONFLICT (team_id, uuid) DO NOTHING"
        with persons_db_connection(writer=True, autocommit=True) as conn, conn.cursor() as cursor:
            cursor.execute(upsert, [person_uuid])
            cursor.execute(upsert, [person_uuid])
        assert _persons_fetchall(f"SELECT count(*) FROM {self.table}") == [(1,)]

    def test_hobby_migrations_stop_with_a_clear_message_on_duplicate_person_uuids(self) -> None:
        person_uuid = str(uuid4())
        self._write_migration(
            "20000101000001",
            "create_table",
            f"CREATE TABLE {self.table} (id SERIAL PRIMARY KEY, team_id INT NOT NULL, uuid UUID NOT NULL); "
            f"INSERT INTO {self.table} (team_id, uuid) VALUES (1, '{person_uuid}'), (1, '{person_uuid}');",
        )
        self._copy_hobby_migrations_onto_test_table()

        with pytest.raises(psycopg.Error, match=r"1 duplicate \(team_id, uuid\) pair"):
            self._apply("--hobby")

        assert _persons_fetchall("SELECT count(*) FROM pg_indexes WHERE tablename = %s", [self.table]) == [(1,)]
        assert len(self._recorded_migrations()) == 1
