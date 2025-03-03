from posthog.hogql_queries.insights.paths_v2.paths_v2_query_runner import PathsV2QueryRunner
from posthog.models import Team
from posthog.schema import PathsV2Query, PathsV2QueryResponse
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
)
from posthog.test.test_journeys import journeys_for


def create_events(team: Team) -> None:
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


class TestPathsV2(ClickhouseTestMixin, APIBaseTest):
    maxDiff = None

    def _run_paths_v2_query(self) -> PathsV2QueryResponse:
        query = PathsV2Query()
        query_runner = PathsV2QueryRunner(team=self.team, query=query)
        return query_runner.calculate()

    def test_simple_path_query(self):
        response = self._run_paths_v2_query()

        assert response.results == []


class TestPathsV2BaseEventsQuery:
    pass
