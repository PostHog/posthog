from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_person,
    _create_event,
    snapshot_clickhouse_queries,
)
from posthog.models.person.util import create_person
from datetime import datetime


class TestPersonOptimization(ClickhouseTestMixin, APIBaseTest):
    """
    Mostly tests for the optimization of pre-filtering before aggregating. See https://github.com/PostHog/posthog/pull/25604
    """

    def setUp(self):
        super().setUp()
        self.first_person = _create_person(
            team_id=self.team.pk,
            distinct_ids=["1"],
            properties={"$some_prop": "something", "$another_prop": "something1"},
            created_at=datetime(2024, 1, 1, 12),
        )
        self.second_person = _create_person(
            team_id=self.team.pk,
            properties={"$some_prop": "ifwematcholdversionsthiswillmatch", "$another_prop": "something2"},
            distinct_ids=["2"],
            version=1,
            created_at=datetime(2024, 1, 1, 13),
        )
        # update second_person with the correct prop
        create_person(
            team_id=self.team.pk,
            uuid=str(self.second_person.uuid),
            properties={"$some_prop": "something", "$another_prop": "something2"},
            created_at=datetime(2024, 1, 1, 13),
            version=2,
        )
        self.third_person = _create_person(
            team_id=self.team.pk,
            distinct_ids=["3"],
            properties={"$some_prop": "not something", "$another_prop": "something3"},
            created_at=datetime(2024, 1, 1, 14),
        )
        # deleted
        self.deleted_person = _create_person(
            team_id=self.team.pk,
            properties={"$some_prop": "ifwematcholdversionsthiswillmatch", "$another_prop": "something2"},
            distinct_ids=["deleted"],
            created_at=datetime(2024, 1, 1, 13),
            version=1,
        )
        create_person(team_id=self.team.pk, uuid=str(self.deleted_person.uuid), version=2, is_deleted=True)

    @snapshot_clickhouse_queries
    def test_simple_filter(self):
        response = execute_hogql_query(
            parse_select("select id, properties.$some_prop from persons where properties.$some_prop = 'something'"),
            self.team,
        )
        assert len(response.results) == 2

    @snapshot_clickhouse_queries
    def test_alias(self):
        # This isn't supported by the WhereClauseExtractor yet
        response = execute_hogql_query(
            parse_select(
                "select id, an_alias.properties.email from persons as an_alias where an_alias.properties.$some_prop = 'something'"
            ),
            self.team,
        )
        assert len(response.results) == 2

    @snapshot_clickhouse_queries
    def test_subquery_alias(self):
        _create_event(event="$pageview", distinct_id="3", team=self.team)
        response = execute_hogql_query(
            parse_select(
                """
                select person_id, persons.id from (
                    select
                        person_id
                    from events
                ) as source
                inner join persons ON (source.person_id=persons.id)
                where notEquals(persons.properties.$some_prop, 'something')
                """
            ),
            self.team,
        )
        assert len(response.results) == 1

    @snapshot_clickhouse_queries
    def test_join(self):
        response = execute_hogql_query(
            parse_select(
                "select id, properties.email from persons where properties.$some_prop = 'something' and pdi.distinct_id = '1'"
            ),
            self.team,
        )
        assert len(response.results) == 1

        # more complex query
        response = execute_hogql_query(
            parse_select("""
            select id, properties.email from persons where
                (properties.$some_prop = 'something' and pdi.distinct_id = '1') OR
                (properties.$some_prop = 'whatevs')
            """),
            self.team,
        )
        assert len(response.results) == 1

    @snapshot_clickhouse_queries
    def test_events_filter(self):
        _create_event(event="$pageview", distinct_id="1", team=self.team)
        response = execute_hogql_query(
            parse_select("select properties.email from events where person.properties.$some_prop = 'something'"),
            self.team,
        )
        assert len(response.results) == 1

    @snapshot_clickhouse_queries
    def test_versions_handled_correctly(self):
        # Tests whether we correctly grab $some_prop from the person with the highest version
        response = execute_hogql_query(
            parse_select("select id, properties.$some_prop from persons ORDER BY created_at limit 100"),
            self.team,
        )
        assert len(response.results) == 3

    @snapshot_clickhouse_queries
    def test_left_join_with_negation(self):
        _create_event(event="$pageview", distinct_id="1", team=self.team)
        _create_event(event="$pageview", distinct_id="2", team=self.team)
        _create_event(event="$pageview", distinct_id="3", team=self.team)
        response = execute_hogql_query(
            parse_select(
                "select id, persons.properties.$some_prop from events left join persons ON (events.person_id=persons.id) where notEquals(persons.properties.$some_prop, 'something')"
            ),
            self.team,
        )
        assert len(response.results) == 1
        assert [x[0] for x in response.results] == [
            self.third_person.uuid,
        ]
        response = execute_hogql_query(
            parse_select(
                "select id, persons.properties.$some_prop from events left join persons ON (events.person_id=persons.id) where persons.properties.$some_prop != 'something'"
            ),
            self.team,
        )
        assert len(response.results) == 1

        response = execute_hogql_query(
            parse_select(
                "select id, persons.properties.$some_prop from events left join persons ON (events.person_id=persons.id) where persons.properties.$some_prop !~ '^something$'"
            ),
            self.team,
        )
        assert len(response.results) == 1

        response = execute_hogql_query(
            parse_select(
                "select id, persons.properties.$some_prop from events left join persons ON (events.person_id=persons.id) where not (persons.properties.$some_prop = 'something')"
            ),
            self.team,
        )
        assert len(response.results) == 1

        response = execute_hogql_query(
            parse_select(
                "select id, persons.properties.$some_prop from events left join persons ON (events.person_id=persons.id) where not persons.properties.$some_prop = 'something'"
            ),
            self.team,
        )
        assert len(response.results) == 1

    @snapshot_clickhouse_queries
    def test_limit_and_order_by(self):
        response = execute_hogql_query(
            parse_select("select id, properties.$some_prop from persons ORDER BY created_at limit 3"),
            self.team,
        )
        assert len(response.results) == 3
        assert [x[0] for x in response.results] == [
            self.first_person.uuid,
            self.second_person.uuid,
            self.third_person.uuid,
        ]

        response = execute_hogql_query(
            parse_select("select id, properties.$some_prop from persons ORDER BY created_at limit 2, 1"),
            self.team,
        )
        assert len(response.results) == 2
        assert [x[0] for x in response.results] == [self.second_person.uuid, self.third_person.uuid]
