from typing import Optional

import pytest
from freezegun import freeze_time
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    snapshot_clickhouse_queries,
)

from parameterized import parameterized

from posthog.schema import BoxPlotDatum, ChartDisplayType, DateRange, EventsNode, TrendsFilter, TrendsQuery

from posthog.hogql_queries.insights.trends.boxplot_trends_query_runner import BoxPlotTrendsQueryRunner
from posthog.models.utils import uuid7


@freeze_time("2024-01-01T00:00:00Z")
class TestBoxPlotTrendsQueryRunner(ClickhouseTestMixin, APIBaseTest):
    def _create_events(self, data, event="$pageview"):
        for id, timestamps in data:
            with freeze_time(timestamps[0][0]):
                _create_person(
                    team_id=self.team.pk,
                    distinct_ids=[id],
                    properties={
                        "name": id,
                        **({"email": "test@posthog.com"} if id == "test" else {}),
                    },
                )
            for timestamp, *rest in timestamps:
                properties = rest[0] if rest else {}
                _create_event(
                    team=self.team,
                    event=event,
                    distinct_id=id,
                    timestamp=timestamp,
                    uuid=str(uuid7()),
                    properties=properties,
                )

    def _run_boxplot_query(
        self,
        date_from,
        date_to,
        interval="day",
        math_property="revenue",
        properties=None,
        filter_test_accounts: Optional[bool] = False,
        series=None,
    ):
        query = TrendsQuery(
            dateRange=DateRange(date_from=date_from, date_to=date_to),
            interval=interval,
            properties=properties or [],
            filterTestAccounts=filter_test_accounts,
            trendsFilter=TrendsFilter(display=ChartDisplayType.BOX_PLOT),
            series=series or [EventsNode(kind="EventsNode", math="sum", math_property=math_property)],
        )
        runner = BoxPlotTrendsQueryRunner(team=self.team, query=query)
        return runner.calculate()

    @staticmethod
    def _parse_boxplot_results(response) -> list[BoxPlotDatum]:
        return [BoxPlotDatum(**d) for d in response.results]

    @snapshot_clickhouse_queries
    def test_no_data_fills_all_dates_with_zeros(self):
        response = self._run_boxplot_query("2023-12-08", "2023-12-10")
        data = self._parse_boxplot_results(response)

        assert len(data) == 3
        for datum in data:
            assert datum.min == 0.0
            assert datum.max == 0.0
            assert datum.mean == 0.0

    @parameterized.expand(
        [
            (
                "uniform_distribution",
                ["10", "20", "30", "40", "50"],
                10.0,
                50.0,
                30.0,
            ),
            (
                "single_value",
                ["42"],
                42.0,
                42.0,
                42.0,
            ),
            (
                "two_values",
                ["100", "200"],
                100.0,
                200.0,
                150.0,
            ),
            (
                "identical_values",
                ["7", "7", "7", "7"],
                7.0,
                7.0,
                7.0,
            ),
            (
                "negative_values",
                ["-30", "-20", "-10", "0", "10"],
                -30.0,
                10.0,
                -10.0,
            ),
            (
                "large_values",
                ["1000000", "2000000", "3000000"],
                1000000.0,
                3000000.0,
                2000000.0,
            ),
            (
                "decimal_values",
                ["1.5", "2.5", "3.5", "4.5", "5.5"],
                1.5,
                5.5,
                3.5,
            ),
        ]
    )
    @snapshot_clickhouse_queries
    def test_statistics_for_distribution(self, _name, values, expected_min, expected_max, expected_mean):
        self._create_events(
            data=[
                (
                    "user1",
                    [(f"2023-12-02 {10 + i}:00:00", {"revenue": v}) for i, v in enumerate(values)],
                ),
            ]
        )

        response = self._run_boxplot_query("2023-12-02", "2023-12-02")
        data = self._parse_boxplot_results(response)

        assert len(data) == 1
        datum = data[0]

        assert datum.min == expected_min
        assert datum.max == expected_max
        assert datum.mean == pytest.approx(expected_mean, abs=0.01)
        assert datum.min <= datum.p25 <= datum.median <= datum.p75 <= datum.max

    @snapshot_clickhouse_queries
    def test_multiple_days_produce_separate_buckets_with_correct_stats(self):
        self._create_events(
            data=[
                (
                    "user1",
                    [
                        ("2023-12-02 10:00:00", {"revenue": "100"}),
                        ("2023-12-02 11:00:00", {"revenue": "200"}),
                        ("2023-12-03 10:00:00", {"revenue": "500"}),
                        ("2023-12-03 11:00:00", {"revenue": "600"}),
                    ],
                ),
            ]
        )

        response = self._run_boxplot_query("2023-12-02", "2023-12-03")
        data = self._parse_boxplot_results(response)

        assert len(data) == 2

        day1 = data[0]
        assert day1.day == "2023-12-02"
        assert day1.min == 100.0
        assert day1.max == 200.0
        assert day1.mean == 150.0
        assert day1.min <= day1.p25 <= day1.median <= day1.p75 <= day1.max

        day2 = data[1]
        assert day2.day == "2023-12-03"
        assert day2.min == 500.0
        assert day2.max == 600.0
        assert day2.mean == 550.0
        assert day2.min <= day2.p25 <= day2.median <= day2.p75 <= day2.max

    @snapshot_clickhouse_queries
    def test_multiple_users_aggregate_within_same_day(self):
        self._create_events(
            data=[
                ("user1", [("2023-12-02 10:00:00", {"revenue": "10"})]),
                ("user2", [("2023-12-02 11:00:00", {"revenue": "50"})]),
                ("user3", [("2023-12-02 12:00:00", {"revenue": "90"})]),
            ]
        )

        response = self._run_boxplot_query("2023-12-02", "2023-12-02")
        data = self._parse_boxplot_results(response)

        assert len(data) == 1
        datum = data[0]
        assert datum.min == 10.0
        assert datum.max == 90.0
        assert datum.mean == 50.0

    @snapshot_clickhouse_queries
    def test_sparse_data_fills_missing_dates_with_zeros(self):
        self._create_events(
            data=[
                (
                    "user1",
                    [
                        ("2023-12-01 10:00:00", {"revenue": "100"}),
                        ("2023-12-05 10:00:00", {"revenue": "500"}),
                    ],
                ),
            ]
        )

        response = self._run_boxplot_query("2023-12-01", "2023-12-07")
        data = self._parse_boxplot_results(response)

        days = [d.day for d in data]
        assert days == [
            "2023-12-01",
            "2023-12-02",
            "2023-12-03",
            "2023-12-04",
            "2023-12-05",
            "2023-12-06",
            "2023-12-07",
        ]

        days_with_data = {d.day: d for d in data}
        assert days_with_data["2023-12-01"].min == 100.0
        assert days_with_data["2023-12-05"].min == 500.0

        for zero_day in ["2023-12-02", "2023-12-03", "2023-12-04", "2023-12-06", "2023-12-07"]:
            datum = days_with_data[zero_day]
            assert datum.min == 0.0
            assert datum.max == 0.0
            assert datum.mean == 0.0

    @parameterized.expand(
        [
            ("day", "2023-12-02", "2023-12-02", "%Y-%m-%d"),
            ("hour", "2023-12-02 10:00:00", "2023-12-02 12:00:00", "%Y-%m-%d %H:%M:%S"),
            ("minute", "2023-12-02 10:00:00", "2023-12-02 10:05:00", "%Y-%m-%d %H:%M:%S"),
            ("week", "2023-11-27", "2023-12-10", "%Y-%m-%d"),
            ("month", "2023-10-01", "2023-12-31", "%Y-%m-%d"),
        ]
    )
    @snapshot_clickhouse_queries
    def test_day_format_varies_by_interval(self, interval, date_from, date_to, expected_format):
        self._create_events(
            data=[
                (
                    "user1",
                    [("2023-12-02 10:00:00", {"revenue": "100"})],
                ),
            ]
        )

        response = self._run_boxplot_query(date_from, date_to, interval=interval)

        data = self._parse_boxplot_results(response)
        assert len(data) >= 1
        from datetime import datetime

        datetime.strptime(data[0].day, expected_format)

    @parameterized.expand(
        [
            (
                "filter_test_accounts_off",
                False,
                9999.0,
            ),
            (
                "filter_test_accounts_on",
                True,
                100.0,
            ),
        ]
    )
    @snapshot_clickhouse_queries
    def test_filter_test_accounts(self, _name, filter_test_accounts, expected_max):
        self._create_events(
            data=[
                ("test", [("2023-12-02 10:00:00", {"revenue": "9999"})]),
                ("regular_user", [("2023-12-02 10:00:00", {"revenue": "100"})]),
            ]
        )

        response = self._run_boxplot_query("2023-12-02", "2023-12-02", filter_test_accounts=filter_test_accounts)

        data = self._parse_boxplot_results(response)
        assert len(data) == 1
        assert data[0].max == expected_max

    @parameterized.expand(
        [
            (
                "filter_chrome_only",
                [{"key": "$browser", "value": "Chrome"}],
                100.0,
                100.0,
            ),
            (
                "filter_firefox_only",
                [{"key": "$browser", "value": "Firefox"}],
                9999.0,
                9999.0,
            ),
            (
                "no_filter_sees_both",
                [],
                100.0,
                9999.0,
            ),
        ]
    )
    @snapshot_clickhouse_queries
    def test_property_filters(self, _name, properties, expected_min, expected_max):
        self._create_events(
            data=[
                (
                    "user1",
                    [
                        ("2023-12-02 10:00:00", {"revenue": "100", "$browser": "Chrome"}),
                        ("2023-12-02 11:00:00", {"revenue": "9999", "$browser": "Firefox"}),
                    ],
                ),
            ]
        )

        response = self._run_boxplot_query("2023-12-02", "2023-12-02", properties=properties)

        data = self._parse_boxplot_results(response)
        assert len(data) == 1
        assert data[0].min == expected_min
        assert data[0].max == expected_max

    @snapshot_clickhouse_queries
    def test_multiple_series_returns_data_for_each(self):
        self._create_events(
            data=[("user1", [("2023-12-02 10:00:00", {"revenue": "100"})])],
        )
        self._create_events(
            data=[("user2", [("2023-12-02 10:00:00", {"other_prop": "9999"})])],
            event="other_event",
        )

        response = self._run_boxplot_query(
            "2023-12-02",
            "2023-12-02",
            series=[
                EventsNode(kind="EventsNode", math="sum", math_property="revenue"),
                EventsNode(kind="EventsNode", event="other_event", math="sum", math_property="other_prop"),
            ],
        )

        data = self._parse_boxplot_results(response)
        assert len(data) == 2
        series_0 = [d for d in data if d.series_index == 0]
        series_1 = [d for d in data if d.series_index == 1]
        assert len(series_0) == 1
        assert len(series_1) == 1
        assert series_0[0].min == 100.0
        assert series_0[0].max == 100.0
        assert series_0[0].series_label is not None
        assert series_1[0].min == 9999.0
        assert series_1[0].max == 9999.0
        assert series_1[0].series_label is not None

    @parameterized.expand(
        [
            ("all_missing", [{}, {}]),
            ("single_missing", [{}]),
        ]
    )
    @snapshot_clickhouse_queries
    def test_none_property_values_become_zero(self, _name, event_properties):
        self._create_events(
            data=[
                (
                    "user1",
                    [(f"2023-12-02 {10 + i}:00:00", props) for i, props in enumerate(event_properties)],
                ),
            ]
        )

        response = self._run_boxplot_query("2023-12-02", "2023-12-02")
        data = self._parse_boxplot_results(response)

        assert len(data) == 1
        datum = data[0]
        assert datum.min == 0.0
        assert datum.max == 0.0
        assert datum.mean == 0.0
        assert datum.median == 0.0
        assert datum.p25 == 0.0
        assert datum.p75 == 0.0

    @snapshot_clickhouse_queries
    def test_results_are_ordered_by_day_ascending(self):
        self._create_events(
            data=[
                (
                    "user1",
                    [
                        ("2023-12-05 10:00:00", {"revenue": "500"}),
                        ("2023-12-01 10:00:00", {"revenue": "100"}),
                        ("2023-12-03 10:00:00", {"revenue": "300"}),
                    ],
                ),
            ]
        )

        response = self._run_boxplot_query("2023-12-01", "2023-12-05")
        data = self._parse_boxplot_results(response)

        days = [d.day for d in data]
        assert days == ["2023-12-01", "2023-12-02", "2023-12-03", "2023-12-04", "2023-12-05"]
        assert data[0].min == 100.0
        assert data[2].min == 300.0
        assert data[4].min == 500.0

    @snapshot_clickhouse_queries
    def test_custom_event_name(self):
        self._create_events(
            data=[("user1", [("2023-12-02 10:00:00", {"amount": "42"})])],
            event="purchase",
        )

        response = self._run_boxplot_query(
            "2023-12-02",
            "2023-12-02",
            series=[EventsNode(kind="EventsNode", event="purchase", math="sum", math_property="amount")],
        )

        data = self._parse_boxplot_results(response)
        assert len(data) == 1
        assert data[0].min == 42.0

    @snapshot_clickhouse_queries
    def test_each_datum_has_label_and_day(self):
        self._create_events(
            data=[
                (
                    "user1",
                    [
                        ("2023-12-02 10:00:00", {"revenue": "100"}),
                        ("2023-12-03 10:00:00", {"revenue": "200"}),
                    ],
                ),
            ]
        )

        response = self._run_boxplot_query("2023-12-02", "2023-12-03")

        for datum in self._parse_boxplot_results(response):
            assert datum.day is not None
            assert datum.label is not None
            assert len(datum.label) > 0

    @snapshot_clickhouse_queries
    def test_session_duration_produces_boxplot_data(self):
        from posthog.schema import PropertyMathType

        session_1 = str(uuid7("2023-12-02T10:00:00"))
        session_2 = str(uuid7("2023-12-02T11:00:00"))

        self._create_events(
            data=[
                (
                    "user1",
                    [
                        ("2023-12-02 10:00:00", {"$session_id": session_1}),
                        ("2023-12-02 10:05:00", {"$session_id": session_1}),
                    ],
                ),
                (
                    "user2",
                    [
                        ("2023-12-02 11:00:00", {"$session_id": session_2}),
                        ("2023-12-02 11:10:00", {"$session_id": session_2}),
                    ],
                ),
            ]
        )

        response = self._run_boxplot_query(
            "2023-12-02",
            "2023-12-02",
            math_property="$session_duration",
            series=[
                EventsNode(
                    kind="EventsNode",
                    math=PropertyMathType.AVG,
                    math_property="$session_duration",
                    math_property_type="session_properties",
                )
            ],
        )

        data = self._parse_boxplot_results(response)
        assert len(data) == 1
        datum = data[0]
        assert datum.day == "2023-12-02"
        assert datum.min > 0
        assert datum.max > 0
        assert datum.min <= datum.p25 <= datum.median <= datum.p75 <= datum.max
