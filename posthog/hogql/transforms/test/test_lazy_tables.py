from typing import Any

import pytest
from posthog.test.base import BaseTest

from django.test import override_settings

from posthog.schema import HogQLQueryModifiers, PersonsOnEventsMode

from posthog.hogql.context import HogQLContext
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_and_print_ast
from posthog.hogql.test.utils import pretty_print_in_tests

from products.data_warehouse.backend.models.join import DataWarehouseJoin


class TestLazyJoins(BaseTest):
    snapshot: Any
    maxDiff = None

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_resolve_lazy_tables(self):
        printed = self._print_select("select event, pdi.person_id from events")
        assert printed == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    @override_settings(PERSON_ON_EVENTS_OVERRIDE=False, PERSON_ON_EVENTS_V2_OVERRIDE=False)
    def test_resolve_lazy_tables_traversed_fields(self):
        printed = self._print_select("select event, person_id from events")
        assert printed == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_resolve_lazy_tables_two_levels(self):
        printed = self._print_select("select event, pdi.person.id from events")
        assert printed == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    @override_settings(PERSON_ON_EVENTS_OVERRIDE=False, PERSON_ON_EVENTS_V2_OVERRIDE=False)
    def test_resolve_lazy_tables_two_levels_traversed(self):
        printed = self._print_select("select event, person.id from events")
        assert printed == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    @override_settings(PERSON_ON_EVENTS_OVERRIDE=False, PERSON_ON_EVENTS_V2_OVERRIDE=False)
    def test_resolve_lazy_tables_one_level_properties(self):
        printed = self._print_select("select person.properties.$browser from person_distinct_ids")
        assert printed == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    @override_settings(PERSON_ON_EVENTS_OVERRIDE=False, PERSON_ON_EVENTS_V2_OVERRIDE=False)
    def test_resolve_lazy_tables_one_level_properties_deep(self):
        printed = self._print_select("select person.properties.$browser.in.json from person_distinct_ids")
        assert printed == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_resolve_lazy_tables_two_levels_properties(self):
        printed = self._print_select("select event, pdi.person.properties.$browser from events")
        assert printed == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    @override_settings(PERSON_ON_EVENTS_OVERRIDE=False, PERSON_ON_EVENTS_V2_OVERRIDE=False)
    def test_resolve_lazy_tables_two_levels_properties_duplicate(self):
        printed = self._print_select("select event, person.properties, person.properties.name from events")
        assert printed == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    @override_settings(PERSON_ON_EVENTS_OVERRIDE=False, PERSON_ON_EVENTS_V2_OVERRIDE=False)
    def test_resolve_lazy_table_as_select_table(self):
        printed = self._print_select("select id, properties.email, properties.$browser from persons")
        assert printed == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    @override_settings(PERSON_ON_EVENTS_OVERRIDE=False, PERSON_ON_EVENTS_V2_OVERRIDE=False)
    def test_resolve_lazy_table_as_table_in_join(self):
        printed = self._print_select(
            "select event, distinct_id, events.person_id, persons.properties.email from events left join persons on persons.id = events.person_id limit 10"
        )
        assert printed == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_select_count_from_lazy_table(self):
        printed = self._print_select("select count() from persons")
        assert printed == self.snapshot

    def _print_select(self, select: str, modifiers: HogQLQueryModifiers | None = None):
        expr = parse_select(select)
        query, _ = prepare_and_print_ast(
            expr,
            HogQLContext(
                team_id=self.team.pk,
                enable_select_queries=True,
                modifiers=modifiers if modifiers is not None else HogQLQueryModifiers(),
            ),
            "clickhouse",
        )
        return pretty_print_in_tests(query, self.team.pk)

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_lazy_join_on_lazy_table(self):
        DataWarehouseJoin(
            team=self.team,
            source_table_name="cohort_people",
            source_table_key="person_id",
            joining_table_name="persons",
            joining_table_key="id",
            field_name="new_person",
        ).save()

        printed = self._print_select("select new_person.id from cohort_people")
        assert printed == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_lazy_join_on_lazy_table_with_properties(self):
        DataWarehouseJoin(
            team=self.team,
            source_table_name="cohort_people",
            source_table_key="person_id",
            joining_table_name="persons",
            joining_table_key="properties.email",
            field_name="new_person",
        ).save()

        printed = self._print_select("select new_person.id from cohort_people")
        assert printed == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_lazy_join_on_lazy_table_with_person_properties(self):
        DataWarehouseJoin(
            team=self.team,
            source_table_name="persons",
            source_table_key="properties.email",
            joining_table_name="events",
            joining_table_key="event",
            field_name="events",
        ).save()

        printed = self._print_select("select events.event from persons")
        assert printed == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_resolve_lazy_table_indirectly_referenced(self):
        # Ensures that the override table is added as a join, even when it is
        # only indirectly referenced in the query as part of the join constraint
        # of a lazy join.
        printed = self._print_select(
            "select person.id from events",
            HogQLQueryModifiers(personsOnEventsMode=PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_JOINED),
        )
        assert printed == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_resolve_lazy_table_indirect_duplicate_references(self):
        # Ensures that the override table is only joined one time, even when it
        # is referenced via two different selected columns.
        printed = self._print_select(
            "select person_id, person.properties from events",
            HogQLQueryModifiers(personsOnEventsMode=PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_JOINED),
        )
        assert printed == self.snapshot
