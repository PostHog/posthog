from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from django.conf import settings
from django.test import SimpleTestCase

import psycopg
from parameterized import parameterized

from posthog.management.commands.apply_persons_migrations import NO_TRANSACTION_MARKER, TRACKING_TABLE, _apply_migration

_MIGRATIONS_DIR = Path(settings.BASE_DIR) / "rust" / "persons_migrations"


def _concurrent_migrations() -> list[tuple[str, str, bool]]:
    cases = []
    for path in sorted(_MIGRATIONS_DIR.glob("*.sql")):
        content = path.read_text()
        if "CONCURRENTLY" in content:
            cases.append((path.name, content, False))
    return cases


class _FakeCursor:
    def __init__(self, fail_on: str | None = None) -> None:
        self.executed: list[str] = []
        self._fail_on = fail_on

    def execute(self, query: str, params: Any = None) -> None:
        self.executed.append(query)
        if self._fail_on is not None and self._fail_on in query:
            raise psycopg.errors.QueryCanceled("canceling statement due to statement timeout")


class _FakeConnection:
    def __init__(self) -> None:
        self.transactions_opened = 0

    @contextmanager
    def transaction(self) -> Iterator[None]:
        self.transactions_opened += 1
        yield


class TestApplyPersonsMigrations(SimpleTestCase):
    @parameterized.expand(
        [
            *_concurrent_migrations(),
            ("unmarked migration", "ALTER TABLE lifecycle_op_person ADD COLUMN spare INT;\n", True),
        ]
    )
    def test_transaction_use_follows_the_no_transaction_marker(
        self, name: str, sql_content: str, expect_transaction: bool
    ) -> None:
        conn, cursor = _FakeConnection(), _FakeCursor()

        _apply_migration(conn, cursor, name, sql_content)

        assert conn.transactions_opened == (1 if expect_transaction else 0)
        assert sql_content in cursor.executed
        assert any(TRACKING_TABLE in query for query in cursor.executed)

    def test_a_marked_migration_that_fails_is_not_recorded(self) -> None:
        conn, cursor = _FakeConnection(), _FakeCursor(fail_on="CREATE INDEX CONCURRENTLY")
        sql_content = (
            f"{NO_TRANSACTION_MARKER}\nCREATE INDEX CONCURRENTLY some_index ON lifecycle_op_person (team_id);\n"
        )

        with pytest.raises(psycopg.errors.QueryCanceled):
            _apply_migration(conn, cursor, "some_migration.sql", sql_content)

        assert not any(TRACKING_TABLE in query for query in cursor.executed)
