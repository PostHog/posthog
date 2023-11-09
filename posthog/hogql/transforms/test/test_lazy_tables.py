from typing import Any

import pytest
from django.test import override_settings

from posthog.hogql.context import HogQLContext
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import print_ast
from posthog.hogql.test.utils import pretty_print_in_tests
from posthog.test.base import BaseTest


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

    def _print_select(self, select: str):
        expr = parse_select(select)
        query = print_ast(
            expr,
            HogQLContext(team_id=self.team.pk, enable_select_queries=True),
            "clickhouse",
        )
        return pretty_print_in_tests(query, self.team.pk)
