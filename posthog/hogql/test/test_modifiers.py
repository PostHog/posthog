from posthog.hogql.modifiers import create_default_modifiers_for_team
from posthog.hogql.query import execute_hogql_query
from posthog.schema import HogQLQueryModifiers
from posthog.test.base import BaseTest
from django.test import override_settings
from posthog.utils import PersonOnEventsMode


class TestModifiers(BaseTest):
    @override_settings(PERSON_ON_EVENTS_OVERRIDE=False, PERSON_ON_EVENTS_V2_OVERRIDE=False)
    def test_create_default_modifiers_for_team_init(self):
        assert self.team.person_on_events_mode == "disabled"
        modifiers = create_default_modifiers_for_team(self.team)
        assert modifiers.personsOnEventsMode == PersonOnEventsMode.DISABLED  # NB! not a None
        modifiers = create_default_modifiers_for_team(
            self.team, HogQLQueryModifiers(personsOnEventsMode=PersonOnEventsMode.V1_ENABLED)
        )
        assert modifiers.personsOnEventsMode == PersonOnEventsMode.V1_ENABLED
        modifiers = create_default_modifiers_for_team(
            self.team, HogQLQueryModifiers(personsOnEventsMode=PersonOnEventsMode.V2_ENABLED)
        )
        assert modifiers.personsOnEventsMode == PersonOnEventsMode.V2_ENABLED

    def test_modifiers_person_on_events_mode_v1_enabled(self):
        query = "SELECT event, person_id FROM events"

        # Control
        response = execute_hogql_query(
            query, team=self.team, modifiers=HogQLQueryModifiers(personsOnEventsMode=PersonOnEventsMode.DISABLED)
        )
        assert " JOIN " in response.clickhouse

        # Test
        response = execute_hogql_query(
            query, team=self.team, modifiers=HogQLQueryModifiers(personsOnEventsMode=PersonOnEventsMode.V1_ENABLED)
        )
        assert " JOIN " not in response.clickhouse
