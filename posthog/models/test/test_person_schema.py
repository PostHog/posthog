"""Smoke test that Rust sqlx migrations ran and created posthog_person_new table."""

import pytest

from django.conf import settings
from django.db import connection
from django.test import TestCase

from posthog.models.person import Person


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
