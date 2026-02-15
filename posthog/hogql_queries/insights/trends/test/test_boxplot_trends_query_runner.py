from typing import Optional

import pytest
from freezegun import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, _create_person

from parameterized import parameterized

from posthog.schema import ChartDisplayType, DateRange, EventsNode, TrendsFilter, TrendsQuery

from posthog.hogql_queries.insights.trends.boxplot_trends_query_runner import BoxPlotTrendsQueryRunner
from posthog.models.utils import uuid7


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

    def test_empty_results_when_no_data(self):
        response = self._run_boxplot_query("2023-12-08", "2023-12-15")

        assert response.boxplot_data == []
        assert response.results == []

    def test_empty_results_when_no_series(self):
        query = TrendsQuery(
            dateRange=DateRange(date_from="2023-12-08", date_to="2023-12-15"),
            trendsFilter=TrendsFilter(display=ChartDisplayType.BOX_PLOT),
            series=[],
        )
        runner = BoxPlotTrendsQueryRunner(team=self.team, query=query)
        response = runner.calculate()

        assert response.results == []

    def test_basic_statistics_correctness(self):
        self._create_events(
            data=[
                (
                    "user1",
                    [
                        ("2023-12-02 10:00:00", {"revenue": "10"}),
                        ("2023-12-02 11:00:00", {"revenue": "20"}),
                        ("2023-12-02 12:00:00", {"revenue": "30"}),
                        ("2023-12-02 13:00:00", {"revenue": "40"}),
                        ("2023-12-02 14:00:00", {"revenue": "50"}),
                    ],
                ),
            ]
        )

        response = self._run_boxplot_query("2023-12-02", "2023-12-02")

        assert len(response.boxplot_data) == 1
        datum = response.boxplot_data[0]

        assert datum.min == 10.0
        assert datum.max == 50.0
        assert datum.mean == 30.0
        assert datum.q1 == pytest.approx(20.0, abs=1.0)
        assert datum.median == pytest.approx(30.0, abs=1.0)
        assert datum.q3 == pytest.approx(40.0, abs=1.0)

    def test_multiple_days_produce_multiple_datums(self):
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

        assert len(response.boxplot_data) == 2

        day1 = response.boxplot_data[0]
        assert day1.day == "2023-12-02"
        assert day1.min == 100.0
        assert day1.max == 200.0
        assert day1.mean == 150.0

        day2 = response.boxplot_data[1]
        assert day2.day == "2023-12-03"
        assert day2.min == 500.0
        assert day2.max == 600.0
        assert day2.mean == 550.0

    @parameterized.expand(
        [
            ("day", "2023-12-02", "2023-12-02", "%Y-%m-%d"),
            ("hour", "2023-12-02 10:00:00", "2023-12-02 12:00:00", "%Y-%m-%d %H:%M:%S"),
        ]
    )
    def test_day_format_varies_by_interval(self, interval, date_from, date_to, expected_format):
        self._create_events(
            data=[
                (
                    "user1",
                    [
                        ("2023-12-02 10:00:00", {"revenue": "100"}),
                    ],
                ),
            ]
        )

        response = self._run_boxplot_query(date_from, date_to, interval=interval)

        assert len(response.boxplot_data) >= 1
        from datetime import datetime

        datetime.strptime(response.boxplot_data[0].day, expected_format)

    def test_filter_test_accounts(self):
        self._create_events(
            data=[
                (
                    "test",
                    [
                        ("2023-12-02 10:00:00", {"revenue": "9999"}),
                    ],
                ),
                (
                    "regular_user",
                    [
                        ("2023-12-02 10:00:00", {"revenue": "100"}),
                    ],
                ),
            ]
        )

        response_with_test = self._run_boxplot_query("2023-12-02", "2023-12-02", filter_test_accounts=False)
        response_without_test = self._run_boxplot_query("2023-12-02", "2023-12-02", filter_test_accounts=True)

        assert len(response_with_test.boxplot_data) == 1
        assert response_with_test.boxplot_data[0].max == 9999.0

        assert len(response_without_test.boxplot_data) == 1
        assert response_without_test.boxplot_data[0].max == 100.0
        assert response_without_test.boxplot_data[0].min == 100.0

    def test_property_filters(self):
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

        response = self._run_boxplot_query(
            "2023-12-02",
            "2023-12-02",
            properties=[{"key": "$browser", "value": "Chrome"}],
        )

        assert len(response.boxplot_data) == 1
        assert response.boxplot_data[0].max == 100.0
        assert response.boxplot_data[0].min == 100.0

    def test_only_first_series_is_used(self):
        self._create_events(
            data=[
                (
                    "user1",
                    [
                        ("2023-12-02 10:00:00", {"revenue": "100"}),
                    ],
                ),
            ]
        )
        self._create_events(
            data=[
                (
                    "user2",
                    [
                        ("2023-12-02 10:00:00", {"other_prop": "9999"}),
                    ],
                ),
            ],
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

        assert len(response.boxplot_data) == 1
        assert response.boxplot_data[0].min == 100.0
        assert response.boxplot_data[0].max == 100.0

    def test_none_property_values_become_zero(self):
        self._create_events(
            data=[
                (
                    "user1",
                    [
                        ("2023-12-02 10:00:00", {}),
                        ("2023-12-02 11:00:00", {}),
                    ],
                ),
            ]
        )

        response = self._run_boxplot_query("2023-12-02", "2023-12-02")

        assert len(response.boxplot_data) == 1
        datum = response.boxplot_data[0]
        assert datum.min == 0.0
        assert datum.max == 0.0
        assert datum.mean == 0.0
        assert datum.median == 0.0
        assert datum.q1 == 0.0
        assert datum.q3 == 0.0
