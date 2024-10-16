from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_person,
    _create_event,
    snapshot_clickhouse_queries,
)


class TestPersonOptimization(ClickhouseTestMixin, APIBaseTest):
    """
    Mostly tests for the optimization of pre-filtering before aggregating. See https://github.com/PostHog/posthog/pull/25604
    """

    def setUp(self):
        super().setUp()
        _create_person(
            team_id=self.team.pk,
            distinct_ids=["1"],
            properties={"$some_prop": "something", "$another_prop": "something1"},
        )
        _create_person(
            team_id=self.team.pk,
            distinct_ids=["2"],
            properties={"$some_prop": "something", "$another_prop": "something2"},
        )
        _create_person(
            team_id=self.team.pk,
            distinct_ids=["3"],
            properties={"$some_prop": "not something", "$another_prop": "something3"},
        )

    @snapshot_clickhouse_queries
    def test_simple_filter(self):
        response = execute_hogql_query(
            parse_select("select id, properties.email from persons where properties.$some_prop = 'something'"),
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
