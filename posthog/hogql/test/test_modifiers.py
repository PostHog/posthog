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
            HogQLQueryModifiers(personsOnEventsMode=PersonsOnEventsMode.v1_enabled),
        )
        assert modifiers.personsOnEventsMode == PersonsOnEventsMode.v1_enabled
        modifiers = create_default_modifiers_for_team(
            self.team,
            HogQLQueryModifiers(personsOnEventsMode=PersonsOnEventsMode.v2_enabled),
        )
        assert modifiers.personsOnEventsMode == PersonsOnEventsMode.v2_enabled

    def test_modifiers_persons_on_events_mode_v1_enabled(self):
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
            modifiers=HogQLQueryModifiers(personsOnEventsMode=PersonsOnEventsMode.v1_enabled),
        )
        assert " JOIN " not in response.clickhouse

    def test_modifiers_persons_on_events_mode_mapping(self):
        query = "SELECT event, person.id, person.properties, person.created_at FROM events"

        test_cases = [
            (
                PersonsOnEventsMode.disabled,
                "events.event AS event",
                "events__pdi__person.id AS id",
                "events__pdi__person.properties AS properties",
                "toTimeZone(events__pdi__person.created_at, %(hogql_val_0)s) AS created_at",
            ),
            (
                PersonsOnEventsMode.v1_enabled,
                "events.event AS event",
                "events.person_id AS id",
                "events.person_properties AS properties",
                "toTimeZone(events.person_created_at, %(hogql_val_0)s) AS created_at",
            ),
            (
                PersonsOnEventsMode.v1_mixed,
                "events.event AS event",
                "events__pdi.person_id AS id",
                "events.person_properties AS properties",
                "toTimeZone(events__pdi__person.created_at, %(hogql_val_0)s) AS created_at",
            ),
            (
                PersonsOnEventsMode.v2_enabled,
                "events.event AS event",
                "ifNull(nullIf(events__override.override_person_id, %(hogql_val_0)s), events.person_id) AS id",
                "events.person_properties AS properties",
                "toTimeZone(events.person_created_at, %(hogql_val_1)s) AS created_at",
            ),
        ]

        for mode, *expected in test_cases:
            response = execute_hogql_query(
                query,
                team=self.team,
                modifiers=HogQLQueryModifiers(personsOnEventsMode=mode),
            )
            assert f"SELECT {', '.join(expected)} FROM" in response.clickhouse, f"PoE mode: {mode}"

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
        )
        assert (
            "SELECT nullIf(nullIf(events.`mat_$browser`, ''), 'null') AS `$browser` FROM events" in response.clickhouse
        )

        response = execute_hogql_query(
            "SELECT properties.$browser FROM events",
            team=self.team,
            modifiers=HogQLQueryModifiers(materializationMode=MaterializationMode.legacy_null_as_null),
        )
        assert (
            "SELECT nullIf(nullIf(events.`mat_$browser`, ''), 'null') AS `$browser` FROM events" in response.clickhouse
        )

        response = execute_hogql_query(
            "SELECT properties.$browser FROM events",
            team=self.team,
            modifiers=HogQLQueryModifiers(materializationMode=MaterializationMode.legacy_null_as_string),
        )
        assert "SELECT nullIf(events.`mat_$browser`, '') AS `$browser` FROM events" in response.clickhouse

        response = execute_hogql_query(
            "SELECT properties.$browser FROM events",
            team=self.team,
            modifiers=HogQLQueryModifiers(materializationMode=MaterializationMode.disabled),
        )
        assert (
            "SELECT replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(events.properties, %(hogql_val_0)s), ''), 'null'), '^\"|\"$', '') AS `$browser` FROM events"
            in response.clickhouse
        )
