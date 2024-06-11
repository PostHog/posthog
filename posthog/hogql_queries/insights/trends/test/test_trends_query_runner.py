import zoneinfo
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from unittest.mock import MagicMock, patch
from django.test import override_settings
from freezegun import freeze_time
from posthog.clickhouse.client.execute import sync_execute
from posthog.hogql import ast
from posthog.hogql.constants import MAX_SELECT_RETURNED_ROWS, LimitContext
from posthog.hogql.modifiers import create_default_modifiers_for_team
from posthog.hogql_queries.insights.trends.trends_query_runner import TrendsQueryRunner, BREAKDOWN_OTHER_DISPLAY
from posthog.models.cohort.cohort import Cohort
from posthog.models.property_definition import PropertyDefinition

from posthog.schema import (
    ActionsNode,
    BaseMathType,
    BreakdownFilter,
    BreakdownItem,
    BreakdownType,
    ChartDisplayType,
    CompareItem,
    CountPerActorMathType,
    InsightDateRange,
    DayItem,
    EventsNode,
    HogQLQueryModifiers,
    InCohortVia,
    IntervalType,
    PropertyMathType,
    TrendsFilter,
    TrendsQuery,
)

from posthog.schema import Series as InsightActorsQuerySeries
from posthog.settings import HOGQL_INCREASED_MAX_EXECUTION_TIME
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    also_test_with_materialized_columns,
    flush_persons_and_events,
)


@dataclass
class Series:
    event: str
    timestamps: list[str]


@dataclass
class SeriesTestData:
    distinct_id: str
    events: list[Series]
    properties: dict[str, str | int]


