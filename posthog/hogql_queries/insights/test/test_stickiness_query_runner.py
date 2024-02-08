from dataclasses import dataclass
from typing import Dict, List, Optional, Union
from django.test import override_settings

from freezegun import freeze_time
from posthog.hogql_queries.insights.stickiness_query_runner import StickinessQueryRunner
from posthog.models.action.action import Action
from posthog.models.action_step import ActionStep
from posthog.models.group.util import create_group
from posthog.models.group_type_mapping import GroupTypeMapping
from posthog.models.property_definition import PropertyDefinition
from posthog.schema import (
    ActionsNode,
    CohortPropertyFilter,
    DateRange,
    ElementPropertyFilter,
    EmptyPropertyFilter,
    EventPropertyFilter,
    EventsNode,
    FeaturePropertyFilter,
    GroupPropertyFilter,
    HogQLPropertyFilter,
    IntervalType,
    MathGroupTypeIndex,
    PersonPropertyFilter,
    PropertyGroupFilter,
    PropertyOperator,
    RecordingDurationFilter,
    SessionPropertyFilter,
    StickinessFilter,
    StickinessQuery,
    StickinessQueryResponse,
)
from posthog.test.base import APIBaseTest, _create_event, _create_person


@dataclass
class Series:
    event: str
    timestamps: List[str]


@dataclass
class SeriesTestData:
    distinct_id: str
    events: List[Series]
    properties: Dict[str, str | int]


StickinessProperties = Union[
    List[
        Union[
            EventPropertyFilter,
            PersonPropertyFilter,
            ElementPropertyFilter,
            SessionPropertyFilter,
            CohortPropertyFilter,
            RecordingDurationFilter,
            GroupPropertyFilter,
            FeaturePropertyFilter,
            HogQLPropertyFilter,
            EmptyPropertyFilter,
        ]
    ],
    PropertyGroupFilter,
]


