from datetime import datetime

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, snapshot_clickhouse_queries

from posthog.schema import BreakdownFilter, DateRange, EventsNode, FunnelsFilter, FunnelsQuery

from posthog.hogql_queries.insights.funnels.funnels_query_runner import FunnelsQueryRunner
from posthog.test.test_journeys import journeys_for


class TestFunnelBreakdownsByCurrentURL(ClickhouseTestMixin, APIBaseTest):
    def setUp(self):
        super().setUp()
        journey = {
            "person1": [
                # no trailing slash
                {
                    "event": "watched movie",
                    "timestamp": datetime(2020, 1, 2, 12, 1),
                    "properties": {
                        "$current_url": "https://example.com",
                        "$pathname": "",
                    },
                },
                # trailing question mark
                {
                    "event": "watched movie",
                    "timestamp": datetime(2020, 1, 2, 12, 2),
                    "properties": {
                        "$current_url": "https://example.com?",
                        "$pathname": "?",
                    },
                },
                {
                    "event": "terminate funnel",
                    "timestamp": datetime(2020, 1, 2, 12, 3),
                },
            ],
            "person2": [
                # trailing slash
                {
                    "event": "watched movie",
                    "timestamp": datetime(2020, 1, 2, 12, 1),
                    "properties": {
                        "$current_url": "https://example.com/",
                        "$pathname": "/",
                    },
                },
                # trailing hash
                {
                    "event": "watched movie",
                    "timestamp": datetime(2020, 1, 2, 12, 2),
                    "properties": {
                        "$current_url": "https://example.com#",
                        "$pathname": "#",
                    },
                },
                {
                    "event": "terminate funnel",
                    "timestamp": datetime(2020, 1, 2, 12, 3),
                },
            ],
            "person3": [
                # no trailing slash
                {
                    "event": "watched movie",
                    "timestamp": datetime(2020, 1, 2, 12, 1),
                    "properties": {
                        "$current_url": "https://example.com/home",
                        "$pathname": "/home",
                    },
                },
                {
                    "event": "terminate funnel",
                    "timestamp": datetime(2020, 1, 2, 12, 2),
                },
            ],
            "person4": [
                # trailing slash
                {
                    "event": "watched movie",
                    "timestamp": datetime(2020, 1, 2, 12, 1),
                    "properties": {
                        "$current_url": "https://example.com/home/",
                        "$pathname": "/home/",
                    },
                },
                # trailing hash
                {
                    "event": "watched movie",
                    "timestamp": datetime(2020, 1, 2, 12, 2),
                    "properties": {
                        "$current_url": "https://example.com/home#",
                        "$pathname": "/home#",
                    },
                },
                # all the things
                {
                    "event": "watched movie",
                    "timestamp": datetime(2020, 1, 2, 12, 3),
                    "properties": {
                        "$current_url": "https://example.com/home/?#",
                        "$pathname": "/home/?#",
                    },
                },
                {
                    "event": "terminate funnel",
                    "timestamp": datetime(2020, 1, 2, 12, 4),
                },
            ],
        }

        journeys_for(journey, team=self.team, create_people=True)

    def _run(self, query: FunnelsQuery):
        results = FunnelsQueryRunner(query=query, team=self.team).calculate().results
        return results

    @snapshot_clickhouse_queries
    def test_breakdown_by_pathname(self) -> None:
        response = self._run(
            FunnelsQuery(
                series=[
                    EventsNode(event="watched movie", name="watched movie"),
                    EventsNode(event="terminate funnel", name="terminate funnel"),
                ],
                dateRange=DateRange(
                    date_from="2020-01-02T00:00:00Z",
                    date_to="2020-01-12T00:00:00Z",
                ),
                funnelsFilter=FunnelsFilter(),
                breakdownFilter=BreakdownFilter(
                    breakdown="$pathname",
                    breakdown_type="event",
                    breakdown_normalize_url=True,
                    breakdown_limit=100,  # never have other
                ),
            )
        )

        actual = []
        for breakdown_value in response:
            for funnel_step in breakdown_value:
                actual.append(
                    (
                        funnel_step["name"],
                        funnel_step["count"],
                        funnel_step["breakdown"],
                    )
                )

        sk = lambda x: (x[1], x[2][0], x[0])
        assert sorted(actual, key=sk) == sorted(
            [
                ("watched movie", 2, ["/"]),
                ("terminate funnel", 2, ["/"]),
                ("watched movie", 2, ["/home"]),
                ("terminate funnel", 2, ["/home"]),
            ],
            key=sk,
        )

    @snapshot_clickhouse_queries
    def test_breakdown_by_current_url(self) -> None:
        response = self._run(
            FunnelsQuery(
                series=[
                    EventsNode(event="watched movie", name="watched movie"),
                    EventsNode(event="terminate funnel", name="terminate funnel"),
                ],
                dateRange=DateRange(
                    date_from="2020-01-02T00:00:00Z",
                    date_to="2020-01-12T00:00:00Z",
                ),
                funnelsFilter=FunnelsFilter(),
                breakdownFilter=BreakdownFilter(
                    breakdown="$current_url",
                    breakdown_type="event",
                    breakdown_normalize_url=True,
                    breakdown_limit=100,  # never have other
                ),
            )
        )

        actual = []
        for breakdown_value in response:
            for funnel_step in breakdown_value:
                actual.append(
                    (
                        funnel_step["name"],
                        funnel_step["count"],
                        funnel_step["breakdown"],
                    )
                )

        sk = lambda x: (x[1], x[2][0], x[0])
        assert sorted(actual, key=sk) == sorted(
            [
                ("watched movie", 2, ["https://example.com/home"]),
                ("terminate funnel", 2, ["https://example.com/home"]),
                ("watched movie", 2, ["https://example.com"]),
                ("terminate funnel", 2, ["https://example.com"]),
            ],
            key=sk,
        )
