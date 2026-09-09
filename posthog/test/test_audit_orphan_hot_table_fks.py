from django.db import connection
from django.test import TestCase

from posthog.management.commands.audit_orphan_hot_table_fks import find_orphan_fks, known_django_tables


class TestAuditOrphanHotTableFks(TestCase):
    def _create_orphan(self, table: str, deferrable: bool = True) -> None:
        clause = "DEFERRABLE INITIALLY DEFERRED" if deferrable else ""
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                CREATE TABLE {table} (
                    id serial PRIMARY KEY,
                    team_id integer NOT NULL REFERENCES posthog_team(id) {clause}
                )
                """
            )

    def test_reports_a_table_with_no_model_that_references_posthog_team(self):
        self._create_orphan("retired_feature_rows")

        found = {row["referencing_table"] for row in find_orphan_fks()}

        self.assertIn("retired_feature_rows", found)

    def test_records_the_constraint_and_that_it_is_deferred(self):
        self._create_orphan("retired_deferred_rows")

        row = next(r for r in find_orphan_fks() if r["referencing_table"] == "retired_deferred_rows")

        self.assertEqual(row["referenced_table"], "posthog_team")
        self.assertTrue(row["deferred"])

    def test_reports_an_immediate_constraint_as_not_deferred(self):
        self._create_orphan("retired_immediate_rows", deferrable=False)

        row = next(r for r in find_orphan_fks() if r["referencing_table"] == "retired_immediate_rows")

        self.assertFalse(row["deferred"])

    def test_ignores_tables_that_still_have_a_django_model(self):
        found = {row["referencing_table"] for row in find_orphan_fks()}

        self.assertNotIn("posthog_dashboard", found)
        self.assertTrue(found.isdisjoint(known_django_tables()))
