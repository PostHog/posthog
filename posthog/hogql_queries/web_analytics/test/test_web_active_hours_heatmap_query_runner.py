from typing import Optional, Union

from freezegun import freeze_time

from posthog.hogql_queries.web_analytics.web_active_hours_heatmap_query_runner import EventsHeatMapQueryRunner
from posthog.models.utils import uuid7
from posthog.schema import (
    DateRange,
    EventsHeatMapQuery,
    SessionTableVersion,
    HogQLQueryModifiers,
    WebAnalyticsOrderByDirection,
    WebAnalyticsOrderByFields,
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


# @snapshot_clickhouse_queries
class TestWebActiveHoursHeatMapQueryRunner(ClickhouseTestMixin, APIBaseTest):
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
                    properties={
                        "$session_id": session_id,
                        "$start_timestamp": timestamp,
                        **properties,
                    },
                )

    def _run_web_active_hours_heatmap_query_runner(
        self,
        date_from,
        date_to,
        properties=None,
        session_table_version: SessionTableVersion = SessionTableVersion.V2,
        filter_test_accounts: Optional[bool] = False,
        order_by: Optional[list[Union[WebAnalyticsOrderByFields, WebAnalyticsOrderByDirection]]] = None,
    ):
        modifiers = HogQLQueryModifiers(sessionTableVersion=session_table_version)
        query = EventsHeatMapQuery(
            dateRange=DateRange(date_from=date_from, date_to=date_to),
            properties=properties or [],
            filterTestAccounts=filter_test_accounts,
            orderBy=order_by,
            source=EventsNode(kind="EventsNode"),
        )
        runner = EventsHeatMapQueryRunner(team=self.team, query=query, modifiers=modifiers)
        return runner.calculate()

    def test_empty_results_when_no_data(self):
        response = self._run_web_active_hours_heatmap_query_runner("2023-12-08", "2023-12-15")
        self.assertEqual([], response.results.data)

    def test_basic_active_hours(self):
        self._create_events(
            data=[
                (
                    "user1",
                    [
                        ("2023-12-02 10:00:00", {}),  # Saturday 10:00
                        ("2023-12-02 10:30:00", {}),  # Same hour, should count once
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

        response = self._run_web_active_hours_heatmap_query_runner("2023-12-01", "2023-12-04")

        # Convert results to a dict for easier testing
        results_dict = {(r.row, r.column): r.value for r in response.results.data}

        # Saturday (day 6) expectations
        self.assertEqual(results_dict.get((6, 10)), 2)  # Two users at 10:00
        self.assertEqual(results_dict.get((6, 11)), 1)  # One user at 11:00

        # Sunday (day 7) expectations
        self.assertEqual(results_dict.get((7, 15)), 1)  # One user at 15:00

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
        response = self._run_web_active_hours_heatmap_query_runner(
            "2023-12-01", "2023-12-03", filter_test_accounts=False
        )
        results_dict = {(r.row, r.column): r.value for r in response.results.data}
        self.assertEqual(results_dict.get((6, 10)), 2)  # Both users

        # Without test accounts
        response = self._run_web_active_hours_heatmap_query_runner(
            "2023-12-01", "2023-12-03", filter_test_accounts=True
        )
        results_dict = {(r.row, r.column): r.value for r in response.results.data}
        self.assertEqual(results_dict.get((6, 10)), 1)  # Only regular user

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

        response = self._run_web_active_hours_heatmap_query_runner("all", "2024-01-20")
        results_dict = {(r.row, r.column): r.value for r in response.results.data}

        self.assertEqual(results_dict.get((6, 10)), 1)  # December visit
        self.assertEqual(results_dict.get((1, 11)), 1)  # January visit

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

        response = self._run_web_active_hours_heatmap_query_runner(
            "2023-12-01",
            "2023-12-03",
            properties=[{"key": "$browser", "value": "Chrome"}],
        )

        results_dict = {(r.row, r.column): r.value for r in response.results.data}
        self.assertEqual(results_dict.get((6, 10)), 1)  # Chrome visit
        self.assertNotIn((6, 11), results_dict)  # Firefox visit filtered out

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

        response = self._run_web_active_hours_heatmap_query_runner("2023-12-01", "2023-12-04")

        # Test day-hour combinations
        day_hour_dict = {(r.row, r.column): r.value for r in response.results.data}
        self.assertEqual(day_hour_dict.get((6, 10)), 2)  # Two users on Saturday at 10:00
        self.assertEqual(day_hour_dict.get((6, 11)), 1)  # One user on Saturday at 11:00
        self.assertEqual(day_hour_dict.get((7, 10)), 1)  # One user on Sunday at 10:00
        self.assertEqual(day_hour_dict.get((7, 15)), 1)  # One user on Sunday at 15:00

        # Test days aggregation
        days_dict = {r.row: r.value for r in response.results.rowAggregations}
        self.assertEqual(days_dict.get(6), 2)  # Two users on Saturday
        self.assertEqual(days_dict.get(7), 2)  # Two users on Sunday

        # Test hours aggregation
        hours_dict = {r.column: r.value for r in response.results.columnAggregations}
        self.assertEqual(hours_dict.get(10), 2)  # Two users at 10:00
        self.assertEqual(hours_dict.get(11), 1)  # One user at 11:00
        self.assertEqual(hours_dict.get(15), 1)  # One user at 15:00

        # Test total users
        self.assertEqual(response.results.allAggregations, 2)  # Two unique users overall

    def test_empty_results_structure(self):
        response = self._run_web_active_hours_heatmap_query_runner("2023-12-08", "2023-12-15")

        self.assertEqual(response.results.data, [])
        self.assertEqual(response.results.rowAggregations, [])
        self.assertEqual(response.results.columnAggregations, [])
        self.assertEqual(response.results.allAggregations, 0)

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

        # Set the event in the source node
        query = EventsHeatMapQuery(
            dateRange=DateRange(date_from="2023-12-01", date_to="2023-12-03"),
            properties=[],
            filterTestAccounts=False,
            orderBy=None,
            source=EventsNode(kind="EventsNode", event="custom_event"),
        )
        runner = EventsHeatMapQueryRunner(team=self.team, query=query, modifiers=HogQLQueryModifiers())
        response = runner.calculate()
        results_dict = {(r.row, r.column): r.value for r in response.results.data}
        self.assertEqual(results_dict.get((6, 10)), 1)  # Should see the custom event

    def test_conversion_goal_expr(self):
        from posthog.hogql import ast

        class CustomGoalRunner(EventsHeatMapQueryRunner):
            @property
            def conversion_goal_expr(self):
                return ast.CompareOperation(
                    op=ast.CompareOperationOp.Eq,
                    left=ast.Field(chain=["events", "event"]),
                    right=ast.Constant(value="goal_event"),
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
            event="goal_event",
        )

        query = EventsHeatMapQuery(
            dateRange=DateRange(date_from="2023-12-01", date_to="2023-12-03"),
            properties=[],
            filterTestAccounts=False,
            orderBy=None,
            source=EventsNode(kind="EventsNode"),
        )
        runner = CustomGoalRunner(team=self.team, query=query, modifiers=HogQLQueryModifiers())
        response = runner.calculate()
        results_dict = {(r.row, r.column): r.value for r in response.results.data}
        self.assertEqual(results_dict.get((6, 10)), 1)  # Should see the goal event

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

        query = EventsHeatMapQuery(
            dateRange=DateRange(date_from="2023-12-01", date_to="2023-12-03"),
            properties=[],
            filterTestAccounts=False,
            orderBy=None,
            source=EventsNode(kind="EventsNode"),
            conversionGoal=ActionConversionGoal(actionId=action.id),
        )
        runner = EventsHeatMapQueryRunner(team=self.team, query=query, modifiers=HogQLQueryModifiers())
        response = runner.calculate()
        results_dict = {(r.row, r.column): r.value for r in response.results.data}
        self.assertEqual(results_dict.get((6, 10)), 1)

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

        query = EventsHeatMapQuery(
            dateRange=DateRange(date_from="2023-12-01", date_to="2023-12-03"),
            properties=[],
            filterTestAccounts=False,
            orderBy=None,
            source=EventsNode(kind="EventsNode"),
            conversionGoal=CustomEventConversionGoal(customEventName="my_custom_event"),
        )
        runner = EventsHeatMapQueryRunner(team=self.team, query=query, modifiers=HogQLQueryModifiers())
        response = runner.calculate()
        results_dict = {(r.row, r.column): r.value for r in response.results.data}
        self.assertEqual(results_dict.get((6, 10)), 1)
