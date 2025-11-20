"""Verify that posthog_person table is properly partitioned by team_id."""

import pytest

from django.conf import settings
from django.db import connections
from django.test import TestCase

from posthog.models.person import Person


def table_exists(table_name: str) -> bool:
    """Check if a table exists in persons database."""
    # Use persons_db_writer connection since person tables are in separate database
    persons_conn = connections["persons_db_writer"]
    with persons_conn.cursor() as cursor:
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
    """Check if a table is partitioned in persons database."""
    # Use persons_db_writer connection since person tables are in separate database
    persons_conn = connections["persons_db_writer"]
    with persons_conn.cursor() as cursor:
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
    """Get the partitioning strategy for a table (h = HASH, r = RANGE, l = LIST) in persons database."""
    # Use persons_db_writer connection since person tables are in separate database
    persons_conn = connections["persons_db_writer"]
    with persons_conn.cursor() as cursor:
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
    """Count how many partitions exist for a parent table in persons database."""
    # Use persons_db_writer connection since person tables are in separate database
    persons_conn = connections["persons_db_writer"]
    with persons_conn.cursor() as cursor:
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
    """Verify person table structure created by sqlx migrations."""

    def test_person_table_exists(self):
        """Verify person table exists."""
        self.assertTrue(
            table_exists(settings.PERSON_TABLE_NAME),
            f"{settings.PERSON_TABLE_NAME} table does not exist. "
            "Rust sqlx migrations from rust/persons_migrations/ should have created it.",
        )

    def test_person_table_is_partitioned(self):
        """Verify person table is partitioned."""
        self.assertTrue(
            is_table_partitioned(settings.PERSON_TABLE_NAME),
            f"{settings.PERSON_TABLE_NAME} should be a partitioned table. "
            "Sqlx migration 20251113000001_add_partitioned_person_table.sql should have created it.",
        )

    def test_person_table_uses_hash_partitioning(self):
        """Verify person table uses HASH partitioning strategy."""
        strategy = get_partition_strategy(settings.PERSON_TABLE_NAME)
        self.assertEqual(
            strategy,
            "h",
            f"{settings.PERSON_TABLE_NAME} should use HASH partitioning (got '{strategy}'). "
            "Check sqlx migration 20251113000001_add_partitioned_person_table.sql.",
        )

    def test_person_table_has_64_partitions(self):
        """Verify person table has 64 hash partitions."""
        count = get_partition_count(settings.PERSON_TABLE_NAME)
        self.assertEqual(
            count,
            64,
            f"{settings.PERSON_TABLE_NAME} should have 64 partitions (got {count}). "
            "Check sqlx migration 20251113000001_add_partitioned_person_table.sql.",
        )

    def test_partition_tables_exist(self):
        """Verify individual partition tables exist (spot check)."""
        # Check a few partitions exist
        # Note: sqlx migration hardcodes partition names as posthog_person_p{i}
        # regardless of whether parent table is posthog_person or posthog_person_new
        for i in [0, 1, 31, 63]:
            partition_name = f"posthog_person_p{i}"
            self.assertTrue(
                table_exists(partition_name),
                f"Partition {partition_name} does not exist. "
                "Sqlx migration should have created 64 partitions (p0 through p63).",
            )

    def test_person_table_configuration(self):
        """Verify Person model uses the configured table name."""
        self.assertEqual(
            Person._meta.db_table,
            settings.PERSON_TABLE_NAME,
            f"Person model db_table '{Person._meta.db_table}' "
            f"does not match configured PERSON_TABLE_NAME '{settings.PERSON_TABLE_NAME}'",
        )

    @pytest.mark.skip(reason="This test should only be enabled if the PersonQuerySet is used")
    def test_person_queryset_enforces_team_id(self):
        """Verify Person queries raise ValueError when team_id filter is missing."""
        with self.assertRaises(ValueError) as cm:
            # This should raise because no team_id filter
            list(Person.objects.all())

        self.assertIn("team_id filter", str(cm.exception))
        self.assertIn("Partitioned table", str(cm.exception))

    @pytest.mark.skip(reason="This test should only be enabled if the PersonQuerySet is used")
    def test_person_delete_enforces_team_id(self):
        """Verify Person.delete() raises ValueError when team_id filter is missing."""
        with self.assertRaises(ValueError) as cm:
            Person.objects.all().delete()

        self.assertIn("delete query missing required team_id filter", str(cm.exception))
        self.assertIn("Partitioned table", str(cm.exception))

    @pytest.mark.skip(reason="This test should only be enabled if the PersonQuerySet is used")
    def test_person_update_enforces_team_id(self):
        """Verify Person.update() raises ValueError when team_id filter is missing."""
        with self.assertRaises(ValueError) as cm:
            Person.objects.all().update(properties={})

        self.assertIn("update query missing required team_id filter", str(cm.exception))
        self.assertIn("Partitioned table", str(cm.exception))
