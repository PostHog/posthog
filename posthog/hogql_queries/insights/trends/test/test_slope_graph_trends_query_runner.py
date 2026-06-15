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


@freeze_time("2024-06-15T12:00:00Z")
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

    def _run(self, date_from, date_to, series=None, breakdown=None, interval="day"):
        query = TrendsQuery(
            dateRange=DateRange(date_from=date_from, date_to=date_to),
            interval=interval,
            breakdownFilter=breakdown,
            trendsFilter=TrendsFilter(display=ChartDisplayType.SLOPE_GRAPH),
            series=series or [EventsNode(kind="EventsNode", event="$pageview", math="total")],
        )
        return SlopeGraphTrendsQueryRunner(team=self.team, query=query).calculate()

    @snapshot_clickhouse_queries
    def test_returns_first_and_last_day_buckets_ignoring_the_middle(self):
        self._create_events(
            [
                ("first_day", [("2024-05-01T10:00:00Z",), ("2024-05-01T11:00:00Z",)]),
                ("middle", [("2024-05-05T10:00:00Z",), ("2024-05-06T10:00:00Z",)]),
                ("last_day", [("2024-05-10T08:00:00Z",), ("2024-05-10T09:00:00Z",), ("2024-05-10T10:00:00Z",)]),
            ]
        )
        response = self._run("2024-05-01", "2024-05-10")

        assert len(response.results) == 1
        result = response.results[0]
        assert len(result["data"]) == 2
        # Only the first and last day count — the middle days are never queried.
        assert result["data"][0] == 2
        assert result["data"][1] == 3

    @snapshot_clickhouse_queries
    def test_groups_by_month_returning_first_and_last_month(self):
        self._create_events(
            [
                ("jan", [("2024-01-05T10:00:00Z",), ("2024-01-20T10:00:00Z",)]),
                ("feb", [("2024-02-10T10:00:00Z",)]),
                ("mar", [("2024-03-01T10:00:00Z",), ("2024-03-10T10:00:00Z",), ("2024-03-20T10:00:00Z",)]),
            ]
        )
        response = self._run("2024-01-01", "2024-03-31", interval="month")

        result = response.results[0]
        # First month total vs last month total; February (the middle bucket) is ignored.
        assert result["data"][0] == 2
        assert result["data"][1] == 3
        assert result["days"] == ["2024-01-01", "2024-03-01"]

    @snapshot_clickhouse_queries
    def test_no_events_yields_zero_endpoints(self):
        response = self._run("2024-05-01", "2024-05-10")
        for result in response.results:
            assert len(result["data"]) == 2
            assert result["data"][0] == 0
            assert result["data"][1] == 0

    @snapshot_clickhouse_queries
    def test_breakdown_produces_one_two_point_line_per_value(self):
        self._create_events(
            [
                ("a", [("2024-05-01T10:00:00Z", {"plan": "free"})]),
                ("b", [("2024-05-10T10:00:00Z", {"plan": "paid"}), ("2024-05-10T11:00:00Z", {"plan": "paid"})]),
            ]
        )
        response = self._run(
            "2024-05-01",
            "2024-05-10",
            breakdown=BreakdownFilter(breakdown="plan", breakdown_type="event"),
        )

        # Each breakdown value is its own slope line, each with exactly two points.
        assert len(response.results) >= 2
        for result in response.results:
            assert len(result["data"]) == 2
            assert len(result["labels"]) == 2

    @snapshot_clickhouse_queries
    def test_last_bucket_is_the_current_partial_period_not_trimmed(self):
        response = self._run("2024-04-01", "2024-06-15", interval="month")

        result = response.results[0]
        # The last bucket is the current, still-accumulating month — kept as-is (the frontend dashes it).
        assert result["days"] == ["2024-04-01", "2024-06-01"]
        assert response.resolved_date_range is not None
        assert response.resolved_date_range.date_to.strftime("%Y-%m-%d") == "2024-06-15"

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
