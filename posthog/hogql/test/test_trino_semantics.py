from posthog.test.base import APIBaseTest

from django.test import SimpleTestCase

from posthog.schema import HogQLQueryModifiers

from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.errors import QueryError
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_and_print_ast
from posthog.hogql.property_access_types import RestrictedProperty
from posthog.hogql.transforms.trino.errors import TrinoLoweringError

from posthog.constants import AvailableFeature
from posthog.models import PropertyDefinition
from posthog.schema_enums import InCohortVia, InlineCohortCalculation, PersonsOnEventsMode

from products.access_control.backend.models.property_access_control import PropertyAccessControl
from products.access_control.backend.property_access_control import PropertyAccessLevel
from products.actions.backend.models.action import Action
from products.cohorts.backend.models.cohort import Cohort


class TestTrinoSemantics(APIBaseTest):
    def _semantic_context(
        self,
        table_names: list[str],
        modifiers: HogQLQueryModifiers | None = None,
    ) -> HogQLContext:
        modifiers = modifiers or HogQLQueryModifiers()
        if modifiers.personsOnEventsMode is None:
            modifiers.personsOnEventsMode = PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS
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

    def test_v2_events_person_fields_use_exported_properties_and_latest_person_mapping(self) -> None:
        context = self._semantic_context(["events", "persons"])

        sql, _ = prepare_and_print_ast(
            parse_select("SELECT person_id, person.id, person.properties.email FROM events"),
            context,
            "trino",
        )

        self.assertIn('"ducklake"."analytics"."events"', sql)
        self.assertIn('"ducklake"."analytics"."persons"', sql)
        self.assertIn('"events"."person_properties"', sql)
        self.assertNotIn("raw_persons", sql)
        self.assertNotIn("raw_person_distinct_ids", sql)
        self.assertNotIn("raw_person_distinct_id_overrides", sql)
        self.assertIn("person_distinct_id_version", sql)
        self.assertIn("person_version", sql)
        self.assertIn("_inserted_at", sql)

    def test_restricted_user_cannot_compile_any_trino_query(self) -> None:
        self.organization.available_product_features = [
            {
                "name": AvailableFeature.PROPERTY_ACCESS_CONTROL,
                "key": AvailableFeature.PROPERTY_ACCESS_CONTROL,
            }
        ]
        self.organization.save()
        self.team.organization.refresh_from_db()
        restricted_property = PropertyDefinition.objects.create(
            team=self.team,
            name="private_email",
            property_type="String",
            type=PropertyDefinition.Type.EVENT,
        )
        PropertyAccessControl.objects.create(
            team=self.team,
            property_definition=restricted_property,
            access_level=PropertyAccessLevel.NONE.value,
        )
        context = self._semantic_context(["events"])
        context.restricted_properties = None

        with self.assertRaisesRegex(TrinoLoweringError, "TRINO_RESTRICTED_PROPERTIES_UNSUPPORTED"):
            prepare_and_print_ast(parse_select("SELECT 1"), context, "trino")


class TestTrinoAccessControl(SimpleTestCase):
    def test_preloaded_restriction_rejects_query_without_property_reads(self) -> None:
        context = HogQLContext(
            database=Database(include_posthog_tables=True),
            enable_select_queries=True,
            modifiers=HogQLQueryModifiers(
                personsOnEventsMode=PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS
            ),
            restricted_properties={
                RestrictedProperty(
                    name="private_email",
                    property_type=PropertyDefinition.Type.EVENT,
                )
            },
        )

        with self.assertRaisesRegex(TrinoLoweringError, "TRINO_RESTRICTED_PROPERTIES_UNSUPPORTED"):
            prepare_and_print_ast(parse_select("SELECT 1"), context, "trino")


class TestTrinoPersonsSemantics(SimpleTestCase):
    def _context(self, modifiers: HogQLQueryModifiers | None = None) -> HogQLContext:
        return HogQLContext(
            database=Database(include_posthog_tables=True),
            modifiers=modifiers
            or HogQLQueryModifiers(personsOnEventsMode=PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS),
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
        self.assertNotIn("__trino_physical_persons", sql)
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

    def test_physical_persons_relation_is_not_addressable_by_hogql_name(self) -> None:
        context = self._context()

        with self.assertRaises(QueryError):
            prepare_and_print_ast(
                parse_select("SELECT id FROM __trino_physical_persons"),
                context,
                "trino",
            )

    def test_non_v2_persons_on_events_modes_fail_closed(self) -> None:
        for mode in (
            None,
            PersonsOnEventsMode.DISABLED,
            PersonsOnEventsMode.PERSON_ID_NO_OVERRIDE_PROPERTIES_ON_EVENTS,
            PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_JOINED,
        ):
            with self.subTest(mode=mode):
                context = self._context(HogQLQueryModifiers(personsOnEventsMode=mode))

                with self.assertRaisesRegex(
                    TrinoLoweringError,
                    "TRINO_PERSONS_ON_EVENTS_MODE_UNSUPPORTED",
                ):
                    prepare_and_print_ast(parse_select("SELECT 1"), context, "trino")
