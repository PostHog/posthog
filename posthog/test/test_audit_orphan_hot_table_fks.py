from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import TestCase

from posthog.management.commands.audit_orphan_hot_table_fks import find_orphan_fks, known_django_tables


class TestAuditOrphanHotTableFks(TestCase):
    def _create_orphan(self, table: str, deferrable: bool = True, on_delete: str = "") -> None:
        clause = "DEFERRABLE INITIALLY DEFERRED" if deferrable else ""
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                CREATE TABLE {table} (
                    id serial PRIMARY KEY,
                    team_id integer NOT NULL REFERENCES posthog_team(id) {on_delete} {clause}
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

    def test_ignores_a_constraint_postgres_clears_on_its_own(self):
        self._create_orphan("retired_cascade_rows", on_delete="ON DELETE CASCADE")
        self._create_orphan("retired_set_null_rows", on_delete="ON DELETE SET NULL")

        found = {row["referencing_table"] for row in find_orphan_fks()}

        self.assertNotIn("retired_cascade_rows", found)
        self.assertNotIn("retired_set_null_rows", found)

    def test_records_the_blocking_delete_action(self):
        self._create_orphan("retired_no_action_rows")

        row = next(r for r in find_orphan_fks() if r["referencing_table"] == "retired_no_action_rows")

        self.assertEqual(row["delete_action"], "a")

    def test_command_reports_findings_without_failing_by_default(self):
        self._create_orphan("retired_reported_rows")
        out = StringIO()

        call_command("audit_orphan_hot_table_fks", stdout=out)

        self.assertIn("retired_reported_rows", out.getvalue())

    def test_command_fails_when_asked_to_and_findings_exist(self):
        self._create_orphan("retired_alerting_rows")

        with self.assertRaises(CommandError):
            call_command("audit_orphan_hot_table_fks", "--fail-on-findings", stdout=StringIO())
