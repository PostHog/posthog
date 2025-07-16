import itertools
import re
import zoneinfo
from dataclasses import dataclass
from datetime import datetime, timedelta
from itertools import groupby
from typing import Any, Optional
from unittest.mock import MagicMock, patch

import pytest
from django.test import override_settings
from freezegun import freeze_time
from pydantic import ValidationError

from posthog.clickhouse.client.execute import sync_execute
from posthog.hogql import ast
from posthog.hogql.constants import MAX_SELECT_RETURNED_ROWS, LimitContext
from posthog.hogql.modifiers import create_default_modifiers_for_team
from posthog.hogql_queries.insights.trends.breakdown import (
    BREAKDOWN_NULL_DISPLAY,
    BREAKDOWN_NULL_STRING_LABEL,
    BREAKDOWN_OTHER_STRING_LABEL,
)
from posthog.hogql_queries.insights.trends.trends_query_runner import (
    BREAKDOWN_OTHER_DISPLAY,
    TrendsQueryRunner,
)
from posthog.models import GroupTypeMapping
from posthog.models.action.action import Action
from posthog.models.cohort.cohort import Cohort
from posthog.models.group.util import create_group
from posthog.models.property_definition import PropertyDefinition
from posthog.models.team.team import Team
from posthog.schema import (
    ActionsNode,
    BaseMathType,
    Breakdown,
    BreakdownFilter,
    BreakdownItem,
    BreakdownType,
    ChartDisplayType,
    CompareFilter,
    CompareItem,
    CountPerActorMathType,
    DayItem,
    EventMetadataPropertyFilter,
    EventPropertyFilter,
    EventsNode,
    HogQLQueryModifiers,
    InCohortVia,
    DateRange,
    IntervalType,
    MultipleBreakdownType,
    PersonPropertyFilter,
    PropertyMathType,
    PropertyOperator,
    TrendsFilter,
    TrendsQuery,
    TrendsFormulaNode,
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
from posthog.hogql.query import execute_hogql_query


@dataclass
class Series:
    event: str
    timestamps: list[str]


@dataclass
class GroupTestProperties:
    group0_properties: Optional[dict[str, str | int]] = None
    group1_properties: Optional[dict[str, str | int]] = None
    group2_properties: Optional[dict[str, str | int]] = None
    group3_properties: Optional[dict[str, str | int]] = None
    group4_properties: Optional[dict[str, str | int]] = None


@dataclass
class SeriesTestData:
    distinct_id: str
    events: list[Series]
    properties: dict[str, str | int]
    group_properties: Optional[GroupTestProperties] = None


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

    def _create_group(self, **kwargs):
        create_group(**kwargs)
        props = kwargs.get("properties")
        index = kwargs.get("group_type_index")

        if props is not None:
            for key, value in props.items():
                prop_def_exists = PropertyDefinition.objects.filter(team=self.team, name=key).exists()
                if prop_def_exists is False:
                    if isinstance(value, str):
                        type = "String"
                    elif isinstance(value, bool):
                        type = "Boolean"
                    elif isinstance(value, int):
                        type = "Numeric"
                    else:
                        type = "String"

                    PropertyDefinition.objects.create(
                        team=self.team,
                        name=key,
                        property_type=type,
                        group_type_index=index,
                        type=PropertyDefinition.Type.GROUP,
                    )

    def _create_test_groups(self):
        GroupTypeMapping.objects.create(
            team=self.team, project_id=self.team.project_id, group_type="organization", group_type_index=0
        )
        GroupTypeMapping.objects.create(
            team=self.team, project_id=self.team.project_id, group_type="company", group_type_index=1
        )

        self._create_group(
            team_id=self.team.pk,
            group_type_index=0,
            group_key="org:5",
            properties={"name": "Hedgeflix", "industry": "finance"},
        )
        self._create_group(
            team_id=self.team.pk,
            group_type_index=0,
            group_key="org:6",
            properties={"name": "Hedgebox", "industry": "technology"},
        )
        self._create_group(
            team_id=self.team.pk,
            group_type_index=0,
            group_key="org:7",
            properties={"name": "Hedgebank", "industry": "finance"},
        )
        self._create_group(
            team_id=self.team.pk,
            group_type_index=1,
            group_key="company:10",
            properties={"name": "Hedgeheadquarters", "industry": "service", "employee_count": "50-249"},
        )

    def _create_test_events_for_groups(self):
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
                    properties={"$browser": "Chrome", "prop": 10, "bool_field": True, "$group_0": "org:5"},
                    group_properties=GroupTestProperties(
                        group0_properties={"industry": "finance"},
                    ),
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
                    properties={"$browser": "Firefox", "prop": 20, "bool_field": False, "$group_0": "org:6"},
                    group_properties=GroupTestProperties(
                        group0_properties={"industry": "technology"},
                    ),
                ),
                SeriesTestData(
                    distinct_id="p3",
                    events=[
                        Series(event="$pageview", timestamps=["2020-01-12T12:00:00Z"]),
                        Series(event="$pageleave", timestamps=["2020-01-13T12:00:00Z"]),
                    ],
                    properties={
                        "$browser": "Edge",
                        "prop": 30,
                        "bool_field": True,
                        "$group_0": "org:7",
                        "$group_1": "company:10",
                    },
                    group_properties=GroupTestProperties(
                        group0_properties={"industry": "finance"},
                        group1_properties={"industry": "service", "employee_count": "50-249"},
                    ),
                ),
                SeriesTestData(
                    distinct_id="p4",
                    events=[
                        Series(event="$pageview", timestamps=["2020-01-15T12:00:00Z"]),
                        Series(event="$pageleave", timestamps=["2020-01-16T12:00:00Z"]),
                    ],
                    properties={"$browser": "Safari", "prop": 40, "bool_field": False, "$group_0": "company:10"},
                    group_properties=GroupTestProperties(
                        group0_properties={"industry": "service", "employee_count": "50-249"},
                    ),
                ),
            ]
        )

    def _create_trends_query(
        self,
        date_from: str,
        date_to: Optional[str],
        interval: IntervalType,
        series: Optional[list[EventsNode | ActionsNode]],
        trends_filters: Optional[TrendsFilter] = None,
        breakdown: Optional[BreakdownFilter] = None,
        compare_filters: Optional[CompareFilter] = None,
        filter_test_accounts: Optional[bool] = None,
        explicit_date: Optional[bool] = None,
        properties: Optional[Any] = None,
    ) -> TrendsQuery:
        query_series: list[EventsNode | ActionsNode] = [EventsNode(event="$pageview")] if series is None else series
        return TrendsQuery(
            dateRange=DateRange(date_from=date_from, date_to=date_to, explicitDate=explicit_date),
            interval=interval,
            series=query_series,
            trendsFilter=trends_filters,
            breakdownFilter=breakdown,
            compareFilter=compare_filters,
            filterTestAccounts=filter_test_accounts,
            properties=properties,
        )

    def _create_query_runner(
        self,
        date_from: str,
        date_to: Optional[str],
        interval: IntervalType,
        series: Optional[list[EventsNode | ActionsNode]],
        trends_filters: Optional[TrendsFilter] = None,
        breakdown: Optional[BreakdownFilter] = None,
        compare_filters: Optional[CompareFilter] = None,
        filter_test_accounts: Optional[bool] = None,
        hogql_modifiers: Optional[HogQLQueryModifiers] = None,
        limit_context: Optional[LimitContext] = None,
        explicit_date: Optional[bool] = None,
        properties: Optional[Any] = None,
    ) -> TrendsQueryRunner:
        query = self._create_trends_query(
            date_from=date_from,
            date_to=date_to,
            interval=interval,
            series=series,
            trends_filters=trends_filters,
            breakdown=breakdown,
            compare_filters=compare_filters,
            filter_test_accounts=filter_test_accounts,
            explicit_date=explicit_date,
            properties=properties,
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
        compare_filters: Optional[CompareFilter] = None,
        properties: Optional[Any] = None,
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
            compare_filters=compare_filters,
            properties=properties,
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
                "9-Jan 00:00",
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

        # Check the timings
        response_groups = [
            k
            for k, _ in groupby(
                response.timings, key=lambda query_timing: "".join(re.findall(r"series_\d+", query_timing.k))
            )
        ]
        assert response_groups[0] == ""
        assert response_groups[1] == "series_0"
        assert response_groups[2] == "series_1"
        assert response_groups[3] == ""

    def test_formula(self):
        self._create_test_events()

        response = self._run_trends_query(
            self.default_date_from,
            self.default_date_to,
            IntervalType.DAY,
            [EventsNode(event="$pageview"), EventsNode(event="$pageleave")],
            TrendsFilter(formulas=["A+2*B"]),
        )

        self.assertEqual(1, len(response.results))
        self.assertEqual(22, response.results[0]["count"])
        self.assertEqual("Formula (A+2*B)", response.results[0]["label"])
        self.assertEqual([1, 0, 3, 5, 7, 0, 2, 2, 1, 0, 1], response.results[0]["data"])

    def test_multiple_formulas(self):
        self._create_test_events()

        response = self._run_trends_query(
            self.default_date_from,
            self.default_date_to,
            IntervalType.DAY,
            [EventsNode(event="$pageview"), EventsNode(event="$pageleave")],
            TrendsFilter(formulas=["A+2*B", "A-B"]),
        )

        self.assertEqual(2, len(response.results))

        # First formula A+B
        self.assertEqual(22, response.results[0]["count"])
        self.assertEqual("Formula (A+2*B)", response.results[0]["label"])
        self.assertEqual([1, 0, 3, 5, 7, 0, 2, 2, 1, 0, 1], response.results[0]["data"])

        # Second formula A-B
        self.assertEqual(4, response.results[1]["count"])
        self.assertEqual("Formula (A-B)", response.results[1]["label"])
        self.assertEqual([1, 0, 0, 2, -2, 0, 2, -1, 1, 0, 1], response.results[1]["data"])

    def test_formula_with_compare(self):
        self._create_test_events()

        response = self._run_trends_query(
            "2020-01-15",
            "2020-01-19",
            IntervalType.DAY,
            [EventsNode(event="$pageview"), EventsNode(event="$pageleave")],
            TrendsFilter(formula="A+2*B"),
            compare_filters=CompareFilter(compare=True),
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

    def test_formula_with_compare_to_day(self):
        self._create_test_events()

        response = self._run_trends_query(
            "2020-01-15",
            "2020-01-19",
            IntervalType.DAY,
            [EventsNode(event="$pageview"), EventsNode(event="$pageleave")],
            TrendsFilter(formula="A+2*B"),
            compare_filters=CompareFilter(compare=True, compare_to="-2d"),
        )

        # one for current, one for previous
        self.assertEqual(2, len(response.results))

        # current
        self.assertEqual("current", response.results[0]["compare_label"])
        self.assertEqual(6, response.results[0]["count"])
        self.assertEqual([2, 2, 1, 0, 1], response.results[0]["data"])

        # previous
        self.assertEqual("previous", response.results[1]["compare_label"])
        self.assertEqual(12, response.results[1]["count"])
        self.assertEqual([7, 0, 2, 2, 1], response.results[1]["data"])

        # response shape
        self.assertEqual("Formula (A+2*B)", response.results[0]["label"])
        self.assertEqual(True, response.results[0]["compare"])

    def test_formula_with_compare_to_week(self):
        self._create_test_events()

        response = self._run_trends_query(
            "2020-01-15",
            "2020-01-19",
            IntervalType.DAY,
            [EventsNode(event="$pageview"), EventsNode(event="$pageleave")],
            TrendsFilter(formulas=["A+2*B"]),
            compare_filters=CompareFilter(compare=True, compare_to="-1w"),
        )

        # one for current, one for previous
        self.assertEqual(2, len(response.results))

        # current
        self.assertEqual("current", response.results[0]["compare_label"])
        self.assertEqual(6, response.results[0]["count"])
        self.assertEqual([2, 2, 1, 0, 1], response.results[0]["data"])

        # previous
        self.assertEqual("previous", response.results[1]["compare_label"])
        self.assertEqual(9, response.results[1]["count"])
        self.assertEqual([0, 1, 0, 3, 5], response.results[1]["data"])

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
            ),
            compare_filters=CompareFilter(compare=True),
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

    def test_formula_with_compare_to_total_value(self):
        self._create_test_events()

        response = self._run_trends_query(
            "2020-01-15",
            "2020-01-19",
            IntervalType.DAY,
            [EventsNode(event="$pageview"), EventsNode(event="$pageleave")],
            TrendsFilter(
                formula="A+2*B",
                display=ChartDisplayType.BOLD_NUMBER,  # total value
            ),
            compare_filters=CompareFilter(compare=True, compare_to="-1w"),
        )

        # one for current, one for previous
        self.assertEqual(2, len(response.results))

        # current
        self.assertEqual("current", response.results[0]["compare_label"])
        self.assertEqual(6, response.results[0]["aggregated_value"])

        # previous
        self.assertEqual("previous", response.results[1]["compare_label"])
        self.assertEqual(9, response.results[1]["aggregated_value"])

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
            TrendsFilter(formula="A+2*B"),
            BreakdownFilter(breakdown_type=BreakdownType.EVENT, breakdown="$browser"),
            CompareFilter(compare=True),
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

    def test_formula_with_breakdown_and_compare_to(self):
        self._create_test_events()

        response = self._run_trends_query(
            "2020-01-15",
            "2020-01-19",
            IntervalType.DAY,
            [EventsNode(event="$pageview"), EventsNode(event="$pageleave")],
            TrendsFilter(formula="A+2*B"),
            BreakdownFilter(breakdown_type=BreakdownType.EVENT, breakdown="$browser"),
            CompareFilter(compare=True, compare_to="-3d"),
        )

        # chrome, ff, edge and safari for previous, and chrome and safari for current
        assert len(response.results) == 6

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
        assert response.results[2]["count"] == 7
        assert response.results[2]["data"] == [3, 3, 0, 1, 0]

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
            ),
            BreakdownFilter(breakdown_type=BreakdownType.EVENT, breakdown="$browser"),
            CompareFilter(compare=True),
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

    def test_trends_with_cohort_filter(self):
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
            name="cohort p1",
        )
        cohort.calculate_people_ch(pending_version=0)

        response = self._run_trends_query(
            "2020-01-09",
            "2020-01-20",
            IntervalType.DAY,
            [EventsNode(event="$pageview", properties=[{"key": "id", "value": cohort.pk, "type": "cohort"}])],
        )

        assert len(response.results) == 1
        assert response.results[0]["count"] == 6
        assert response.results[0]["data"] == [0, 0, 1, 1, 1, 0, 1, 0, 1, 0, 1, 0]

    def test_trends_with_cohort_filter_other_team_in_project(self):
        self._create_test_events()
        other_team_in_project = Team.objects.create(organization=self.organization, project=self.project)
        cohort = Cohort.objects.create(
            team=other_team_in_project,  # Not self.team!
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
            name="cohort p1 other team",
        )
        cohort.calculate_people_ch(pending_version=0)

        response = self._run_trends_query(
            "2020-01-09",
            "2020-01-20",
            IntervalType.DAY,
            [EventsNode(event="$pageview", properties=[{"key": "id", "value": cohort.pk, "type": "cohort"}])],
        )

        assert len(response.results) == 1
        assert response.results[0]["count"] == 6
        assert response.results[0]["data"] == [0, 0, 1, 1, 1, 0, 1, 0, 1, 0, 1, 0]

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

        response.results.sort(key=lambda r: r["count"])

        assert response.results[0]["label"] == "Formula (A+B)"
        assert response.results[0]["breakdown_value"] == cohort1.pk
        assert response.results[0]["count"] == 9
        assert response.results[0]["data"] == [0, 0, 2, 2, 2, 0, 1, 0, 1, 0, 1, 0]

        assert response.results[1]["label"] == "Formula (A+B)"
        assert response.results[1]["breakdown_value"] == "all"
        assert response.results[1]["count"] == 16
        assert response.results[1]["data"] == [1, 0, 2, 4, 4, 0, 2, 1, 1, 0, 1, 0]

        # action needs to be unset to display custom label
        assert response.results[0]["action"] is None

    def test_multiple_formula_with_multi_cohort_all_breakdown(self):
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
            TrendsFilter(
                formulaNodes=[
                    TrendsFormulaNode(formula="A+B", custom_name="Formula (A+B)"),
                    TrendsFormulaNode(formula="B+1", custom_name="Formula (B+1)"),
                ]
            ),
            BreakdownFilter(breakdown_type=BreakdownType.COHORT, breakdown=[cohort1.pk, "all"]),
        )

        assert len(response.results) == 4

        response.results.sort(key=lambda r: r["count"])

        assert response.results[0]["label"] == "Formula (A+B)"
        assert response.results[0]["breakdown_value"] == cohort1.pk
        assert response.results[0]["count"] == 9
        assert response.results[0]["data"] == [0, 0, 2, 2, 2, 0, 1, 0, 1, 0, 1, 0]

        assert response.results[1]["label"] == "Formula (B+1)"
        assert response.results[1]["breakdown_value"] == cohort1.pk
        assert response.results[1]["count"] == 15
        assert response.results[1]["data"] == [1, 1, 2, 2, 2, 1, 1, 1, 1, 1, 1, 1]

        assert response.results[2]["label"] == "Formula (A+B)"
        assert response.results[2]["breakdown_value"] == "all"
        assert response.results[2]["count"] == 16
        assert response.results[2]["data"] == [1, 0, 2, 4, 4, 0, 2, 1, 1, 0, 1, 0]

        assert response.results[3]["label"] == "Formula (B+1)"
        assert response.results[3]["breakdown_value"] == "all"
        assert response.results[3]["count"] == 18
        assert response.results[3]["data"] == [1, 1, 2, 2, 4, 1, 1, 2, 1, 1, 1, 1]

        # action needs to be unset to display custom label
        assert response.results[0]["action"] is None

    def test_formula_with_multi_cohort_all_breakdown_with_compare(self):
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
            "2020-01-15",
            "2020-01-20",
            IntervalType.DAY,
            [EventsNode(event="$pageview"), EventsNode(event="$pageleave")],
            TrendsFilter(formula="A+B"),
            BreakdownFilter(breakdown_type=BreakdownType.COHORT, breakdown=[cohort1.pk, "all"]),
            compare_filters=CompareFilter(compare=True),
        )

        assert len(response.results) == 4

        response.results.sort(key=lambda r: r["count"])

        self.assertEqual(True, response.results[0]["compare"])
        self.assertEqual(True, response.results[1]["compare"])
        self.assertEqual(True, response.results[2]["compare"])
        self.assertEqual(True, response.results[3]["compare"])

        self.assertEqual("current", response.results[0]["compare_label"])
        self.assertEqual("current", response.results[1]["compare_label"])
        self.assertEqual("previous", response.results[2]["compare_label"])
        self.assertEqual("previous", response.results[3]["compare_label"])

        assert response.results[0]["label"] == "Formula (A+B)"
        assert response.results[0]["breakdown_value"] == cohort1.pk
        assert response.results[0]["count"] == 3
        assert response.results[0]["data"] == [1.0, 0.0, 1.0, 0.0, 1.0, 0.0]

        assert response.results[1]["label"] == "Formula (A+B)"
        assert response.results[1]["breakdown_value"] == "all"
        assert response.results[1]["count"] == 5
        assert response.results[1]["data"] == [2.0, 1.0, 1.0, 0.0, 1.0, 0.0]

        assert response.results[2]["label"] == "Formula (A+B)"
        assert response.results[2]["breakdown_value"] == cohort1.pk
        assert response.results[2]["count"] == 6
        assert response.results[2]["data"] == [0.0, 0.0, 2.0, 2.0, 2.0, 0.0]

        assert response.results[3]["label"] == "Formula (A+B)"
        assert response.results[3]["breakdown_value"] == "all"
        assert response.results[3]["count"] == 11
        assert response.results[3]["data"] == [1.0, 0.0, 2.0, 4.0, 4.0, 0.0]

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

        self.assertEqual(mock_sync_execute.call_count, 2)
        for mock_execute_call_args in mock_sync_execute.call_args_list:
            self.assertIn(f" max_execution_time={HOGQL_INCREASED_MAX_EXECUTION_TIME},", mock_execute_call_args[0][0])

    def test_trends_compare(self):
        self._create_test_events()

        response = self._run_trends_query(
            "2020-01-15",
            "2020-01-19",
            IntervalType.DAY,
            [EventsNode(event="$pageview")],
            TrendsFilter(),
            compare_filters=CompareFilter(compare=True),
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

        self.assertEqual(
            ["15-Jan-2020", "16-Jan-2020", "17-Jan-2020", "18-Jan-2020", "19-Jan-2020"],
            response.results[0]["labels"],
        )

        self.assertEqual(
            ["10-Jan-2020", "11-Jan-2020", "12-Jan-2020", "13-Jan-2020", "14-Jan-2020"],
            response.results[1]["labels"],
        )

    def test_trends_compare_weeks(self):
        self._create_test_events()

        with freeze_time("2020-01-24"):
            response = self._run_trends_query(
                "-7d",
                None,
                IntervalType.DAY,
                [EventsNode(event="$pageview")],
                TrendsFilter(),
                compare_filters=CompareFilter(compare=True),
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
                [
                    "17-Jan-2020",
                    "18-Jan-2020",
                    "19-Jan-2020",
                    "20-Jan-2020",
                    "21-Jan-2020",
                    "22-Jan-2020",
                    "23-Jan-2020",
                    "24-Jan-2020",
                ],
                response.results[0]["labels"],
            )

            self.assertEqual(
                [
                    "10-Jan-2020",
                    "11-Jan-2020",
                    "12-Jan-2020",
                    "13-Jan-2020",
                    "14-Jan-2020",
                    "15-Jan-2020",
                    "16-Jan-2020",
                    "17-Jan-2020",
                ],
                response.results[1]["labels"],
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

    def test_trends_breakdowns_session_duration_histogram(self):
        self._create_test_events()

        response = self._run_trends_query(
            "2020-01-09",
            "2020-01-20",
            IntervalType.DAY,
            [EventsNode(event="$pageview", math=PropertyMathType.AVG, math_property="$session_duration")],
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
            TrendsFilter(),
            BreakdownFilter(breakdown_type=BreakdownType.EVENT, breakdown="$browser"),
            CompareFilter(compare=True),
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

    def test_trends_aggregation_wau_long_interval(self):
        """Test weekly active users with a week interval.

        When using WEEKLY_ACTIVE math with an interval of WEEK or greater,
        we should treat it like a normal unique users calculation (DAU) rather than
        the sliding window calculation used for daily intervals.
        """
        self._create_test_events()

        # First run the regular trends query to verify it works
        trends_query = self._create_trends_query(
            "2020-01-09",
            "2020-01-20",
            IntervalType.WEEK,
            [EventsNode(event="$pageview", math=BaseMathType.WEEKLY_ACTIVE)],
        )

        # Create a query runner and calculate the trends
        query_runner = TrendsQueryRunner(team=self.team, query=trends_query)
        response = query_runner.calculate()

        assert response.results[0]["data"] == [2, 4, 1]

        # Now run actors queries for each date range and verify the counts
        options = query_runner.to_actors_query_options()
        assert options.day is not None and len(options.day) == 3

        # Expected actor IDs for each week - based on our test event data
        expected_actors_by_week = [
            ["p1", "p2"],  # Week 1: Jan 9-15
            ["p1", "p2", "p3", "p4"],  # Week 2: Jan 16-22
            ["p1"],  # Week 3: Jan 23-29
        ]

        for i, day in enumerate(options.day):
            actors_query = query_runner.to_actors_query(time_frame=day.value, series_index=0)
            result = execute_hogql_query(query=actors_query, team=self.team)

            actual_actor_ids = [row[2][0] for row in result.results]
            expected_actor_ids = expected_actors_by_week[i]

            self.assertCountEqual(actual_actor_ids, expected_actor_ids)

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

    def test_trends_aggregation_mau_long_interval(self):
        self._create_test_events()

        response = self._run_trends_query(
            "2019-12-31",
            "2020-02-01",
            IntervalType.MONTH,
            [EventsNode(event="$pageview", math=BaseMathType.MONTHLY_ACTIVE)],
            None,
            None,
        )

        assert response.results[0]["data"] == [0, 4, 0]

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

    def test_trends_display_aggregate_interval(self):
        self._create_test_events()

        response = self._run_trends_query(
            "2020-01-09",
            "2020-01-20",
            IntervalType.MONTH,  # E.g. UI sets interval to month, but we need the total value across all days
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

        # Now hide other aggregation
        response = self._run_trends_query(
            "2020-01-09",
            "2020-01-20",
            IntervalType.DAY,
            [EventsNode(event="$pageview")],
            TrendsFilter(display=ChartDisplayType.ACTIONS_LINE_GRAPH),
            BreakdownFilter(
                breakdown="breakdown_value",
                breakdown_type=BreakdownType.EVENT,
                breakdown_limit=10,
                breakdown_hide_other_aggregation=True,
            ),
        )
        self.assertEqual(len(response.results), 10)

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

        # Test actions table - it shows total values

        response = self._run_trends_query(
            "2020-01-09",
            "2020-01-20",
            IntervalType.DAY,
            [EventsNode(event="$pageview")],
            TrendsFilter(display=ChartDisplayType.ACTIONS_TABLE),
            BreakdownFilter(breakdown="breakdown_value", breakdown_type=BreakdownType.EVENT, breakdown_limit=10),
        )
        self.assertEqual(len(response.results), 11)

        # Now hide other aggregation
        response = self._run_trends_query(
            "2020-01-09",
            "2020-01-20",
            IntervalType.DAY,
            [EventsNode(event="$pageview")],
            TrendsFilter(display=ChartDisplayType.ACTIONS_TABLE),
            BreakdownFilter(
                breakdown="breakdown_value",
                breakdown_type=BreakdownType.EVENT,
                breakdown_limit=10,
                breakdown_hide_other_aggregation=True,
            ),
        )
        self.assertEqual(len(response.results), 10)

    def test_multiple_breakdowns_values_limit(self):
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
            BreakdownFilter(breakdowns=[Breakdown(property="breakdown_value", type=MultipleBreakdownType.EVENT)]),
        )

        self.assertEqual(len(response.results), 26)

        response = self._run_trends_query(
            "2020-01-09",
            "2020-01-20",
            IntervalType.DAY,
            [EventsNode(event="$pageview")],
            TrendsFilter(display=ChartDisplayType.ACTIONS_LINE_GRAPH),
            BreakdownFilter(
                breakdowns=[Breakdown(property="breakdown_value", type=MultipleBreakdownType.EVENT)], breakdown_limit=10
            ),
        )
        self.assertEqual(len(response.results), 11)

        # Now hide other aggregation
        response = self._run_trends_query(
            "2020-01-09",
            "2020-01-20",
            IntervalType.DAY,
            [EventsNode(event="$pageview")],
            TrendsFilter(display=ChartDisplayType.ACTIONS_LINE_GRAPH),
            BreakdownFilter(
                breakdowns=[Breakdown(property="breakdown_value", type=MultipleBreakdownType.EVENT)],
                breakdown_limit=10,
                breakdown_hide_other_aggregation=True,
            ),
        )
        self.assertEqual(len(response.results), 10)

        response = self._run_trends_query(
            "2020-01-09",
            "2020-01-20",
            IntervalType.DAY,
            [EventsNode(event="$pageview")],
            TrendsFilter(display=ChartDisplayType.ACTIONS_LINE_GRAPH),
            BreakdownFilter(breakdowns=[Breakdown(property="breakdown_value", type=MultipleBreakdownType.EVENT)]),
            limit_context=LimitContext.EXPORT,
        )
        self.assertEqual(len(response.results), 30)

        # Test actions table - it shows total values

        response = self._run_trends_query(
            "2020-01-09",
            "2020-01-20",
            IntervalType.DAY,
            [EventsNode(event="$pageview")],
            TrendsFilter(display=ChartDisplayType.ACTIONS_TABLE),
            BreakdownFilter(
                breakdowns=[Breakdown(property="breakdown_value", type=MultipleBreakdownType.EVENT)], breakdown_limit=10
            ),
        )
        self.assertEqual(len(response.results), 11)

        # Now hide other aggregation
        response = self._run_trends_query(
            "2020-01-09",
            "2020-01-20",
            IntervalType.DAY,
            [EventsNode(event="$pageview")],
            TrendsFilter(display=ChartDisplayType.ACTIONS_TABLE),
            BreakdownFilter(
                breakdowns=[Breakdown(property="breakdown_value", type=MultipleBreakdownType.EVENT)],
                breakdown_limit=10,
                breakdown_hide_other_aggregation=True,
            ),
        )
        self.assertEqual(len(response.results), 10)

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
            TrendsFilter(display=ChartDisplayType.BOLD_NUMBER),
            None,
            compare_filters=CompareFilter(compare=True),
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
            BreakdownFilter(breakdown_type=None, breakdown=None),
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
            TrendsFilter(),
            None,
            CompareFilter(compare=True),
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

    def test_to_actors_query_options_compare_to(self):
        self._create_test_events()
        flush_persons_and_events()

        runner = self._create_query_runner(
            "2020-01-09",
            "2020-01-20",
            IntervalType.DAY,
            [EventsNode(event="$pageview")],
            TrendsFilter(),
            None,
            compare_filters=CompareFilter(compare=True, compare_to="-1w"),
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

        # single breakdown
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
            BreakdownItem(label="Chrome", value="Chrome"),
            BreakdownItem(label="Firefox", value="Firefox"),
            BreakdownItem(label="Edge", value="Edge"),
            BreakdownItem(label=BREAKDOWN_OTHER_DISPLAY, value="$$_posthog_breakdown_other_$$"),
        ]

        # multiple breakdowns
        runner = self._create_query_runner(
            "2020-01-09",
            "2020-01-20",
            IntervalType.DAY,
            [EventsNode(event="$pageview")],
            None,
            BreakdownFilter(breakdowns=[Breakdown(type=BreakdownType.EVENT, property="$browser")], breakdown_limit=3),
        )

        response = runner.to_actors_query_options()
        assert response.day is not None
        assert response.series == [InsightActorsQuerySeries(label="$pageview", value=0)]
        assert response.breakdowns is not None
        assert response.breakdowns[0].values == [
            BreakdownItem(label="Chrome", value="Chrome"),
            BreakdownItem(label="Firefox", value="Firefox"),
            BreakdownItem(label="Edge", value="Edge"),
            BreakdownItem(label=BREAKDOWN_OTHER_DISPLAY, value="$$_posthog_breakdown_other_$$"),
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

        runner = self._create_query_runner(
            "2020-01-09",
            "2020-01-20",
            IntervalType.DAY,
            [EventsNode(event="$pageview")],
            None,
            BreakdownFilter(breakdowns=[Breakdown(type=BreakdownType.EVENT, property="bool_field")]),
        )

        response = runner.to_actors_query_options()

        assert response.series == [InsightActorsQuerySeries(label="$pageview", value=0)]

        assert response.breakdowns is not None
        assert response.breakdowns[0].values == [
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
            BreakdownItem(label="[10,17.5]", value="[10,17.5]"),
            BreakdownItem(label="[17.5,25]", value="[17.5,25]"),
            BreakdownItem(label="[25,32.5]", value="[25,32.5]"),
            BreakdownItem(label="[32.5,40.01]", value="[32.5,40.01]"),
            BreakdownItem(label='["",""]', value='["",""]'),
        ]

        runner = self._create_query_runner(
            "2020-01-09",
            "2020-01-20",
            IntervalType.DAY,
            [EventsNode(event="$pageview")],
            None,
            BreakdownFilter(breakdowns=[Breakdown(type=BreakdownType.EVENT, property="prop", histogram_bin_count=4)]),
        )
        response = runner.to_actors_query_options()

        assert response.series == [InsightActorsQuerySeries(label="$pageview", value=0)]
        assert response.breakdowns is not None
        assert response.breakdowns[0].values == [
            BreakdownItem(label="[10,17.5]", value="[10,17.5]"),
            BreakdownItem(label="[17.5,25]", value="[17.5,25]"),
            BreakdownItem(label="[25,32.5]", value="[25,32.5]"),
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
            BreakdownItem(label="Edge", value="Edge"),
            BreakdownItem(label="Safari", value="Safari"),
        ]

        runner = self._create_query_runner(
            "2020-01-09",
            "2020-01-20",
            IntervalType.DAY,
            [EventsNode(event="$pageview")],
            None,
            BreakdownFilter(breakdowns=[Breakdown(type=BreakdownType.HOGQL, property="properties.$browser")]),
        )

        response = runner.to_actors_query_options()

        assert response.series == [InsightActorsQuerySeries(label="$pageview", value=0)]
        assert response.breakdowns is not None
        assert response.breakdowns[0].values == [
            BreakdownItem(label="Chrome", value="Chrome"),
            BreakdownItem(label="Firefox", value="Firefox"),
            BreakdownItem(label="Edge", value="Edge"),
            BreakdownItem(label="Safari", value="Safari"),
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
            BreakdownItem(label="Edge", value="Edge"),
            BreakdownItem(label="Safari", value="Safari"),
        ]

        runner = self._create_query_runner(
            "2020-01-09",
            "2020-01-20",
            IntervalType.DAY,
            [EventsNode(event="$pageview")],
            TrendsFilter(display=ChartDisplayType.ACTIONS_BAR_VALUE),
            BreakdownFilter(breakdowns=[Breakdown(type=BreakdownType.EVENT, property="$browser")]),
        )

        response = runner.to_actors_query_options()

        assert response.day is None
        assert response.series == [InsightActorsQuerySeries(label="$pageview", value=0)]
        assert response.breakdowns is not None
        assert response.breakdowns[0].values == [
            BreakdownItem(label="Chrome", value="Chrome"),
            BreakdownItem(label="Firefox", value="Firefox"),
            BreakdownItem(label="Edge", value="Edge"),
            BreakdownItem(label="Safari", value="Safari"),
        ]

    def test_to_actors_query_options_multiple_breakdowns(self):
        self._create_test_events()
        flush_persons_and_events()

        runner = self._create_query_runner(
            "2020-01-09",
            "2020-01-20",
            IntervalType.DAY,
            [EventsNode(event="$pageview")],
            TrendsFilter(display=ChartDisplayType.ACTIONS_BAR_VALUE),
            BreakdownFilter(
                breakdowns=[
                    Breakdown(type=BreakdownType.EVENT, property="$browser"),
                    Breakdown(type=BreakdownType.EVENT, property="prop", histogram_bin_count=2),
                    Breakdown(type=BreakdownType.EVENT, property="bool_field"),
                ]
            ),
        )

        response = runner.to_actors_query_options()

        assert response.day is None
        assert response.series == [InsightActorsQuerySeries(label="$pageview", value=0)]
        assert response.breakdowns is not None
        assert response.breakdowns[0].values == [
            BreakdownItem(label="Chrome", value="Chrome"),
            BreakdownItem(label="Firefox", value="Firefox"),
            BreakdownItem(label="Edge", value="Edge"),
            BreakdownItem(label="Safari", value="Safari"),
        ]
        assert response.breakdowns[1].values == [
            BreakdownItem(label="[10,25]", value="[10,25]"),
            BreakdownItem(label="[25,40.01]", value="[25,40.01]"),
            BreakdownItem(label='["",""]', value='["",""]'),
        ]
        assert response.breakdowns[2].values == [
            BreakdownItem(label="true", value="true"),
            BreakdownItem(label="false", value="false"),
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
        assert response.select_from.table.where.exprs[0].right.value == datetime(  # type: ignore
            2020, 1, 9, 12, 37, 42, tzinfo=zoneinfo.ZoneInfo(key="UTC")
        )
        assert response.select_from.table.where.exprs[1].right.value == datetime(  # type: ignore
            2020, 1, 10, 0, 0, tzinfo=zoneinfo.ZoneInfo(key="UTC")
        )

        # date_from ends at specific time
        response = runner.to_actors_query(
            time_frame="2020-01-20", series_index=0, breakdown_value=None, compare_value=None
        )
        assert response.select_from.table.where.exprs[0].right.value == datetime(  # type: ignore
            2020, 1, 20, 0, 0, tzinfo=zoneinfo.ZoneInfo(key="UTC")
        )
        assert response.select_from.table.where.exprs[1].right.value == datetime(  # type: ignore
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

    def test_trends_multiple_event_breakdowns(self):
        self._create_test_events()
        flush_persons_and_events()

        # two breakdowns
        response = self._run_trends_query(
            "2020-01-09",
            "2020-01-20",
            IntervalType.DAY,
            [EventsNode(event="$pageview")],
            None,
            BreakdownFilter(
                breakdowns=[Breakdown(type="event", property="$browser"), Breakdown(type="event", property="prop")]
            ),
        )

        breakdown_labels = [result["breakdown_value"] for result in response.results]

        assert len(response.results) == 4
        assert len(breakdown_labels) == 4
        assert breakdown_labels == [["Chrome", "10"], ["Firefox", "20"], ["Edge", "30"], ["Safari", "40"]]
        assert response.results[0]["label"] == "Chrome::10"
        assert response.results[1]["label"] == "Firefox::20"
        assert response.results[2]["label"] == "Edge::30"
        assert response.results[3]["label"] == "Safari::40"
        assert response.results[0]["count"] == 6
        assert response.results[1]["count"] == 2
        assert response.results[2]["count"] == 1
        assert response.results[3]["count"] == 1

        # three breakdowns
        response = self._run_trends_query(
            "2020-01-09",
            "2020-01-20",
            IntervalType.DAY,
            [EventsNode(event="$pageview")],
            None,
            BreakdownFilter(
                breakdowns=[
                    Breakdown(type="event", property="$browser"),
                    Breakdown(type="event", property="prop"),
                    Breakdown(type="event", property="bool_field"),
                ]
            ),
        )

        breakdown_labels = [result["breakdown_value"] for result in response.results]

        assert len(response.results) == 4
        assert len(breakdown_labels) == 4
        assert breakdown_labels == [
            ["Chrome", "10", "true"],
            ["Firefox", "20", "false"],
            ["Edge", "30", "true"],
            ["Safari", "40", "false"],
        ]
        assert response.results[0]["label"] == "Chrome::10::true"
        assert response.results[1]["label"] == "Firefox::20::false"
        assert response.results[2]["label"] == "Edge::30::true"
        assert response.results[3]["label"] == "Safari::40::false"
        assert response.results[0]["count"] == 6
        assert response.results[1]["count"] == 2
        assert response.results[2]["count"] == 1
        assert response.results[3]["count"] == 1

    def test_trends_multiple_breakdowns_have_max_limit(self):
        # max three breakdowns are allowed
        with pytest.raises(ValidationError, match=".*at most 3.*"):
            BreakdownFilter(
                breakdowns=[
                    Breakdown(type="event", property="$browser"),
                    Breakdown(type="event", property="prop"),
                    Breakdown(type="event", property="bool_field"),
                    Breakdown(type="event", property="bool_field"),
                ]
            )

    def test_trends_event_and_person_breakdowns(self):
        self._create_test_events()
        flush_persons_and_events()

        # two breakdowns
        response = self._run_trends_query(
            "2020-01-09",
            "2020-01-20",
            IntervalType.DAY,
            [EventsNode(event="$pageview")],
            None,
            BreakdownFilter(
                breakdowns=[Breakdown(type="event", property="$browser"), Breakdown(type="person", property="name")]
            ),
        )

        breakdown_labels = [result["breakdown_value"] for result in response.results]

        assert len(response.results) == 4
        assert len(breakdown_labels) == 4
        assert breakdown_labels == [["Chrome", "p1"], ["Firefox", "p2"], ["Edge", "p3"], ["Safari", "p4"]]
        assert response.results[0]["label"] == "Chrome::p1"
        assert response.results[1]["label"] == "Firefox::p2"
        assert response.results[2]["label"] == "Edge::p3"
        assert response.results[3]["label"] == "Safari::p4"
        assert response.results[0]["count"] == 6
        assert response.results[1]["count"] == 2
        assert response.results[2]["count"] == 1
        assert response.results[3]["count"] == 1

    def test_trends_event_person_group_breakdowns(self):
        self._create_test_groups()
        self._create_test_events_for_groups()
        flush_persons_and_events()

        # two breakdowns
        response = self._run_trends_query(
            "2020-01-09",
            "2020-01-20",
            IntervalType.DAY,
            [EventsNode(event="$pageview")],
            None,
            BreakdownFilter(
                breakdowns=[
                    Breakdown(type="event", property="$browser"),
                    Breakdown(type="group", group_type_index=0, property="industry"),
                ]
            ),
        )

        breakdown_labels = [result["breakdown_value"] for result in response.results]

        assert len(response.results) == 4
        assert len(breakdown_labels) == 4
        assert breakdown_labels == [
            ["Chrome", "finance"],
            ["Firefox", "technology"],
            ["Edge", "finance"],
            ["Safari", "$$_posthog_breakdown_null_$$"],
        ]
        assert response.results[0]["label"] == "Chrome::finance"
        assert response.results[1]["label"] == "Firefox::technology"
        assert response.results[2]["label"] == "Edge::finance"
        assert response.results[3]["label"] == "Safari::$$_posthog_breakdown_null_$$"
        assert response.results[0]["count"] == 6
        assert response.results[1]["count"] == 2
        assert response.results[2]["count"] == 1
        assert response.results[3]["count"] == 1

    def test_trends_event_with_two_group_breakdowns(self):
        self._create_test_groups()
        self._create_test_events_for_groups()
        flush_persons_and_events()

        # two breakdowns
        response = self._run_trends_query(
            "2020-01-09",
            "2020-01-20",
            IntervalType.DAY,
            [EventsNode(event="$pageview")],
            None,
            BreakdownFilter(
                breakdowns=[
                    Breakdown(type="group", group_type_index=1, property="employee_count"),
                    Breakdown(type="group", group_type_index=0, property="industry"),
                ]
            ),
        )

        breakdown_labels = [result["breakdown_value"] for result in response.results]

        assert len(response.results) == 4
        assert len(breakdown_labels) == 4
        assert breakdown_labels == [
            ["50-249", "finance"],
            ["$$_posthog_breakdown_null_$$", "finance"],
            ["$$_posthog_breakdown_null_$$", "technology"],
            ["$$_posthog_breakdown_null_$$", "$$_posthog_breakdown_null_$$"],
        ]
        assert response.results[0]["label"] == "50-249::finance"
        assert response.results[1]["label"] == "$$_posthog_breakdown_null_$$::finance"
        assert response.results[2]["label"] == "$$_posthog_breakdown_null_$$::technology"
        assert response.results[3]["label"] == "$$_posthog_breakdown_null_$$::$$_posthog_breakdown_null_$$"
        assert response.results[0]["count"] == 1
        assert response.results[1]["count"] == 6
        assert response.results[2]["count"] == 2
        assert response.results[3]["count"] == 1

    def test_trends_event_with_three_group_breakdowns(self):
        self._create_test_groups()
        self._create_test_events_for_groups()
        flush_persons_and_events()

        # two breakdowns
        response = self._run_trends_query(
            "2020-01-09",
            "2020-01-20",
            IntervalType.DAY,
            [EventsNode(event="$pageview")],
            None,
            BreakdownFilter(
                breakdowns=[
                    Breakdown(type="group", group_type_index=0, property="industry"),
                    Breakdown(type="group", group_type_index=0, property="name"),
                    Breakdown(type="group", group_type_index=1, property="employee_count"),
                ]
            ),
        )

        breakdown_labels = [result["breakdown_value"] for result in response.results]

        assert len(response.results) == 4
        assert len(breakdown_labels) == 4
        assert breakdown_labels == [
            ["finance", "Hedgebank", "50-249"],
            ["finance", "Hedgeflix", "$$_posthog_breakdown_null_$$"],
            ["technology", "Hedgebox", "$$_posthog_breakdown_null_$$"],
            ["$$_posthog_breakdown_null_$$", "$$_posthog_breakdown_null_$$", "$$_posthog_breakdown_null_$$"],
        ]
        assert response.results[0]["label"] == "finance::Hedgebank::50-249"
        assert response.results[1]["label"] == "finance::Hedgeflix::$$_posthog_breakdown_null_$$"
        assert response.results[2]["label"] == "technology::Hedgebox::$$_posthog_breakdown_null_$$"
        assert (
            response.results[3]["label"]
            == "$$_posthog_breakdown_null_$$::$$_posthog_breakdown_null_$$::$$_posthog_breakdown_null_$$"
        )
        assert response.results[0]["count"] == 1
        assert response.results[1]["count"] == 6
        assert response.results[2]["count"] == 2
        assert response.results[3]["count"] == 1

    def test_trends_event_metadata_filter_group(self):
        self._create_test_groups()
        self._create_test_events_for_groups()
        flush_persons_and_events()

        # Equals
        response = self._run_trends_query(
            "2020-01-09",
            "2020-01-20",
            IntervalType.DAY,
            [
                EventsNode(
                    event="$pageview",
                    properties=[
                        EventMetadataPropertyFilter(
                            type="event_metadata", operator="exact", key="$group_0", value="org:5"
                        )
                    ],
                )
            ],
            None,
        )
        assert response.results[0]["count"] == 6

        # Not Equals
        response = self._run_trends_query(
            "2020-01-09",
            "2020-01-20",
            IntervalType.DAY,
            [
                EventsNode(
                    event="$pageview",
                    properties=[
                        EventMetadataPropertyFilter(
                            type="event_metadata", operator="is_not", key="$group_0", value="org:5"
                        )
                    ],
                )
            ],
            None,
        )

        assert response.results[0]["count"] == 4

    def test_trends_event_multiple_breakdowns_normalizes_url(self):
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
                    properties={"$url": "https://posthog.com/?"},
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
                    properties={"$url": "https://posthog.com"},
                ),
                SeriesTestData(
                    distinct_id="p3",
                    events=[
                        Series(event="$pageview", timestamps=["2020-01-12T12:00:00Z"]),
                        Series(event="$pageleave", timestamps=["2020-01-13T12:00:00Z"]),
                    ],
                    properties={"$url": "https://posthog.com/foo/bar/#"},
                ),
                SeriesTestData(
                    distinct_id="p4",
                    events=[
                        Series(event="$pageview", timestamps=["2020-01-15T12:00:00Z"]),
                        Series(event="$pageleave", timestamps=["2020-01-16T12:00:00Z"]),
                    ],
                    properties={"$url": "https://posthog.com/foo/bar/"},
                ),
            ]
        )
        flush_persons_and_events()

        response = self._run_trends_query(
            "2020-01-09",
            "2020-01-20",
            IntervalType.DAY,
            [EventsNode(event="$pageview")],
            None,
            BreakdownFilter(
                breakdowns=[
                    Breakdown(property="$url", normalize_url=True),
                ]
            ),
        )
        breakdown_labels = [result["breakdown_value"] for result in response.results]

        assert len(response.results) == 2
        assert len(breakdown_labels) == 2
        assert breakdown_labels == [
            ["https://posthog.com"],
            ["https://posthog.com/foo/bar"],
        ]

        for normalize_url in (False, None):
            response = self._run_trends_query(
                "2020-01-09",
                "2020-01-20",
                IntervalType.DAY,
                [EventsNode(event="$pageview")],
                None,
                BreakdownFilter(
                    breakdowns=[
                        Breakdown(property="$url", normalize_url=normalize_url),
                    ]
                ),
            )
            breakdown_labels = [result["breakdown_value"] for result in response.results]
            assert len(response.results) == 4
            assert len(breakdown_labels) == 4

    def test_trends_event_multiple_numeric_breakdowns(self):
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
                    properties={"$bin": 4},
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
                    properties={"$bin": 8},
                ),
                SeriesTestData(
                    distinct_id="p3",
                    events=[
                        Series(event="$pageview", timestamps=["2020-01-12T12:00:00Z"]),
                        Series(event="$pageleave", timestamps=["2020-01-13T12:00:00Z"]),
                    ],
                    properties={"$bin": 16},
                ),
                SeriesTestData(
                    distinct_id="p4",
                    events=[
                        Series(event="$pageview", timestamps=["2020-01-15T12:00:00Z"]),
                        Series(event="$pageleave", timestamps=["2020-01-16T12:00:00Z"]),
                    ],
                    properties={"$bin": 32},
                ),
                SeriesTestData(
                    distinct_id="p5",
                    events=[
                        Series(event="$pageview", timestamps=["2020-01-15T12:00:00Z"]),
                        Series(event="$pageleave", timestamps=["2020-01-16T12:00:00Z"]),
                    ],
                    properties={"$bin": 64},
                ),
                SeriesTestData(
                    distinct_id="p6",
                    events=[
                        Series(event="$pageview", timestamps=["2020-01-15T12:00:00Z"]),
                        Series(event="$pageleave", timestamps=["2020-01-16T11:00:00Z"]),
                        Series(event="$pageleave", timestamps=["2020-01-16T12:00:00Z"]),
                    ],
                    properties={"$bin": 128},
                ),
            ]
        )
        flush_persons_and_events()

        response = self._run_trends_query(
            "2020-01-09",
            "2020-01-20",
            IntervalType.DAY,
            [EventsNode(event="$pageview")],
            None,
            BreakdownFilter(
                breakdowns=[
                    Breakdown(property="$bin"),
                ],
            ),
        )
        breakdown_labels = [result["breakdown_value"] for result in response.results]

        assert len(response.results) == 6
        assert len(breakdown_labels) == 6
        assert breakdown_labels == [["4"], ["8"], ["128"], ["16"], ["32"], ["64"]]

    def test_trends_event_multiple_numeric_breakdowns_into_bins(self):
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
                    properties={"$bin": 4},
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
                    properties={"$bin": 8},
                ),
                SeriesTestData(
                    distinct_id="p3",
                    events=[
                        Series(event="$pageview", timestamps=["2020-01-12T12:00:00Z"]),
                        Series(event="$pageleave", timestamps=["2020-01-13T12:00:00Z"]),
                    ],
                    properties={"$bin": 16},
                ),
                SeriesTestData(
                    distinct_id="p4",
                    events=[
                        Series(event="$pageview", timestamps=["2020-01-15T12:00:00Z"]),
                        Series(event="$pageleave", timestamps=["2020-01-16T12:00:00Z"]),
                    ],
                    properties={"$bin": 32},
                ),
                SeriesTestData(
                    distinct_id="p5",
                    events=[
                        Series(event="$pageview", timestamps=["2020-01-15T12:00:00Z"]),
                        Series(event="$pageleave", timestamps=["2020-01-16T12:00:00Z"]),
                    ],
                    properties={"$bin": 64},
                ),
                SeriesTestData(
                    distinct_id="p6",
                    events=[
                        Series(event="$pageview", timestamps=["2020-01-15T12:00:00Z"]),
                        Series(event="$pageleave", timestamps=["2020-01-16T11:00:00Z"]),
                        Series(event="$pageleave", timestamps=["2020-01-16T12:00:00Z"]),
                    ],
                    properties={"$bin": 128},
                ),
                SeriesTestData(
                    distinct_id="p7",
                    events=[
                        Series(event="$pageview", timestamps=["2020-01-15T12:00:00Z"]),
                        Series(event="$pageleave", timestamps=["2020-01-16T11:00:00Z"]),
                        Series(event="$pageleave", timestamps=["2020-01-16T12:00:00Z"]),
                    ],
                    properties={},
                ),
            ]
        )
        flush_persons_and_events()

        response = self._run_trends_query(
            "2020-01-09",
            "2020-01-20",
            IntervalType.DAY,
            [EventsNode(event="$pageview")],
            None,
            BreakdownFilter(
                breakdowns=[
                    Breakdown(property="$bin", histogram_bin_count=5),
                ],
            ),
        )
        breakdown_labels = [result["breakdown_value"] for result in response.results]

        assert len(response.results) == 5
        assert len(breakdown_labels) == 5
        assert breakdown_labels == [
            ["[4,28.8]"],
            ["[103.2,128.01]"],
            ["[28.8,53.6]"],
            ["[53.6,78.4]"],
            [BREAKDOWN_NULL_STRING_LABEL],
        ]
        assert [9, 1, 1, 1, 1] == [r["count"] for r in response.results]

        response = self._run_trends_query(
            "2020-01-09",
            "2020-01-20",
            IntervalType.DAY,
            [EventsNode(event="$pageview")],
            None,
            BreakdownFilter(
                breakdowns=[
                    Breakdown(property="$bin", histogram_bin_count=5),
                ],
                breakdown_limit=2,
            ),
        )
        breakdown_labels = [result["breakdown_value"] for result in response.results]

        assert len(response.results) == 3
        assert len(breakdown_labels) == 3
        assert breakdown_labels == [
            ["[4,28.8]"],
            ["[103.2,128.01]"],
            [BREAKDOWN_OTHER_STRING_LABEL],
        ]
        assert [9, 1, 3] == [r["count"] for r in response.results]

    def test_trends_event_histogram_breakdowns_return_equal_result(self):
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
                    properties={"$bin": 4},
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
                    properties={"$bin": 8},
                ),
                SeriesTestData(
                    distinct_id="p3",
                    events=[
                        Series(event="$pageview", timestamps=["2020-01-12T12:00:00Z"]),
                        Series(event="$pageleave", timestamps=["2020-01-13T12:00:00Z"]),
                    ],
                    properties={"$bin": 16},
                ),
                SeriesTestData(
                    distinct_id="p4",
                    events=[
                        Series(event="$pageview", timestamps=["2020-01-12T12:00:00Z"]),
                        Series(event="$pageleave", timestamps=["2020-01-13T12:00:00Z"]),
                    ],
                    properties={},
                ),
            ]
        )
        flush_persons_and_events()

        single_breakdown_response = self._run_trends_query(
            "2020-01-09",
            "2020-01-20",
            IntervalType.DAY,
            [EventsNode(event="$pageview")],
            None,
            BreakdownFilter(breakdown="$bin", breakdown_histogram_bin_count=5),
        )
        multiple_breakdowns_response = self._run_trends_query(
            "2020-01-09",
            "2020-01-20",
            IntervalType.DAY,
            [EventsNode(event="$pageview")],
            None,
            BreakdownFilter(
                breakdowns=[
                    Breakdown(property="$bin", histogram_bin_count=5),
                ],
            ),
        )

        single_breakdown_values = [result["breakdown_value"] for result in single_breakdown_response.results]
        multiple_breakdown_values = [result["breakdown_value"][0] for result in multiple_breakdowns_response.results]

        assert len(single_breakdown_response.results) == len(multiple_breakdowns_response.results) == 4
        assert len(single_breakdown_values) == len(multiple_breakdown_values) == 4
        assert (
            single_breakdown_values
            == multiple_breakdown_values
            == [
                "[4,6.4]",
                "[6.4,8.8]",
                "[13.6,16.01]",
                BREAKDOWN_NULL_STRING_LABEL,
            ]
        )
        assert (
            [r["count"] for r in single_breakdown_response.results]
            == [r["count"] for r in multiple_breakdowns_response.results]
            == [6, 2, 1, 1]
        )

    def test_trends_event_breakdowns_handle_null(self):
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
                    properties={"$bin": 4},
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
                    properties={"$second_bin": 2},
                ),
            ]
        )
        flush_persons_and_events()

        # single
        response = self._run_trends_query(
            "2020-01-09",
            "2020-01-20",
            IntervalType.DAY,
            [EventsNode(event="$pageview")],
            None,
            BreakdownFilter(
                breakdown="$bin",
                breakdown_histogram_bin_count=10,
            ),
        )
        breakdown_labels = [result["breakdown_value"] for result in response.results]

        assert len(response.results) == 2
        assert len(breakdown_labels) == 2
        assert breakdown_labels == ["[4,4.01]", BREAKDOWN_NULL_STRING_LABEL]

        # single and the property is not included by the date range
        response = self._run_trends_query(
            "2020-01-14",
            "2020-01-20",
            IntervalType.DAY,
            [EventsNode(event="$pageview")],
            None,
            BreakdownFilter(
                breakdown="$second_bin",
                breakdown_histogram_bin_count=10,
            ),
        )
        breakdown_labels = [result["breakdown_value"] for result in response.results]

        assert len(response.results) == 1
        assert len(breakdown_labels) == 1
        # must return the placeholder value to ensure the frontend doesn't show an empty cell
        assert breakdown_labels == [BREAKDOWN_NULL_STRING_LABEL]

        # multiple
        response = self._run_trends_query(
            "2020-01-09",
            "2020-01-20",
            IntervalType.DAY,
            [EventsNode(event="$pageview")],
            None,
            BreakdownFilter(breakdowns=[Breakdown(property="$bin", histogram_bin_count=10)]),
        )
        breakdown_labels = [result["breakdown_value"] for result in response.results]

        assert len(response.results) == 2
        assert len(breakdown_labels) == 2
        assert breakdown_labels == [["[4,4.01]"], [BREAKDOWN_NULL_STRING_LABEL]]

        # multiple, two properties
        response = self._run_trends_query(
            "2020-01-09",
            "2020-01-20",
            IntervalType.DAY,
            [EventsNode(event="$pageview")],
            None,
            BreakdownFilter(
                breakdowns=[
                    Breakdown(property="$bin", histogram_bin_count=10),
                    Breakdown(property="$second_bin", histogram_bin_count=10),
                ]
            ),
        )
        breakdown_labels = [result["breakdown_value"] for result in response.results]

        assert len(response.results) == 2
        assert len(breakdown_labels) == 2
        assert breakdown_labels == [
            ["[4,4.01]", BREAKDOWN_NULL_STRING_LABEL],
            [BREAKDOWN_NULL_STRING_LABEL, "[2,2.01]"],
        ]

        # multiple and the property is not included by the date range
        response = self._run_trends_query(
            "2020-01-14",
            "2020-01-20",
            IntervalType.DAY,
            [EventsNode(event="$pageview")],
            None,
            BreakdownFilter(
                breakdowns=[
                    Breakdown(property="$second_bin", histogram_bin_count=10),
                ]
            ),
        )
        breakdown_labels = [result["breakdown_value"] for result in response.results]

        assert len(response.results) == 1
        assert len(breakdown_labels) == 1
        # must return the placeholder value to ensure the frontend doesn't show an empty cell
        assert breakdown_labels == [[BREAKDOWN_NULL_STRING_LABEL]]

    def test_trends_event_breakdowns_can_combine_bool_sting_and_numeric_in_any_order(self):
        self._create_test_events()
        flush_persons_and_events()

        breakdowns = [
            Breakdown(property="prop", histogram_bin_count=2),
            Breakdown(property="$browser"),
            Breakdown(property="bool_field"),
        ]
        for breakdown_filter in itertools.combinations(breakdowns, 3):
            response = self._run_trends_query(
                "2020-01-09",
                "2020-01-20",
                IntervalType.DAY,
                [EventsNode(event="$pageview")],
                None,
                BreakdownFilter(breakdowns=breakdown_filter),
            )
            breakdown_labels = [sorted(result["breakdown_value"]) for result in response.results]

            assert len(response.results) == 4
            assert len(breakdown_labels) == 4
            assert breakdown_labels == [
                sorted(["[10,25]", "Chrome", "true"]),
                sorted(["[10,25]", "Firefox", "false"]),
                sorted(["[25,40.01]", "Edge", "true"]),
                sorted(["[25,40.01]", "Safari", "false"]),
            ]

    def test_trends_event_breakdowns_handle_none_histogram_bin_count(self):
        self._create_test_events()
        flush_persons_and_events()

        # multiple
        response = self._run_trends_query(
            "2020-01-09",
            "2020-01-20",
            IntervalType.DAY,
            [EventsNode(event="$pageview")],
            None,
            BreakdownFilter(
                breakdowns=[
                    Breakdown(property="prop", histogram_bin_count=2),
                    Breakdown(property="$browser", histogram_bin_count=None),
                ]
            ),
        )
        breakdown_labels = [result["breakdown_value"] for result in response.results]

        assert len(response.results) == 4
        assert len(breakdown_labels) == 4
        assert breakdown_labels == [
            ["[10,25]", "Chrome"],
            ["[10,25]", "Firefox"],
            ["[25,40.01]", "Edge"],
            ["[25,40.01]", "Safari"],
        ]

    def test_trends_event_math_session_duration_with_breakdowns(self):
        self._create_test_events()
        flush_persons_and_events()

        s_response = self._run_trends_query(
            "2020-01-09",
            "2020-01-20",
            IntervalType.DAY,
            [EventsNode(event="$pageview", math=PropertyMathType.MEDIAN, math_property="$session_duration")],
            None,
            BreakdownFilter(
                breakdown="$session_duration",
                breakdown_type=BreakdownType.SESSION,
            ),
        )
        m_response = self._run_trends_query(
            "2020-01-09",
            "2020-01-20",
            IntervalType.DAY,
            [EventsNode(event="$pageview", math=PropertyMathType.MEDIAN, math_property="$session_duration")],
            None,
            BreakdownFilter(
                breakdowns=[Breakdown(property="$session_duration", type=MultipleBreakdownType.SESSION)],
            ),
        )

        single_breakdown_values = [result["breakdown_value"] for result in s_response.results]
        multiple_breakdown_values = [result["breakdown_value"][0] for result in m_response.results]

        assert len(s_response.results) == len(m_response.results) == 1
        assert len(single_breakdown_values) == len(multiple_breakdown_values) == 1
        assert single_breakdown_values == multiple_breakdown_values == ["0"]
        assert s_response.results[0]["label"] == m_response.results[0]["label"] == "0"
        assert s_response.results[0]["count"] == m_response.results[0]["count"] == 0

    def test_trends_event_math_session_duration_with_breakdowns_and_histogram_bins(self):
        self._create_test_events()
        flush_persons_and_events()

        s_response = self._run_trends_query(
            "2020-01-09",
            "2020-01-20",
            IntervalType.DAY,
            [EventsNode(event="$pageview", math=PropertyMathType.MEDIAN, math_property="$session_duration")],
            None,
            BreakdownFilter(
                breakdown="$session_duration", breakdown_type=BreakdownType.SESSION, breakdown_histogram_bin_count=4
            ),
        )
        m_response = self._run_trends_query(
            "2020-01-09",
            "2020-01-20",
            IntervalType.DAY,
            [EventsNode(event="$pageview", math=PropertyMathType.MEDIAN, math_property="$session_duration")],
            None,
            BreakdownFilter(
                breakdowns=[
                    Breakdown(property="$session_duration", type=MultipleBreakdownType.SESSION, histogram_bin_count=4)
                ],
            ),
        )

        single_breakdown_values = [result["breakdown_value"] for result in s_response.results]
        multiple_breakdown_values = [result["breakdown_value"][0] for result in m_response.results]

        assert len(s_response.results) == len(m_response.results) == 1
        assert len(single_breakdown_values) == len(multiple_breakdown_values) == 1
        assert single_breakdown_values == multiple_breakdown_values == ["[0,0.01]"]
        assert s_response.results[0]["label"] == m_response.results[0]["label"] == "[0,0.01]"
        assert s_response.results[0]["count"] == m_response.results[0]["count"] == 0

    def test_trends_event_math_wau_with_breakdowns(self):
        self._create_test_events()
        flush_persons_and_events()

        s_response = self._run_trends_query(
            "2020-01-09",
            "2020-01-20",
            IntervalType.DAY,
            [EventsNode(event="$pageview", math=BaseMathType.WEEKLY_ACTIVE)],
            None,
            BreakdownFilter(breakdown="$session_duration", breakdown_type="session", breakdown_histogram_bin_count=4),
        )
        m_response = self._run_trends_query(
            "2020-01-09",
            "2020-01-20",
            IntervalType.DAY,
            [EventsNode(event="$pageview", math=BaseMathType.WEEKLY_ACTIVE)],
            None,
            BreakdownFilter(
                breakdowns=[Breakdown(property="$session_duration", type="session", histogram_bin_count=4)],
            ),
        )

        single_breakdown_values = [result["breakdown_value"] for result in s_response.results]
        multiple_breakdown_values = [result["breakdown_value"][0] for result in m_response.results]

        assert len(s_response.results) == len(m_response.results) == 1
        assert len(single_breakdown_values) == len(multiple_breakdown_values) == 1
        assert single_breakdown_values == multiple_breakdown_values == ["[0,0.01]"]
        assert s_response.results[0]["label"] == m_response.results[0]["label"] == "[0,0.01]"
        assert s_response.results[0]["count"] == m_response.results[0]["count"] == 33

    def test_trends_event_math_mau_with_breakdowns(self):
        self._create_test_events()
        flush_persons_and_events()

        s_response = self._run_trends_query(
            "2020-01-09",
            "2020-02-10",
            IntervalType.DAY,
            [EventsNode(event="$pageview", math=BaseMathType.MONTHLY_ACTIVE)],
            None,
            BreakdownFilter(breakdown="$browser"),
        )
        m_response = self._run_trends_query(
            "2020-01-09",
            "2020-02-10",
            IntervalType.DAY,
            [EventsNode(event="$pageview", math=BaseMathType.MONTHLY_ACTIVE)],
            None,
            BreakdownFilter(
                breakdowns=[Breakdown(property="$browser", type="event")],
            ),
        )

        single_breakdown_values = [result["breakdown_value"] for result in s_response.results]
        multiple_breakdown_values = [result["breakdown_value"][0] for result in m_response.results]

        assert len(s_response.results) == len(m_response.results) == 4
        assert len(single_breakdown_values) == len(multiple_breakdown_values) == 4
        assert single_breakdown_values == multiple_breakdown_values == ["Firefox", "Chrome", "Edge", "Safari"]
        assert s_response.results[0]["count"] == m_response.results[0]["count"] == 33
        assert s_response.results[1]["count"] == m_response.results[1]["count"] == 31
        assert s_response.results[2]["count"] == m_response.results[2]["count"] == 30
        assert s_response.results[3]["count"] == m_response.results[3]["count"] == 27

    def test_trends_multiple_breakdowns_hogql(self):
        self._create_test_events()

        response = self._run_trends_query(
            "2020-01-09",
            "2020-01-20",
            IntervalType.DAY,
            [EventsNode(event="$pageview")],
            None,
            BreakdownFilter(breakdowns=[Breakdown(property="properties.$browser", type=MultipleBreakdownType.HOGQL)]),
        )

        breakdown_labels = [result["breakdown_value"] for result in response.results]

        assert len(response.results) == 4
        assert breakdown_labels == [["Chrome"], ["Firefox"], ["Edge"], ["Safari"]]
        assert response.results[0]["label"] == "Chrome"
        assert response.results[1]["label"] == "Firefox"
        assert response.results[2]["label"] == "Edge"
        assert response.results[3]["label"] == "Safari"
        assert response.results[0]["count"] == 6
        assert response.results[1]["count"] == 2
        assert response.results[2]["count"] == 1
        assert response.results[3]["count"] == 1

    def test_trends_multiple_breakdowns_hogql_and_numeric_prop(self):
        self._create_test_events()

        response = self._run_trends_query(
            "2020-01-09",
            "2020-01-20",
            IntervalType.DAY,
            [EventsNode(event="$pageview")],
            None,
            BreakdownFilter(
                breakdowns=[
                    Breakdown(property="properties.$browser", type=MultipleBreakdownType.HOGQL),
                    Breakdown(property="prop", histogram_bin_count=2),
                ]
            ),
        )

        breakdown_labels = [result["breakdown_value"] for result in response.results]

        assert len(response.results) == 4
        assert breakdown_labels == [
            ["Chrome", "[10,25]"],
            ["Firefox", "[10,25]"],
            ["Edge", "[25,40.01]"],
            ["Safari", "[25,40.01]"],
        ]
        assert response.results[0]["label"] == "Chrome::[10,25]"
        assert response.results[1]["label"] == "Firefox::[10,25]"
        assert response.results[2]["label"] == "Edge::[25,40.01]"
        assert response.results[3]["label"] == "Safari::[25,40.01]"
        assert response.results[0]["count"] == 6
        assert response.results[1]["count"] == 2
        assert response.results[2]["count"] == 1
        assert response.results[3]["count"] == 1

    def test_trends_event_multiple_breakdowns_combined_types(self):
        """
        Test all possible combinations do not throw.
        """
        self._create_test_events_for_groups()
        flush_persons_and_events()

        breakdowns = [
            Breakdown(property="prop", histogram_bin_count=2, type=MultipleBreakdownType.EVENT),
            Breakdown(property="$browser", type=MultipleBreakdownType.EVENT),
            Breakdown(property="bool_field", type=MultipleBreakdownType.EVENT),
            Breakdown(property="properties.$browser", type=MultipleBreakdownType.HOGQL),
            Breakdown(property="name", type=MultipleBreakdownType.PERSON),
            Breakdown(property="$session_duration", type=MultipleBreakdownType.SESSION),
            Breakdown(type="group", group_type_index=1, property="employee_count"),
            Breakdown(type="group", group_type_index=0, property="industry"),
        ]

        for breakdown_filter in itertools.permutations(breakdowns, 2):
            response = self._run_trends_query(
                "2020-01-09",
                "2020-01-20",
                IntervalType.DAY,
                [EventsNode(event="$pageview")],
                None,
                BreakdownFilter(breakdowns=breakdown_filter),
            )
            breakdown_labels = [sorted(result["breakdown_value"]) for result in response.results]

            self.assertNotEqual(len(response.results), 0, breakdown_filter)
            self.assertNotEqual(len(breakdown_labels), 0, breakdown_filter)

    def test_trends_multiple_breakdowns_multiple_hogql(self):
        self._create_test_events()

        response = self._run_trends_query(
            "2020-01-09",
            "2020-01-20",
            IntervalType.DAY,
            [EventsNode(event="$pageview"), EventsNode(event="$pageleave")],
            None,
            BreakdownFilter(breakdowns=[Breakdown(type=MultipleBreakdownType.HOGQL, property="properties.$browser")]),
        )

        breakdown_labels = [result["breakdown_value"] for result in response.results]

        assert len(response.results) == 8
        assert breakdown_labels == [
            ["Chrome"],
            ["Firefox"],
            ["Edge"],
            ["Safari"],
            ["Chrome"],
            ["Edge"],
            ["Firefox"],
            ["Safari"],
        ]
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

    def test_to_insight_query_applies_multiple_breakdowns(self):
        self._create_test_events()
        flush_persons_and_events()

        response = self._run_trends_query(
            "2020-01-09",
            "2020-01-20",
            IntervalType.DAY,
            [EventsNode(event="$pageview")],
            TrendsFilter(display=ChartDisplayType.ACTIONS_BAR_VALUE),
            BreakdownFilter(
                breakdowns=[
                    Breakdown(type=BreakdownType.EVENT, property="$browser"),
                    Breakdown(type=BreakdownType.EVENT, property="prop", histogram_bin_count=2),
                    Breakdown(type=BreakdownType.EVENT, property="bool_field"),
                ]
            ),
        )

        breakdown_labels = [result["breakdown_value"] for result in response.results]

        assert len(response.results) == 4
        assert breakdown_labels == [
            ["Chrome", "[10,25]", "true"],
            ["Firefox", "[10,25]", "false"],
            ["Edge", "[25,40.01]", "true"],
            ["Safari", "[25,40.01]", "false"],
        ]

    def test_to_actors_query_options_orders_options_with_histogram_breakdowns(self):
        self._create_test_events()
        self._create_events(
            [
                SeriesTestData(
                    distinct_id="p99",
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
                    properties={},
                ),
            ]
        )
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
            BreakdownItem(label="[10,17.5]", value="[10,17.5]"),
            BreakdownItem(label="[17.5,25]", value="[17.5,25]"),
            BreakdownItem(label="[25,32.5]", value="[25,32.5]"),
            BreakdownItem(label="[32.5,40.01]", value="[32.5,40.01]"),
            BreakdownItem(label='["",""]', value='["",""]'),
            BreakdownItem(label=BREAKDOWN_NULL_DISPLAY, value=BREAKDOWN_NULL_STRING_LABEL),
        ]

        runner = self._create_query_runner(
            "2020-01-09",
            "2020-01-20",
            IntervalType.DAY,
            [EventsNode(event="$pageview")],
            None,
            BreakdownFilter(breakdowns=[Breakdown(type=BreakdownType.EVENT, property="prop", histogram_bin_count=4)]),
        )
        response = runner.to_actors_query_options()

        assert response.series == [InsightActorsQuerySeries(label="$pageview", value=0)]
        assert response.breakdowns is not None
        assert response.series == [InsightActorsQuerySeries(label="$pageview", value=0)]
        assert response.breakdowns[0].values == [
            BreakdownItem(label="[10,17.5]", value="[10,17.5]"),
            BreakdownItem(label="[17.5,25]", value="[17.5,25]"),
            BreakdownItem(label="[25,32.5]", value="[25,32.5]"),
            BreakdownItem(label="[32.5,40.01]", value="[32.5,40.01]"),
            BreakdownItem(label='["",""]', value='["",""]'),
            BreakdownItem(label=BREAKDOWN_NULL_DISPLAY, value=BREAKDOWN_NULL_STRING_LABEL),
        ]

    def test_to_insight_query_applies_breakdown_limit(self):
        self._create_test_events()
        flush_persons_and_events()

        response = self._run_trends_query(
            "2020-01-09",
            "2020-01-20",
            IntervalType.DAY,
            [EventsNode(event="$pageview")],
            TrendsFilter(display=ChartDisplayType.ACTIONS_BAR_VALUE),
            BreakdownFilter(breakdown="$browser", breakdown_limit=2),
        )

        breakdown_labels = [result["breakdown_value"] for result in response.results]

        assert len(response.results) == 3
        assert breakdown_labels == ["Chrome", "Firefox", BREAKDOWN_OTHER_STRING_LABEL]

        response = self._run_trends_query(
            "2020-01-09",
            "2020-01-20",
            IntervalType.DAY,
            [EventsNode(event="$pageview")],
            TrendsFilter(display=ChartDisplayType.ACTIONS_BAR_VALUE),
            BreakdownFilter(breakdowns=[Breakdown(property="$browser")], breakdown_limit=2),
        )

        breakdown_labels = [result["breakdown_value"] for result in response.results]

        assert len(response.results) == 3
        assert breakdown_labels == [["Chrome"], ["Firefox"], [BREAKDOWN_OTHER_STRING_LABEL]]

    def test_trends_table_uses_breakdown_bins(self):
        self._create_test_events()
        flush_persons_and_events()

        for display in [
            ChartDisplayType.ACTIONS_PIE,
            ChartDisplayType.ACTIONS_BAR_VALUE,
            ChartDisplayType.ACTIONS_TABLE,
        ]:
            response = self._run_trends_query(
                "2020-01-09",
                "2020-01-20",
                IntervalType.DAY,
                [EventsNode(event="$pageview")],
                TrendsFilter(display=display),
                BreakdownFilter(
                    breakdown="prop",
                    breakdown_type=MultipleBreakdownType.EVENT,
                    breakdown_histogram_bin_count=2,
                    breakdown_limit=10,
                    breakdown_hide_other_aggregation=True,
                ),
            )

            breakdown_labels = [result["breakdown_value"] for result in response.results]
            assert len(response.results) == 2
            assert breakdown_labels == ["[10,25]", "[25,40.01]"]
            assert response.results[0]["aggregated_value"] == 8
            assert response.results[1]["aggregated_value"] == 2

            response = self._run_trends_query(
                "2020-01-09",
                "2020-01-20",
                IntervalType.DAY,
                [EventsNode(event="$pageview")],
                TrendsFilter(display=display),
                BreakdownFilter(
                    breakdowns=[Breakdown(property="prop", type=MultipleBreakdownType.EVENT, histogram_bin_count=2)],
                    breakdown_limit=10,
                    breakdown_hide_other_aggregation=True,
                ),
            )

            breakdown_labels = [result["breakdown_value"] for result in response.results]
            assert len(response.results) == 2
            assert breakdown_labels == [["[10,25]"], ["[25,40.01]"]]
            assert response.results[0]["aggregated_value"] == 8
            assert response.results[1]["aggregated_value"] == 2

    def test_trends_math_first_time_for_user_basic(self):
        self._create_test_events()
        flush_persons_and_events()

        response = self._run_trends_query(
            "2020-01-09",
            "2020-01-20",
            IntervalType.DAY,
            [EventsNode(event="$pageview", math=BaseMathType.FIRST_TIME_FOR_USER)],
            TrendsFilter(display=ChartDisplayType.ACTIONS_LINE_GRAPH),
        )

        assert len(response.results) == 1
        assert response.results[0]["count"] == 4
        assert response.results[0]["data"] == [1, 0, 1, 1, 0, 0, 1, 0, 0, 0, 0, 0]

        # must not include the person with the id `p2`
        response = self._run_trends_query(
            "2020-01-10",
            "2020-01-20",
            IntervalType.DAY,
            [EventsNode(event="$pageview", math=BaseMathType.FIRST_TIME_FOR_USER)],
            TrendsFilter(display=ChartDisplayType.ACTIONS_LINE_GRAPH),
        )

        assert len(response.results) == 1
        assert response.results[0]["count"] == 3
        assert response.results[0]["data"] == [0, 1, 1, 0, 0, 1, 0, 0, 0, 0, 0]

        # must not include the persons with the ids `p1` and `p2`
        response = self._run_trends_query(
            "2020-01-12",
            "2020-01-20",
            IntervalType.DAY,
            [EventsNode(event="$pageview", math=BaseMathType.FIRST_TIME_FOR_USER)],
            TrendsFilter(display=ChartDisplayType.ACTIONS_LINE_GRAPH),
        )

        assert len(response.results) == 1
        assert response.results[0]["count"] == 2
        assert response.results[0]["data"] == [1, 0, 0, 1, 0, 0, 0, 0, 0]

        # no such persons
        response = self._run_trends_query(
            "2020-01-16",
            "2020-01-20",
            IntervalType.DAY,
            [EventsNode(event="$pageview", math=BaseMathType.FIRST_TIME_FOR_USER)],
            TrendsFilter(display=ChartDisplayType.ACTIONS_LINE_GRAPH),
        )

        assert len(response.results) == 1
        assert response.results[0]["count"] == 0
        assert response.results[0]["data"] == [0, 0, 0, 0, 0]

    def test_trends_math_first_time_for_user_breakdowns_basic(self):
        self._create_test_events()
        flush_persons_and_events()

        # single breakdown
        response = self._run_trends_query(
            "2020-01-09",
            "2020-01-20",
            IntervalType.DAY,
            [EventsNode(event="$pageview", math=BaseMathType.FIRST_TIME_FOR_USER)],
            TrendsFilter(display=ChartDisplayType.ACTIONS_LINE_GRAPH),
            BreakdownFilter(breakdown="$browser"),
        )

        assert len(response.results) == 4

        count = [result["count"] for result in response.results]
        assert count == [1, 1, 1, 1]

        breakdowns = [result["breakdown_value"] for result in response.results]
        assert breakdowns == ["Chrome", "Edge", "Firefox", "Safari"]

        data = [result["data"] for result in response.results]
        matrix = [
            [0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0],
            [0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0],
            [1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
            [0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0],
        ]
        assert data == matrix

        # multiple breakdowns
        response = self._run_trends_query(
            "2020-01-09",
            "2020-01-20",
            IntervalType.DAY,
            [EventsNode(event="$pageview", math=BaseMathType.FIRST_TIME_FOR_USER)],
            TrendsFilter(display=ChartDisplayType.ACTIONS_LINE_GRAPH),
            BreakdownFilter(breakdowns=[Breakdown(property="$browser")]),
        )

        assert len(response.results) == 4

        count = [result["count"] for result in response.results]
        assert count == [1, 1, 1, 1]

        breakdowns = [result["breakdown_value"] for result in response.results]
        assert breakdowns == [["Chrome"], ["Edge"], ["Firefox"], ["Safari"]]

        data = [result["data"] for result in response.results]
        assert data == matrix

    def test_trends_math_first_time_for_user_breakdowns_with_bins(self):
        self._create_test_events()
        flush_persons_and_events()

        # single breakdown
        response = self._run_trends_query(
            "2020-01-09",
            "2020-01-20",
            IntervalType.DAY,
            [EventsNode(event="$pageview", math=BaseMathType.FIRST_TIME_FOR_USER)],
            TrendsFilter(display=ChartDisplayType.ACTIONS_LINE_GRAPH),
            BreakdownFilter(breakdown="prop", breakdown_type=BreakdownType.EVENT, breakdown_histogram_bin_count=2),
        )

        assert len(response.results) == 2

        count = [result["count"] for result in response.results]
        assert count == [2, 2]

        breakdowns = [result["breakdown_value"] for result in response.results]
        assert breakdowns == ["[10,25]", "[25,40.01]"]

        data = [result["data"] for result in response.results]
        matrix = [
            [1, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0],
            [0, 0, 0, 1, 0, 0, 1, 0, 0, 0, 0, 0],
        ]
        assert data == matrix

        # multiple breakdowns
        response = self._run_trends_query(
            "2020-01-09",
            "2020-01-20",
            IntervalType.DAY,
            [EventsNode(event="$pageview", math=BaseMathType.FIRST_TIME_FOR_USER)],
            TrendsFilter(display=ChartDisplayType.ACTIONS_LINE_GRAPH),
            BreakdownFilter(breakdowns=[Breakdown(property="prop", type=BreakdownType.EVENT, histogram_bin_count=2)]),
        )

        assert len(response.results) == 2

        count = [result["count"] for result in response.results]
        assert count == [2, 2]

        breakdowns = [result["breakdown_value"] for result in response.results]
        assert breakdowns == [["[10,25]"], ["[25,40.01]"]]

        data = [result["data"] for result in response.results]
        assert data == matrix

    def test_trends_math_first_time_for_user_with_filters(self):
        self._create_test_events()
        flush_persons_and_events()

        response = self._run_trends_query(
            "2020-01-09",
            "2020-01-20",
            IntervalType.DAY,
            [
                EventsNode(
                    event="$pageview",
                    math=BaseMathType.FIRST_TIME_FOR_USER,
                    properties=[EventPropertyFilter(key="$browser", operator=PropertyOperator.EXACT, value="Chrome")],
                )
            ],
            TrendsFilter(display=ChartDisplayType.ACTIONS_LINE_GRAPH),
        )

        assert len(response.results) == 1
        assert response.results[0]["count"] == 1
        assert response.results[0]["data"] == [0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0]

        response = self._run_trends_query(
            "2020-01-09",
            "2020-01-20",
            IntervalType.DAY,
            [
                EventsNode(
                    event="$pageview",
                    math=BaseMathType.FIRST_TIME_FOR_USER,
                    properties=[PersonPropertyFilter(key="name", operator=PropertyOperator.EXACT, value="p4")],
                )
            ],
            TrendsFilter(display=ChartDisplayType.ACTIONS_LINE_GRAPH),
        )

        assert len(response.results) == 1
        assert response.results[0]["count"] == 1
        assert response.results[0]["data"] == [0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0]

    def test_trends_math_first_time_for_user_with_total_values(self):
        self._create_test_events()
        flush_persons_and_events()

        for display in [
            ChartDisplayType.ACTIONS_PIE,
            ChartDisplayType.ACTIONS_BAR_VALUE,
            ChartDisplayType.ACTIONS_TABLE,
            ChartDisplayType.BOLD_NUMBER,
        ]:
            response = self._run_trends_query(
                "2020-01-09",
                "2020-01-20",
                IntervalType.DAY,
                [
                    EventsNode(
                        event="$pageview",
                        math=BaseMathType.FIRST_TIME_FOR_USER,
                    )
                ],
                TrendsFilter(display=display),
            )

            assert len(response.results) == 1
            assert response.results[0]["aggregated_value"] == 4

            response = self._run_trends_query(
                "2020-01-14",
                "2020-01-20",
                IntervalType.DAY,
                [
                    EventsNode(
                        event="$pageview",
                        math=BaseMathType.FIRST_TIME_FOR_USER,
                    )
                ],
                TrendsFilter(display=display),
            )

            assert len(response.results) == 1
            assert response.results[0]["aggregated_value"] == 1

    def test_trends_math_first_time_for_user_handles_multiple_ids(self):
        timestamp = "2020-01-11T12:00:00Z"

        with freeze_time(timestamp):
            _create_person(
                team_id=self.team.pk,
                distinct_ids=["anon1", "p1"],
                properties={},
            )
            _create_person(
                team_id=self.team.pk,
                distinct_ids=["anon2", "p2"],
                properties={},
            )
            _create_person(
                team_id=self.team.pk,
                distinct_ids=["anon3"],
                properties={},
            )

        # p1
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="anon1",
            timestamp="2020-01-11T12:00:00Z",
            properties={},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            timestamp="2020-01-12T12:00:00Z",
            properties={},
        )

        # p2
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="anon2",
            timestamp="2020-01-12T12:00:00Z",
            properties={},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p2",
            timestamp="2020-01-12T12:01:00Z",
            properties={},
        )

        # anon3
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="anon3",
            timestamp="2020-01-12T12:00:00Z",
            properties={},
        )

        response = self._run_trends_query(
            "2020-01-09",
            "2020-01-12",
            IntervalType.DAY,
            [
                EventsNode(
                    event="$pageview",
                    math=BaseMathType.FIRST_TIME_FOR_USER,
                )
            ],
            TrendsFilter(display=ChartDisplayType.ACTIONS_LINE_GRAPH),
        )

        assert len(response.results) == 1
        assert response.results[0]["count"] == 3
        assert response.results[0]["data"] == [0, 0, 1, 2]

    def test_trends_math_first_time_for_user_filters_first_events(self):
        timestamp = "2020-01-11T12:00:00Z"

        with freeze_time(timestamp):
            _create_person(
                team_id=self.team.pk,
                distinct_ids=["anon1", "p1"],
                properties={},
            )

        # p1
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="anon1",
            timestamp="2020-01-11T12:00:00Z",
            properties={"$browser": "Chrome"},
        )

        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            timestamp="2020-01-12T12:00:00Z",
            properties={"$browser": "Safari"},
        )

        PropertyDefinition.objects.create(team=self.team, name="$browser", property_type="String")

        # has data
        response = self._run_trends_query(
            "2020-01-10",
            "2020-01-12",
            IntervalType.DAY,
            [
                EventsNode(
                    event="$pageview",
                    math=BaseMathType.FIRST_TIME_FOR_USER,
                    properties=[EventPropertyFilter(key="$browser", operator=PropertyOperator.EXACT, value="Chrome")],
                )
            ],
            TrendsFilter(display=ChartDisplayType.ACTIONS_LINE_GRAPH),
        )

        assert len(response.results) == 1
        assert response.results[0]["count"] == 1
        assert response.results[0]["data"] == [0, 1, 0]

        response = self._run_trends_query(
            "2020-01-10",
            "2020-01-12",
            IntervalType.DAY,
            [
                EventsNode(
                    event="$pageview",
                    math=BaseMathType.FIRST_TIME_FOR_USER,
                )
            ],
            TrendsFilter(display=ChartDisplayType.ACTIONS_LINE_GRAPH),
            properties=[EventPropertyFilter(key="$browser", operator=PropertyOperator.EXACT, value="Chrome")],
        )

        assert len(response.results) == 1
        assert response.results[0]["count"] == 1
        assert response.results[0]["data"] == [0, 1, 0]

        # no data
        response = self._run_trends_query(
            "2020-01-10",
            "2020-01-12",
            IntervalType.DAY,
            [
                EventsNode(
                    event="$pageview",
                    math=BaseMathType.FIRST_TIME_FOR_USER,
                    properties=[EventPropertyFilter(key="$browser", operator=PropertyOperator.EXACT, value="Safari")],
                )
            ],
            TrendsFilter(display=ChartDisplayType.ACTIONS_LINE_GRAPH),
        )

        assert len(response.results) == 1
        assert response.results[0]["count"] == 0
        assert response.results[0]["data"] == [0, 0, 0]

        response = self._run_trends_query(
            "2020-01-10",
            "2020-01-12",
            IntervalType.DAY,
            [
                EventsNode(
                    event="$pageview",
                    math=BaseMathType.FIRST_TIME_FOR_USER,
                )
            ],
            TrendsFilter(display=ChartDisplayType.ACTIONS_LINE_GRAPH),
            properties=[EventPropertyFilter(key="$browser", operator=PropertyOperator.EXACT, value="Safari")],
        )

        assert len(response.results) == 1
        assert response.results[0]["count"] == 0
        assert response.results[0]["data"] == [0, 0, 0]

    def test_trends_math_first_time_for_user_prioritizes_first_event(self):
        timestamp = "2020-01-11T12:00:00Z"

        with freeze_time(timestamp):
            _create_person(
                team_id=self.team.pk,
                distinct_ids=["p1"],
                properties={},
            )

        # p1
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            timestamp="2020-01-11T12:00:00Z",
            properties={"$browser": "Chrome"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            timestamp="2020-01-11T12:00:00Z",
            properties={"$browser": "Safari"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            timestamp="2020-01-11T12:00:01Z",
            properties={"$browser": "Firefox"},
        )

        PropertyDefinition.objects.create(team=self.team, name="$browser", property_type="String")

        response = self._run_trends_query(
            "2020-01-10",
            "2020-01-12",
            IntervalType.DAY,
            [
                EventsNode(
                    event="$pageview",
                    math=BaseMathType.FIRST_TIME_FOR_USER,
                    properties=[EventPropertyFilter(key="$browser", operator=PropertyOperator.EXACT, value="Chrome")],
                )
            ],
            TrendsFilter(display=ChartDisplayType.ACTIONS_LINE_GRAPH),
        )

        assert len(response.results) == 1
        assert response.results[0]["count"] == 1
        assert response.results[0]["data"] == [0, 1, 0]

        # Tricky: events with the same timestamp but different properties will still be considered as a first-time appearance.
        response = self._run_trends_query(
            "2020-01-10",
            "2020-01-12",
            IntervalType.DAY,
            [
                EventsNode(
                    event="$pageview",
                    math=BaseMathType.FIRST_TIME_FOR_USER,
                    properties=[EventPropertyFilter(key="$browser", operator=PropertyOperator.EXACT, value="Safari")],
                )
            ],
            TrendsFilter(display=ChartDisplayType.ACTIONS_LINE_GRAPH),
        )

        assert len(response.results) == 1
        assert response.results[0]["count"] == 1
        assert response.results[0]["data"] == [0, 1, 0]

        response = self._run_trends_query(
            "2020-01-10",
            "2020-01-12",
            IntervalType.DAY,
            [
                EventsNode(
                    event="$pageview",
                    math=BaseMathType.FIRST_TIME_FOR_USER,
                    properties=[EventPropertyFilter(key="$browser", operator=PropertyOperator.EXACT, value="Firefox")],
                )
            ],
            TrendsFilter(display=ChartDisplayType.ACTIONS_LINE_GRAPH),
        )

        assert len(response.results) == 1
        assert response.results[0]["count"] == 0

    def test_trends_math_first_time_for_user_date_ranges(self):
        self._create_test_events()
        flush_persons_and_events()

        response = self._run_trends_query(
            "2020-01-09",
            "2020-01-20",
            IntervalType.DAY,
            [
                EventsNode(
                    event="$pageview",
                    math=BaseMathType.FIRST_TIME_FOR_USER,
                    properties=[EventPropertyFilter(key="$browser", operator=PropertyOperator.EXACT, value="Chrome")],
                )
            ],
            TrendsFilter(display=ChartDisplayType.ACTIONS_LINE_GRAPH),
        )

        assert len(response.results) == 1
        assert response.results[0]["count"] == 1
        assert len(response.results[0]["days"]) == 12
        assert response.results[0]["days"][0] == "2020-01-09"
        assert response.results[0]["days"][11] == "2020-01-20"

    def test_trends_math_first_time_for_user_interval_types(self):
        self._create_test_events()
        flush_persons_and_events()

        with freeze_time("2020-01-20"):
            response = self._run_trends_query(
                "-180d",
                None,
                IntervalType.MONTH,
                [
                    EventsNode(
                        event="$pageview",
                        math=BaseMathType.FIRST_TIME_FOR_USER,
                    )
                ],
                TrendsFilter(display=ChartDisplayType.ACTIONS_LINE_GRAPH),
            )

        assert len(response.results) == 1
        assert response.results[0]["count"] == 4
        assert len(response.results[0]["days"]) == 7

        with freeze_time("2020-01-20"):
            response = self._run_trends_query(
                "-180d",
                None,
                IntervalType.WEEK,
                [
                    EventsNode(
                        event="$pageview",
                        math=BaseMathType.FIRST_TIME_FOR_USER,
                    )
                ],
                TrendsFilter(display=ChartDisplayType.ACTIONS_LINE_GRAPH),
            )

        assert len(response.results) == 1
        assert response.results[0]["count"] == 4
        assert len(response.results[0]["days"]) == 27

        with freeze_time("2020-01-20"):
            response = self._run_trends_query(
                "-30d",
                None,
                IntervalType.HOUR,
                [
                    EventsNode(
                        event="$pageview",
                        math=BaseMathType.FIRST_TIME_FOR_USER,
                    )
                ],
                TrendsFilter(display=ChartDisplayType.ACTIONS_LINE_GRAPH),
            )

        assert len(response.results) == 1
        assert response.results[0]["count"] == 4
        assert len(response.results[0]["days"]) == 721

        with freeze_time("2020-01-11T12:30:00Z"):
            response = self._run_trends_query(
                "-1h",
                None,
                IntervalType.MINUTE,
                [
                    EventsNode(
                        event="$pageview",
                        math=BaseMathType.FIRST_TIME_FOR_USER,
                    )
                ],
                TrendsFilter(display=ChartDisplayType.ACTIONS_LINE_GRAPH),
            )

        assert len(response.results) == 1
        assert response.results[0]["count"] == 1
        assert len(response.results[0]["days"]) == 61

    def test_trends_math_first_time_for_user_all_events(self):
        self._create_test_events()
        flush_persons_and_events()

        with freeze_time("2020-01-20"):
            response = self._run_trends_query(
                "-180d",
                None,
                IntervalType.MONTH,
                [
                    EventsNode(
                        event=None,
                        math=BaseMathType.FIRST_TIME_FOR_USER,
                    )
                ],
                TrendsFilter(display=ChartDisplayType.ACTIONS_LINE_GRAPH),
            )

            assert len(response.results) == 1
            assert response.results[0]["count"] == 4

    def test_trends_math_first_time_for_user_actions(self):
        self._create_test_events()
        flush_persons_and_events()

        action = Action.objects.create(
            team=self.team,
            name="viewed from chrome and left",
            steps_json=[
                {
                    "event": "$pageview",
                    "properties": [{"key": "$browser", "type": "event", "value": "Chrome", "operator": "icontains"}],
                },
                {
                    "event": "$pageleave",
                    "properties": [{"key": "$browser", "type": "event", "value": "Chrome", "operator": "icontains"}],
                },
            ],
        )

        response = self._run_trends_query(
            "2020-01-09",
            "2020-01-20",
            IntervalType.DAY,
            [ActionsNode(id=action.id, math=BaseMathType.FIRST_TIME_FOR_USER)],
            TrendsFilter(display=ChartDisplayType.ACTIONS_LINE_GRAPH),
        )

        assert len(response.results) == 1
        assert response.results[0]["count"] == 1
        assert response.results[0]["data"] == [0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0]

        action = Action.objects.create(
            team=self.team,
            name="viewed from chrome or firefox",
            steps_json=[
                {
                    "event": "$pageview",
                    "properties": [{"key": "$browser", "type": "event", "value": "Chrome", "operator": "icontains"}],
                },
                {
                    "event": "$pageview",
                    "properties": [{"key": "$browser", "type": "event", "value": "Firefox", "operator": "icontains"}],
                },
            ],
        )

        response = self._run_trends_query(
            "2020-01-09",
            "2020-01-20",
            IntervalType.DAY,
            [ActionsNode(id=action.id, math=BaseMathType.FIRST_TIME_FOR_USER)],
            TrendsFilter(display=ChartDisplayType.ACTIONS_LINE_GRAPH),
        )

        assert len(response.results) == 1
        assert response.results[0]["count"] == 2
        assert response.results[0]["data"] == [1, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0]

    def test_multiple_breakdowns_work_with_formula(self):
        self._create_test_events()
        flush_persons_and_events()

        response = self._run_trends_query(
            "2020-01-09",
            "2020-01-20",
            IntervalType.DAY,
            [EventsNode(event="$pageview")],
            TrendsFilter(display=ChartDisplayType.ACTIONS_LINE_GRAPH, formula="A*10"),
            BreakdownFilter(breakdowns=[Breakdown(property="$browser", type=MultipleBreakdownType.EVENT)]),
        )

        breakdown_labels = [result["breakdown_value"] for result in response.results]

        assert len(response.results) == 4
        assert breakdown_labels == [["Chrome"], ["Firefox"], ["Edge"], ["Safari"]]
        assert [result["data"] for result in response.results] == [
            [0, 0, 10, 10, 10, 0, 10, 0, 10, 0, 10, 0],
            [10, 0, 0, 10, 0, 0, 0, 0, 0, 0, 0, 0],
            [0, 0, 0, 10, 0, 0, 0, 0, 0, 0, 0, 0],
            [0, 0, 0, 0, 0, 0, 10, 0, 0, 0, 0, 0],
        ]

    def test_multiple_series_and_multiple_breakdowns_work_with_formula(self):
        self._create_test_events()
        flush_persons_and_events()

        response = self._run_trends_query(
            "2020-01-09",
            "2020-01-20",
            IntervalType.DAY,
            [EventsNode(event="$pageview"), EventsNode(event="$pageview")],
            TrendsFilter(display=ChartDisplayType.ACTIONS_LINE_GRAPH, formula="A/B*100"),
            BreakdownFilter(
                breakdowns=[
                    Breakdown(property="$browser", type=MultipleBreakdownType.EVENT),
                    Breakdown(property="prop", type=MultipleBreakdownType.EVENT, histogram_bin_count=2),
                ]
            ),
        )

        breakdown_labels = [result["breakdown_value"] for result in response.results]
        assert len(response.results) == 4
        assert breakdown_labels == [
            ["Chrome", "[10,25]"],
            ["Firefox", "[10,25]"],
            ["Edge", "[25,40.01]"],
            ["Safari", "[25,40.01]"],
        ]
        assert [result["data"] for result in response.results] == [
            [0, 0, 100, 100, 100, 0, 100, 0, 100, 0, 100, 0],
            [100, 0, 0, 100, 0, 0, 0, 0, 0, 0, 0, 0],
            [0, 0, 0, 100, 0, 0, 0, 0, 0, 0, 0, 0],
            [0, 0, 0, 0, 0, 0, 100, 0, 0, 0, 0, 0],
        ]

    def test_trends_with_formula_and_multiple_breakdowns_hide_other_breakdowns(self):
        PropertyDefinition.objects.create(team=self.team, name="breakdown_value", property_type="String")

        for value in list(range(30)):
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id=f"person_{value}",
                timestamp="2020-01-11T12:00:00Z",
                properties={"breakdown_value": str(value)},
            )

        response = self._run_trends_query(
            "2020-01-09",
            "2020-01-20",
            IntervalType.DAY,
            [EventsNode(event="$pageview"), EventsNode(event="$pageview")],
            TrendsFilter(display=ChartDisplayType.ACTIONS_LINE_GRAPH, formula="A+B"),
            BreakdownFilter(
                breakdowns=[Breakdown(property="breakdown_value", type=MultipleBreakdownType.EVENT)], breakdown_limit=10
            ),
        )
        breakdowns = [b for result in response.results for b in result["breakdown_value"]]
        self.assertIn(BREAKDOWN_OTHER_STRING_LABEL, breakdowns)

        response = self._run_trends_query(
            "2020-01-09",
            "2020-01-20",
            IntervalType.DAY,
            [EventsNode(event="$pageview"), EventsNode(event="$pageview")],
            TrendsFilter(display=ChartDisplayType.ACTIONS_LINE_GRAPH, formula="A+B"),
            BreakdownFilter(
                breakdowns=[Breakdown(property="breakdown_value", type=MultipleBreakdownType.EVENT)],
                breakdown_limit=10,
                breakdown_hide_other_aggregation=True,
            ),
        )
        breakdowns = [b for result in response.results for b in result["breakdown_value"]]
        self.assertNotIn(BREAKDOWN_OTHER_STRING_LABEL, breakdowns)

    def test_trends_aggregation_total_with_null(self):
        self._create_events(
            [
                SeriesTestData(
                    distinct_id="p1",
                    events=[
                        Series(event="$pageview", timestamps=["2020-01-08T12:00:00Z"]),
                    ],
                    properties={
                        "$browser": "Chrome",
                        "prop": 30,
                        "bool_field": True,
                        "nullable_prop": "1.1",
                    },
                ),
                SeriesTestData(
                    distinct_id="p7",
                    events=[
                        Series(event="$pageview", timestamps=["2020-01-15T12:00:00Z"]),
                    ],
                    properties={
                        "$browser": "Chrome",
                        "prop": 30,
                        "bool_field": True,
                        "nullable_prop": "1.1",
                    },
                ),
                SeriesTestData(
                    distinct_id="p3",
                    events=[
                        Series(event="$pageview", timestamps=["2020-01-12T12:00:00Z"]),
                    ],
                    properties={
                        "$browser": "Chrome",
                        "prop": 30,
                        "bool_field": True,
                        "nullable_prop": "garbage",
                    },
                ),
                SeriesTestData(
                    distinct_id="p4",
                    events=[
                        Series(event="$pageview", timestamps=["2020-01-15T12:00:00Z"]),
                    ],
                    properties={
                        "$browser": "Chrome",
                        "prop": 40,
                        "bool_field": False,
                        "nullable_prop": "garbage",
                    },
                ),
                SeriesTestData(
                    distinct_id="p5",
                    events=[
                        Series(event="$pageview", timestamps=["2020-01-09T12:00:00Z"]),
                    ],
                    properties={
                        "$browser": "Chrome",
                        "prop": 40,
                        "bool_field": False,
                        "nullable_prop": "garbage",
                    },
                ),
            ]
        )

        # need to let property be inferred as a different type first and then override
        # to get the `toFloat` cast
        nullable_prop = PropertyDefinition.objects.get(name="nullable_prop")
        nullable_prop.property_type = "Numeric"
        nullable_prop.save()

        nullable_prop = PropertyDefinition.objects.get(name="nullable_prop")

        response = self._run_trends_query(
            "2020-01-08",
            "2020-01-15",
            IntervalType.DAY,
            [EventsNode(event="$pageview", math=PropertyMathType.SUM, math_property="nullable_prop")],
            None,
            BreakdownFilter(breakdown="$browser", breakdown_type=BreakdownType.EVENT),
        )

        assert len(response.results) == 1
        assert response.results[0]["data"] == [1.1, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.1]

    def test_trends_aggregation_first_matching_event_for_user(self):
        _create_person(
            team=self.team,
            distinct_ids=["p1"],
            properties={},
        )
        _create_person(
            team=self.team,
            distinct_ids=["p2"],
            properties={},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id=f"p1",
            timestamp="2020-01-06T12:00:00Z",
            properties={"$browser": "Firefox"},
        )

        for i in range(1, 3):
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id=f"p{i}",
                timestamp="2020-01-08T12:00:00Z",
                properties={"$browser": "Chrome"},
            )
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id=f"p{i}",
                timestamp="2020-01-09T12:00:00Z",
                properties={"$browser": "Chrome"},
            )
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id=f"p{i}",
                timestamp="2020-01-10T12:00:00Z",
                properties={"$browser": "Firefox"},
            )
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id=f"p{i}",
                timestamp="2020-01-11T12:00:00Z",
                properties={"$browser": "Firefox"},
            )

        flush_persons_and_events()

        response = self._run_trends_query(
            "2020-01-08",
            "2020-01-11",
            IntervalType.DAY,
            [
                EventsNode(
                    event="$pageview",
                    math=BaseMathType.FIRST_MATCHING_EVENT_FOR_USER,
                    properties=[EventPropertyFilter(key="$browser", operator=PropertyOperator.EXACT, value="Firefox")],
                )
            ],
            TrendsFilter(display=ChartDisplayType.ACTIONS_LINE_GRAPH),
        )

        assert len(response.results) == 1
        assert response.results[0]["count"] == 1
        assert response.results[0]["data"] == [0, 0, 1, 0]

    def test_trends_aggregation_first_matching_event_for_user_with_breakdown_and_filter_being_the_same(self):
        _create_person(
            team=self.team,
            distinct_ids=["p1"],
            properties={},
        )
        _create_person(
            team=self.team,
            distinct_ids=["p2"],
            properties={},
        )
        _create_person(
            team=self.team,
            distinct_ids=["p3"],
            properties={},
        )

        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id=f"p1",
            timestamp="2020-01-06T12:00:00Z",
            properties={"$browser": "Firefox"},
        )

        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            timestamp="2020-01-10T12:00:00Z",
            properties={"$browser": "Firefox"},
        )

        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p2",
            timestamp="2020-01-10T12:00:00Z",
            properties={"$browser": "Firefox"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p2",
            timestamp="2020-01-11T12:00:00Z",
            properties={"$browser": "Firefox"},
        )

        for i in range(1, 4):
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id=f"p{i}",
                timestamp="2020-01-08T12:00:00Z",
                properties={"$browser": "Chrome"},
            )
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id=f"p{i}",
                timestamp="2020-01-09T12:00:00Z",
                properties={"$browser": "Chrome"},
            )

        flush_persons_and_events()

        response = self._run_trends_query(
            "2020-01-08",
            "2020-01-11",
            IntervalType.DAY,
            [
                EventsNode(
                    event="$pageview",
                    math=BaseMathType.FIRST_MATCHING_EVENT_FOR_USER,
                    properties=[EventPropertyFilter(key="$browser", operator=PropertyOperator.EXACT, value="Firefox")],
                )
            ],
            TrendsFilter(display=ChartDisplayType.ACTIONS_LINE_GRAPH),
            BreakdownFilter(breakdown_type=BreakdownType.EVENT, breakdown="$browser"),
        )

        assert len(response.results) == 1

        # firefox
        assert response.results[0]["breakdown_value"] == "Firefox"
        assert response.results[0]["count"] == 1
        # match on 10th (p2) for third day in time range
        assert response.results[0]["data"] == [0, 0, 1, 0]

    def test_trends_aggregation_first_matching_event_for_user_with_breakdown_and_filter_being_different(self):
        _create_person(
            team=self.team,
            distinct_ids=["p1"],
            properties={},
        )
        _create_person(
            team=self.team,
            distinct_ids=["p2"],
            properties={},
        )

        for i in range(1, 3):
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id=f"p{i}",
                timestamp="2020-01-08T12:00:00Z",
                properties={"$browser": "Chrome", "breakdown_prop": i},
            )
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id=f"p{i}",
                timestamp="2020-01-10T12:00:00Z",
                properties={"$browser": "Firefox", "breakdown_prop": i},
            )
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id=f"p{i}",
                timestamp="2020-01-11T12:00:00Z",
                properties={"$browser": "Firefox", "breakdown_prop": i},
            )
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id=f"p{i}",
                timestamp="2020-01-09T12:00:00Z",
                properties={"$browser": "Chrome", "breakdown_prop": i},
            )

        flush_persons_and_events()

        response = self._run_trends_query(
            "2020-01-08",
            "2020-01-11",
            IntervalType.DAY,
            [
                EventsNode(
                    event="$pageview",
                    math=BaseMathType.FIRST_MATCHING_EVENT_FOR_USER,
                    properties=[EventPropertyFilter(key="$browser", operator=PropertyOperator.EXACT, value="Firefox")],
                )
            ],
            TrendsFilter(display=ChartDisplayType.ACTIONS_LINE_GRAPH),
            BreakdownFilter(breakdown_type=BreakdownType.EVENT, breakdown="breakdown_prop"),
        )

        response.results.sort(key=lambda x: x["breakdown_value"])

        assert len(response.results) == 2

        # 1
        assert response.results[0]["breakdown_value"] == "1"
        assert response.results[0]["count"] == 1
        # match on 10th (p2) for third day in time range
        assert response.results[0]["data"] == [0, 0, 1, 0]

        # 2
        assert response.results[1]["breakdown_value"] == "2"
        assert response.results[1]["count"] == 1
        # match on 10th (p2) for third day in time range
        assert response.results[1]["data"] == [0, 0, 1, 0]

    def test_multiple_formulas_with_compare_to_week(self):
        self._create_test_events()

        response = self._run_trends_query(
            "2020-01-15",
            "2020-01-19",
            IntervalType.DAY,
            [EventsNode(event="$pageview"), EventsNode(event="$pageleave")],
            TrendsFilter(formulas=["A+B", "A-B"]),
            compare_filters=CompareFilter(compare=True, compare_to="-1w"),
        )

        # two formulas, each with current and previous
        self.assertEqual(4, len(response.results))

        # First formula current
        self.assertEqual("current", response.results[0]["compare_label"])
        self.assertEqual("Formula (A+B)", response.results[0]["label"])
        self.assertEqual([2, 1, 1, 0, 1], response.results[0]["data"])

        # First formula previous
        self.assertEqual("previous", response.results[1]["compare_label"])
        self.assertEqual("Formula (A+B)", response.results[1]["label"])
        self.assertEqual([0, 1, 0, 2, 4], response.results[1]["data"])

        # Second formula current
        self.assertEqual("current", response.results[2]["compare_label"])
        self.assertEqual("Formula (A-B)", response.results[2]["label"])
        self.assertEqual([2, -1, 1, 0, 1], response.results[2]["data"])

        # Second formula previous
        self.assertEqual("previous", response.results[3]["compare_label"])
        self.assertEqual("Formula (A-B)", response.results[3]["label"])
        self.assertEqual([0, 1, 0, 0, 2], response.results[3]["data"])

    def test_trends_aggregation_property_avg_person_property(self):
        _create_person(
            team_id=self.team.pk,
            distinct_ids=["p1"],
            properties={"score": 5},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            timestamp="2020-01-11T12:00:00Z",
            properties={"score": 6},  # Event property with same name but different value
        )

        response = self._run_trends_query(
            date_from="2020-01-09",
            date_to="2020-01-19",
            interval=IntervalType.DAY,
            series=[
                EventsNode(
                    event="$pageview",
                    math=PropertyMathType.AVG,
                    math_property="score",
                    math_property_type="person_properties",  # Specify that we want to use the person property
                )
            ],
        )

        self.assertEqual(response.results[0]["count"], 5.0)  # Should use person property value
        self.assertEqual(response.results[0]["data"], [0.0, 0.0, 5.0] + [0.0] * 8)

    def _compare_trends_test(self, compare_filters: CompareFilter):
        """
        Test a TrendsQuery with daily aggregation that has compare to previous period enabled.
        It uses a -7d window, sets the team's timezone to US/Pacific, and generates events at 9PM and 11PM each day.
        """
        # Set the team's timezone to US/Pacific
        self.team.timezone = "US/Pacific"
        self.team.save()

        # Create a person
        _create_person(
            team_id=self.team.pk,
            distinct_ids=["test_user"],
            properties={},
        )

        # Get the current time and generate events for the past 15 days
        # We'll freeze time at 10PM Pacific time
        freeze_time_at = datetime.now(zoneinfo.ZoneInfo("US/Pacific")).replace(
            hour=22, minute=0, second=0, microsecond=0
        )

        # Generate one event at 9PM and another at 11PM each day for the past 16 days.
        # On the first day at 9 PM and on the last day at 11 PM, generate 10 events
        for days_ago in range(0, 15):
            event_date = freeze_time_at - timedelta(days=days_ago)

            # Create event at 9PM
            for _ in range(10 if days_ago == 14 else 1):
                _create_event(
                    team=self.team,
                    event="$pageview",
                    distinct_id="test_user",
                    timestamp=(event_date - timedelta(hours=1)).isoformat(),  # 9PM
                    properties={"key": "value"},
                )

            # Create event at 11PM
            for _ in range(10 if days_ago == 0 else 1):
                _create_event(
                    team=self.team,
                    event="$pageview",
                    distinct_id="test_user",
                    timestamp=(event_date + timedelta(hours=1)).isoformat(),  # 11PM
                    properties={"key": "value"},
                )

        with freeze_time(freeze_time_at.isoformat()):
            response = TrendsQueryRunner(
                query=self._create_trends_query(
                    date_from="-7d",
                    date_to=None,
                    interval=IntervalType.DAY,
                    series=[EventsNode(event="$pageview")],
                    trends_filters=TrendsFilter(display=ChartDisplayType.ACTIONS_LINE_GRAPH),
                    compare_filters=compare_filters,
                ),
                team=self.team,
            ).calculate()

        # Verify the response
        self.assertEqual(2, len(response.results), "Should have 2 results (current and previous period)")

        # Check compare labels
        self.assertEqual("current", response.results[0]["compare_label"])
        self.assertEqual("previous", response.results[1]["compare_label"])

        # Check that each period has 8 days of data (includes one extra day)
        self.assertEqual(8, len(response.results[0]["data"]))
        self.assertEqual(8, len(response.results[1]["data"]))

        # Each day should have 2 events (9PM and 11PM)
        for value in response.results[0]["data"][0:-1]:
            self.assertEqual(2, value)
        self.assertEqual(11, response.results[0]["data"][-1])

        for value in response.results[1]["data"][1:-1]:
            self.assertEqual(2, value)
        self.assertEqual(11, response.results[1]["data"][0])

        # Test with bold number to make sure it represents just a week
        with freeze_time(freeze_time_at.isoformat()):
            response = TrendsQueryRunner(
                query=self._create_trends_query(
                    date_from="-7d",
                    date_to=None,
                    interval=IntervalType.DAY,
                    series=[EventsNode(event="$pageview")],
                    trends_filters=TrendsFilter(display=ChartDisplayType.BOLD_NUMBER),
                    compare_filters=compare_filters,
                ),
                team=self.team,
            ).calculate()

        self.assertEqual(2, len(response.results), "Should have 2 results (current and previous period)")
        for result in response.results:
            self.assertEqual(14, result["aggregated_value"])

    def test_trends_daily_compare_to_previous_period(self):
        self._compare_trends_test(CompareFilter(compare=True))

    def test_trends_daily_compare_to_7_days_ago(self):
        self._compare_trends_test(CompareFilter(compare=True, compare_to="-7d"))
