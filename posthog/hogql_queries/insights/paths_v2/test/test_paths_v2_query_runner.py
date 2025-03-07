from abc import ABC
from datetime import datetime

from clickhouse_driver.util.escape import UUID
from freezegun.api import freeze_time
import pytz
from posthog.hogql.query import execute_hogql_query
from posthog.hogql_queries.insights.paths_v2.paths_v2_query_runner import (
    POSTHOG_OTHER,
    POSTHOG_DROPOFF,
    PathsV2QueryRunner,
)
from posthog.models import Team
from posthog.schema import PathsV2Filter, PathsV2Item, PathsV2Query, PathsV2QueryResponse
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
)
from posthog.test.test_journeys import journeys_for


def create_sequences(team: Team) -> None:
    _ = journeys_for(
        team=team,
        events_by_person={
            # User 1 (Full Funnel)
            "person1": [
                {"event": "Landing Page", "timestamp": "2023-03-10 12:00:00"},
                {"event": "Product View", "timestamp": "2023-03-10 12:05:00"},
                {"event": "Add to Cart", "timestamp": "2023-03-10 12:10:00"},
                {"event": "Checkout", "timestamp": "2023-03-10 12:15:00"},
                {"event": "Purchase", "timestamp": "2023-03-10 12:20:00"},
            ],
            # User 2 (Search before purchase)
            "person2": [
                {"event": "Landing Page", "timestamp": "2023-03-11 11:30:00"},
                {"event": "Search", "timestamp": "2023-03-11 11:32:00"},
                {"event": "Product View", "timestamp": "2023-03-11 11:35:00"},
                {"event": "Add to Cart", "timestamp": "2023-03-11 11:38:00"},
                {"event": "Checkout", "timestamp": "2023-03-11 11:42:00"},
                {"event": "Purchase", "timestamp": "2023-03-11 11:45:00"},
            ],
            # User 3 (Abandoned Cart)
            "person3": [
                {"event": "Landing Page", "timestamp": "2023-03-12 10:00:00"},
                {"event": "Product View", "timestamp": "2023-03-12 10:02:00"},
                {"event": "Add to Cart", "timestamp": "2023-03-12 10:05:00"},
            ],
            # User 4 (Bounced)
            "person4": [
                {"event": "Landing Page", "timestamp": "2023-03-13 09:00:00"},
            ],
        },
    )


class SharedSetup(ClickhouseTestMixin, APIBaseTest, ABC):
    def _get_query_runner(self, query: PathsV2Query | None = None) -> PathsV2QueryRunner:
        if query is None:
            query = PathsV2Query()
        return PathsV2QueryRunner(team=self.team, query=query)


