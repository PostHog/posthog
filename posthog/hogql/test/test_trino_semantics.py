from posthog.test.base import APIBaseTest

from posthog.schema import HogQLQueryModifiers

from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_and_print_ast

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

    def test_lazy_person_join_expands_before_trino_printing(self) -> None:
        modifiers = HogQLQueryModifiers(personsOnEventsMode=PersonsOnEventsMode.DISABLED)
        context = self._semantic_context(
            ["events", "raw_persons", "raw_person_distinct_ids", "raw_person_distinct_id_overrides"],
            modifiers,
        )

        sql, _ = prepare_and_print_ast(
            parse_select("SELECT person.properties.email FROM events"),
            context,
            "trino",
        )

        self.assertNotIn("person.properties.email", sql)
        self.assertIn('"ducklake"."analytics"."raw_persons"', sql)
        self.assertIn(" JOIN ", sql)
