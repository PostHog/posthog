from posthog.hogql.modifiers import create_default_modifiers_for_team
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query
from posthog.models import Person, Team
from posthog.schema import PersonsOnEventsMode, HogQLQueryModifiers
from posthog.test.base import (
    ClickhouseTestMixin,
    APIBaseTest,
    _create_person,
    _create_event,
    snapshot_clickhouse_queries,
    also_test_with_materialized_columns,
    QueryMatchingTest,
)


def _person_with_pageview(distinct_id: str, team: Team, person_properties: dict | None = None) -> Person:
    person = _create_person(
        distinct_ids=[distinct_id],
        team=team,
        properties=person_properties,
    )
    _create_event(
        event="$pageview",
        team=team,
        distinct_id=distinct_id,
    )
    return person


class TestPersonNotContainsPersonOnEvents(ClickhouseTestMixin, APIBaseTest, QueryMatchingTest):
    def setUp(self):
        super().setUp()

        self._distinct_id = "TestPersonNotContainsPersonOnEvents-distinct-id"
        self._person = _person_with_pageview(self._distinct_id, self.team, {"email": "my-example@gmail.com"})
        _person_with_pageview("TestPersonNotContainsPersonOnEvents-distinct_id_with_no_email", self.team, {})

        self._modifiers = create_default_modifiers_for_team(
            self.team,
            HogQLQueryModifiers(personsOnEventsMode=PersonsOnEventsMode.PERSON_ID_NO_OVERRIDE_PROPERTIES_ON_EVENTS),
        )

    @snapshot_clickhouse_queries
    @also_test_with_materialized_columns(person_properties=["email"])
    def test_can_filter_by_not_contains_and_get_no_results(self) -> None:
        generated_query = parse_select(
            """
            SELECT person_id, distinct_id
            FROM events
            WHERE person.properties.email NOT LIKE '%@gmail.com%'
            """,
        )

        response = execute_hogql_query(generated_query, self.team, modifiers=self._modifiers)
        assert response.results == []

    @snapshot_clickhouse_queries
    @also_test_with_materialized_columns(person_properties=["email"])
    def test_can_filter_by_not_contains_and_get_results(self) -> None:
        generated_query = parse_select(
            """
            SELECT person_id, distinct_id
            FROM events
            WHERE person.properties.email NOT LIKE '%@hotmail.com%'
            """,
        )

        response = execute_hogql_query(generated_query, self.team, modifiers=self._modifiers)
        assert response.results == [(self._person.uuid, self._distinct_id)]


class TestPersonsNotContainsOnEmail(ClickhouseTestMixin, APIBaseTest, QueryMatchingTest):
    def setUp(self):
        super().setUp()

        self._distinct_id = "TestPersonsNotContainsOnEmail-distinct-id"
        self._person = _person_with_pageview(self._distinct_id, self.team, {"email": "my-example@gmail.com"})

        _person_with_pageview("TestPersonsNotContainsOnEmail-distinct_id_with_no_email", self.team, {})

    @snapshot_clickhouse_queries
    @also_test_with_materialized_columns(person_properties=["email"])
    def test_can_filter_by_not_contains_and_get_no_results(self) -> None:
        generated_query = parse_select(
            """
            SELECT person_id, distinct_id
            FROM events
            WHERE person.properties.email NOT LIKE '%@gmail.com%'
            """
        )

        response = execute_hogql_query(generated_query, self.team)
        assert response.results == []

    @snapshot_clickhouse_queries
    @also_test_with_materialized_columns(person_properties=["email"])
    def test_can_filter_by_not_contains_and_get_results(self) -> None:
        generated_query = parse_select(
            """
            SELECT person_id, distinct_id
            FROM events
            WHERE person.properties.email NOT LIKE '%@hotmail.com%'
            """,
        )

        response = execute_hogql_query(generated_query, self.team)
        assert response.results == [(self._person.uuid, self._distinct_id)]
