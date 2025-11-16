"""Smoke test that Rust sqlx migrations ran and created the partitioned person table."""

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
                SELECT FROM pg_tables
                WHERE schemaname = 'public' AND tablename = %s AND tableowner = 'postgres'
            )
        """,
            [table_name],
        )
        result = cursor.fetchone()
        if result[0]:
            # Check if it has partitions
            cursor.execute(
                """
                SELECT COUNT(*) FROM pg_partitioned_table
                WHERE relid = %s::regclass
            """,
                [f"public.{table_name}"],
            )
            return cursor.fetchone()[0] > 0
        return False


def get_table_primary_key(table_name: str) -> list[str]:
    """Get primary key columns of a table."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT a.attname
            FROM pg_index i
            JOIN pg_attribute a ON a.attrelid = i.indrelid
                AND a.attnum = ANY(i.indkey)
            WHERE i.indrelid = %s::regclass
                AND i.indisprimary
            ORDER BY a.attnum
        """,
            [f"public.{table_name}"],
        )
        return [row[0] for row in cursor.fetchall()]


class TestPersonSchemaConsistency(TestCase):
    """Smoke test that Rust sqlx migrations ran successfully."""

    def test_posthog_person_table_exists(self):
        """Verify posthog_person table exists (created by sqlx migrations)."""
        self.assertTrue(
            table_exists("posthog_person"),
            "posthog_person table does not exist. "
            "Rust sqlx migrations from rust/persons_migrations/ should have created it.",
        )

    def test_posthog_person_is_partitioned(self):
        """Verify posthog_person table is partitioned."""
        self.assertTrue(
            is_table_partitioned("posthog_person"),
            "posthog_person table is not partitioned. "
            "The swap migration (20251116000001) should have renamed posthog_person_new to posthog_person.",
        )

    def test_posthog_person_has_composite_primary_key(self):
        """Verify posthog_person has composite PK (team_id, id) from partitioned schema."""
        pk_columns = get_table_primary_key("posthog_person")
        self.assertEqual(
            pk_columns,
            ["team_id", "id"],
            f"Expected composite primary key (team_id, id) but got {pk_columns}. "
            "This indicates the table wasn't properly swapped to the partitioned schema.",
        )

    def test_posthog_person_new_placeholder_exists(self):
        """Verify posthog_person_new placeholder table exists for compatibility."""
        self.assertTrue(
            table_exists("posthog_person_new"),
            "posthog_person_new placeholder table does not exist. "
            "The swap migration should have created this for backward compatibility.",
        )
