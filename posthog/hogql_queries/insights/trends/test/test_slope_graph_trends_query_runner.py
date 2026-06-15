from freezegun import freeze_time
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    snapshot_clickhouse_queries,
)

from parameterized import parameterized

from posthog.schema import BreakdownFilter, ChartDisplayType, DateRange, EventsNode, TrendsFilter, TrendsQuery

from posthog.hogql_queries.insights.trends.slope_graph_trends_query_runner import SlopeGraphTrendsQueryRunner
from posthog.models.utils import uuid7


@freeze_time("2024-01-20T00:00:00Z")
class TestSlopeGraphTrendsQueryRunner(ClickhouseTestMixin, APIBaseTest):
    def _create_events(self, data, event="$pageview"):
        for distinct_id, timestamps in data:
            with freeze_time(timestamps[0][0]):
                _create_person(team_id=self.team.pk, distinct_ids=[distinct_id], properties={"name": distinct_id})
            for timestamp, *rest in timestamps:
                _create_event(
                    team=self.team,
                    event=event,
                    distinct_id=distinct_id,
                    timestamp=timestamp,
                    uuid=str(uuid7()),
                    properties=rest[0] if rest else {},
                )

    def _run(self, date_from, date_to, series=None, breakdown=None, include_incomplete_period=False):
        query = TrendsQuery(
            dateRange=DateRange(date_from=date_from, date_to=date_to),
            interval="day",
            breakdownFilter=breakdown,
            trendsFilter=TrendsFilter(
                display=ChartDisplayType.SLOPE_GRAPH,
                slopeIncludeIncompletePeriod=include_incomplete_period,
            ),
            series=series or [EventsNode(kind="EventsNode", event="$pageview", math="total")],
        )
        return SlopeGraphTrendsQueryRunner(team=self.team, query=query).calculate()

    @snapshot_clickhouse_queries
    def test_returns_two_points_collapsing_first_and_second_half(self):
        # Two events well inside the first half, three well inside the second half.
        self._create_events(
            [
                ("early", [("2024-01-02T10:00:00Z",), ("2024-01-03T10:00:00Z",)]),
                ("late", [("2024-01-16T10:00:00Z",), ("2024-01-17T10:00:00Z",), ("2024-01-18T10:00:00Z",)]),
            ]
        )
        response = self._run("2024-01-01", "2024-01-19")

        assert len(response.results) == 1
        result = response.results[0]
        assert len(result["data"]) == 2
        assert len(result["labels"]) == 2
        # The slope is the first-half total vs the second-half total — which together cover the range.
        assert result["data"][0] == 2
        assert result["data"][1] == 3

    @snapshot_clickhouse_queries
    def test_event_on_the_split_day_is_counted_once_in_the_end_window(self):
        self._create_events(
            [
                ("early", [("2024-01-02T10:00:00Z",)]),
                ("on_split_day", [("2024-01-10T10:00:00Z",)]),
            ]
        )
        response = self._run("2024-01-01", "2024-01-19")

        result = response.results[0]
        assert result["data"][0] == 1
        assert result["data"][1] == 1
        assert result["count"] == 2

    @snapshot_clickhouse_queries
    def test_no_events_yields_zero_endpoints(self):
        response = self._run("2024-01-01", "2024-01-19")
        for result in response.results:
            assert len(result["data"]) == 2
            assert result["data"][0] == 0
            assert result["data"][1] == 0

    @snapshot_clickhouse_queries
    def test_breakdown_produces_one_two_point_line_per_value(self):
        self._create_events(
            [
                ("a", [("2024-01-02T10:00:00Z", {"plan": "free"})]),
                ("b", [("2024-01-16T10:00:00Z", {"plan": "paid"}), ("2024-01-17T10:00:00Z", {"plan": "paid"})]),
            ]
        )
        response = self._run(
            "2024-01-01",
            "2024-01-19",
            breakdown=BreakdownFilter(breakdown="plan", breakdown_type="event"),
        )

        # Each breakdown value is its own slope line, each with exactly two points.
        assert len(response.results) >= 2
        for result in response.results:
            assert len(result["data"]) == 2
            assert len(result["labels"]) == 2

    @parameterized.expand(
        [
            ("excluded_by_default", False, 2),
            ("included_when_opted_in", True, 3),
        ]
    )
    @freeze_time("2024-01-20T12:00:00Z")
    def test_current_incomplete_period(self, _name, include_incomplete_period, expected_count):
        self._create_events(
            [
                ("early", [("2024-01-11T10:00:00Z",)]),
                ("yesterday", [("2024-01-19T10:00:00Z",)]),
                ("today_so_far", [("2024-01-20T09:00:00Z",)]),
            ]
        )
        response = self._run("2024-01-11", "2024-01-20", include_incomplete_period=include_incomplete_period)

        assert response.results[0]["count"] == expected_count

    @parameterized.expand(
        [
            ("action_series", {"action": {"order": 2}, "breakdown_value": None}, (2, "None")),
            ("formula_series_uses_top_level_order", {"action": None, "order": 1, "breakdown_value": None}, (1, "None")),
            ("formula_series_defaults_to_zero", {"action": None, "breakdown_value": None}, (0, "None")),
            ("breakdown_included_in_key", {"action": {"order": 0}, "breakdown_value": "paid"}, (0, "paid")),
        ]
    )
    def test_series_key(self, _name, result, expected_key):
        assert SlopeGraphTrendsQueryRunner._series_key(result) == expected_key