class TestPathsV2(SharedSetup):
    maxDiff = None

    def _run_paths_v2_query(self) -> PathsV2QueryResponse:
        query_runner = self._get_query_runner()
        return query_runner.calculate()

    def test_simple_path_query(self):
        create_sequences(self.team)

        response = self._run_paths_v2_query()

        self.assertEqual(
            response.results,
            [
                PathsV2Item(value=2.0, source_step="Landing Page", target_step="Product View", step_index=1),
                PathsV2Item(value=1.0, source_step="Landing Page", target_step="Search", step_index=1),
                # Landing Page -> Dropoff
                PathsV2Item(value=3.0, source_step="Product View", target_step="Add to Cart", step_index=2),
                PathsV2Item(value=2.0, source_step="Add to Cart", target_step="Checkout", step_index=3),
                PathsV2Item(value=1.0, source_step="Checkout", target_step="Purchase", step_index=1),
                PathsV2Item(value=1.0, source_step="Search", target_step="Product View", step_index=1),
            ],
        )

    def test_aggregates_nodes_exceeding_limit(self):
        _ = journeys_for(
            team=self.team,
            events_by_person={
                # 6x a1 -> b1
                "person1": [{"event": "a1"}, {"event": "b1"}],
                "person2": [{"event": "a1"}, {"event": "b1"}],
                "person3": [{"event": "a1"}, {"event": "b1"}],
                "person4": [{"event": "a1"}, {"event": "b1"}],
                "person5": [{"event": "a1"}, {"event": "b1"}],
                "person6": [{"event": "a1"}, {"event": "b1"}],
                # 5x a1 -> b2
                "person7": [{"event": "a1"}, {"event": "b2"}],
                "person8": [{"event": "a1"}, {"event": "b2"}],
                "person9": [{"event": "a1"}, {"event": "b2"}],
                "person10": [{"event": "a1"}, {"event": "b2"}],
                "person11": [{"event": "a1"}, {"event": "b2"}],
                # 4x a2 -> dropoff
                "person12": [{"event": "a2"}],
                "person13": [{"event": "a2"}],
                "person14": [{"event": "a2"}],
                "person15": [{"event": "a2"}],
                # 3x a3 -> a3
                "person16": [{"event": "a3"}, {"event": "a3"}],
                "person17": [{"event": "a3"}, {"event": "a3"}],
                "person18": [{"event": "a3"}, {"event": "a3"}],
                # 2x a4 (grouped into "other") -> b1
                "person19": [{"event": "a4"}, {"event": "b1"}],
                "person20": [{"event": "a4"}, {"event": "b1"}],
                # 1x a5 (grouped into "other") -> dropoff
                "person21": [{"event": "a5"}],
            },
        )
        filter = PathsV2Filter(maxRowsPerStep=3)
        query = PathsV2Query(pathsV2Filter=filter)
        query_runner = self._get_query_runner(query=query)

        response = query_runner.calculate()

        self.assertEqual(
            [item for item in response.results if item.step_index == 1],
            [
                PathsV2Item(step_index=1, source_step="a1", target_step="b1", value=6),
                PathsV2Item(step_index=1, source_step="a1", target_step="b2", value=5),
                PathsV2Item(step_index=1, source_step="a2", target_step=POSTHOG_DROPOFF, value=4),
                PathsV2Item(step_index=1, source_step="a3", target_step="a3", value=3),
                PathsV2Item(step_index=1, source_step=POSTHOG_OTHER, target_step="b1", value=2),
                PathsV2Item(step_index=1, source_step=POSTHOG_OTHER, target_step=POSTHOG_DROPOFF, value=1),
            ],
        )

    def test_aggregates_nodes_grouping(self):
        _ = journeys_for(
            team=self.team,
            events_by_person={
                # 2x a1 -> b1
                "person1": [{"event": "a1"}, {"event": "b1"}],
                "person2": [{"event": "a1"}, {"event": "b1"}],
                # 1x a2 -> b2
                "person3": [{"event": "a2"}, {"event": "b2"}],
                # 1x a3 -> b3
                "person4": [{"event": "a3"}, {"event": "b3"}],
            },
        )

        filter = PathsV2Filter(maxRowsPerStep=1)
        query = PathsV2Query(pathsV2Filter=filter)
        query_runner = self._get_query_runner(query=query)

        response = query_runner.calculate()

        self.assertEqual(
            [item for item in response.results if item.step_index == 1],
            [
                PathsV2Item(step_index=1, source_step="a1", target_step="b1", value=2),
                PathsV2Item(step_index=1, source_step=POSTHOG_OTHER, target_step=POSTHOG_OTHER, value=2),
            ],
        )

    def test_collapses_events(self):
        _ = journeys_for(
            team=self.team,
            events_by_person={
                "person": [
                    {"event": "a"},
                    {"event": "b"},
                    {"event": "b"},
                    {"event": "c"},
                    {"event": "c"},
                ],
            },
        )

        # doesn't collapse when false
        filter = PathsV2Filter(collapseEvents=False)

        query = PathsV2Query(pathsV2Filter=filter)
        query_runner = self._get_query_runner(query=query)
        response = query_runner.calculate()

        self.assertEqual(
            response.results,
            [
                PathsV2Item(value=1.0, source_step=None, step_index=1.0, target_step="a"),
                PathsV2Item(value=1.0, source_step="a", step_index=2.0, target_step="b"),
                PathsV2Item(value=1.0, source_step="b", step_index=3.0, target_step="b"),
                PathsV2Item(value=1.0, source_step="b", step_index=4.0, target_step="c"),
                PathsV2Item(value=1.0, source_step="c", step_index=5.0, target_step="c"),
            ],
        )

        # collapses when true
        filter = PathsV2Filter(collapseEvents=True)

        query = PathsV2Query(pathsV2Filter=filter)
        query_runner = self._get_query_runner(query=query)
        response = query_runner.calculate()

        self.assertEqual(
            response.results,
            [
                PathsV2Item(value=1.0, source_step=None, step_index=1.0, target_step="a"),
                PathsV2Item(value=1.0, source_step="a", step_index=2.0, target_step="b"),
                PathsV2Item(value=1.0, source_step="b", step_index=3.0, target_step="c"),
            ],
        )


class TestPathsV2BaseEventsQuery(SharedSetup):
    maxDiff = None

    def test_event_base(self):
        with freeze_time("2020-01-11T12:00:00Z"):
            create_sequences(self.team)
        query_runner = self._get_query_runner()

        query = query_runner._event_base_query()

        response = execute_hogql_query(
            query=query,
            team=self.team,
        )

        self.assertEqual(
            response.results[0],
            (
                datetime(2020, 1, 11, 12, 0, tzinfo=pytz.utc),
                UUID("6fe525b8-2801-9e99-09f6-524b2b0ed086"),
                "Add to Cart",
            ),
        )
