from typing import NamedTuple
from posthog.hogql.modifiers import create_default_modifiers_for_team
from posthog.hogql.query import execute_hogql_query
from posthog.models import Cohort
from posthog.schema import HogQLQueryModifiers, PersonsArgMaxVersion, PersonsOnEventsMode, MaterializationMode
from posthog.test.base import BaseTest
from django.test import override_settings


class TestModifiers(BaseTest):
    @override_settings(PERSON_ON_EVENTS_OVERRIDE=False, PERSON_ON_EVENTS_V2_OVERRIDE=False)
    def test_create_default_modifiers_for_team_init(self):
        assert self.team.person_on_events_mode == "disabled"
        modifiers = create_default_modifiers_for_team(self.team)
        assert modifiers.personsOnEventsMode == PersonsOnEventsMode.disabled  # NB! not a None
        modifiers = create_default_modifiers_for_team(
            self.team,
            HogQLQueryModifiers(personsOnEventsMode=PersonsOnEventsMode.person_id_no_override_properties_on_events),
        )
        assert modifiers.personsOnEventsMode == PersonsOnEventsMode.person_id_no_override_properties_on_events
        modifiers = create_default_modifiers_for_team(
            self.team,
            HogQLQueryModifiers(personsOnEventsMode=PersonsOnEventsMode.person_id_override_properties_on_events),
        )
        assert modifiers.personsOnEventsMode == PersonsOnEventsMode.person_id_override_properties_on_events

    def test_team_modifiers_override(self):
        assert self.team.modifiers is None
        modifiers = create_default_modifiers_for_team(self.team)
        assert modifiers.personsOnEventsMode == self.team.default_modifiers["personsOnEventsMode"]
        assert modifiers.personsOnEventsMode == PersonsOnEventsMode.disabled  # the default mode

        self.team.modifiers = {"personsOnEventsMode": PersonsOnEventsMode.person_id_override_properties_on_events}
        self.team.save()
        modifiers = create_default_modifiers_for_team(self.team)
        assert modifiers.personsOnEventsMode == PersonsOnEventsMode.person_id_override_properties_on_events
        assert self.team.default_modifiers["personsOnEventsMode"] == PersonsOnEventsMode.disabled  # no change here

        self.team.modifiers = {"personsOnEventsMode": PersonsOnEventsMode.person_id_no_override_properties_on_events}
        self.team.save()
        modifiers = create_default_modifiers_for_team(self.team)
        assert modifiers.personsOnEventsMode == PersonsOnEventsMode.person_id_no_override_properties_on_events

    def test_modifiers_persons_on_events_mode_person_id_override_properties_on_events(self):
        query = "SELECT event, person_id FROM events"

        # Control
        response = execute_hogql_query(
            query,
            team=self.team,
            modifiers=HogQLQueryModifiers(personsOnEventsMode=PersonsOnEventsMode.disabled),
        )
        assert " JOIN " in response.clickhouse

        # Test
        response = execute_hogql_query(
            query,
            team=self.team,
            modifiers=HogQLQueryModifiers(
                personsOnEventsMode=PersonsOnEventsMode.person_id_no_override_properties_on_events
            ),
        )
        assert " JOIN " not in response.clickhouse

    def test_modifiers_persons_on_events_mode_mapping(self):
        query = "SELECT event, person.id, person.properties, person.created_at FROM events"

        class TestCase(NamedTuple):
            mode: PersonsOnEventsMode
            expected_columns: list[str]
            other_expected_values: list[str] = []

        test_cases: list[TestCase] = [
            TestCase(
                PersonsOnEventsMode.disabled,
                [
                    "events.event AS event",
                    "events__pdi__person.id AS id",
                    "events__pdi__person.properties AS properties",
                    "toTimeZone(events__pdi__person.created_at, %(hogql_val_0)s) AS created_at",
                ],
            ),
            TestCase(
                PersonsOnEventsMode.person_id_no_override_properties_on_events,
                [
                    "events.event AS event",
                    "events.person_id AS id",
                    "events.person_properties AS properties",
                    "toTimeZone(events.person_created_at, %(hogql_val_0)s) AS created_at",
                ],
            ),
            TestCase(
                PersonsOnEventsMode.person_id_override_properties_on_events,
                [
                    "events.event AS event",
                    "if(not(empty(events__override.distinct_id)), events__override.person_id, events.person_id) AS id",
                    "events.person_properties AS properties",
                    "toTimeZone(events.person_created_at, %(hogql_val_0)s) AS created_at",
                ],
                [
                    "events__override ON equals(events.distinct_id, events__override.distinct_id)",
                ],
            ),
            TestCase(
                PersonsOnEventsMode.person_id_override_properties_joined,
                [
                    "events.event AS event",
                    "events__person.id AS id",
                    "events__person.properties AS properties",
                    "toTimeZone(events__person.created_at, %(hogql_val_0)s) AS created_at",
                ],
                [
                    "events__person ON equals(if(not(empty(events__override.distinct_id)), events__override.person_id, events.person_id), events__person.id)",
                    "events__override ON equals(events.distinct_id, events__override.distinct_id)",
                ],
            ),
        ]

        for test_case in test_cases:
            clickhouse_query = execute_hogql_query(
                query,
                team=self.team,
                modifiers=HogQLQueryModifiers(personsOnEventsMode=test_case.mode),
                pretty=False,
            ).clickhouse
            assert clickhouse_query is not None
            assert (
                f"SELECT {', '.join(test_case.expected_columns)} FROM" in clickhouse_query
            ), f"PoE mode: {test_case.mode}"
            for value in test_case.other_expected_values:
                assert value in clickhouse_query

    def test_modifiers_persons_argmax_version_v2(self):
        query = "SELECT * FROM persons"

        # Control (v1)
        response = execute_hogql_query(
            query,
            team=self.team,
            modifiers=HogQLQueryModifiers(personsArgMaxVersion=PersonsArgMaxVersion.v1),
        )
        assert "in(tuple(person.id, person.version)" not in response.clickhouse

        # Test (v2)
        response = execute_hogql_query(
            query,
            team=self.team,
            modifiers=HogQLQueryModifiers(personsArgMaxVersion=PersonsArgMaxVersion.v2),
        )
        assert "in(tuple(person.id, person.version)" in response.clickhouse

    def test_modifiers_persons_argmax_version_auto(self):
        # Use the v2 query when selecting properties.x
        response = execute_hogql_query(
            "SELECT id, properties.$browser, is_identified FROM persons",
            team=self.team,
            modifiers=HogQLQueryModifiers(personsArgMaxVersion=PersonsArgMaxVersion.auto),
        )
        assert "in(tuple(person.id, person.version)" in response.clickhouse

        # Use the v2 query when selecting properties
        response = execute_hogql_query(
            "SELECT id, properties FROM persons",
            team=self.team,
            modifiers=HogQLQueryModifiers(personsArgMaxVersion=PersonsArgMaxVersion.auto),
        )
        assert "in(tuple(person.id, person.version)" in response.clickhouse

        # Use the v1 query when not selecting any properties
        response = execute_hogql_query(
            "SELECT id, is_identified FROM persons",
            team=self.team,
            modifiers=HogQLQueryModifiers(personsArgMaxVersion=PersonsArgMaxVersion.auto),
        )
        assert "in(tuple(person.id, person.version)" not in response.clickhouse

    def test_modifiers_in_cohort_join(self):
        cohort = Cohort.objects.create(team=self.team, name="test")
        response = execute_hogql_query(
            f"select * from persons where id in cohort {cohort.pk}",
            team=self.team,
            modifiers=HogQLQueryModifiers(inCohortVia="subquery"),
        )
        assert "LEFT JOIN" not in response.clickhouse

        # Use the v1 query when not selecting any properties
        response = execute_hogql_query(
            f"select * from persons where id in cohort {cohort.pk}",
            team=self.team,
            modifiers=HogQLQueryModifiers(inCohortVia="leftjoin"),
        )
        assert "LEFT JOIN" in response.clickhouse

    def test_modifiers_materialization_mode(self):
        try:
            from ee.clickhouse.materialized_columns.analyze import materialize
        except ModuleNotFoundError:
            # EE not available? Assume we're good
            self.assertEqual(1 + 2, 3)
            return
        materialize("events", "$browser")

        response = execute_hogql_query(
            "SELECT properties.$browser FROM events",
            team=self.team,
            modifiers=HogQLQueryModifiers(materializationMode=MaterializationMode.auto),
            pretty=False,
        )
        assert (
            "SELECT nullIf(nullIf(events.`mat_$browser`, ''), 'null') AS `$browser` FROM events" in response.clickhouse
        )

        response = execute_hogql_query(
            "SELECT properties.$browser FROM events",
            team=self.team,
            modifiers=HogQLQueryModifiers(materializationMode=MaterializationMode.legacy_null_as_null),
            pretty=False,
        )
        assert (
            "SELECT nullIf(nullIf(events.`mat_$browser`, ''), 'null') AS `$browser` FROM events" in response.clickhouse
        )

        response = execute_hogql_query(
            "SELECT properties.$browser FROM events",
            team=self.team,
            modifiers=HogQLQueryModifiers(materializationMode=MaterializationMode.legacy_null_as_string),
            pretty=False,
        )
        assert "SELECT nullIf(events.`mat_$browser`, '') AS `$browser` FROM events" in response.clickhouse

        response = execute_hogql_query(
            "SELECT properties.$browser FROM events",
            team=self.team,
            modifiers=HogQLQueryModifiers(materializationMode=MaterializationMode.disabled),
            pretty=False,
        )
        assert (
            "SELECT replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(events.properties, %(hogql_val_0)s), ''), 'null'), '^\"|\"$', '') AS `$browser` FROM events"
            in response.clickhouse
        )