@override_settings(IN_UNIT_TESTING=True)
class TestTrendsQueryRunner(ClickhouseTestMixin, APIBaseTest):
    default_date_from = "2020-01-09"
    default_date_to = "2020-01-19"

    def _create_events(self, data: list[SeriesTestData]):
        person_result = []
        properties_to_create: dict[str, str] = {}
        for person in data:
            first_timestamp = person.events[0].timestamps[0]

            for key, value in person.properties.items():
                if key not in properties_to_create:
                    if isinstance(value, bool):
                        type = "Boolean"
                    elif isinstance(value, int):
                        type = "Numeric"
                    else:
                        type = "String"
                    properties_to_create[key] = type

            with freeze_time(first_timestamp):
                person_result.append(
                    _create_person(
                        team_id=self.team.pk,
                        distinct_ids=[person.distinct_id],
                        properties={
                            "name": person.distinct_id,
                            **({"email": "test@posthog.com"} if person.distinct_id == "p1" else {}),
                        },
                    )
                )
            for event in person.events:
                for timestamp in event.timestamps:
                    _create_event(
                        team=self.team,
                        event=event.event,
                        distinct_id=person.distinct_id,
                        timestamp=timestamp,
                        properties=person.properties,
                    )

        for key, value in properties_to_create.items():
            PropertyDefinition.objects.create(team=self.team, name=key, property_type=value)

        return person_result

    def _create_test_events(self):
        self._create_events(
            [
                SeriesTestData(
                    distinct_id="p1",
                    events=[
                        Series(
                            event="$pageview",
                            timestamps=[
                                "2020-01-11T12:00:00Z",
                                "2020-01-12T12:00:00Z",
                                "2020-01-13T12:00:00Z",
                                "2020-01-15T12:00:00Z",
                                "2020-01-17T12:00:00Z",
                                "2020-01-19T12:00:00Z",
                            ],
                        ),
                        Series(
                            event="$pageleave",
                            timestamps=[
                                "2020-01-11T12:00:00Z",
                                "2020-01-12T12:00:00Z",
                                "2020-01-13T12:00:00Z",
                            ],
                        ),
                    ],
                    properties={"$browser": "Chrome", "prop": 10, "bool_field": True},
                ),
                SeriesTestData(
                    distinct_id="p2",
                    events=[
                        Series(
                            event="$pageview",
                            timestamps=["2020-01-09T12:00:00Z", "2020-01-12T12:00:00Z"],
                        ),
                        Series(
                            event="$pageleave",
                            timestamps=[
                                "2020-01-13T12:00:00Z",
                            ],
                        ),
                    ],
                    properties={"$browser": "Firefox", "prop": 20, "bool_field": False},
                ),
                SeriesTestData(
                    distinct_id="p3",
                    events=[
                        Series(event="$pageview", timestamps=["2020-01-12T12:00:00Z"]),
                        Series(event="$pageleave", timestamps=["2020-01-13T12:00:00Z"]),
                    ],
                    properties={"$browser": "Edge", "prop": 30, "bool_field": True},
                ),
                SeriesTestData(
                    distinct_id="p4",
                    events=[
                        Series(event="$pageview", timestamps=["2020-01-15T12:00:00Z"]),
                        Series(event="$pageleave", timestamps=["2020-01-16T12:00:00Z"]),
                    ],
                    properties={"$browser": "Safari", "prop": 40, "bool_field": False},
                ),
            ]
        )

    def _create_query_runner(
        self,
        date_from: str,
        date_to: Optional[str],
        interval: IntervalType,
        series: Optional[list[EventsNode | ActionsNode]],
        trends_filters: Optional[TrendsFilter] = None,
        breakdown: Optional[BreakdownFilter] = None,
        filter_test_accounts: Optional[bool] = None,
        hogql_modifiers: Optional[HogQLQueryModifiers] = None,
        limit_context: Optional[LimitContext] = None,
        explicit_date: Optional[bool] = None,
    ) -> TrendsQueryRunner:
        query_series: list[EventsNode | ActionsNode] = [EventsNode(event="$pageview")] if series is None else series
        query = TrendsQuery(
            dateRange=InsightDateRange(date_from=date_from, date_to=date_to, explicitDate=explicit_date),
            interval=interval,
            series=query_series,
            trendsFilter=trends_filters,
            breakdownFilter=breakdown,
            filterTestAccounts=filter_test_accounts,
        )
        return TrendsQueryRunner(team=self.team, query=query, modifiers=hogql_modifiers, limit_context=limit_context)

    def _run_trends_query(
        self,
        date_from: str,
        date_to: Optional[str],
        interval: IntervalType,
        series: Optional[list[EventsNode | ActionsNode]],
        trends_filters: Optional[TrendsFilter] = None,
        breakdown: Optional[BreakdownFilter] = None,
        *,
        filter_test_accounts: Optional[bool] = None,
        hogql_modifiers: Optional[HogQLQueryModifiers] = None,
        limit_context: Optional[LimitContext] = None,
    ):
        return self._create_query_runner(
            date_from=date_from,
            date_to=date_to,
            interval=interval,
            series=series,
            trends_filters=trends_filters,
            breakdown=breakdown,
            filter_test_accounts=filter_test_accounts,
            hogql_modifiers=hogql_modifiers,
            limit_context=limit_context,
        ).calculate()

    def test_trends_label(self):
        self._create_test_events()

        response = self._run_trends_query(
            self.default_date_from,
            self.default_date_to,
            IntervalType.DAY,
            None,
            None,
            None,
        )

        self.assertEqual("$pageview", response.results[0]["label"])

    def test_trends_count(self):
        self._create_test_events()

        response = self._run_trends_query(
            self.default_date_from,
            self.default_date_to,
            IntervalType.DAY,
            None,
            None,
            None,
        )

        self.assertEqual(10, response.results[0]["count"])

    def test_trends_data(self):
        self._create_test_events()

        response = self._run_trends_query(
            self.default_date_from,
            self.default_date_to,
            IntervalType.DAY,
            None,
            None,
            None,
        )

        self.assertEqual([1, 0, 1, 3, 1, 0, 2, 0, 1, 0, 1], response.results[0]["data"])

    def test_trends_days(self):
        self._create_test_events()

        response = self._run_trends_query(
            self.default_date_from,
            self.default_date_to,
            IntervalType.DAY,
            None,
            None,
            None,
        )

        self.assertEqual(
            [
                "2020-01-09",
                "2020-01-10",
                "2020-01-11",
                "2020-01-12",
                "2020-01-13",
                "2020-01-14",
                "2020-01-15",
                "2020-01-16",
                "2020-01-17",
                "2020-01-18",
                "2020-01-19",
            ],
            response.results[0]["days"],
        )

    def test_trends_labels(self):
        self._create_test_events()

        response = self._run_trends_query(
            self.default_date_from,
            self.default_date_to,
            IntervalType.DAY,
            None,
            None,
            None,
        )

        self.assertEqual(
            [
                "9-Jan-2020",
                "10-Jan-2020",
                "11-Jan-2020",
                "12-Jan-2020",
                "13-Jan-2020",
                "14-Jan-2020",
                "15-Jan-2020",
                "16-Jan-2020",
                "17-Jan-2020",
                "18-Jan-2020",
                "19-Jan-2020",
            ],
            response.results[0]["labels"],
        )

    def test_trends_labels_hour(self):
        self._create_test_events()

        response = self._run_trends_query(
            self.default_date_from,
            self.default_date_from,
            IntervalType.HOUR,
            [EventsNode(event="$pageview")],
        )

        self.assertEqual(
            [
                "9-Jan-2020 00:00",
            ],
            response.results[0]["labels"],
            response.results[0]["labels"],
        )

    def test_trends_multiple_series(self):
        self._create_test_events()

        response = self._run_trends_query(
            self.default_date_from,
            self.default_date_to,
            IntervalType.DAY,
            [EventsNode(event="$pageview"), EventsNode(event="$pageleave")],
        )

        self.assertEqual(2, len(response.results))

        self.assertEqual("$pageview", response.results[0]["label"])
        self.assertEqual("$pageleave", response.results[1]["label"])

        self.assertEqual(10, response.results[0]["count"])
        self.assertEqual(6, response.results[1]["count"])

        self.assertEqual([1, 0, 1, 3, 1, 0, 2, 0, 1, 0, 1], response.results[0]["data"])
        self.assertEqual([0, 0, 1, 1, 3, 0, 0, 1, 0, 0, 0], response.results[1]["data"])

    def test_formula(self):
        self._create_test_events()

        response = self._run_trends_query(
            self.default_date_from,
            self.default_date_to,
            IntervalType.DAY,
            [EventsNode(event="$pageview"), EventsNode(event="$pageleave")],
            TrendsFilter(formula="A+2*B"),
        )

        self.assertEqual(1, len(response.results))
        self.assertEqual(22, response.results[0]["count"])
        self.assertEqual("Formula (A+2*B)", response.results[0]["label"])
        self.assertEqual([1, 0, 3, 5, 7, 0, 2, 2, 1, 0, 1], response.results[0]["data"])

    def test_formula_total_value(self):
        self._create_test_events()

        response = self._run_trends_query(
            self.default_date_from,
            self.default_date_to,
            IntervalType.DAY,
            [EventsNode(event="$pageview"), EventsNode(event="$pageleave")],
            TrendsFilter(
                formula="A+2*B",
                display=ChartDisplayType.BOLD_NUMBER,  # total value
            ),
        )
        self.assertEqual(1, len(response.results))
        self.assertEqual(22, response.results[0]["aggregated_value"])
        self.assertEqual(0, response.results[0]["count"])  # it has always been so :shrug:
        self.assertEqual("Formula (A+2*B)", response.results[0]["label"])
        self.assertEqual(None, response.results[0].get("data"))

    def test_formula_with_compare(self):
        self._create_test_events()

        response = self._run_trends_query(
            "2020-01-15",
            "2020-01-19",
            IntervalType.DAY,
            [EventsNode(event="$pageview"), EventsNode(event="$pageleave")],
            TrendsFilter(formula="A+2*B", compare=True),
        )

        # one for current, one for previous
        self.assertEqual(2, len(response.results))

        # current
        self.assertEqual("current", response.results[0]["compare_label"])
        self.assertEqual(6, response.results[0]["count"])
        self.assertEqual([2, 2, 1, 0, 1], response.results[0]["data"])

        # previous
        self.assertEqual("previous", response.results[1]["compare_label"])
        self.assertEqual(15, response.results[1]["count"])
        self.assertEqual([0, 3, 5, 7, 0], response.results[1]["data"])

        # response shape
        self.assertEqual("Formula (A+2*B)", response.results[0]["label"])
        self.assertEqual(True, response.results[0]["compare"])

    def test_formula_with_compare_total_value(self):
        self._create_test_events()

        response = self._run_trends_query(
            "2020-01-15",
            "2020-01-19",
            IntervalType.DAY,
            [EventsNode(event="$pageview"), EventsNode(event="$pageleave")],
            TrendsFilter(
                formula="A+2*B",
                display=ChartDisplayType.BOLD_NUMBER,  # total value
                compare=True,
            ),
        )

        # one for current, one for previous
        self.assertEqual(2, len(response.results))

        # current
        self.assertEqual("current", response.results[0]["compare_label"])
        self.assertEqual(6, response.results[0]["aggregated_value"])

        # previous
        self.assertEqual("previous", response.results[1]["compare_label"])
        self.assertEqual(15, response.results[1]["aggregated_value"])

        # response shape
        self.assertEqual("Formula (A+2*B)", response.results[0]["label"])
        self.assertEqual(0, response.results[0]["count"])  # it has always been so :shrug:
        self.assertEqual(None, response.results[0].get("data"))

    def test_formula_with_breakdown(self):
        self._create_test_events()

        response = self._run_trends_query(
            "2020-01-09",
            "2020-01-20",
            IntervalType.DAY,
            [EventsNode(event="$pageview"), EventsNode(event="$pageleave")],
            TrendsFilter(formula="A+2*B"),
            BreakdownFilter(breakdown_type=BreakdownType.EVENT, breakdown="$browser"),
        )

        # one for each breakdown value
        assert len(response.results) == 4

        # chrome
        assert response.results[0]["breakdown_value"] == "Chrome"
        assert response.results[0]["count"] == 12
        assert response.results[0]["data"] == [0, 0, 3, 3, 3, 0, 1, 0, 1, 0, 1, 0]

        # firefox
        assert response.results[1]["breakdown_value"] == "Firefox"
        assert response.results[1]["count"] == 4

        # response shape
        assert response.results[0]["label"] == "Formula (A+2*B)"
        assert response.results[0]["action"] is None  # action needs to be unset to display custom label

    def test_formula_with_breakdown_and_compare(self):
        self._create_test_events()

        response = self._run_trends_query(
            "2020-01-15",
            "2020-01-19",
            IntervalType.DAY,
            [EventsNode(event="$pageview"), EventsNode(event="$pageleave")],
            TrendsFilter(formula="A+2*B", compare=True),
            BreakdownFilter(breakdown_type=BreakdownType.EVENT, breakdown="$browser"),
        )

        # chrome, ff and edge for previous, and chrome and safari for current
        assert len(response.results) == 5

        assert response.results[0]["compare_label"] == "current"
        assert response.results[0]["breakdown_value"] == "Chrome"
        assert response.results[0]["label"] == "Formula (A+2*B)"
        assert response.results[0]["count"] == 3
        assert response.results[0]["data"] == [1, 0, 1, 0, 1]

        assert response.results[1]["compare_label"] == "current"
        assert response.results[1]["breakdown_value"] == "Safari"
        assert response.results[1]["count"] == 3

        assert response.results[2]["compare_label"] == "previous"
        assert response.results[2]["label"] == "Formula (A+2*B)"
        assert response.results[2]["breakdown_value"] == "Chrome"
        assert response.results[2]["count"] == 9

    def test_formula_with_breakdown_and_compare_total_value(self):
        self._create_test_events()

        response = self._run_trends_query(
            "2020-01-15",
            "2020-01-19",
            IntervalType.DAY,
            [EventsNode(event="$pageview"), EventsNode(event="$pageleave")],
            TrendsFilter(
                formula="A+2*B",
                display=ChartDisplayType.BOLD_NUMBER,  # total value
                compare=True,
            ),
            BreakdownFilter(breakdown_type=BreakdownType.EVENT, breakdown="$browser"),
        )

        # chrome, ff and edge for previous, and chrome and safari for current
        assert len(response.results) == 5

        assert response.results[0]["compare_label"] == "current"
        assert response.results[0]["breakdown_value"] == "Chrome"
        assert response.results[0]["label"] == "Formula (A+2*B)"
        assert response.results[0]["aggregated_value"] == 3
        assert response.results[0]["count"] == 0
        assert response.results[0].get("data") is None

        assert response.results[1]["compare_label"] == "current"
        assert response.results[1]["breakdown_value"] == "Safari"
        assert response.results[1]["aggregated_value"] == 3

        assert response.results[2]["compare_label"] == "previous"
        assert response.results[2]["label"] == "Formula (A+2*B)"
        assert response.results[2]["breakdown_value"] == "Chrome"
        assert response.results[2]["aggregated_value"] == 9

    def test_formula_with_multi_cohort_breakdown(self):
        self._create_test_events()
        cohort1 = Cohort.objects.create(
            team=self.team,
            groups=[
                {
                    "properties": [
                        {
                            "key": "name",
                            "value": "p1",
                            "type": "person",
                        }
                    ]
                }
            ],
            name="cohort p1",
        )
        cohort1.calculate_people_ch(pending_version=0)
        cohort2 = Cohort.objects.create(
            team=self.team,
            groups=[
                {
                    "properties": [
                        {
                            "key": "name",
                            "value": "p2",
                            "type": "person",
                        }
                    ]
                }
            ],
            name="cohort p2",
        )
        cohort2.calculate_people_ch(pending_version=0)

        response = self._run_trends_query(
            "2020-01-09",
            "2020-01-20",
            IntervalType.DAY,
            [EventsNode(event="$pageview"), EventsNode(event="$pageleave")],
            TrendsFilter(formula="A+B"),
            BreakdownFilter(breakdown_type=BreakdownType.COHORT, breakdown=[cohort1.pk, cohort2.pk]),
        )

        assert len(response.results) == 2

        assert response.results[0]["label"] == "Formula (A+B)"
        assert response.results[0]["breakdown_value"] == cohort1.pk
        assert response.results[0]["count"] == 9
        assert response.results[0]["data"] == [0, 0, 2, 2, 2, 0, 1, 0, 1, 0, 1, 0]

        assert response.results[1]["label"] == "Formula (A+B)"
        assert response.results[1]["breakdown_value"] == cohort2.pk
        assert response.results[1]["count"] == 3

        # action needs to be unset to display custom label
        assert response.results[0]["action"] is None

    def test_formula_with_multi_cohort_all_breakdown(self):
        self._create_test_events()
        cohort1 = Cohort.objects.create(
            team=self.team,
            groups=[
                {
                    "properties": [
                        {
                            "key": "name",
                            "value": "p1",
                            "type": "person",
                        }
                    ]
                }
            ],
            name="cohort p1",
        )
        cohort1.calculate_people_ch(pending_version=0)

        response = self._run_trends_query(
            "2020-01-09",
            "2020-01-20",
            IntervalType.DAY,
            [EventsNode(event="$pageview"), EventsNode(event="$pageleave")],
            TrendsFilter(formula="A+B"),
            BreakdownFilter(breakdown_type=BreakdownType.COHORT, breakdown=[cohort1.pk, "all"]),
        )

        assert len(response.results) == 2

        assert response.results[0]["label"] == "Formula (A+B)"
        assert response.results[0]["breakdown_value"] == "all"
        assert response.results[0]["count"] == 16

        assert response.results[1]["label"] == "Formula (A+B)"
        assert response.results[1]["breakdown_value"] == cohort1.pk
        assert response.results[1]["count"] == 9
        assert response.results[1]["data"] == [0, 0, 2, 2, 2, 0, 1, 0, 1, 0, 1, 0]

        # action needs to be unset to display custom label
        assert response.results[0]["action"] is None

    def test_formula_with_breakdown_and_no_data(self):
        self._create_test_events()

        # Neither side returns a response
        response = self._run_trends_query(
            self.default_date_from,
            self.default_date_to,
            IntervalType.DAY,
            [EventsNode(event="$pageviewxxx"), EventsNode(event="$pageleavexxx")],
            TrendsFilter(formula="A+2*B"),
            BreakdownFilter(breakdown_type=BreakdownType.PERSON, breakdown="$browser"),
        )
        self.assertEqual(0, len(response.results))

        # One returns a response, the other side doesn't
        response = self._run_trends_query(
            self.default_date_from,
            self.default_date_to,
            IntervalType.DAY,
            [EventsNode(event="$pageview"), EventsNode(event="$pageleavexxx")],
            TrendsFilter(formula="A+2*B"),
            BreakdownFilter(breakdown_type=BreakdownType.PERSON, breakdown="$browser"),
        )
        self.assertEqual([1, 0, 1, 3, 1, 0, 2, 0, 1, 0, 1], response.results[0]["data"])

    @patch("posthog.hogql.query.sync_execute", wraps=sync_execute)
    def test_breakdown_is_context_aware(self, mock_sync_execute: MagicMock):
        self._create_test_events()

        self._run_trends_query(
            self.default_date_from,
            self.default_date_to,
            IntervalType.DAY,
            [EventsNode(event="$pageviewxxx"), EventsNode(event="$pageleavexxx")],
            TrendsFilter(formula="A+2*B"),
            BreakdownFilter(breakdown_type=BreakdownType.PERSON, breakdown="$browser"),
            limit_context=LimitContext.QUERY_ASYNC,
        )

        self.assertEqual(mock_sync_execute.call_count, 4)
        for mock_execute_call_args in mock_sync_execute.call_args_list:
            self.assertIn(f" max_execution_time={HOGQL_INCREASED_MAX_EXECUTION_TIME},", mock_execute_call_args[0][0])

    def test_trends_compare(self):
        self._create_test_events()

        response = self._run_trends_query(
            "2020-01-15",
            "2020-01-19",
            IntervalType.DAY,
            [EventsNode(event="$pageview")],
            TrendsFilter(compare=True),
        )

        self.assertEqual(2, len(response.results))

        self.assertEqual(True, response.results[0]["compare"])
        self.assertEqual(True, response.results[1]["compare"])

        self.assertEqual("current", response.results[0]["compare_label"])
        self.assertEqual("previous", response.results[1]["compare_label"])

        self.assertEqual(
            [
                "2020-01-15",
                "2020-01-16",
                "2020-01-17",
                "2020-01-18",
                "2020-01-19",
            ],
            response.results[0]["days"],
        )
        self.assertEqual(
            [
                "2020-01-10",
                "2020-01-11",
                "2020-01-12",
                "2020-01-13",
                "2020-01-14",
            ],
            response.results[1]["days"],
        )

        self.assertEqual(["day 0", "day 1", "day 2", "day 3", "day 4"], response.results[0]["labels"])
        self.assertEqual(["day 0", "day 1", "day 2", "day 3", "day 4"], response.results[1]["labels"])

    def test_trends_compare_weeks(self):
        self._create_test_events()

        with freeze_time("2020-01-24"):
            response = self._run_trends_query(
                "-7d",
                None,
                IntervalType.DAY,
                [EventsNode(event="$pageview")],
                TrendsFilter(compare=True),
            )

            self.assertEqual(2, len(response.results))

            self.assertEqual(True, response.results[0]["compare"])
            self.assertEqual(True, response.results[1]["compare"])

            self.assertEqual("current", response.results[0]["compare_label"])
            self.assertEqual("previous", response.results[1]["compare_label"])

            self.assertEqual(
                [
                    "2020-01-17",
                    "2020-01-18",
                    "2020-01-19",
                    "2020-01-20",
                    "2020-01-21",
                    "2020-01-22",
                    "2020-01-23",
                    "2020-01-24",
                ],
                response.results[0]["days"],
            )
            self.assertEqual(
                [
                    "2020-01-10",
                    "2020-01-11",
                    "2020-01-12",
                    "2020-01-13",
                    "2020-01-14",
                    "2020-01-15",
                    "2020-01-16",
                    "2020-01-17",
                ],
                response.results[1]["days"],
            )

            self.assertEqual(
                ["day 0", "day 1", "day 2", "day 3", "day 4", "day 5", "day 6", "day 7"], response.results[0]["labels"]
            )
            self.assertEqual(
                ["day 0", "day 1", "day 2", "day 3", "day 4", "day 5", "day 6", "day 7"], response.results[1]["labels"]
            )

    def test_trends_breakdowns(self):
        self._create_test_events()

        response = self._run_trends_query(
            "2020-01-09",
            "2020-01-20",
            IntervalType.DAY,
            [EventsNode(event="$pageview")],
            None,
            BreakdownFilter(breakdown_type=BreakdownType.EVENT, breakdown="$browser"),
        )

        breakdown_labels = [result["breakdown_value"] for result in response.results]

        assert len(response.results) == 4
        assert breakdown_labels == ["Chrome", "Firefox", "Edge", "Safari"]
        assert response.results[0]["label"] == "Chrome"
        assert response.results[1]["label"] == "Firefox"
        assert response.results[2]["label"] == "Edge"
        assert response.results[3]["label"] == "Safari"
        assert response.results[0]["count"] == 6
        assert response.results[1]["count"] == 2
        assert response.results[2]["count"] == 1
        assert response.results[3]["count"] == 1

    def test_trends_breakdowns_boolean(self):
        self._create_test_events()

        response = self._run_trends_query(
            "2020-01-09",
            "2020-01-20",
            IntervalType.DAY,
            [EventsNode(event="$pageview")],
            None,
            BreakdownFilter(breakdown_type=BreakdownType.EVENT, breakdown="bool_field"),
        )

        breakdown_labels = [result["breakdown_value"] for result in response.results]

        assert len(response.results) == 2
        assert breakdown_labels == ["true", "false"]

        assert response.results[0]["label"] == f"true"
        assert response.results[1]["label"] == f"false"

        assert response.results[0]["count"] == 7
        assert response.results[1]["count"] == 3

    def test_trends_breakdowns_histogram(self):
        self._create_test_events()

        response = self._run_trends_query(
            "2020-01-09",
            "2020-01-20",
            IntervalType.DAY,
            [EventsNode(event="$pageview")],
            None,
            BreakdownFilter(
                breakdown_type=BreakdownType.EVENT,
                breakdown="prop",
                breakdown_histogram_bin_count=4,
            ),
        )

        breakdown_labels = [result["breakdown_value"] for result in response.results]

        assert len(response.results) == 4
        assert breakdown_labels == ["[10,17.5]", "[17.5,25]", "[25,32.5]", "[32.5,40.01]"]

        assert response.results[0]["label"] == "[10,17.5]"
        assert response.results[1]["label"] == "[17.5,25]"
        assert response.results[2]["label"] == "[25,32.5]"
        assert response.results[3]["label"] == "[32.5,40.01]"

        assert response.results[0]["data"] == [0, 0, 1, 1, 1, 0, 1, 0, 1, 0, 1, 0]
        assert response.results[1]["data"] == [1, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0]
        assert response.results[2]["data"] == [0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0]
        assert response.results[3]["data"] == [0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0]

    def test_trends_breakdowns_cohort(self):
        self._create_test_events()
        cohort = Cohort.objects.create(
            team=self.team,
            groups=[
                {
                    "properties": [
                        {
                            "key": "name",
                            "value": "p1",
                            "type": "person",
                        }
                    ]
                }
            ],
            name="cohort",
        )
        cohort.calculate_people_ch(pending_version=0)

        response = self._run_trends_query(
            "2020-01-09",
            "2020-01-20",
            IntervalType.DAY,
            [EventsNode(event="$pageview")],
            None,
            BreakdownFilter(breakdown_type=BreakdownType.COHORT, breakdown=[cohort.pk]),
        )

        assert len(response.results) == 1

        assert response.results[0]["label"] == f"cohort"
        assert response.results[0]["count"] == 6
        assert response.results[0]["data"] == [
            0,
            0,
            1,
            1,
            1,
            0,
            1,
            0,
            1,
            0,
            1,
            0,
        ]

    def test_trends_breakdowns_hogql(self):
        self._create_test_events()

        response = self._run_trends_query(
            "2020-01-09",
            "2020-01-20",
            IntervalType.DAY,
            [EventsNode(event="$pageview")],
            None,
            BreakdownFilter(breakdown_type=BreakdownType.HOGQL, breakdown="properties.$browser"),
        )

        breakdown_labels = [result["breakdown_value"] for result in response.results]

        assert len(response.results) == 4
        assert breakdown_labels == ["Chrome", "Firefox", "Edge", "Safari"]
        assert response.results[0]["label"] == "Chrome"
        assert response.results[1]["label"] == "Firefox"
        assert response.results[2]["label"] == "Edge"
        assert response.results[3]["label"] == "Safari"
        assert response.results[0]["count"] == 6
        assert response.results[1]["count"] == 2
        assert response.results[2]["count"] == 1
        assert response.results[3]["count"] == 1

    def test_trends_breakdowns_multiple_hogql(self):
        self._create_test_events()

        response = self._run_trends_query(
            "2020-01-09",
            "2020-01-20",
            IntervalType.DAY,
            [EventsNode(event="$pageview"), EventsNode(event="$pageleave")],
            None,
            BreakdownFilter(breakdown_type=BreakdownType.HOGQL, breakdown="properties.$browser"),
        )

        breakdown_labels = [result["breakdown_value"] for result in response.results]

        assert len(response.results) == 8
        assert breakdown_labels == ["Chrome", "Firefox", "Edge", "Safari", "Chrome", "Edge", "Firefox", "Safari"]
        assert response.results[0]["label"] == f"$pageview - Chrome"
        assert response.results[1]["label"] == f"$pageview - Firefox"
        assert response.results[2]["label"] == f"$pageview - Edge"
        assert response.results[3]["label"] == f"$pageview - Safari"
        assert response.results[4]["label"] == f"$pageleave - Chrome"
        assert response.results[5]["label"] == f"$pageleave - Edge"
        assert response.results[6]["label"] == f"$pageleave - Firefox"
        assert response.results[7]["label"] == f"$pageleave - Safari"
        assert response.results[0]["count"] == 6
        assert response.results[1]["count"] == 2
        assert response.results[2]["count"] == 1
        assert response.results[3]["count"] == 1
        assert response.results[4]["count"] == 3
        assert response.results[5]["count"] == 1
        assert response.results[6]["count"] == 1
        assert response.results[7]["count"] == 1

    def test_trends_breakdowns_and_compare(self):
        self._create_test_events()

        response = self._run_trends_query(
            "2020-01-15",
            "2020-01-20",
            IntervalType.DAY,
            [EventsNode(event="$pageview")],
            TrendsFilter(compare=True),
            BreakdownFilter(breakdown_type=BreakdownType.EVENT, breakdown="$browser"),
        )

        breakdown_labels = [result["breakdown_value"] for result in response.results]

        assert len(response.results) == 5
        assert breakdown_labels == [
            "Chrome",
            "Safari",
            "Chrome",
            "Firefox",
            "Edge",
        ]

        assert response.results[0]["label"] == f"Chrome"
        assert response.results[1]["label"] == f"Safari"
        assert response.results[2]["label"] == f"Chrome"
        assert response.results[3]["label"] == f"Firefox"
        assert response.results[4]["label"] == f"Edge"

        assert response.results[0]["count"] == 3
        assert response.results[1]["count"] == 1
        assert response.results[2]["count"] == 3
        assert response.results[3]["count"] == 2
        assert response.results[4]["count"] == 1

        assert response.results[0]["compare_label"] == "current"
        assert response.results[1]["compare_label"] == "current"
        assert response.results[2]["compare_label"] == "previous"
        assert response.results[3]["compare_label"] == "previous"
        assert response.results[4]["compare_label"] == "previous"

        assert response.results[0]["compare"] is True
        assert response.results[1]["compare"] is True
        assert response.results[2]["compare"] is True
        assert response.results[3]["compare"] is True
        assert response.results[4]["compare"] is True

    def test_trends_breakdown_and_aggregation_query_orchestration(self):
        self._create_test_events()

        response = self._run_trends_query(
            "2020-01-09",
            "2020-01-20",
            IntervalType.DAY,
            [EventsNode(event="$pageview", math=PropertyMathType.SUM, math_property="prop")],
            None,
            BreakdownFilter(breakdown_type=BreakdownType.EVENT, breakdown="$browser"),
        )

        breakdown_labels = [result["breakdown_value"] for result in response.results]

        assert len(response.results) == 4
        assert breakdown_labels == ["Chrome", "Firefox", "Safari", "Edge"]
        assert response.results[0]["label"] == "Chrome"
        assert response.results[1]["label"] == "Firefox"
        assert response.results[2]["label"] == "Safari"
        assert response.results[3]["label"] == "Edge"

        assert response.results[0]["data"] == [
            0,
            0,
            10,
            10,
            10,
            0,
            10,
            0,
            10,
            0,
            10,
            0,
        ]

        assert response.results[1]["data"] == [
            20,
            0,
            0,
            20,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
        ]
        assert response.results[2]["data"] == [
            0,
            0,
            0,
            0,
            0,
            0,
            40,
            0,
            0,
            0,
            0,
            0,
        ]
        assert response.results[3]["data"] == [
            0,
            0,
            0,
            30,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
        ]

    def test_trends_aggregation_hogql(self):
        self._create_test_events()

        response = self._run_trends_query(
            "2020-01-09",
            "2020-01-20",
            IntervalType.DAY,
            [EventsNode(event="$pageview", math="hogql", math_hogql="sum(properties.prop)")],
            None,
            None,
        )

        assert len(response.results) == 1
        assert response.results[0]["data"] == [
            20,
            0,
            10,
            60,
            10,
            0,
            50,
            0,
            10,
            0,
            10,
            0,
        ]

    def test_trends_aggregation_total(self):
        self._create_test_events()

        response = self._run_trends_query(
            "2020-01-09",
            "2020-01-20",
            IntervalType.DAY,
            [EventsNode(event="$pageview", math=BaseMathType.TOTAL)],
            None,
            None,
        )

        assert len(response.results) == 1
        assert response.results[0]["count"] == 10

    def test_trends_aggregation_dau(self):
        self._create_test_events()

        response = self._run_trends_query(
            "2020-01-09",
            "2020-01-20",
            IntervalType.DAY,
            [EventsNode(event="$pageview", math=BaseMathType.DAU)],
            None,
            None,
        )

        assert len(response.results) == 1
        assert response.results[0]["data"] == [1, 0, 1, 3, 1, 0, 2, 0, 1, 0, 1, 0]

    def test_trends_aggregation_wau(self):
        self._create_test_events()

        response = self._run_trends_query(
            "2020-01-09",
            "2020-01-20",
            IntervalType.DAY,
            [EventsNode(event="$pageview", math=BaseMathType.WEEKLY_ACTIVE)],
            None,
            None,
        )

        assert len(response.results) == 1
        assert response.results[0]["data"] == [1, 1, 2, 3, 3, 3, 4, 4, 4, 4, 2, 2]

    def test_trends_aggregation_mau(self):
        self._create_test_events()

        response = self._run_trends_query(
            "2020-01-09",
            "2020-01-20",
            IntervalType.DAY,
            [EventsNode(event="$pageview", math=BaseMathType.MONTHLY_ACTIVE)],
            None,
            None,
        )

        assert len(response.results) == 1
        assert response.results[0]["data"] == [1, 1, 2, 3, 3, 3, 4, 4, 4, 4, 4, 4]

    def test_trends_aggregation_unique(self):
        self._create_test_events()

        response = self._run_trends_query(
            "2020-01-09",
            "2020-01-20",
            IntervalType.DAY,
            [EventsNode(event="$pageview", math=BaseMathType.UNIQUE_SESSION)],
            None,
            None,
        )

        assert len(response.results) == 1
        assert response.results[0]["data"] == [1, 0, 1, 1, 1, 0, 1, 0, 1, 0, 1, 0]

    def test_trends_aggregation_property_sum(self):
        self._create_test_events()

        response = self._run_trends_query(
            "2020-01-09",
            "2020-01-20",
            IntervalType.DAY,
            [EventsNode(event="$pageview", math=PropertyMathType.SUM, math_property="prop")],
            None,
            None,
        )

        assert len(response.results) == 1
        assert response.results[0]["data"] == [
            20,
            0,
            10,
            60,
            10,
            0,
            50,
            0,
            10,
            0,
            10,
            0,
        ]

    def test_trends_aggregation_property_avg(self):
        self._create_test_events()

        response = self._run_trends_query(
            "2020-01-09",
            "2020-01-20",
            IntervalType.DAY,
            [EventsNode(event="$pageview", math=PropertyMathType.AVG, math_property="prop")],
            None,
            None,
        )

        assert len(response.results) == 1
        assert response.results[0]["data"] == [
            20,
            0,
            10,
            20,
            10,
            0,
            25,
            0,
            10,
            0,
            10,
            0,
        ]

    def test_trends_aggregation_per_actor_max(self):
        self._create_test_events()

        response = self._run_trends_query(
            "2020-01-09",
            "2020-01-20",
            IntervalType.DAY,
            [EventsNode(event="$pageview", math=CountPerActorMathType.MAX_COUNT_PER_ACTOR)],
            None,
            None,
        )

        assert len(response.results) == 1
        assert response.results[0]["data"] == [
            1,
            0,
            1,
            1,
            1,
            0,
            1,
            0,
            1,
            0,
            1,
            0,
        ]

    def test_trends_display_aggregate(self):
        self._create_test_events()

        response = self._run_trends_query(
            "2020-01-09",
            "2020-01-20",
            IntervalType.DAY,
            [EventsNode(event="$pageview")],
            TrendsFilter(display=ChartDisplayType.BOLD_NUMBER),
            None,
        )

        assert len(response.results) == 1
        assert response.results[0]["data"] == []
        assert response.results[0]["days"] == []
        assert response.results[0]["count"] == 0
        assert response.results[0]["aggregated_value"] == 10

    def test_trends_display_cumulative(self):
        self._create_test_events()

        response = self._run_trends_query(
            "2020-01-09",
            "2020-01-20",
            IntervalType.DAY,
            [EventsNode(event="$pageview")],
            TrendsFilter(display=ChartDisplayType.ACTIONS_LINE_GRAPH_CUMULATIVE),
            None,
        )

        assert len(response.results) == 1
        assert response.results[0]["count"] == 10
        assert response.results[0]["data"] == [
            1,
            1,
            2,
            5,
            6,
            6,
            8,
            8,
            9,
            9,
            10,
            10,
        ]

    def test_breakdown_values_limit(self):
        PropertyDefinition.objects.create(team=self.team, name="breakdown_value", property_type="String")

        for value in list(range(30)):
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id=f"person_{value}",
                timestamp="2020-01-11T12:00:00Z",
                properties={"breakdown_value": f"{value}"},
            )

        response = self._run_trends_query(
            "2020-01-09",
            "2020-01-20",
            IntervalType.DAY,
            [EventsNode(event="$pageview")],
            TrendsFilter(display=ChartDisplayType.ACTIONS_LINE_GRAPH),
            BreakdownFilter(breakdown="breakdown_value", breakdown_type=BreakdownType.EVENT),
        )

        self.assertEqual(len(response.results), 26)

        response = self._run_trends_query(
            "2020-01-09",
            "2020-01-20",
            IntervalType.DAY,
            [EventsNode(event="$pageview")],
            TrendsFilter(display=ChartDisplayType.ACTIONS_LINE_GRAPH),
            BreakdownFilter(breakdown="breakdown_value", breakdown_type=BreakdownType.EVENT, breakdown_limit=10),
        )
        self.assertEqual(len(response.results), 11)

        response = self._run_trends_query(
            "2020-01-09",
            "2020-01-20",
            IntervalType.DAY,
            [EventsNode(event="$pageview")],
            TrendsFilter(display=ChartDisplayType.ACTIONS_LINE_GRAPH),
            BreakdownFilter(breakdown="breakdown_value", breakdown_type=BreakdownType.EVENT),
            limit_context=LimitContext.EXPORT,
        )
        self.assertEqual(len(response.results), 30)

    def test_breakdown_values_unknown_property(self):
        # same as above test, just without creating the property definition
        for value in list(range(30)):
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id=f"person_{value}",
                timestamp="2020-01-11T12:00:00Z",
                properties={"breakdown_value": f"{value}"},
            )

        response = self._run_trends_query(
            "2020-01-09",
            "2020-01-20",
            IntervalType.DAY,
            [EventsNode(event="$pageview")],
            TrendsFilter(display=ChartDisplayType.ACTIONS_LINE_GRAPH),
            BreakdownFilter(breakdown="breakdown_value", breakdown_type=BreakdownType.EVENT),
        )

        self.assertEqual(len(response.results), 26)

        response = self._run_trends_query(
            "2020-01-09",
            "2020-01-20",
            IntervalType.DAY,
            [EventsNode(event="$pageview")],
            TrendsFilter(display=ChartDisplayType.ACTIONS_LINE_GRAPH),
            BreakdownFilter(breakdown="breakdown_value", breakdown_type=BreakdownType.EVENT, breakdown_limit=10),
        )
        self.assertEqual(len(response.results), 11)

    def test_breakdown_values_world_map_limit(self):
        PropertyDefinition.objects.create(team=self.team, name="breakdown_value", property_type="String")

        for value in list(range(250)):
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id=f"person_{value}",
                timestamp="2020-01-11T12:00:00Z",
                properties={"breakdown_value": f"{value}"},
            )

        query_runner = self._create_query_runner(
            "2020-01-09",
            "2020-01-20",
            IntervalType.DAY,
            [EventsNode(event="$pageview")],
            TrendsFilter(display=ChartDisplayType.WORLD_MAP),
            BreakdownFilter(breakdown="breakdown_value", breakdown_type=BreakdownType.EVENT),
        )
        query = query_runner.to_queries()[0]
        assert isinstance(query, ast.SelectQuery) and query.limit == ast.Constant(value=MAX_SELECT_RETURNED_ROWS)

        response = query_runner.calculate()
        assert len(response.results) == 250

    def test_previous_period_with_number_display(self):
        self._create_test_events()

        response = self._run_trends_query(
            "2020-01-09",
            "2020-01-20",
            IntervalType.DAY,
            [EventsNode(event="$pageview")],
            TrendsFilter(display=ChartDisplayType.BOLD_NUMBER, compare=True),
            None,
        )

        assert len(response.results) == 2

    def test_formula_rounding(self):
        _create_event(
            team=self.team,
            event="$pageleave",
            distinct_id="person_1",
            timestamp="2020-01-11T12:00:00Z",
            properties={},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="person_2",
            timestamp="2020-01-11T12:00:00Z",
            properties={},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="person_3",
            timestamp="2020-01-11T12:00:00Z",
            properties={},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="person_4",
            timestamp="2020-01-11T12:00:00Z",
            properties={},
        )

        response = self._run_trends_query(
            "2020-01-11T00:00:00Z",
            "2020-01-11T23:59:59Z",
            IntervalType.DAY,
            [EventsNode(event="$pageview"), EventsNode(event="$pageleave")],
            TrendsFilter(formula="B/A"),
        )

        self.assertEqual(1, len(response.results))
        self.assertEqual([1 / 3], response.results[0]["data"])

    @also_test_with_materialized_columns(["$some_property"])
    def test_properties_filtering_with_materialized_columns_and_empty_string_as_property(self):
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="person_1",
            timestamp="2020-01-11T12:00:00Z",
            properties={"$some_property": ""},
        )

        self.team.test_account_filters = [
            {
                "key": "$some_property",
                "value": ["other_value", "yet_another_value"],
                "operator": "is_not",
                "type": "event",
            },
        ]
        self.team.save()

        response = self._run_trends_query(
            date_from="2020-01-11T00:00:00Z",
            date_to="2020-01-11T23:59:59Z",
            interval=IntervalType.DAY,
            series=[EventsNode(event="$pageview")],
            filter_test_accounts=True,
        )

        assert response.results[0]["data"] == [1]

    def test_smoothing(self):
        self._create_test_events()

        response = self._run_trends_query(
            "2020-01-09",
            "2020-01-20",
            IntervalType.DAY,
            [EventsNode(event="$pageview")],
            TrendsFilter(smoothingIntervals=7),
            None,
        )

        assert response.results[0]["data"] == [1, 0, 0, 1, 1, 1, 1, 1, 1, 1, 0, 0]

    @patch("posthog.hogql_queries.query_runner.create_default_modifiers_for_team")
    def test_cohort_modifier(self, patch_create_default_modifiers_for_team):
        self._create_test_events()

        cohort1 = Cohort.objects.create(
            team=self.team,
            groups=[
                {
                    "properties": [
                        {
                            "key": "name",
                            "value": "p1",
                            "type": "person",
                        }
                    ]
                }
            ],
            name="cohort1",
        )
        cohort1.calculate_people_ch(pending_version=0)

        cohort2 = Cohort.objects.create(
            team=self.team,
            groups=[
                {
                    "properties": [
                        {
                            "key": "name",
                            "value": "p2",
                            "type": "person",
                        }
                    ]
                }
            ],
            name="cohort2",
        )
        cohort2.calculate_people_ch(pending_version=0)

        modifiers = create_default_modifiers_for_team(self.team)

        patch_create_default_modifiers_for_team.return_value = modifiers

        self._run_trends_query(
            "2020-01-09",
            "2020-01-20",
            IntervalType.DAY,
            [EventsNode(event="$pageview")],
            None,
            BreakdownFilter(breakdown_type=BreakdownType.COHORT, breakdown=[cohort1.pk, cohort2.pk]),
            hogql_modifiers=modifiers,
        )

        assert modifiers.inCohortVia == InCohortVia.LEFTJOIN_CONJOINED

    @patch("posthog.hogql_queries.query_runner.create_default_modifiers_for_team")
    def test_cohort_modifier_with_all_cohort(self, patch_create_default_modifiers_for_team):
        self._create_test_events()

        cohort1 = Cohort.objects.create(
            team=self.team,
            groups=[
                {
                    "properties": [
                        {
                            "key": "name",
                            "value": "p1",
                            "type": "person",
                        }
                    ]
                }
            ],
            name="cohort1",
        )
        cohort1.calculate_people_ch(pending_version=0)

        cohort2 = Cohort.objects.create(
            team=self.team,
            groups=[
                {
                    "properties": [
                        {
                            "key": "name",
                            "value": "p2",
                            "type": "person",
                        }
                    ]
                }
            ],
            name="cohort2",
        )
        cohort2.calculate_people_ch(pending_version=0)

        modifiers = create_default_modifiers_for_team(self.team)

        patch_create_default_modifiers_for_team.return_value = modifiers

        self._run_trends_query(
            "2020-01-09",
            "2020-01-20",
            IntervalType.DAY,
            [EventsNode(event="$pageview")],
            None,
            BreakdownFilter(breakdown_type=BreakdownType.COHORT, breakdown=[cohort1.pk, cohort2.pk, "all"]),
            hogql_modifiers=modifiers,
        )

        assert modifiers.inCohortVia == InCohortVia.AUTO

    @patch("posthog.hogql_queries.query_runner.create_default_modifiers_for_team")
    def test_cohort_modifier_with_too_few_cohorts(self, patch_create_default_modifiers_for_team):
        self._create_test_events()

        cohort1 = Cohort.objects.create(
            team=self.team,
            groups=[
                {
                    "properties": [
                        {
                            "key": "name",
                            "value": "p1",
                            "type": "person",
                        }
                    ]
                }
            ],
            name="cohort1",
        )
        cohort1.calculate_people_ch(pending_version=0)

        cohort2 = Cohort.objects.create(
            team=self.team,
            groups=[
                {
                    "properties": [
                        {
                            "key": "name",
                            "value": "p2",
                            "type": "person",
                        }
                    ]
                }
            ],
            name="cohort2",
        )
        cohort2.calculate_people_ch(pending_version=0)

        modifiers = create_default_modifiers_for_team(self.team)

        patch_create_default_modifiers_for_team.return_value = modifiers

        self._run_trends_query(
            "2020-01-09",
            "2020-01-20",
            IntervalType.DAY,
            [EventsNode(event="$pageview")],
            None,
            BreakdownFilter(breakdown_type=BreakdownType.COHORT, breakdown=[cohort1.pk, cohort2.pk, "all"]),
            hogql_modifiers=modifiers,
        )

        assert modifiers.inCohortVia == InCohortVia.AUTO

    @patch("posthog.hogql_queries.insights.trends.trends_query_runner.execute_hogql_query")
    def test_should_throw_exception(self, patch_sync_execute):
        patch_sync_execute.side_effect = Exception("Error thrown inside thread")

        with self.assertRaises(Exception) as e:
            self._run_trends_query(
                "2020-01-09",
                "2020-01-20",
                IntervalType.DAY,
                [EventsNode(event="$pageview")],
                None,
                None,
            )

        self.assertEqual(
            str(e.exception),
            "Error thrown inside thread",
        )

    def test_to_actors_query_options(self):
        self._create_test_events()
        flush_persons_and_events()

        runner = self._create_query_runner(
            "2020-01-09",
            "2020-01-20",
            IntervalType.DAY,
            [EventsNode(event="$pageview")],
            None,
            None,
        )
        response = runner.to_actors_query_options()

        assert response.day == [
            DayItem(label="9-Jan-2020", value=datetime(2020, 1, 9, 0, 0, tzinfo=zoneinfo.ZoneInfo(key="UTC"))),
            DayItem(label="10-Jan-2020", value=datetime(2020, 1, 10, 0, 0, tzinfo=zoneinfo.ZoneInfo(key="UTC"))),
            DayItem(label="11-Jan-2020", value=datetime(2020, 1, 11, 0, 0, tzinfo=zoneinfo.ZoneInfo(key="UTC"))),
            DayItem(label="12-Jan-2020", value=datetime(2020, 1, 12, 0, 0, tzinfo=zoneinfo.ZoneInfo(key="UTC"))),
            DayItem(label="13-Jan-2020", value=datetime(2020, 1, 13, 0, 0, tzinfo=zoneinfo.ZoneInfo(key="UTC"))),
            DayItem(label="14-Jan-2020", value=datetime(2020, 1, 14, 0, 0, tzinfo=zoneinfo.ZoneInfo(key="UTC"))),
            DayItem(label="15-Jan-2020", value=datetime(2020, 1, 15, 0, 0, tzinfo=zoneinfo.ZoneInfo(key="UTC"))),
            DayItem(label="16-Jan-2020", value=datetime(2020, 1, 16, 0, 0, tzinfo=zoneinfo.ZoneInfo(key="UTC"))),
            DayItem(label="17-Jan-2020", value=datetime(2020, 1, 17, 0, 0, tzinfo=zoneinfo.ZoneInfo(key="UTC"))),
            DayItem(label="18-Jan-2020", value=datetime(2020, 1, 18, 0, 0, tzinfo=zoneinfo.ZoneInfo(key="UTC"))),
            DayItem(label="19-Jan-2020", value=datetime(2020, 1, 19, 0, 0, tzinfo=zoneinfo.ZoneInfo(key="UTC"))),
            DayItem(label="20-Jan-2020", value=datetime(2020, 1, 20, 0, 0, tzinfo=zoneinfo.ZoneInfo(key="UTC"))),
        ]

        assert response.breakdown is None

        assert response.series == [InsightActorsQuerySeries(label="$pageview", value=0)]

        assert response.compare is None

    def test_to_actors_query_options_compare(self):
        self._create_test_events()
        flush_persons_and_events()

        runner = self._create_query_runner(
            "2020-01-09",
            "2020-01-20",
            IntervalType.DAY,
            [EventsNode(event="$pageview")],
            TrendsFilter(compare=True),
            None,
        )
        response = runner.to_actors_query_options()

        assert response.day == [
            DayItem(label="9-Jan-2020", value=datetime(2020, 1, 9, 0, 0, tzinfo=zoneinfo.ZoneInfo(key="UTC"))),
            DayItem(label="10-Jan-2020", value=datetime(2020, 1, 10, 0, 0, tzinfo=zoneinfo.ZoneInfo(key="UTC"))),
            DayItem(label="11-Jan-2020", value=datetime(2020, 1, 11, 0, 0, tzinfo=zoneinfo.ZoneInfo(key="UTC"))),
            DayItem(label="12-Jan-2020", value=datetime(2020, 1, 12, 0, 0, tzinfo=zoneinfo.ZoneInfo(key="UTC"))),
            DayItem(label="13-Jan-2020", value=datetime(2020, 1, 13, 0, 0, tzinfo=zoneinfo.ZoneInfo(key="UTC"))),
            DayItem(label="14-Jan-2020", value=datetime(2020, 1, 14, 0, 0, tzinfo=zoneinfo.ZoneInfo(key="UTC"))),
            DayItem(label="15-Jan-2020", value=datetime(2020, 1, 15, 0, 0, tzinfo=zoneinfo.ZoneInfo(key="UTC"))),
            DayItem(label="16-Jan-2020", value=datetime(2020, 1, 16, 0, 0, tzinfo=zoneinfo.ZoneInfo(key="UTC"))),
            DayItem(label="17-Jan-2020", value=datetime(2020, 1, 17, 0, 0, tzinfo=zoneinfo.ZoneInfo(key="UTC"))),
            DayItem(label="18-Jan-2020", value=datetime(2020, 1, 18, 0, 0, tzinfo=zoneinfo.ZoneInfo(key="UTC"))),
            DayItem(label="19-Jan-2020", value=datetime(2020, 1, 19, 0, 0, tzinfo=zoneinfo.ZoneInfo(key="UTC"))),
            DayItem(label="20-Jan-2020", value=datetime(2020, 1, 20, 0, 0, tzinfo=zoneinfo.ZoneInfo(key="UTC"))),
        ]

        assert response.breakdown is None

        assert response.series == [InsightActorsQuerySeries(label="$pageview", value=0)]

        assert response.compare == [
            CompareItem(label="Current", value="current"),
            CompareItem(label="Previous", value="previous"),
        ]

    def test_to_actors_query_options_multiple_series(self):
        self._create_test_events()
        flush_persons_and_events()

        runner = self._create_query_runner(
            "2020-01-09",
            "2020-01-20",
            IntervalType.DAY,
            [EventsNode(event="$pageview"), EventsNode(event="$pageleave")],
            None,
            None,
        )
        response = runner.to_actors_query_options()

        assert response.series == [
            InsightActorsQuerySeries(label="$pageview", value=0),
            InsightActorsQuerySeries(label="$pageleave", value=1),
        ]

    def test_to_actors_query_options_breakdowns(self):
        self._create_test_events()
        flush_persons_and_events()

        runner = self._create_query_runner(
            "2020-01-09",
            "2020-01-20",
            IntervalType.DAY,
            [EventsNode(event="$pageview")],
            None,
            BreakdownFilter(breakdown_type=BreakdownType.EVENT, breakdown="$browser", breakdown_limit=3),
        )

        response = runner.to_actors_query_options()

        assert response.day is not None
        assert response.series == [InsightActorsQuerySeries(label="$pageview", value=0)]
        assert response.breakdown == [
            BreakdownItem(label=BREAKDOWN_OTHER_DISPLAY, value="$$_posthog_breakdown_other_$$"),
            BreakdownItem(label="Chrome", value="Chrome"),
            BreakdownItem(label="Firefox", value="Firefox"),
            BreakdownItem(label="Safari", value="Safari"),
        ]

    def test_to_actors_query_options_breakdowns_boolean(self):
        self._create_test_events()
        flush_persons_and_events()

        runner = self._create_query_runner(
            "2020-01-09",
            "2020-01-20",
            IntervalType.DAY,
            [EventsNode(event="$pageview")],
            None,
            BreakdownFilter(breakdown_type=BreakdownType.EVENT, breakdown="bool_field"),
        )

        response = runner.to_actors_query_options()

        assert response.series == [InsightActorsQuerySeries(label="$pageview", value=0)]

        assert response.breakdown == [
            BreakdownItem(label="true", value="true"),
            BreakdownItem(label="false", value="false"),
        ]

    def test_to_actors_query_options_breakdowns_histogram(self):
        self._create_test_events()
        flush_persons_and_events()

        runner = self._create_query_runner(
            "2020-01-09",
            "2020-01-20",
            IntervalType.DAY,
            [EventsNode(event="$pageview")],
            None,
            BreakdownFilter(
                breakdown_type=BreakdownType.EVENT,
                breakdown="prop",
                breakdown_histogram_bin_count=4,
            ),
        )

        response = runner.to_actors_query_options()

        assert response.series == [InsightActorsQuerySeries(label="$pageview", value=0)]

        assert response.breakdown == [
            BreakdownItem(label="[10.0,17.5]", value="[10.0,17.5]"),
            BreakdownItem(label="[17.5,25.0]", value="[17.5,25.0]"),
            BreakdownItem(label="[25.0,32.5]", value="[25.0,32.5]"),
            BreakdownItem(label="[32.5,40.01]", value="[32.5,40.01]"),
            BreakdownItem(label='["",""]', value='["",""]'),
        ]

    def test_to_actors_query_options_breakdowns_cohort(self):
        self._create_test_events()
        flush_persons_and_events()

        cohort = Cohort.objects.create(
            team=self.team,
            groups=[
                {
                    "properties": [
                        {
                            "key": "name",
                            "value": "p1",
                            "type": "person",
                        }
                    ]
                }
            ],
            name="cohort",
        )
        cohort.calculate_people_ch(pending_version=0)

        runner = self._create_query_runner(
            "2020-01-09",
            "2020-01-20",
            IntervalType.DAY,
            [EventsNode(event="$pageview")],
            None,
            BreakdownFilter(breakdown_type=BreakdownType.COHORT, breakdown=[cohort.pk]),
        )

        response = runner.to_actors_query_options()

        assert response.series == [InsightActorsQuerySeries(label="$pageview", value=0)]

        assert response.breakdown == [BreakdownItem(label="cohort", value=cohort.pk)]

    def test_to_actors_query_options_breakdowns_hogql(self):
        self._create_test_events()
        flush_persons_and_events()

        runner = self._create_query_runner(
            "2020-01-09",
            "2020-01-20",
            IntervalType.DAY,
            [EventsNode(event="$pageview")],
            None,
            BreakdownFilter(breakdown_type=BreakdownType.HOGQL, breakdown="properties.$browser"),
        )

        response = runner.to_actors_query_options()

        assert response.series == [InsightActorsQuerySeries(label="$pageview", value=0)]

        assert response.breakdown == [
            BreakdownItem(label="Chrome", value="Chrome"),
            BreakdownItem(label="Firefox", value="Firefox"),
            BreakdownItem(label="Safari", value="Safari"),
            BreakdownItem(label="Edge", value="Edge"),
        ]

    def test_to_actors_query_options_bar_value(self):
        self._create_test_events()
        flush_persons_and_events()

        runner = self._create_query_runner(
            "2020-01-09",
            "2020-01-20",
            IntervalType.DAY,
            [EventsNode(event="$pageview")],
            TrendsFilter(display=ChartDisplayType.ACTIONS_BAR_VALUE),
            BreakdownFilter(breakdown_type=BreakdownType.EVENT, breakdown="$browser"),
        )

        response = runner.to_actors_query_options()

        assert response.day is None
        assert response.series == [InsightActorsQuerySeries(label="$pageview", value=0)]
        assert response.breakdown == [
            BreakdownItem(label="Chrome", value="Chrome"),
            BreakdownItem(label="Firefox", value="Firefox"),
            BreakdownItem(label="Safari", value="Safari"),
            BreakdownItem(label="Edge", value="Edge"),
        ]

    @patch("posthog.hogql.query.sync_execute", wraps=sync_execute)
    def test_limit_is_context_aware(self, mock_sync_execute: MagicMock):
        self._run_trends_query(
            "2020-01-09",
            "2020-01-20",
            IntervalType.DAY,
            [EventsNode(event="$pageview")],
            limit_context=LimitContext.QUERY_ASYNC,
        )

        mock_sync_execute.assert_called_once()
        self.assertIn(f" max_execution_time={HOGQL_INCREASED_MAX_EXECUTION_TIME},", mock_sync_execute.call_args[0][0])

    def test_actors_query_explicit_dates(self):
        self._create_test_events()
        flush_persons_and_events()

        runner = self._create_query_runner(
            "2020-01-09 12:37:42",
            "2020-01-20 12:37:42",
            IntervalType.DAY,
            [EventsNode(event="$pageview")],
            None,
            None,
            explicit_date=True,
        )

        # date_to starts at specific time
        response = runner.to_actors_query(
            time_frame="2020-01-09", series_index=0, breakdown_value=None, compare_value=None
        )
        assert response.select_from.table.where.exprs[1].right.value == datetime(  # type: ignore
            2020, 1, 9, 12, 37, 42, tzinfo=zoneinfo.ZoneInfo(key="UTC")
        )
        assert response.select_from.table.where.exprs[2].right.value == datetime(  # type: ignore
            2020, 1, 10, 0, 0, tzinfo=zoneinfo.ZoneInfo(key="UTC")
        )

        # date_from ends at specific time
        response = runner.to_actors_query(
            time_frame="2020-01-20", series_index=0, breakdown_value=None, compare_value=None
        )
        assert response.select_from.table.where.exprs[1].right.value == datetime(  # type: ignore
            2020, 1, 20, 0, 0, tzinfo=zoneinfo.ZoneInfo(key="UTC")
        )
        assert response.select_from.table.where.exprs[2].right.value == datetime(  # type: ignore
            2020, 1, 20, 12, 37, 42, tzinfo=zoneinfo.ZoneInfo(key="UTC")
        )

    def test_sampling_adjustment(self):
        for value in list(range(30)):
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id=f"person_{value}",
                timestamp="2020-01-11T12:00:00Z",
                properties={"breakdown_value": f"{value}"},
            )

        # line graph
        runner = self._create_query_runner(
            "2020-01-01",
            "2020-01-31",
            IntervalType.MONTH,
            [EventsNode(event="$pageview")],
            TrendsFilter(display=ChartDisplayType.ACTIONS_LINE_GRAPH),
        )
        runner.query.samplingFactor = 0.1
        response = runner.calculate()
        assert len(response.results) == 1
        # 10% of 30 is 3, so check we're adjusting the results back up
        assert response.results[0]["count"] > 5 and response.results[0]["count"] < 30

        # big number
        runner = self._create_query_runner(
            "2020-01-01",
            "2020-01-31",
            IntervalType.MONTH,
            [EventsNode(event="$pageview")],
            TrendsFilter(display=ChartDisplayType.BOLD_NUMBER),
        )
        runner.query.samplingFactor = 0.1
        response = runner.calculate()
        assert len(response.results) == 1
        # 10% of 30 is 3, so check we're adjusting the results back up
        assert response.results[0]["aggregated_value"] > 5 and response.results[0]["aggregated_value"] < 30
