from posthog.hogql.parser import parse_select
from posthog.schema import (
    PersonsOnEventsMode,
    InsightActorsQuery,
    TrendsQuery,
    ActorsQuery,
    EventsNode,
    InsightDateRange,
)
from posthog.hogql_queries.actors_query_runner import ActorsQueryRunner
from posthog.hogql.modifiers import create_default_modifiers_for_team
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

from unittest.mock import patch, Mock


@patch("posthoganalytics.feature_enabled", new=Mock(return_value=True))  # for persons-inner-where-optimization
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
        _create_event(event="$pageview", distinct_id="1", team=self.team)
        _create_event(event="$pageview", distinct_id="2", team=self.team)
        _create_event(event="$pageview", distinct_id="3", team=self.team)
        self.modifiers = create_default_modifiers_for_team(self.team)
        self.modifiers.personsOnEventsMode = PersonsOnEventsMode.DISABLED
        # self.modifiers.optimizeJoinedFilters = True
        # self.modifiers.personsArgMaxVersion = PersonsArgMaxVersion.V1

    @snapshot_clickhouse_queries
    def test_simple_filter(self):
        response = execute_hogql_query(
            parse_select("select id, properties from persons where properties.$some_prop = 'something'"),
            self.team,
            modifiers=self.modifiers,
        )
        assert len(response.results) == 2
        assert response.clickhouse
        self.assertIn("where_optimization", response.clickhouse)
        self.assertNotIn("in(tuple(person.id, person.version)", response.clickhouse)

    @snapshot_clickhouse_queries
    def test_joins_are_left_alone_for_now(self):
        response = execute_hogql_query(
            parse_select("select uuid from events where person.properties.$some_prop = 'something'"),
            self.team,
            modifiers=self.modifiers,
        )
        assert len(response.results) == 2
        assert response.clickhouse
        self.assertIn("in(tuple(person.id, person.version)", response.clickhouse)
        self.assertNotIn("where_optimization", response.clickhouse)

    def test_person_modal_not_optimized_yet(self):
        source_query = TrendsQuery(
            series=[EventsNode(event="$pageview")],
            dateRange=InsightDateRange(date_from="2024-01-01", date_to="2024-01-07"),
            # breakdownFilter=BreakdownFilter(breakdown="$", breakdown_type=BreakdownType.PERSON),
        )
        insight_actors_query = InsightActorsQuery(
            source=source_query,
            day="2024-01-01",
            modifiers=self.modifiers,
        )
        actors_query = ActorsQuery(
            source=insight_actors_query,
            offset=0,
            select=[
                "actor",
                "created_at",
                "event_count",
                # "matched_recordings",
            ],
            orderBy=["event_count DESC"],
            modifiers=self.modifiers,
        )
        query_runner = ActorsQueryRunner(query=actors_query, team=self.team)
        response = execute_hogql_query(query_runner.to_query(), self.team, modifiers=self.modifiers)
        assert response.clickhouse
        self.assertNotIn("where_optimization", response.clickhouse)
