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
