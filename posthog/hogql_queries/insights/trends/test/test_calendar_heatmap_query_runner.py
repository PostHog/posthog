from typing import Optional

from freezegun import freeze_time

from posthog.hogql_queries.insights.trends.calendar_heatmap_query_runner import CalendarHeatmapQueryRunner
from posthog.models.utils import uuid7
from posthog.schema import (
    DateRange,
    CalendarHeatmapQuery,
    EventsNode,
    ActionConversionGoal,
    CustomEventConversionGoal,
)
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
)
from posthog.models import Action


class TestCalendarHeatmapQueryRunner(ClickhouseTestMixin, APIBaseTest):
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
                session_id = str(uuid7())
                properties = rest[0] if rest else {}
                _create_event(
                    team=self.team,
                    event=event,
                    distinct_id=id,
                    timestamp=timestamp,
                    uuid=str(uuid7()),
                    properties={
                        "$session_id": session_id,
                        "$start_timestamp": timestamp,
                        **properties,
                    },
                )

    def _run_calendar_heatmap_query_runner(
        self,
        date_from,
        date_to,
        properties=None,
        filter_test_accounts: Optional[bool] = False,
        series=None,
    ):
        query = CalendarHeatmapQuery(
            dateRange=DateRange(date_from=date_from, date_to=date_to),
            properties=properties or [],
            filterTestAccounts=filter_test_accounts,
            series=series or [EventsNode(kind="EventsNode")],
        )
        runner = CalendarHeatmapQueryRunner(team=self.team, query=query)
        return runner.calculate()

    def test_empty_results_when_no_data(self):
        response = self._run_calendar_heatmap_query_runner("2023-12-08", "2023-12-15")
        assert response.results.data == [], f"Expected empty results, got {response.results.data}"

    def test_basic_active_hours(self):
        self._create_events(
            data=[
                (
                    "user1",
                    [
                        ("2023-12-02 10:00:00", {}),  # Saturday 10:00
                        ("2023-12-02 10:30:00", {}),  # Same hour, should count as another event
                        ("2023-12-02 11:00:00", {}),  # Saturday 11:00
                    ],
                ),
                (
                    "user2",
                    [
                        ("2023-12-02 10:00:00", {}),  # Saturday 10:00
                        ("2023-12-03 15:00:00", {}),  # Sunday 15:00
                    ],
                ),
            ]
        )

        response = self._run_calendar_heatmap_query_runner("2023-12-01", "2023-12-04")

        # Convert results to a dict for easier testing
        results_dict = {(r.row, r.column): r.value for r in response.results.data}

        # Saturday (day 6) expectations
        assert results_dict.get((6, 10)) == 3, f"Expected 3 events at Saturday 10:00, got {results_dict.get((6, 10))}"
        assert results_dict.get((6, 11)) == 1, f"Expected 1 event at Saturday 11:00, got {results_dict.get((6, 11))}"

        # Sunday (day 7) expectations
        assert results_dict.get((7, 15)) == 1, f"Expected 1 event at Sunday 15:00, got {results_dict.get((7, 15))}"

        # Test aggregations
        days_dict = {r.row: r.value for r in response.results.rowAggregations}
        assert days_dict.get(6) == 4, f"Expected 4 events on Saturday, got {days_dict.get(6)}"
        assert days_dict.get(7) == 1, f"Expected 1 event on Sunday, got {days_dict.get(7)}"

        hours_dict = {r.column: r.value for r in response.results.columnAggregations}
        assert hours_dict.get(10) == 3, f"Expected 3 events at 10:00, got {hours_dict.get(10)}"
        assert hours_dict.get(11) == 1, f"Expected 1 event at 11:00, got {hours_dict.get(11)}"
        assert hours_dict.get(15) == 1, f"Expected 1 event at 15:00, got {hours_dict.get(15)}"

        assert response.results.allAggregations == 5, f"Expected 5 total events, got {response.results.allAggregations}"

    def test_filter_test_accounts(self):
        self._create_events(
            data=[
                (
                    "test",  # Test account
                    [
                        ("2023-12-02 10:00:00", {}),
                        ("2023-12-02 11:00:00", {}),
                    ],
                ),
                (
                    "regular_user",
                    [
                        ("2023-12-02 10:00:00", {}),
                    ],
                ),
            ]
        )

        # With test accounts
        response = self._run_calendar_heatmap_query_runner("2023-12-01", "2023-12-03", filter_test_accounts=False)
        results_dict = {(r.row, r.column): r.value for r in response.results.data}
        assert results_dict.get((6, 10)) == 2, f"Expected 2 events with test accounts, got {results_dict.get((6, 10))}"

        # Without test accounts
        response = self._run_calendar_heatmap_query_runner("2023-12-01", "2023-12-03", filter_test_accounts=True)
        results_dict = {(r.row, r.column): r.value for r in response.results.data}
        assert (
            results_dict.get((6, 10)) == 1
        ), f"Expected 1 event without test accounts, got {results_dict.get((6, 10))}"

    def test_all_time_range(self):
        self._create_events(
            data=[
                (
                    "user1",
                    [
                        ("2023-12-02 10:00:00", {}),
                        ("2024-01-15 11:00:00", {}),
                    ],
                ),
            ]
        )

        response = self._run_calendar_heatmap_query_runner("all", "2024-01-20")
        results_dict = {(r.row, r.column): r.value for r in response.results.data}

        assert results_dict.get((6, 10)) == 1, f"Expected 1 December visit, got {results_dict.get((6, 10))}"
        assert results_dict.get((1, 11)) == 1, f"Expected 1 January visit, got {results_dict.get((1, 11))}"

    def test_with_properties(self):
        self._create_events(
            data=[
                (
                    "user1",
                    [
                        ("2023-12-02 10:00:00", {"$browser": "Chrome"}),
                        ("2023-12-02 11:00:00", {"$browser": "Firefox"}),
                    ],
                ),
            ]
        )

        response = self._run_calendar_heatmap_query_runner(
            "2023-12-01",
            "2023-12-03",
            properties=[{"key": "$browser", "value": "Chrome"}],
        )

        results_dict = {(r.row, r.column): r.value for r in response.results.data}
        assert results_dict.get((6, 10)) == 1, f"Expected 1 Chrome visit, got {results_dict.get((6, 10))}"
        assert (
            6,
            11,
        ) not in results_dict, f"Expected Firefox visit to be filtered out, but found {results_dict.get((6, 11))}"

    def test_aggregations(self):
        self._create_events(
            data=[
                (
                    "user1",
                    [
                        ("2023-12-02 10:00:00", {}),  # Saturday 10:00
                        ("2023-12-02 11:00:00", {}),  # Saturday 11:00
                        ("2023-12-03 10:00:00", {}),  # Sunday 10:00
                    ],
                ),
                (
                    "user2",
                    [
                        ("2023-12-02 10:00:00", {}),  # Saturday 10:00
                        ("2023-12-03 15:00:00", {}),  # Sunday 15:00
                    ],
                ),
            ]
        )

        response = self._run_calendar_heatmap_query_runner("2023-12-01", "2023-12-04")

        # Test day-hour combinations
        day_hour_dict = {(r.row, r.column): r.value for r in response.results.data}
        assert (
            day_hour_dict.get((6, 10)) == 2
        ), f"Expected 2 events on Saturday at 10:00, got {day_hour_dict.get((6, 10))}"
        assert (
            day_hour_dict.get((6, 11)) == 1
        ), f"Expected 1 event on Saturday at 11:00, got {day_hour_dict.get((6, 11))}"
        assert day_hour_dict.get((7, 10)) == 1, f"Expected 1 event on Sunday at 10:00, got {day_hour_dict.get((7, 10))}"
        assert day_hour_dict.get((7, 15)) == 1, f"Expected 1 event on Sunday at 15:00, got {day_hour_dict.get((7, 15))}"

        # Test days aggregation
        days_dict = {r.row: r.value for r in response.results.rowAggregations}
        assert days_dict.get(6) == 3, f"Expected 3 events on Saturday, got {days_dict.get(6)}"
        assert days_dict.get(7) == 2, f"Expected 2 events on Sunday, got {days_dict.get(7)}"

        # Test hours aggregation
        hours_dict = {r.column: r.value for r in response.results.columnAggregations}
        assert hours_dict.get(10) == 3, f"Expected 3 events at 10:00, got {hours_dict.get(10)}"
        assert hours_dict.get(11) == 1, f"Expected 1 event at 11:00, got {hours_dict.get(11)}"
        assert hours_dict.get(15) == 1, f"Expected 1 event at 15:00, got {hours_dict.get(15)}"

        # Test total events
        assert response.results.allAggregations == 5, f"Expected 5 total events, got {response.results.allAggregations}"

    def test_empty_results_structure(self):
        response = self._run_calendar_heatmap_query_runner("2023-12-08", "2023-12-15")

        assert response.results.data == [], f"Expected empty data, got {response.results.data}"
        assert (
            response.results.rowAggregations == []
        ), f"Expected empty row aggregations, got {response.results.rowAggregations}"
        assert (
            response.results.columnAggregations == []
        ), f"Expected empty column aggregations, got {response.results.columnAggregations}"
        assert (
            response.results.allAggregations == 0
        ), f"Expected 0 total aggregations, got {response.results.allAggregations}"

    def test_custom_event(self):
        self._create_events(
            data=[
                (
                    "user1",
                    [
                        ("2023-12-02 10:00:00", {}),
                    ],
                ),
            ],
            event="custom_event",
        )

        # Set the event in the series
        query = CalendarHeatmapQuery(
            dateRange=DateRange(date_from="2023-12-01", date_to="2023-12-03"),
            properties=[],
            filterTestAccounts=False,
            series=[EventsNode(kind="EventsNode", event="custom_event")],
        )
        runner = CalendarHeatmapQueryRunner(team=self.team, query=query)
        response = runner.calculate()
        results_dict = {(r.row, r.column): r.value for r in response.results.data}
        assert results_dict.get((6, 10)) == 1, f"Expected 1 custom event, got {results_dict.get((6, 10))}"

    def test_action_conversion_goal(self):
        action = Action.objects.create(
            team=self.team,
            name="Did Custom Event",
            steps_json=[
                {
                    "event": "custom_event",
                }
            ],
        )

        self._create_events(
            data=[
                (
                    "user1",
                    [
                        ("2023-12-02 10:00:00", {}),
                    ],
                ),
            ],
            event="custom_event",
        )

        query = CalendarHeatmapQuery(
            dateRange=DateRange(date_from="2023-12-01", date_to="2023-12-03"),
            properties=[],
            filterTestAccounts=False,
            series=[EventsNode(kind="EventsNode")],
            conversionGoal=ActionConversionGoal(actionId=action.id),
        )
        runner = CalendarHeatmapQueryRunner(team=self.team, query=query)
        response = runner.calculate()
        results_dict = {(r.row, r.column): r.value for r in response.results.data}
        assert results_dict.get((6, 10)) == 1, f"Expected 1 action conversion goal, got {results_dict.get((6, 10))}"

    def test_custom_event_conversion_goal(self):
        self._create_events(
            data=[
                (
                    "user1",
                    [
                        ("2023-12-02 10:00:00", {}),
                    ],
                ),
            ],
            event="my_custom_event",
        )

        query = CalendarHeatmapQuery(
            dateRange=DateRange(date_from="2023-12-01", date_to="2023-12-03"),
            properties=[],
            filterTestAccounts=False,
            series=[EventsNode(kind="EventsNode")],
            conversionGoal=CustomEventConversionGoal(customEventName="my_custom_event"),
        )
        runner = CalendarHeatmapQueryRunner(team=self.team, query=query)
        response = runner.calculate()
        results_dict = {(r.row, r.column): r.value for r in response.results.data}
        assert (
            results_dict.get((6, 10)) == 1
        ), f"Expected 1 custom event conversion goal, got {results_dict.get((6, 10))}"

    def test_unique_users_vs_total_events(self):
        # Create events with multiple events per user in the same hour
        self._create_events(
            data=[
                (
                    "user1",
                    [
                        ("2023-12-02 10:00:00", {}),  # Saturday 10:00
                        ("2023-12-02 10:30:00", {}),  # Same hour
                        ("2023-12-02 10:45:00", {}),  # Same hour
                    ],
                ),
                (
                    "user2",
                    [
                        ("2023-12-02 10:15:00", {}),  # Saturday 10:00
                        ("2023-12-02 10:45:00", {}),  # Same hour
                    ],
                ),
            ]
        )

        # Test total events (default)
        response = self._run_calendar_heatmap_query_runner("2023-12-01", "2023-12-04")
        results_dict = {(r.row, r.column): r.value for r in response.results.data}
        assert results_dict.get((6, 10)) == 5, f"Expected 5 total events at 10:00, got {results_dict.get((6, 10))}"
        assert response.results.allAggregations == 5, f"Expected 5 total events, got {response.results.allAggregations}"

        # Test unique users (dau)
        query = CalendarHeatmapQuery(
            dateRange=DateRange(date_from="2023-12-01", date_to="2023-12-04"),
            properties=[],
            filterTestAccounts=False,
            series=[EventsNode(kind="EventsNode", math="dau")],
        )
        runner = CalendarHeatmapQueryRunner(team=self.team, query=query)
        response = runner.calculate()
        results_dict = {(r.row, r.column): r.value for r in response.results.data}
        assert results_dict.get((6, 10)) == 2, f"Expected 2 unique users at 10:00, got {results_dict.get((6, 10))}"
        assert (
            response.results.allAggregations == 2
        ), f"Expected 2 unique users total, got {response.results.allAggregations}"

    def test_unique_users_across_hours(self):
        # Create events with users active in multiple hours
        self._create_events(
            data=[
                (
                    "user1",
                    [
                        ("2023-12-02 10:00:00", {}),  # Saturday 10:00
                        ("2023-12-02 11:00:00", {}),  # Saturday 11:00
                        ("2023-12-02 12:00:00", {}),  # Saturday 12:00
                    ],
                ),
                (
                    "user2",
                    [
                        ("2023-12-02 10:00:00", {}),  # Saturday 10:00
                        ("2023-12-02 11:30:00", {}),  # Saturday 11:00
                    ],
                ),
            ]
        )

        # Test total events (default)
        response = self._run_calendar_heatmap_query_runner("2023-12-01", "2023-12-04")
        results_dict = {(r.row, r.column): r.value for r in response.results.data}
        assert results_dict.get((6, 10)) == 2, f"Expected 2 events at 10:00, got {results_dict.get((6, 10))}"
        assert results_dict.get((6, 11)) == 2, f"Expected 2 events at 11:00, got {results_dict.get((6, 11))}"
        assert results_dict.get((6, 12)) == 1, f"Expected 1 event at 12:00, got {results_dict.get((6, 12))}"
        assert response.results.allAggregations == 5, f"Expected 5 events total, got {response.results.allAggregations}"

        # Test unique users (dau)
        query = CalendarHeatmapQuery(
            dateRange=DateRange(date_from="2023-12-01", date_to="2023-12-04"),
            properties=[],
            filterTestAccounts=False,
            series=[EventsNode(kind="EventsNode", math="dau")],
        )
        runner = CalendarHeatmapQueryRunner(team=self.team, query=query)
        response = runner.calculate()
        results_dict = {(r.row, r.column): r.value for r in response.results.data}
        assert results_dict.get((6, 10)) == 2, f"Expected 2 unique users at 10:00, got {results_dict.get((6, 10))}"
        assert results_dict.get((6, 11)) == 2, f"Expected 2 unique users at 11:00, got {results_dict.get((6, 11))}"
        assert results_dict.get((6, 12)) == 1, f"Expected 1 unique user at 12:00, got {results_dict.get((6, 12))}"
        assert (
            response.results.allAggregations == 2
        ), f"Expected 2 unique users total, got {response.results.allAggregations}"

    def test_unique_users_across_days(self):
        # Create events with users active across multiple days
        self._create_events(
            data=[
                (
                    "user1",
                    [
                        ("2023-12-02 10:00:00", {}),  # Saturday
                        ("2023-12-03 10:00:00", {}),  # Sunday
                        ("2023-12-04 10:00:00", {}),  # Monday
                    ],
                ),
                (
                    "user2",
                    [
                        ("2023-12-02 10:00:00", {}),  # Saturday
                        ("2023-12-03 10:00:00", {}),  # Sunday
                    ],
                ),
            ]
        )

        # Test total events (default)
        response = self._run_calendar_heatmap_query_runner("2023-12-01", "2023-12-05")
        results_dict = {(r.row, r.column): r.value for r in response.results.data}
        days_dict = {r.row: r.value for r in response.results.rowAggregations}
        assert results_dict.get((6, 10)) == 2, f"Expected 2 events on Saturday, got {results_dict.get((6, 10))}"
        assert results_dict.get((7, 10)) == 2, f"Expected 2 events on Sunday, got {results_dict.get((7, 10))}"
        assert results_dict.get((1, 10)) == 1, f"Expected 1 event on Monday, got {results_dict.get((1, 10))}"
        assert days_dict.get(6) == 2, f"Expected 2 events on Saturday, got {days_dict.get(6)}"
        assert days_dict.get(7) == 2, f"Expected 2 events on Sunday, got {days_dict.get(7)}"
        assert days_dict.get(1) == 1, f"Expected 1 event on Monday, got {days_dict.get(1)}"
        assert response.results.allAggregations == 5, f"Expected 5 events total, got {response.results.allAggregations}"

        # Test unique users (dau)
        query = CalendarHeatmapQuery(
            dateRange=DateRange(date_from="2023-12-01", date_to="2023-12-05"),
            properties=[],
            filterTestAccounts=False,
            series=[EventsNode(kind="EventsNode", math="dau")],
        )
        runner = CalendarHeatmapQueryRunner(team=self.team, query=query)
        response = runner.calculate()
        results_dict = {(r.row, r.column): r.value for r in response.results.data}
        days_dict = {r.row: r.value for r in response.results.rowAggregations}
        assert results_dict.get((6, 10)) == 2, f"Expected 2 unique users on Saturday, got {results_dict.get((6, 10))}"
        assert results_dict.get((7, 10)) == 2, f"Expected 2 unique users on Sunday, got {results_dict.get((7, 10))}"
        assert results_dict.get((1, 10)) == 1, f"Expected 1 unique user on Monday, got {results_dict.get((1, 10))}"
        assert days_dict.get(6) == 2, f"Expected 2 unique users on Saturday, got {days_dict.get(6)}"
        assert days_dict.get(7) == 2, f"Expected 2 unique users on Sunday, got {days_dict.get(7)}"
        assert days_dict.get(1) == 1, f"Expected 1 unique user on Monday, got {days_dict.get(1)}"
        assert (
            response.results.allAggregations == 2
        ), f"Expected 2 unique users total, got {response.results.allAggregations}"

    def test_filter_test_accounts_both_templates(self):
        """Test that filter_test_accounts works for both all users and unique users templates"""
        self._create_events(
            data=[
                (
                    "test",
                    [
                        ("2023-12-02 10:00:00", {}),
                        ("2023-12-02 10:30:00", {}),
                        ("2023-12-02 11:00:00", {}),
                    ],
                ),
                (
                    "regular_user",
                    [
                        ("2023-12-02 10:00:00", {}),
                        ("2023-12-02 12:00:00", {}),
                    ],
                ),
                (
                    "another_regular_user",
                    [
                        ("2023-12-02 10:00:00", {}),
                    ],
                ),
            ]
        )

        response_all_with_test = self._run_calendar_heatmap_query_runner(
            "2023-12-01", "2023-12-03", filter_test_accounts=False
        )
        results_all_with_test = {(r.row, r.column): r.value for r in response_all_with_test.results.data}

        response_all_without_test = self._run_calendar_heatmap_query_runner(
            "2023-12-01", "2023-12-03", filter_test_accounts=True
        )
        results_all_without_test = {(r.row, r.column): r.value for r in response_all_without_test.results.data}

        query_dau_with_test = CalendarHeatmapQuery(
            dateRange=DateRange(date_from="2023-12-01", date_to="2023-12-03"),
            properties=[],
            filterTestAccounts=False,
            series=[EventsNode(kind="EventsNode", math="dau")],
        )
        runner_dau_with_test = CalendarHeatmapQueryRunner(team=self.team, query=query_dau_with_test)
        response_dau_with_test = runner_dau_with_test.calculate()
        results_dau_with_test = {(r.row, r.column): r.value for r in response_dau_with_test.results.data}

        query_dau_without_test = CalendarHeatmapQuery(
            dateRange=DateRange(date_from="2023-12-01", date_to="2023-12-03"),
            properties=[],
            filterTestAccounts=True,
            series=[EventsNode(kind="EventsNode", math="dau")],
        )
        runner_dau_without_test = CalendarHeatmapQueryRunner(team=self.team, query=query_dau_without_test)
        response_dau_without_test = runner_dau_without_test.calculate()
        results_dau_without_test = {(r.row, r.column): r.value for r in response_dau_without_test.results.data}

        assert (
            results_all_with_test.get((6, 10)) == 4
        ), f"Expected 4 events with test accounts, got {results_all_with_test.get((6, 10))}"
        assert (
            results_all_with_test.get((6, 11)) == 1
        ), f"Expected 1 event from test user at 11:00, got {results_all_with_test.get((6, 11))}"
        assert (
            results_all_with_test.get((6, 12)) == 1
        ), f"Expected 1 event from regular_user at 12:00, got {results_all_with_test.get((6, 12))}"
        assert (
            response_all_with_test.results.allAggregations == 6
        ), f"Expected 6 events total with test accounts, got {response_all_with_test.results.allAggregations}"

        assert (
            results_all_without_test.get((6, 10)) == 2
        ), f"Expected 2 events without test accounts, got {results_all_without_test.get((6, 10))}"
        assert (
            (6, 11) not in results_all_without_test
        ), f"Expected test user's 11:00 event to be filtered out, but found {results_all_without_test.get((6, 11))}"
        assert (
            results_all_without_test.get((6, 12)) == 1
        ), f"Expected 1 event from regular_user at 12:00, got {results_all_without_test.get((6, 12))}"
        assert (
            response_all_without_test.results.allAggregations == 3
        ), f"Expected 3 events total without test accounts, got {response_all_without_test.results.allAggregations}"

        assert (
            results_dau_with_test.get((6, 10)) == 3
        ), f"Expected 3 unique users with test accounts, got {results_dau_with_test.get((6, 10))}"
        assert (
            results_dau_with_test.get((6, 11)) == 1
        ), f"Expected 1 unique test user at 11:00, got {results_dau_with_test.get((6, 11))}"
        assert (
            results_dau_with_test.get((6, 12)) == 1
        ), f"Expected 1 unique regular_user at 12:00, got {results_dau_with_test.get((6, 12))}"
        assert (
            response_dau_with_test.results.allAggregations == 3
        ), f"Expected 3 unique users total with test accounts, got {response_dau_with_test.results.allAggregations}"

        assert (
            results_dau_without_test.get((6, 10)) == 2
        ), f"Expected 2 unique users without test accounts, got {results_dau_without_test.get((6, 10))}"
        assert (
            (6, 11) not in results_dau_without_test
        ), f"Expected test user's 11:00 to be filtered out, but found {results_dau_without_test.get((6, 11))}"
        assert (
            results_dau_without_test.get((6, 12)) == 1
        ), f"Expected 1 unique regular_user at 12:00, got {results_dau_without_test.get((6, 12))}"
        assert (
            response_dau_without_test.results.allAggregations == 2
        ), f"Expected 2 unique users total without test accounts, got {response_dau_without_test.results.allAggregations}"

        assert (
            results_dau_with_test.get((6, 10)) == 3
        ), f"Expected 3 unique users with test accounts, got {results_dau_with_test.get((6, 10))}"
        assert (
            results_all_with_test.get((6, 10)) == 4
        ), f"Expected 4 events with test accounts, got {results_all_with_test.get((6, 10))}"

        assert (
            results_dau_without_test.get((6, 10)) == 2
        ), f"Expected 2 unique users without test accounts, got {results_dau_without_test.get((6, 10))}"
        assert (
            results_all_without_test.get((6, 10)) == 2
        ), f"Expected 2 events without test accounts, got {results_all_without_test.get((6, 10))}"

    def test_multiple_event_types_comprehensive(self):
        """Test calendar heatmap with multiple different event types"""
        self._create_events(
            data=[
                (
                    "signup_user1",
                    [
                        ("2023-12-02 10:00:00", {}),
                        ("2023-12-02 11:00:00", {}),
                    ],
                ),
                (
                    "signup_user2",
                    [
                        ("2023-12-02 10:30:00", {}),
                    ],
                ),
            ],
            event="sign_up",
        )

        self._create_events(
            data=[
                (
                    "purchase_user1",
                    [
                        ("2023-12-02 14:00:00", {}),
                    ],
                ),
                (
                    "purchase_user2",
                    [
                        ("2023-12-02 15:00:00", {}),
                    ],
                ),
            ],
            event="purchase",
        )

        # Test sign_up events
        query = CalendarHeatmapQuery(
            dateRange=DateRange(date_from="2023-12-01", date_to="2023-12-03"),
            properties=[],
            filterTestAccounts=False,
            series=[EventsNode(kind="EventsNode", event="sign_up")],
        )
        runner = CalendarHeatmapQueryRunner(team=self.team, query=query)
        response = runner.calculate()
        results_dict = {(r.row, r.column): r.value for r in response.results.data}

        assert results_dict.get((6, 10)) == 2, f"Expected 2 sign_up events at 10:00, got {results_dict.get((6, 10))}"
        assert results_dict.get((6, 11)) == 1, f"Expected 1 sign_up event at 11:00, got {results_dict.get((6, 11))}"
        assert (
            results_dict.get((6, 14)) is None
        ), f"Expected no sign_up events at 14:00, got {results_dict.get((6, 14))}"
        assert (
            response.results.allAggregations == 3
        ), f"Expected 3 total sign_up events, got {response.results.allAggregations}"

        # Test purchase events
        query = CalendarHeatmapQuery(
            dateRange=DateRange(date_from="2023-12-01", date_to="2023-12-03"),
            properties=[],
            filterTestAccounts=False,
            series=[EventsNode(kind="EventsNode", event="purchase")],
        )
        runner = CalendarHeatmapQueryRunner(team=self.team, query=query)
        response = runner.calculate()
        results_dict = {(r.row, r.column): r.value for r in response.results.data}

        assert results_dict.get((6, 14)) == 1, f"Expected 1 purchase event at 14:00, got {results_dict.get((6, 14))}"
        assert results_dict.get((6, 15)) == 1, f"Expected 1 purchase event at 15:00, got {results_dict.get((6, 15))}"
        assert (
            results_dict.get((6, 10)) is None
        ), f"Expected no purchase events at 10:00, got {results_dict.get((6, 10))}"
        assert (
            response.results.allAggregations == 2
        ), f"Expected 2 total purchase events, got {response.results.allAggregations}"

    def test_complex_actions_with_multiple_steps(self):
        """Test calendar heatmap with complex actions containing multiple steps"""
        # Create a complex action with multiple events
        action = Action.objects.create(
            team=self.team,
            name="Complex User Journey",
            steps_json=[
                {"event": "sign_up", "properties": [{"key": "$browser", "value": "Chrome"}]},
                {"event": "purchase", "properties": [{"key": "amount", "value": "100", "operator": "gt"}]},
            ],
        )

        # Create events that match the action steps
        self._create_events(
            data=[
                (
                    "complex_user1",
                    [
                        ("2023-12-02 10:00:00", {"$browser": "Chrome"}),
                    ],
                ),
                (
                    "complex_user2",
                    [
                        ("2023-12-02 11:00:00", {"$browser": "Firefox"}),  # Won't match
                    ],
                ),
            ],
            event="sign_up",
        )

        self._create_events(
            data=[
                (
                    "complex_user3",
                    [
                        ("2023-12-02 14:00:00", {"amount": "150"}),
                    ],
                ),
                (
                    "complex_user4",
                    [
                        ("2023-12-02 15:00:00", {"amount": "050"}),  # Won't match (not > 100)
                    ],
                ),
            ],
            event="purchase",
        )

        query = CalendarHeatmapQuery(
            dateRange=DateRange(date_from="2023-12-01", date_to="2023-12-03"),
            properties=[],
            filterTestAccounts=False,
            series=[EventsNode(kind="EventsNode")],
            conversionGoal=ActionConversionGoal(actionId=action.id),
        )
        runner = CalendarHeatmapQueryRunner(team=self.team, query=query)
        response = runner.calculate()
        results_dict = {(r.row, r.column): r.value for r in response.results.data}

        # Should only count events that match the action criteria
        assert (
            results_dict.get((6, 10)) == 1
        ), f"Expected 1 matching sign_up event at 10:00, got {results_dict.get((6, 10))}"
        assert (
            results_dict.get((6, 14)) == 1
        ), f"Expected 1 matching purchase event at 14:00, got {results_dict.get((6, 14))}"
        assert (
            results_dict.get((6, 11)) is None
        ), f"Expected no matching events at 11:00, got {results_dict.get((6, 11))}"
        assert (
            results_dict.get((6, 15)) is None
        ), f"Expected no matching events at 15:00, got {results_dict.get((6, 15))}"
        assert (
            response.results.allAggregations == 2
        ), f"Expected 2 total matching events, got {response.results.allAggregations}"

    def test_comprehensive_property_filtering(self):
        """Test calendar heatmap with comprehensive property filtering scenarios"""
        self._create_events(
            data=[
                (
                    "prop_user1",
                    [
                        ("2023-12-02 10:00:00", {"$browser": "Chrome", "$os": "Windows", "plan": "premium"}),
                        ("2023-12-02 11:00:00", {"$browser": "Chrome", "$os": "Mac", "plan": "free"}),
                    ],
                ),
                (
                    "prop_user2",
                    [
                        ("2023-12-02 10:30:00", {"$browser": "Firefox", "$os": "Windows", "plan": "premium"}),
                        ("2023-12-02 12:00:00", {"$browser": "Safari", "$os": "Mac", "plan": "premium"}),
                    ],
                ),
            ]
        )

        # Test single property filter
        response = self._run_calendar_heatmap_query_runner(
            "2023-12-01",
            "2023-12-03",
            properties=[{"key": "$browser", "value": "Chrome"}],
        )
        results_dict = {(r.row, r.column): r.value for r in response.results.data}
        assert results_dict.get((6, 10)) == 1, f"Expected 1 Chrome event at 10:00, got {results_dict.get((6, 10))}"
        assert results_dict.get((6, 11)) == 1, f"Expected 1 Chrome event at 11:00, got {results_dict.get((6, 11))}"
        assert (
            response.results.allAggregations == 2
        ), f"Expected 2 total Chrome events, got {response.results.allAggregations}"

        # Test multiple property filters (AND logic)
        response = self._run_calendar_heatmap_query_runner(
            "2023-12-01",
            "2023-12-03",
            properties=[{"key": "$browser", "value": "Chrome"}, {"key": "$os", "value": "Windows"}],
        )
        results_dict = {(r.row, r.column): r.value for r in response.results.data}
        assert (
            results_dict.get((6, 10)) == 1
        ), f"Expected 1 Chrome+Windows event at 10:00, got {results_dict.get((6, 10))}"
        assert (
            results_dict.get((6, 11)) is None
        ), f"Expected no Chrome+Windows events at 11:00, got {results_dict.get((6, 11))}"
        assert (
            response.results.allAggregations == 1
        ), f"Expected 1 total Chrome+Windows event, got {response.results.allAggregations}"

        # Test property filter with premium plan
        response = self._run_calendar_heatmap_query_runner(
            "2023-12-01",
            "2023-12-03",
            properties=[{"key": "plan", "value": "premium"}],
        )
        results_dict = {(r.row, r.column): r.value for r in response.results.data}
        assert results_dict.get((6, 10)) == 2, f"Expected 2 premium events at 10:00, got {results_dict.get((6, 10))}"
        assert results_dict.get((6, 12)) == 1, f"Expected 1 premium event at 12:00, got {results_dict.get((6, 12))}"
        assert (
            response.results.allAggregations == 3
        ), f"Expected 3 total premium events, got {response.results.allAggregations}"

    def test_math_types_comprehensive(self):
        """Test calendar heatmap with different math types - note: currently only supports event counting"""
        self._create_events(
            data=[
                (
                    "math_user1",
                    [
                        ("2023-12-02 10:00:00", {"revenue": "100"}),
                        ("2023-12-02 10:30:00", {"revenue": "50"}),
                        ("2023-12-02 11:00:00", {"revenue": "200"}),
                    ],
                ),
                (
                    "math_user2",
                    [
                        ("2023-12-02 10:15:00", {"revenue": "75"}),
                        ("2023-12-02 12:00:00", {"revenue": "150"}),
                    ],
                ),
            ]
        )

        # Test sum math type - but calendar heatmap currently only counts events, not property values
        query = CalendarHeatmapQuery(
            dateRange=DateRange(date_from="2023-12-01", date_to="2023-12-03"),
            properties=[],
            filterTestAccounts=False,
            series=[EventsNode(kind="EventsNode", math="sum", math_property="revenue")],
        )
        runner = CalendarHeatmapQueryRunner(team=self.team, query=query)
        response = runner.calculate()
        results_dict = {(r.row, r.column): r.value for r in response.results.data}

        # Currently calendar heatmap only counts events, doesn't sum property values
        assert (
            results_dict.get((6, 10)) == 3
        ), f"Expected 3 events at 10:00, got {results_dict.get((6, 10))}"  # 3 events at 10:00
        assert results_dict.get((6, 11)) == 1, f"Expected 1 event at 11:00, got {results_dict.get((6, 11))}"
        assert results_dict.get((6, 12)) == 1, f"Expected 1 event at 12:00, got {results_dict.get((6, 12))}"
        assert response.results.allAggregations == 5, f"Expected 5 total events, got {response.results.allAggregations}"

        # Test average math type - also only counts events
        query = CalendarHeatmapQuery(
            dateRange=DateRange(date_from="2023-12-01", date_to="2023-12-03"),
            properties=[],
            filterTestAccounts=False,
            series=[EventsNode(kind="EventsNode", math="avg", math_property="revenue")],
        )
        runner = CalendarHeatmapQueryRunner(team=self.team, query=query)
        response = runner.calculate()
        results_dict = {(r.row, r.column): r.value for r in response.results.data}

        # Currently calendar heatmap only counts events, doesn't average property values
        assert results_dict.get((6, 10)) == 3, f"Expected 3 events at 10:00, got {results_dict.get((6, 10))}"
        assert results_dict.get((6, 11)) == 1, f"Expected 1 event at 11:00, got {results_dict.get((6, 11))}"
        assert results_dict.get((6, 12)) == 1, f"Expected 1 event at 12:00, got {results_dict.get((6, 12))}"

    def test_edge_cases_special_characters_and_unicode(self):
        """Test calendar heatmap with special characters and unicode in event names and properties"""
        # Create events with special characters in names and properties
        self._create_events(
            data=[
                (
                    "unicode_user1",
                    [
                        ("2023-12-02 10:00:00", {"emoji": "🎉", "special": "test@example.com"}),
                        ("2023-12-02 11:00:00", {"unicode": "测试", "symbols": "!@#$%^&*()"}),
                    ],
                ),
            ],
            event="special_event_🎯",
        )

        # Test with unicode event name
        query = CalendarHeatmapQuery(
            dateRange=DateRange(date_from="2023-12-01", date_to="2023-12-03"),
            properties=[],
            filterTestAccounts=False,
            series=[EventsNode(kind="EventsNode", event="special_event_🎯")],
        )
        runner = CalendarHeatmapQueryRunner(team=self.team, query=query)
        response = runner.calculate()
        results_dict = {(r.row, r.column): r.value for r in response.results.data}

        assert results_dict.get((6, 10)) == 1, f"Expected 1 special event at 10:00, got {results_dict.get((6, 10))}"
        assert results_dict.get((6, 11)) == 1, f"Expected 1 special event at 11:00, got {results_dict.get((6, 11))}"
        assert (
            response.results.allAggregations == 2
        ), f"Expected 2 total special events, got {response.results.allAggregations}"

        # Test with unicode property filter
        response = self._run_calendar_heatmap_query_runner(
            "2023-12-01",
            "2023-12-03",
            properties=[{"key": "unicode", "value": "测试"}],
            series=[EventsNode(kind="EventsNode", event="special_event_🎯")],
        )
        results_dict = {(r.row, r.column): r.value for r in response.results.data}
        assert (
            results_dict.get((6, 11)) == 1
        ), f"Expected 1 unicode filtered event at 11:00, got {results_dict.get((6, 11))}"
        assert (
            results_dict.get((6, 10)) is None
        ), f"Expected no unicode filtered events at 10:00, got {results_dict.get((6, 10))}"
        assert (
            response.results.allAggregations == 1
        ), f"Expected 1 total unicode filtered event, got {response.results.allAggregations}"

    def test_edge_cases_empty_and_null_values(self):
        """Test calendar heatmap with empty and null values in events and properties"""
        self._create_events(
            data=[
                (
                    "empty_user1",
                    [
                        ("2023-12-02 10:00:00", {"empty_string": "", "null_value": None}),
                        ("2023-12-02 11:00:00", {"missing_property": "value"}),
                    ],
                ),
            ]
        )

        # Test with empty string property filter
        response = self._run_calendar_heatmap_query_runner(
            "2023-12-01",
            "2023-12-03",
            properties=[{"key": "empty_string", "value": ""}],
        )
        results_dict = {(r.row, r.column): r.value for r in response.results.data}
        assert (
            results_dict.get((6, 10)) == 1
        ), f"Expected 1 empty string event at 10:00, got {results_dict.get((6, 10))}"
        assert (
            response.results.allAggregations == 1
        ), f"Expected 1 total empty string event, got {response.results.allAggregations}"

        # Test with non-existent property filter
        response = self._run_calendar_heatmap_query_runner(
            "2023-12-01",
            "2023-12-03",
            properties=[{"key": "nonexistent", "value": "anything"}],
        )
        assert (
            response.results.data == []
        ), f"Expected empty results for nonexistent property, got {response.results.data}"
        assert (
            response.results.allAggregations == 0
        ), f"Expected 0 total events for nonexistent property, got {response.results.allAggregations}"

    def test_timezone_handling(self):
        """Test calendar heatmap with different timezone considerations"""
        # Create events at boundary times that might be affected by timezone
        self._create_events(
            data=[
                (
                    "timezone_user1",
                    [
                        ("2023-12-02 00:00:00", {}),  # Midnight
                        ("2023-12-02 23:59:59", {}),  # End of day
                    ],
                ),
            ]
        )

        response = self._run_calendar_heatmap_query_runner("2023-12-01", "2023-12-03")
        results_dict = {(r.row, r.column): r.value for r in response.results.data}

        # Should properly handle boundary times
        assert results_dict.get((6, 0)) == 1, f"Expected 1 event at midnight, got {results_dict.get((6, 0))}"
        assert results_dict.get((6, 23)) == 1, f"Expected 1 event at 23:59, got {results_dict.get((6, 23))}"
        assert response.results.allAggregations == 2, f"Expected 2 total events, got {response.results.allAggregations}"

    def test_large_dataset_performance(self):
        """Test calendar heatmap with larger dataset to ensure performance"""
        # Create a larger dataset
        large_data = []
        for user_id in range(1, 101):  # 100 users
            timestamps = []
            for hour in range(9, 18):  # 9 AM to 5 PM
                timestamps.append((f"2023-12-02 {hour:02d}:00:00", {"user_type": "regular"}))
            large_data.append((f"perf_user{user_id}", timestamps))

        self._create_events(data=large_data)

        response = self._run_calendar_heatmap_query_runner("2023-12-01", "2023-12-03")
        results_dict = {(r.row, r.column): r.value for r in response.results.data}

        # Should handle large dataset efficiently
        assert results_dict.get((6, 9)) == 100, f"Expected 100 events at 9:00, got {results_dict.get((6, 9))}"
        assert results_dict.get((6, 17)) == 100, f"Expected 100 events at 17:00, got {results_dict.get((6, 17))}"
        assert (
            response.results.allAggregations == 900
        ), f"Expected 900 total events, got {response.results.allAggregations}"  # 100 users * 9 hours

        # Test aggregations
        hours_dict = {r.column: r.value for r in response.results.columnAggregations}
        assert hours_dict.get(9) == 100, f"Expected 100 events at 9:00 hour aggregation, got {hours_dict.get(9)}"
        assert hours_dict.get(17) == 100, f"Expected 100 events at 17:00 hour aggregation, got {hours_dict.get(17)}"

    def test_cross_day_boundary_events(self):
        """Test calendar heatmap with events crossing day boundaries"""
        self._create_events(
            data=[
                (
                    "boundary_user1",
                    [
                        ("2023-12-01 23:30:00", {}),  # Friday night
                        ("2023-12-02 00:30:00", {}),  # Saturday morning
                        ("2023-12-02 23:45:00", {}),  # Saturday night
                        ("2023-12-03 00:15:00", {}),  # Sunday morning
                    ],
                ),
            ]
        )

        response = self._run_calendar_heatmap_query_runner("2023-12-01", "2023-12-04")
        results_dict = {(r.row, r.column): r.value for r in response.results.data}

        # Friday (day 5)
        assert results_dict.get((5, 23)) == 1, f"Expected 1 event on Friday at 23:30, got {results_dict.get((5, 23))}"

        # Saturday (day 6)
        assert results_dict.get((6, 0)) == 1, f"Expected 1 event on Saturday at 00:30, got {results_dict.get((6, 0))}"
        assert results_dict.get((6, 23)) == 1, f"Expected 1 event on Saturday at 23:45, got {results_dict.get((6, 23))}"

        # Sunday (day 7)
        assert results_dict.get((7, 0)) == 1, f"Expected 1 event on Sunday at 00:15, got {results_dict.get((7, 0))}"

        # Test day aggregations
        days_dict = {r.row: r.value for r in response.results.rowAggregations}
        assert days_dict.get(5) == 1, f"Expected 1 event on Friday, got {days_dict.get(5)}"
        assert days_dict.get(6) == 2, f"Expected 2 events on Saturday, got {days_dict.get(6)}"
        assert days_dict.get(7) == 1, f"Expected 1 event on Sunday, got {days_dict.get(7)}"

    def test_multiple_series_support(self):
        """Test calendar heatmap with multiple series"""
        self._create_events(
            data=[
                (
                    "multi_user1",
                    [
                        ("2023-12-02 10:00:00", {}),
                        ("2023-12-02 11:00:00", {}),
                    ],
                ),
                (
                    "multi_user2",
                    [
                        ("2023-12-02 10:30:00", {}),
                        ("2023-12-02 12:00:00", {}),
                    ],
                ),
            ]
        )

        # Test two series
        query = CalendarHeatmapQuery(
            dateRange=DateRange(date_from="2023-12-01", date_to="2023-12-03"),
            properties=[],
            filterTestAccounts=False,
            series=[
                EventsNode(kind="EventsNode"),
                EventsNode(kind="EventsNode"),
            ],
        )
        runner = CalendarHeatmapQueryRunner(team=self.team, query=query)
        response = runner.calculate()
        results_dict = {(r.row, r.column): r.value for r in response.results.data}

        # Should have events at 10:00, 11:00, 12:00
        assert results_dict.get((6, 10)) == 2, f"Expected 2 events at 10:00, got {results_dict.get((6, 10))}"
        assert results_dict.get((6, 11)) == 1, f"Expected 1 event at 11:00, got {results_dict.get((6, 11))}"
        assert results_dict.get((6, 12)) == 1, f"Expected 1 event at 12:00, got {results_dict.get((6, 12))}"
        assert response.results.allAggregations == 4, f"Expected 4 total events, got {response.results.allAggregations}"

    def test_property_filter_validation(self):
        """Test that property filters actually work by checking they exclude the correct events"""
        self._create_events(
            data=[
                (
                    "filter_user1",
                    [
                        ("2023-12-02 10:00:00", {"$browser": "Chrome", "plan": "premium"}),
                        ("2023-12-02 11:00:00", {"$browser": "Firefox", "plan": "free"}),
                    ],
                ),
                (
                    "filter_user2",
                    [
                        ("2023-12-02 10:30:00", {"$browser": "Chrome", "plan": "free"}),
                        ("2023-12-02 12:00:00", {"$browser": "Safari", "plan": "premium"}),
                    ],
                ),
            ]
        )

        # First verify no filters - should see all events
        response = self._run_calendar_heatmap_query_runner(
            "2023-12-01",
            "2023-12-03",
            properties=[],
        )
        results_dict = {(r.row, r.column): r.value for r in response.results.data}
        assert (
            results_dict.get((6, 10)) == 2
        ), f"Expected 2 events at 10:00 (no filter), got {results_dict.get((6, 10))}"
        assert results_dict.get((6, 11)) == 1, f"Expected 1 event at 11:00 (no filter), got {results_dict.get((6, 11))}"
        assert results_dict.get((6, 12)) == 1, f"Expected 1 event at 12:00 (no filter), got {results_dict.get((6, 12))}"
        assert (
            response.results.allAggregations == 4
        ), f"Expected 4 total events (no filter), got {response.results.allAggregations}"

        # Now test Chrome filter - should only see Chrome events
        response = self._run_calendar_heatmap_query_runner(
            "2023-12-01",
            "2023-12-03",
            properties=[{"key": "$browser", "value": "Chrome"}],
        )
        results_dict = {(r.row, r.column): r.value for r in response.results.data}
        assert results_dict.get((6, 10)) == 2, f"Expected 2 Chrome events at 10:00, got {results_dict.get((6, 10))}"
        assert (
            results_dict.get((6, 11)) is None
        ), f"Expected no Chrome events at 11:00 (Firefox should be filtered out), got {results_dict.get((6, 11))}"
        assert (
            results_dict.get((6, 12)) is None
        ), f"Expected no Chrome events at 12:00 (Safari should be filtered out), got {results_dict.get((6, 12))}"
        assert (
            response.results.allAggregations == 2
        ), f"Expected 2 total Chrome events, got {response.results.allAggregations}"

        # Test premium filter - should only see premium events
        response = self._run_calendar_heatmap_query_runner(
            "2023-12-01",
            "2023-12-03",
            properties=[{"key": "plan", "value": "premium"}],
        )
        results_dict = {(r.row, r.column): r.value for r in response.results.data}
        assert results_dict.get((6, 10)) == 1, f"Expected 1 premium event at 10:00, got {results_dict.get((6, 10))}"
        assert (
            results_dict.get((6, 11)) is None
        ), f"Expected no premium events at 11:00 (free should be filtered out), got {results_dict.get((6, 11))}"
        assert results_dict.get((6, 12)) == 1, f"Expected 1 premium event at 12:00, got {results_dict.get((6, 12))}"
        assert (
            response.results.allAggregations == 2
        ), f"Expected 2 total premium events, got {response.results.allAggregations}"

        # Test combined filter - Chrome AND premium
        response = self._run_calendar_heatmap_query_runner(
            "2023-12-01",
            "2023-12-03",
            properties=[{"key": "$browser", "value": "Chrome"}, {"key": "plan", "value": "premium"}],
        )
        results_dict = {(r.row, r.column): r.value for r in response.results.data}
        assert (
            results_dict.get((6, 10)) == 1
        ), f"Expected 1 Chrome+premium event at 10:00, got {results_dict.get((6, 10))}"
        assert (
            results_dict.get((6, 11)) is None
        ), f"Expected no Chrome+premium events at 11:00 (Firefox+free should be filtered out), got {results_dict.get((6, 11))}"
        assert (
            results_dict.get((6, 12)) is None
        ), f"Expected no Chrome+premium events at 12:00 (Safari+premium should be filtered out), got {results_dict.get((6, 12))}"
        assert (
            response.results.allAggregations == 1
        ), f"Expected 1 total Chrome+premium event, got {response.results.allAggregations}"

    def test_query_runner_receives_properties_correctly(self):
        """Test that the query runner actually receives and processes properties from the query"""
        self._create_events(
            data=[
                (
                    "debug_user1",
                    [
                        ("2023-12-02 10:00:00", {"$browser": "Chrome"}),
                        ("2023-12-02 11:00:00", {"$browser": "Firefox"}),
                    ],
                ),
            ]
        )

        # Test with properties in the query
        query = CalendarHeatmapQuery(
            dateRange=DateRange(date_from="2023-12-01", date_to="2023-12-03"),
            properties=[{"key": "$browser", "value": "Chrome"}],
            filterTestAccounts=False,
            series=[EventsNode(kind="EventsNode")],
        )
        runner = CalendarHeatmapQueryRunner(team=self.team, query=query)
        response = runner.calculate()

        # Should only find Chrome events
        results_dict = {(r.row, r.column): r.value for r in response.results.data}
        assert results_dict.get((6, 10)) == 1, f"Expected 1 Chrome event at 10:00, got {results_dict.get((6, 10))}"
        assert results_dict.get((6, 11)) is None, f"Expected no Firefox event at 11:00, got {results_dict.get((6, 11))}"
        assert response.results.allAggregations == 1, f"Expected 1 total event, got {response.results.allAggregations}"

    def test_series_level_properties_support(self):
        """Test that series-level properties work correctly (as used by the frontend)"""
        self._create_events(
            data=[
                (
                    "series_user1",
                    [
                        ("2023-12-02 10:00:00", {"$browser": "Chrome"}),
                        ("2023-12-02 11:00:00", {"$browser": "Firefox"}),
                    ],
                ),
            ]
        )

        # Test with properties at the series level (as frontend does)
        query = CalendarHeatmapQuery(
            dateRange=DateRange(date_from="2023-12-01", date_to="2023-12-03"),
            properties=[],  # No top-level properties
            filterTestAccounts=False,
            series=[
                EventsNode(
                    kind="EventsNode",
                    properties=[{"key": "$browser", "value": "Chrome"}],  # Series-level properties
                )
            ],
        )
        runner = CalendarHeatmapQueryRunner(team=self.team, query=query)
        response = runner.calculate()

        # Should only find Chrome events
        results_dict = {(r.row, r.column): r.value for r in response.results.data}
        assert results_dict.get((6, 10)) == 1, f"Expected 1 Chrome event at 10:00, got {results_dict.get((6, 10))}"
        assert results_dict.get((6, 11)) is None, f"Expected no Firefox event at 11:00, got {results_dict.get((6, 11))}"
        assert response.results.allAggregations == 1, f"Expected 1 total event, got {response.results.allAggregations}"

    def test_combined_top_level_and_series_level_properties(self):
        """Test that top-level and series-level properties are combined with AND logic"""
        self._create_events(
            data=[
                (
                    "combo_user1",
                    [
                        ("2023-12-02 10:00:00", {"$browser": "Chrome", "$os": "Windows"}),
                        ("2023-12-02 11:00:00", {"$browser": "Chrome", "$os": "Mac"}),
                        ("2023-12-02 12:00:00", {"$browser": "Firefox", "$os": "Windows"}),
                    ],
                ),
            ]
        )

        # Test with properties at both levels - should AND them together
        query = CalendarHeatmapQuery(
            dateRange=DateRange(date_from="2023-12-01", date_to="2023-12-03"),
            properties=[{"key": "$browser", "value": "Chrome"}],  # Top-level: Chrome
            filterTestAccounts=False,
            series=[
                EventsNode(
                    kind="EventsNode",
                    properties=[{"key": "$os", "value": "Windows"}],  # Series-level: Windows
                )
            ],
        )
        runner = CalendarHeatmapQueryRunner(team=self.team, query=query)
        response = runner.calculate()

        # Should only find Chrome AND Windows events (first event only)
        results_dict = {(r.row, r.column): r.value for r in response.results.data}
        assert (
            results_dict.get((6, 10)) == 1
        ), f"Expected 1 Chrome+Windows event at 10:00, got {results_dict.get((6, 10))}"
        assert (
            results_dict.get((6, 11)) is None
        ), f"Expected no Chrome+Mac event at 11:00, got {results_dict.get((6, 11))}"
        assert (
            results_dict.get((6, 12)) is None
        ), f"Expected no Firefox+Windows event at 12:00, got {results_dict.get((6, 12))}"
        assert response.results.allAggregations == 1, f"Expected 1 total event, got {response.results.allAggregations}"
