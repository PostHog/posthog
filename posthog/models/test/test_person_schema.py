"""Verify that posthog_person table is properly partitioned by team_id."""

from django.db import connection
from django.test import TestCase


def table_exists(table_name: str) -> bool:
    """Check if a table exists."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = %s
            )
        """,
            [table_name],
        )
        return cursor.fetchone()[0]


def is_table_partitioned(table_name: str) -> bool:
    """Check if a table is partitioned."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT EXISTS (
                SELECT FROM pg_partitioned_table pt
                JOIN pg_class c ON pt.partrelid = c.oid
                WHERE c.relname = %s
            )
        """,
            [table_name],
        )
        return cursor.fetchone()[0]


def get_partition_strategy(table_name: str) -> str | None:
    """Get the partitioning strategy for a table (h = HASH, r = RANGE, l = LIST)."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT pt.partstrat
            FROM pg_partitioned_table pt
            JOIN pg_class c ON pt.partrelid = c.oid
            WHERE c.relname = %s
        """,
            [table_name],
        )
        result = cursor.fetchone()
        return result[0] if result else None


def get_partition_count(parent_table: str) -> int:
    """Count how many partitions exist for a parent table."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT COUNT(*)
            FROM pg_inherits i
            JOIN pg_class parent ON i.inhparent = parent.oid
            WHERE parent.relname = %s
        """,
            [parent_table],
        )
        return cursor.fetchone()[0]


class TestPersonSchemaConsistency(TestCase):
    """Verify posthog_person table structure created by sqlx migrations."""

    def test_posthog_person_exists(self):
        """Verify posthog_person table exists."""
        self.assertTrue(
            table_exists("posthog_person"),
            "posthog_person table does not exist. "
            "Rust sqlx migrations from rust/persons_migrations/ should have created it.",
        )

    def test_posthog_person_is_partitioned(self):
        """Verify posthog_person is a partitioned table."""
        self.assertTrue(
            is_table_partitioned("posthog_person"),
            "posthog_person should be a partitioned table. "
            "Sqlx migration 20251113000001_add_partitioned_person_table.sql should have created it.",
        )

    def test_posthog_person_uses_hash_partitioning(self):
        """Verify posthog_person uses HASH partitioning strategy."""
        strategy = get_partition_strategy("posthog_person")
        self.assertEqual(
            strategy,
            "h",
            f"posthog_person should use HASH partitioning (got '{strategy}'). "
            "Check sqlx migration 20251113000001_add_partitioned_person_table.sql.",
        )

    def test_posthog_person_has_64_partitions(self):
        """Verify posthog_person has 64 hash partitions."""
        count = get_partition_count("posthog_person")
        self.assertEqual(
            count,
            64,
            f"posthog_person should have 64 partitions (got {count}). "
            "Check sqlx migration 20251113000001_add_partitioned_person_table.sql.",
        )

    def test_partition_tables_exist(self):
        """Verify individual partition tables exist (spot check)."""
        # Check a few partitions exist
        for i in [0, 1, 31, 63]:
            self.assertTrue(
                table_exists(f"posthog_person_p{i}"),
                f"Partition posthog_person_p{i} does not exist. "
                "Sqlx migration should have created 64 partitions (p0 through p63).",
            )
