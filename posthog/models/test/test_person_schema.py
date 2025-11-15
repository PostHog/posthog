"""Smoke test that Rust sqlx migrations ran and created posthog_person_new table."""

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


class TestPersonSchemaConsistency(TestCase):
    """Smoke test that Rust sqlx migrations ran successfully."""

    def test_posthog_person_new_exists(self):
        """Verify posthog_person_new table was created by sqlx migrations."""
        self.assertTrue(
            table_exists("posthog_person_new"),
            "posthog_person_new table does not exist. "
            "Rust sqlx migrations from rust/persons_migrations/ should have created it.",
        )
