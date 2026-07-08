from freezegun import freeze_time
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    snapshot_clickhouse_queries,
)

from posthog.schema import (
    BreakdownFilter,
    ChartDisplayType,
    DateRange,
    EventPropertyFilter,
    EventsNode,
    FilterLogicalOperator,
    PropertyGroupFilter,
    PropertyGroupFilterValue,
    PropertyOperator,
    TrendsFilter,
    TrendsQuery,
)

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
        # The range ends well before "now" (2024-06-15), so the last bucket is complete.
        assert result["incomplete_end"] is False

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
        assert result["incomplete_end"] is True
        assert response.resolved_date_range is not None
        assert response.resolved_date_range.date_to.strftime("%Y-%m-%d") == "2024-06-15"

    @snapshot_clickhouse_queries
    def test_single_bucket_range_yields_a_one_point_series(self):
        self._create_events([("a", [("2024-05-03T10:00:00Z",), ("2024-05-04T10:00:00Z",)])])
        # A range within one month bucket can't form a slope — one bucket, one point.
        response = self._run("2024-05-01", "2024-05-31", interval="month")

        for result in response.results:
            assert len(result["data"]) == 1

    @snapshot_clickhouse_queries
    def test_keeps_the_query_property_filter_alongside_the_bucket_restriction(self):
        self._create_events(
            [
                ("paid_first", [("2024-05-01T10:00:00Z", {"plan": "paid"})]),
                ("free_first", [("2024-05-01T11:00:00Z", {"plan": "free"})]),
                ("paid_last", [("2024-05-10T10:00:00Z", {"plan": "paid"})]),
            ]
        )
        query = TrendsQuery(
            dateRange=DateRange(date_from="2024-05-01", date_to="2024-05-10"),
            interval="day",
            trendsFilter=TrendsFilter(display=ChartDisplayType.SLOPE_GRAPH),
            series=[EventsNode(kind="EventsNode", event="$pageview", math="total")],
            properties=[EventPropertyFilter(key="plan", value=["paid"], operator=PropertyOperator.EXACT)],
        )
        response = SlopeGraphTrendsQueryRunner(team=self.team, query=query).calculate()

        result = response.results[0]
        # The query's "plan = paid" filter is preserved, so the free event on the first day is excluded.
        assert result["data"][0] == 1
        assert result["data"][1] == 1

    @snapshot_clickhouse_queries
    def test_active_users_math_keeps_its_trailing_window(self):
        # weekly_active counts users active in the trailing 7 days of each bucket. A user active only
        # on May 10 must still count toward the last bucket (May 14), even though May 10 is neither the
        # first nor last bucket — so the two-bucket scan restriction must not apply to this math.
        self._create_events([("u", [("2024-05-10T10:00:00Z",)])])
        response = self._run(
            "2024-05-01",
            "2024-05-14",
            series=[EventsNode(kind="EventsNode", event="$pageview", math="weekly_active")],
        )

        result = response.results[0]
        # May 1: nobody in its trailing window -> 0. May 14: the May 10 user is in its window -> 1.
        assert result["data"] == [0, 1]

    @snapshot_clickhouse_queries
    def test_week_interval_scan_filter_aligns_with_the_buckets(self):
        # The scan filter's bucket windows must line up with the trends week bucketing (incl. team
        # week-start), or first/last week events would be wrongly excluded.
        self._create_events(
            [
                ("first_week", [("2024-05-02T10:00:00Z",)]),
                ("middle_week", [("2024-05-15T10:00:00Z",)]),
                ("last_week", [("2024-05-27T10:00:00Z",)]),
            ]
        )
        response = self._run("2024-05-01", "2024-05-28", interval="week")

        result = response.results[0]
        # First and last week each keep their event; the middle week is sliced off either way.
        assert result["data"] == [1, 1]

    @snapshot_clickhouse_queries
    def test_unique_users_math_is_per_bucket(self):
        self._create_events(
            [
                ("u1", [("2024-05-01T10:00:00Z",), ("2024-05-10T10:00:00Z",)]),
                ("u2", [("2024-05-01T11:00:00Z",)]),
            ]
        )
        response = self._run(
            "2024-05-01",
            "2024-05-10",
            series=[EventsNode(kind="EventsNode", event="$pageview", math="dau")],
        )

        result = response.results[0]
        # May 1: u1 + u2 = 2 unique; May 10: u1 = 1.
        assert result["data"] == [2, 1]

    @snapshot_clickhouse_queries
    def test_formula_series(self):
        self._create_events([("a", [("2024-05-01T10:00:00Z",), ("2024-05-10T10:00:00Z",), ("2024-05-10T11:00:00Z",)])])
        query = TrendsQuery(
            dateRange=DateRange(date_from="2024-05-01", date_to="2024-05-10"),
            interval="day",
            trendsFilter=TrendsFilter(display=ChartDisplayType.SLOPE_GRAPH, formula="A * 2"),
            series=[EventsNode(kind="EventsNode", event="$pageview", math="total")],
        )
        response = SlopeGraphTrendsQueryRunner(team=self.team, query=query).calculate()

        result = response.results[0]
        # Formula A*2 over the two end buckets: May 1 has 1 event -> 2, May 10 has 2 -> 4.
        assert result["data"] == [2, 4]

    @snapshot_clickhouse_queries
    def test_smoothing_does_not_starve_the_last_point(self):
        # Smoothing is a trailing-window moving average that reads interior buckets. The slope must
        # clear it and return the raw first/last bucket values, not a window-starved average.
        self._create_events(
            [
                ("first_day", [("2024-05-01T10:00:00Z",), ("2024-05-01T11:00:00Z",)]),
                ("middle", [("2024-05-05T10:00:00Z",), ("2024-05-06T10:00:00Z",)]),
                ("last_day", [("2024-05-10T08:00:00Z",), ("2024-05-10T09:00:00Z",), ("2024-05-10T10:00:00Z",)]),
            ]
        )
        query = TrendsQuery(
            dateRange=DateRange(date_from="2024-05-01", date_to="2024-05-10"),
            interval="day",
            trendsFilter=TrendsFilter(display=ChartDisplayType.SLOPE_GRAPH, smoothingIntervals=7),
            series=[EventsNode(kind="EventsNode", event="$pageview", math="total")],
        )
        response = SlopeGraphTrendsQueryRunner(team=self.team, query=query).calculate()

        result = response.results[0]
        # Same raw endpoints as the unsmoothed query — smoothing is ignored, not applied to a starved window.
        assert result["data"] == [2, 3]

    @snapshot_clickhouse_queries
    def test_monthly_active_math_keeps_its_trailing_window(self):
        # monthly_active is a 30-day trailing window; like weekly_active it must skip the scan restriction.
        self._create_events([("u", [("2024-04-20T10:00:00Z",)])])
        response = self._run(
            "2024-04-01",
            "2024-05-13",
            series=[EventsNode(kind="EventsNode", event="$pageview", math="monthly_active")],
        )

        result = response.results[0]
        # Apr 1: nobody in its trailing 30 days -> 0. May 13: Apr 20 is within its window -> 1.
        assert result["data"] == [0, 1]

    @snapshot_clickhouse_queries
    def test_hour_interval_first_and_last_hour(self):
        self._create_events(
            [
                ("first_hour", [("2024-06-14T00:15:00Z",)]),
                ("middle_hour", [("2024-06-14T02:15:00Z",)]),
                ("last_hour", [("2024-06-14T04:15:00Z",)]),
            ]
        )
        query = TrendsQuery(
            dateRange=DateRange(date_from="2024-06-14T00:00:00Z", date_to="2024-06-14T04:30:00Z"),
            interval="hour",
            trendsFilter=TrendsFilter(display=ChartDisplayType.SLOPE_GRAPH),
            series=[EventsNode(kind="EventsNode", event="$pageview", math="total")],
        )
        response = SlopeGraphTrendsQueryRunner(team=self.team, query=query).calculate()

        result = response.results[0]
        # First hour (00:00) and last hour (04:00) each keep their event; the 02:00 hour is sliced off.
        assert result["data"] == [1, 1]

    @snapshot_clickhouse_queries
    def test_non_utc_team_timezone(self):
        self.team.timezone = "US/Pacific"
        self.team.save()
        # 20:00 UTC is ~13:00 the same calendar day in Pacific, so these land on May 1 and May 10 PT.
        self._create_events(
            [
                ("first", [("2024-05-01T20:00:00Z",)]),
                ("middle", [("2024-05-05T20:00:00Z",)]),
                ("last", [("2024-05-10T20:00:00Z",)]),
            ]
        )
        response = self._run("2024-05-01", "2024-05-10")

        result = response.results[0]
        # The scan filter aligns to the team's timezone, so the first and last Pacific days are kept.
        assert result["data"] == [1, 1]

    @snapshot_clickhouse_queries
    def test_relative_date_range(self):
        # "now" is frozen at 2024-06-15, so the last 7 days span 2024-06-08..2024-06-15.
        self._create_events(
            [
                ("first", [("2024-06-08T10:00:00Z",)]),
                ("middle", [("2024-06-11T10:00:00Z",)]),
                ("last", [("2024-06-15T10:00:00Z",)]),
            ]
        )
        response = self._run("-7d", None)

        result = response.results[0]
        assert result["data"] == [1, 1]

    @snapshot_clickhouse_queries
    def test_preserves_a_property_group_filter(self):
        self._create_events(
            [
                ("paid_first", [("2024-05-01T10:00:00Z", {"plan": "paid"})]),
                ("free_first", [("2024-05-01T11:00:00Z", {"plan": "free"})]),
                ("paid_last", [("2024-05-10T10:00:00Z", {"plan": "paid"})]),
            ]
        )
        group = PropertyGroupFilter(
            type=FilterLogicalOperator.AND_,
            values=[
                PropertyGroupFilterValue(
                    type=FilterLogicalOperator.AND_,
                    values=[EventPropertyFilter(key="plan", value=["paid"], operator=PropertyOperator.EXACT)],
                )
            ],
        )
        query = TrendsQuery(
            dateRange=DateRange(date_from="2024-05-01", date_to="2024-05-10"),
            interval="day",
            trendsFilter=TrendsFilter(display=ChartDisplayType.SLOPE_GRAPH),
            series=[EventsNode(kind="EventsNode", event="$pageview", math="total")],
            properties=group,
        )
        response = SlopeGraphTrendsQueryRunner(team=self.team, query=query).calculate()

        result = response.results[0]
        # The group's "plan = paid" survives the bucket restriction, so the free event is excluded.
        assert result["data"] == [1, 1]
