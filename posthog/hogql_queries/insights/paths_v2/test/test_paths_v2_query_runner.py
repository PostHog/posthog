from abc import ABC
from datetime import datetime

from clickhouse_driver.util.escape import UUID
from freezegun.api import freeze_time
import pytz
from posthog.hogql.query import execute_hogql_query
from posthog.hogql_queries.insights.paths_v2.paths_v2_query_runner import PathsV2QueryRunner
from posthog.models import Team
from posthog.schema import PathsV2Item, PathsV2Query, PathsV2QueryResponse
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
                {"event": "Landing Page"},
                {"event": "Product View"},
                {"event": "Add to Cart"},
                {"event": "Checkout"},
                {"event": "Purchase"},
            ],
            # User 2 (Search before purchase)
            "person2": [
                {"event": "Landing Page"},
                {"event": "Search"},
                {"event": "Product View"},
                {"event": "Add to Cart"},
                {"event": "Checkout"},
                {"event": "Purchase"},
            ],
            # User 3 (Abandoned Cart)
            "person3": [{"event": "Landing Page"}, {"event": "Product View"}, {"event": "Add to Cart"}],
            # User 4 (Bounced)
            "person4": [{"event": "Landing Page"}],
        },
    )


class SharedSetup(ClickhouseTestMixin, APIBaseTest, ABC):

    def _get_query_runner(self) -> PathsV2QueryRunner:
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
                PathsV2Item(event_count=4.0, source_step="", target_step="Landing Page"),
                PathsV2Item(event_count=3.0, source_step="Product View", target_step="Add to Cart"),
                PathsV2Item(event_count=2.0, source_step="Add to Cart", target_step="Checkout"),
                PathsV2Item(event_count=2.0, source_step="Landing Page", target_step="Product View"),
                PathsV2Item(event_count=1.0, source_step="Checkout", target_step="Purchase"),
                PathsV2Item(event_count=1.0, source_step="Landing Page", target_step="Search"),
                PathsV2Item(event_count=1.0, source_step="Search", target_step="Product View"),
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
