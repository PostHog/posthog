import pytest

from posthog.management.commands.apply_persons_migrations import (
    TRACKING_TABLE,
    _ensure_tracking_table,
    _record_migration,
)
from posthog.persons_db import persons_db_connection

pytestmark = pytest.mark.persons_db_direct


class TestRecordMigration:
    SENTINEL = "99999999999999_test_record_migration_idempotency.sql"

    def _cleanup(self) -> None:
        with persons_db_connection(writer=True, autocommit=True) as conn, conn.cursor() as cursor:
            cursor.execute(f"DELETE FROM {TRACKING_TABLE} WHERE filename = %s", [self.SENTINEL])

    def test_record_migration_is_idempotent(self):
        self._cleanup()
        try:
            with persons_db_connection(writer=True, autocommit=True) as conn, conn.cursor() as cursor:
                _ensure_tracking_table(cursor)
                _record_migration(cursor, self.SENTINEL)
                # Recording the same migration again (as a concurrent runner would) must not raise
                # UniqueViolation and must not create a duplicate tracking row.
                _record_migration(cursor, self.SENTINEL)

                cursor.execute(f"SELECT COUNT(*) FROM {TRACKING_TABLE} WHERE filename = %s", [self.SENTINEL])
                assert cursor.fetchone()[0] == 1
        finally:
            self._cleanup()