class TestStickinessQueryRunner(APIBaseTest):
    default_date_from = "2020-01-11"
    default_date_to = "2020-01-20"

    def _create_events(self, data: List[SeriesTestData]):
        person_result = []
        properties_to_create: Dict[str, str] = {}
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

    def _create_test_groups(self):
        GroupTypeMapping.objects.create(team=self.team, group_type="organization", group_type_index=0)

        create_group(
            team_id=self.team.pk,
            group_type_index=0,
            group_key="org:1",
        )

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
                                "2020-01-14T12:00:00Z",
                                "2020-01-15T12:00:00Z",
                                "2020-01-16T12:00:00Z",
                                "2020-01-17T12:00:00Z",
                                "2020-01-18T12:00:00Z",
                                "2020-01-19T12:00:00Z",
                            ],
                        ),
                        Series(
                            event="$pageleave",
                            timestamps=[
                                "2020-01-11T12:00:00Z",
                                "2020-01-12T12:00:00Z",
                                "2020-01-13T12:00:00Z",
                                "2020-01-14T12:00:00Z",
                                "2020-01-15T12:00:00Z",
                                "2020-01-16T12:00:00Z",
                                "2020-01-17T12:00:00Z",
                                "2020-01-18T12:00:00Z",
                                "2020-01-19T12:00:00Z",
                            ],
                        ),
                    ],
                    properties={"$browser": "Chrome", "prop": 10, "bool_field": True, "$group_0": "org:1"},
                ),
                SeriesTestData(
                    distinct_id="p2",
                    events=[
                        Series(
                            event="$pageview",
                            timestamps=[
                                "2020-01-11T12:00:00Z",
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
                                "2020-01-13T12:00:00Z",
                                "2020-01-15T12:00:00Z",
                                "2020-01-17T12:00:00Z",
                                "2020-01-19T12:00:00Z",
                            ],
                        ),
                    ],
                    properties={"$browser": "Firefox", "prop": 10, "bool_field": False, "$group_0": "org:1"},
                ),
            ]
        )

    def _run_query(
        self,
        series: Optional[List[EventsNode | ActionsNode]] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        interval: Optional[IntervalType] = None,
        properties: Optional[StickinessProperties] = None,
        filters: Optional[StickinessFilter] = None,
        filter_test_accounts: Optional[bool] = False,
    ):
        query_series: List[EventsNode | ActionsNode] = [EventsNode(event="$pageview")] if series is None else series
        query_date_from = date_from or self.default_date_from
        query_date_to = None if date_to == "now" else date_to or self.default_date_to
        query_interval = interval or IntervalType.day

        query = StickinessQuery(
            series=query_series,
            dateRange=DateRange(date_from=query_date_from, date_to=query_date_to),
            interval=query_interval,
            properties=properties,
            stickinessFilter=filters,
            filterTestAccounts=filter_test_accounts,
        )
        return StickinessQueryRunner(team=self.team, query=query).calculate()

    def test_stickiness_runs(self):
        self._create_test_events()

        response = self._run_query()
        assert isinstance(response, StickinessQueryResponse)
        assert isinstance(response.results, List)
        assert isinstance(response.results[0], Dict)

    @override_settings(PERSON_ON_EVENTS_V2_OVERRIDE=True)
    def test_stickiness_runs_with_poe(self):
        self._create_test_events()

        response = self._run_query()
        assert isinstance(response, StickinessQueryResponse)
        assert isinstance(response.results, List)
        assert isinstance(response.results[0], Dict)

    def test_days(self):
        self._create_test_events()

        response = self._run_query()

        result = response.results[0]

        assert result["days"] == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]

    def test_count(self):
        self._create_test_events()

        response = self._run_query()

        result = response.results[0]

        assert result["count"] == 2

    def test_labels(self):
        self._create_test_events()

        response = self._run_query()

        result = response.results[0]

        assert result["label"] == "$pageview"
        assert result["labels"] == [
            "1 day",
            "2 days",
            "3 days",
            "4 days",
            "5 days",
            "6 days",
            "7 days",
            "8 days",
            "9 days",
            "10 days",
        ]

    def test_interval_hour(self):
        self._create_test_events()

        response = self._run_query(interval=IntervalType.hour, date_from="2020-01-11", date_to="2020-01-12")

        result = response.results[0]

        hours_labels = [f"{hour + 1} hour{'' if hour == 0 else 's'}" for hour in range(25)]
        hours_data = [0] * 25
        hours_data[0] = 2

        assert result["label"] == "$pageview"
        assert result["labels"] == hours_labels
        assert result["days"] == [hour + 1 for hour in range(25)]
        assert result["data"] == hours_data

    def test_interval_hour_last_days(self):
        self._create_test_events()

        with freeze_time("2020-01-20T12:00:00Z"):
            response = self._run_query(interval=IntervalType.hour, date_from="-2d", date_to="now")
            result = response.results[0]
            # 61 = 48 + 12 + 1
            hours_labels = [f"{hour + 1} hour{'' if hour == 0 else 's'}" for hour in range(61)]
            hours_data = [0] * 61
            hours_data[0] = 1
            hours_data[1] = 1

            assert result["label"] == "$pageview"
            assert result["labels"] == hours_labels
            assert result["days"] == [hour + 1 for hour in range(61)]
            assert result["data"] == hours_data

    def test_interval_day(self):
        self._create_test_events()

        response = self._run_query(interval=IntervalType.day)

        result = response.results[0]

        assert result["label"] == "$pageview"
        assert result["labels"] == [
            "1 day",
            "2 days",
            "3 days",
            "4 days",
            "5 days",
            "6 days",
            "7 days",
            "8 days",
            "9 days",
            "10 days",
        ]
        assert result["days"] == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
        assert result["data"] == [
            0,
            0,
            0,
            0,
            1,
            0,
            0,
            0,
            1,
            0,
        ]

    def test_interval_week(self):
        self._create_test_events()

        response = self._run_query(interval=IntervalType.week)

        result = response.results[0]

        assert result["label"] == "$pageview"
        assert result["labels"] == ["1 week", "2 weeks", "3 weeks"]
        assert result["days"] == [1, 2, 3]
        assert result["data"] == [0, 0, 2]

    def test_interval_full_weeks(self):
        self._create_test_events()

        with freeze_time("2020-01-23T12:00:00Z"):
            response = self._run_query(interval=IntervalType.week, date_from="-30d", date_to="now")

            result = response.results[0]

            assert result["label"] == "$pageview"
            assert result["labels"] == ["1 week", "2 weeks", "3 weeks", "4 weeks", "5 weeks"]
            assert result["days"] == [1, 2, 3, 4, 5]
            assert result["data"] == [0, 0, 2, 0, 0]

    def test_interval_month(self):
        self._create_test_events()

        response = self._run_query(interval=IntervalType.month)

        result = response.results[0]

        assert result["label"] == "$pageview"
        assert result["labels"] == ["1 month"]
        assert result["days"] == [1]
        assert result["data"] == [2]

    def test_property_filtering(self):
        self._create_test_events()

        response = self._run_query(
            properties=[EventPropertyFilter(key="$browser", operator=PropertyOperator.exact, value="Chrome")]
        )

        result = response.results[0]

        assert result["data"] == [
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            1,
            0,
        ]

    def test_property_filtering_hogql(self):
        self._create_test_events()

        response = self._run_query(properties=[HogQLPropertyFilter(key="properties.$browser == 'Chrome'")])

        result = response.results[0]

        assert result["data"] == [
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            1,
            0,
        ]

    def test_event_filtering(self):
        self._create_test_events()

        series: List[EventsNode | ActionsNode] = [
            EventsNode(
                event="$pageview",
                properties=[EventPropertyFilter(key="$browser", operator=PropertyOperator.exact, value="Chrome")],
            )
        ]

        response = self._run_query(series=series)

        result = response.results[0]

        assert result["data"] == [
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            1,
            0,
        ]

    def test_any_event(self):
        self._create_test_events()

        series: List[EventsNode | ActionsNode] = [
            EventsNode(
                event=None,
            )
        ]

        response = self._run_query(series=series)

        result = response.results[0]

        assert result["label"] == "All events"
        assert result["data"] == [
            0,
            0,
            0,
            0,
            1,
            0,
            0,
            0,
            1,
            0,
        ]

    def test_actions(self):
        self._create_test_events()

        action = Action.objects.create(name="My Action", team=self.team)
        ActionStep.objects.create(
            action=action,
            event="$pageview",
            properties=[{"key": "$browser", "type": "event", "value": "Chrome", "operator": "exact"}],
        )

        series: List[EventsNode | ActionsNode] = [ActionsNode(id=action.pk)]

        response = self._run_query(series=series)

        result = response.results[0]

        assert result["data"] == [
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            1,
            0,
        ]

    def test_compare(self):
        self._create_test_events()

        response = self._run_query(filters=StickinessFilter(compare=True))

        assert response.results[0]["count"] == 2
        assert response.results[0]["compare_label"] == "current"

        assert response.results[1]["count"] == 0
        assert response.results[1]["compare_label"] == "previous"

    def test_filter_test_accounts(self):
        self._create_test_events()

        self.team.test_account_filters = [{"key": "$browser", "type": "event", "value": "Chrome", "operator": "exact"}]
        self.team.save()

        response = self._run_query(filter_test_accounts=True)

        result = response.results[0]

        assert result["data"] == [
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            1,
            0,
        ]

    def test_group_aggregations(self):
        self._create_test_groups()
        self._create_test_events()

        series: List[EventsNode | ActionsNode] = [
            EventsNode(event="$pageview", math="unique_group", math_group_type_index=MathGroupTypeIndex.number_0)
        ]

        response = self._run_query(series=series)

        result = response.results[0]

        assert result["data"] == [
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            1,
            0,
        ]

    def test_hogql_aggregations(self):
        self._create_test_events()

        series: List[EventsNode | ActionsNode] = [
            EventsNode(event="$pageview", math="hogql", math_hogql="e.properties.prop")
        ]

        response = self._run_query(series=series)

        result = response.results[0]

        assert result["data"] == [
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            1,
            0,
        ]
