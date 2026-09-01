from posthog.test.base import APIBaseTest

from django.test import SimpleTestCase

from posthog.schema import HogQLQueryModifiers

from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.errors import QueryError
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_and_print_ast
from posthog.hogql.transforms.trino.errors import TrinoLoweringError

from posthog.schema_enums import InCohortVia, InlineCohortCalculation, PersonsOnEventsMode

from products.actions.backend.models.action import Action
from products.cohorts.backend.models.cohort import Cohort


class TestTrinoSemantics(APIBaseTest):
    def _semantic_context(
        self,
        table_names: list[str],
        modifiers: HogQLQueryModifiers | None = None,
    ) -> HogQLContext:
        modifiers = modifiers or HogQLQueryModifiers()
        return HogQLContext(
            team_id=self.team.pk,
            team=self.team,
            user=self.user,
            database=Database.create_for(
                self.team.pk,
                team=self.team,
                user=self.user,
                modifiers=modifiers,
            ),
            modifiers=modifiers,
            enable_select_queries=True,
            limit_top_select=False,
            restricted_properties=set(),
            use_new_events_schema=False,
            apply_events_retention_floor=False,
            trino_table_locators={name: ("ducklake", "analytics", name) for name in table_names},
        )

    def test_action_semantics_expand_before_trino_printing(self) -> None:
        action = Action.objects.create(
            team=self.team,
            name="completed checkout",
            steps_json=[{"event": "checkout completed"}],
        )
        context = self._semantic_context(["events"])

        sql, _ = prepare_and_print_ast(
            parse_select(f"SELECT event FROM events WHERE matchesAction({action.pk})"),
            context,
            "trino",
        )

        self.assertNotIn("matchesAction", sql)
        self.assertIn('"ducklake"."analytics"."events"', sql)
        self.assertIn("checkout completed", context.values.values())

    def test_cohort_semantics_expand_before_trino_printing(self) -> None:
        cohort = Cohort.objects.create(team=self.team, name="active accounts")
        modifiers = HogQLQueryModifiers(
            inCohortVia=InCohortVia.SUBQUERY,
            inlineCohortCalculation=InlineCohortCalculation.OFF,
        )
        context = self._semantic_context(
            ["events", "raw_cohort_people", "raw_person_distinct_id_overrides"],
            modifiers,
        )

        sql, _ = prepare_and_print_ast(
            parse_select(f"SELECT person_id FROM events WHERE person_id IN COHORT {cohort.pk}"),
            context,
            "trino",
        )

        self.assertNotIn("COHORT", sql)
        self.assertIn('"ducklake"."analytics"."raw_cohort_people"', sql)


class TestTrinoPersonsSemantics(SimpleTestCase):
    def _context(self, modifiers: HogQLQueryModifiers | None = None) -> HogQLContext:
        return HogQLContext(
            database=Database(include_posthog_tables=True),
            modifiers=modifiers or HogQLQueryModifiers(),
            enable_select_queries=True,
            trino_table_locators={
                "events": ("ducklake", "analytics", "events_production"),
                "persons": ("ducklake", "analytics", "persons_production"),
            },
        )

    def test_logical_persons_table_deduplicates_latest_person_versions(self) -> None:
        context = self._context()

        sql, _ = prepare_and_print_ast(
            parse_select("SELECT id, properties.email FROM persons"),
            context,
            "trino",
        )

        self.assertIn('"ducklake"."analytics"."persons_production"', sql)
        self.assertNotIn("raw_persons", sql)
        self.assertIn("GROUP BY", sql)
        self.assertIn("max_by", sql)
        self.assertIn("person_version", sql)
        self.assertIn("_inserted_at", sql)

    def test_logical_persons_table_rejects_unexported_fields(self) -> None:
        context = self._context()

        with self.assertRaisesRegex(QueryError, "Last seen is not available for managed warehouse queries"):
            prepare_and_print_ast(
                parse_select("SELECT last_seen_at FROM persons"),
                context,
                "trino",
            )

    def test_logical_persons_pdi_uses_physical_persons_table(self) -> None:
        context = self._context()

        sql, _ = prepare_and_print_ast(
            parse_select("SELECT pdi.distinct_id FROM persons"),
            context,
            "trino",
        )

        self.assertIn('"ducklake"."analytics"."persons_production"', sql)
        self.assertNotIn("raw_person_distinct_ids", sql)
        self.assertIn("person_distinct_id_version", sql)
        self.assertIn("_inserted_at", sql)

    def test_internal_persons_relation_cannot_bypass_logical_lowering(self) -> None:
        context = self._context()

        with self.assertRaisesRegex(TrinoLoweringError, "TRINO_INTERNAL_TABLE_UNAVAILABLE"):
            prepare_and_print_ast(
                parse_select("SELECT id FROM __trino_physical_persons"),
                context,
                "trino",
            )

    def test_lazy_person_join_uses_physical_persons_table(self) -> None:
        context = self._context(HogQLQueryModifiers(personsOnEventsMode=PersonsOnEventsMode.DISABLED))

        sql, _ = prepare_and_print_ast(
            parse_select("SELECT person.properties.email FROM events"),
            context,
            "trino",
        )

        self.assertNotIn("person.properties.email", sql)
        self.assertIn('"ducklake"."analytics"."persons_production"', sql)
        self.assertNotIn("raw_persons", sql)
        self.assertNotIn("raw_person_distinct_ids", sql)
        self.assertNotIn("raw_person_distinct_id_overrides", sql)
        self.assertIn("GROUP BY", sql)
        self.assertIn("max_by", sql)
        self.assertIn("person_distinct_id_version", sql)
        self.assertIn("person_version", sql)
        self.assertIn("_inserted_at", sql)
        self.assertIn(" JOIN ", sql)
