from typing import Optional, Union
from unittest.case import skip

from django.test import override_settings
from django.utils import timezone
from freezegun import freeze_time

from posthog.hogql_queries.actors_query_runner import ActorsQueryRunner
from posthog.models import Team, Cohort, GroupTypeMapping
from posthog.models.group.util import create_group
from posthog.schema import (
    ActorsQuery,
    BaseMathType,
    BreakdownFilter,
    BreakdownType,
    ChartDisplayType,
    Compare,
    CountPerActorMathType,
    DateRange,
    EventsNode,
    InsightActorsQuery,
    MathGroupTypeIndex,
    PropertyMathType,
    TrendsFilter,
    TrendsQuery,
)
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, _create_person


def get_actors(
    trends_query: TrendsQuery,
    team: Team,
    breakdown: Optional[Union[str, int]] = None,
    compare: Optional[Compare] = None,
    day: Optional[Union[str, int]] = None,
    interval: Optional[int] = None,
    series: Optional[int] = None,
    status: Optional[str] = None,
    offset: Optional[int] = None,
    includeRecordings: Optional[bool] = None,
):
    insight_actors_query = InsightActorsQuery(
        source=trends_query,
        breakdown=breakdown,
        compare=compare,
        day=day,
        interval=interval,
        series=series,
        status=status,
        includeRecordings=includeRecordings,
    )
    actors_query = ActorsQuery(
        source=insight_actors_query,
        offset=offset,
        select=[
            "actor",
            "created_at",
            "event_count",
            *(["matched_recordings"] if includeRecordings else []),
        ],
        orderBy=["event_count DESC"],
    )
    response = ActorsQueryRunner(query=actors_query, team=team).calculate()
    return response.results


def _create_cohort(**kwargs):
    team = kwargs.pop("team")
    name = kwargs.pop("name")
    groups = kwargs.pop("groups")
    cohort = Cohort.objects.create(team=team, name=name, groups=groups, last_calculation=timezone.now())
    cohort.calculate_people_ch(pending_version=0)
    return cohort


def get_distinct_id(result):
    return result[0]["distinct_ids"][0]


def get_group_name(result):
    return result[0]["id"]


def get_event_count(result):
    return result[2]


@override_settings(IN_UNIT_TESTING=True)
class TestTrendsPersons(ClickhouseTestMixin, APIBaseTest):
    maxDiff = None

    def _get_actors(self, trends_query: TrendsQuery, **kwargs):
        return get_actors(trends_query=trends_query, team=self.team, **kwargs, includeRecordings=True)

    def _create_events(self):
        _create_person(
            team_id=self.team.pk,
            distinct_ids=["person1"],
            properties={"$geoip_country_code": "US"},
        )
        _create_person(
            team_id=self.team.pk,
            distinct_ids=["person2"],
            properties={"$geoip_country_code": "DE"},
        )
        _create_person(
            team_id=self.team.pk,
            distinct_ids=["person3"],
            properties={"$geoip_country_code": "DE"},
        )

        _create_event(
            event="$pageview",
            distinct_id="person1",
            timestamp="2023-04-29 16:00",
            properties={"$browser": "Chrome"},
            team=self.team,
        )
        _create_event(
            event="$pageleave",
            distinct_id="person1",
            timestamp="2023-04-29 17:00",
            properties={"$browser": "Chrome"},
            team=self.team,
        )
        _create_event(
            event="$pageview",
            distinct_id="person2",
            timestamp="2023-04-29 17:00",
            properties={"$browser": "Safari"},
            team=self.team,
        )
        _create_event(
            event="$pageview",
            distinct_id="person2",
            timestamp="2023-04-29 18:00",
            properties={"$browser": "Safari"},
            team=self.team,
        )

        _create_event(
            event="$pageview",
            distinct_id="person1",
            timestamp="2023-05-01 16:00",
            properties={"$browser": "Chrome", "some_property": 20},
            team=self.team,
        )
        _create_event(
            event="$pageview",
            distinct_id="person1",
            timestamp="2023-05-01 17:00",
            properties={"$browser": "Chrome"},
            team=self.team,
        )
        _create_event(
            event="$pageview",
            distinct_id="person1",
            timestamp="2023-05-01 18:00",
            properties={"$browser": "Chrome"},
            team=self.team,
        )
        _create_event(
            event="$pageview",
            distinct_id="person2",
            timestamp="2023-05-01 16:00",
            properties={"$browser": "Safari", "some_property": 22},
            team=self.team,
        )
        _create_event(
            event="$pageview",
            distinct_id="person2",
            timestamp="2023-05-01 17:00",
            properties={"$browser": "Safari"},
            team=self.team,
        )
        _create_event(
            event="$pageview",
            distinct_id="person3",
            timestamp="2023-05-01 16:00",
            properties={"$browser": "Safari"},
            team=self.team,
        )

        _create_event(
            event="$pageview",
            distinct_id="person1",
            timestamp="2023-05-06 16:00",
            properties={"some_property": 20},
            team=self.team,
        )

    def test_trends_single_series_persons(self):
        self._create_events()
        source_query = TrendsQuery(
            series=[EventsNode(event="$pageview")],
            dateRange=DateRange(date_from="-7d"),
        )

        result = self._get_actors(trends_query=source_query, day="2023-04-29")

        self.assertEqual(get_distinct_id(result[0]), "person2")
        self.assertEqual(get_event_count(result[0]), 2)
        self.assertEqual(get_distinct_id(result[1]), "person1")
        self.assertEqual(get_event_count(result[1]), 1)

    def test_trends_multiple_series_persons(self):
        self._create_events()
        source_query = TrendsQuery(
            series=[EventsNode(event="$pageview"), EventsNode(event="$pageleave")],
            dateRange=DateRange(date_from="-7d"),
        )

        result = self._get_actors(trends_query=source_query, day="2023-04-29")

        self.assertEqual(len(result), 2)
        self.assertEqual(get_distinct_id(result[0]), "person2")
        self.assertEqual(get_event_count(result[0]), 2)
        self.assertEqual(get_distinct_id(result[1]), "person1")
        self.assertEqual(get_event_count(result[1]), 1)

        result = self._get_actors(trends_query=source_query, day="2023-04-29", series=1)

        self.assertEqual(len(result), 1)
        self.assertEqual(get_distinct_id(result[0]), "person1")
        self.assertEqual(get_event_count(result[0]), 1)

    def test_trends_event_breakdown_persons(self):
        self._create_events()
        source_query = TrendsQuery(
            series=[EventsNode(event="$pageview")],
            dateRange=DateRange(date_from="-7d"),
            breakdownFilter=BreakdownFilter(breakdown="$browser"),
        )

        result = self._get_actors(trends_query=source_query, day="2023-05-01", breakdown="Safari")

        self.assertEqual(len(result), 2)
        self.assertEqual(get_distinct_id(result[0]), "person2")
        self.assertEqual(get_event_count(result[0]), 2)
        self.assertEqual(get_distinct_id(result[1]), "person3")
        self.assertEqual(get_event_count(result[1]), 1)

        result = self._get_actors(trends_query=source_query, day="2023-05-01", breakdown="Firefox")

        self.assertEqual(len(result), 0)

    def test_trends_person_breakdown_persons(self):
        self._create_events()
        source_query = TrendsQuery(
            series=[EventsNode(event="$pageview")],
            dateRange=DateRange(date_from="-7d"),
            breakdownFilter=BreakdownFilter(breakdown="$geoip_country_code", breakdown_type=BreakdownType.person),
        )

        result = self._get_actors(trends_query=source_query, day="2023-05-01", breakdown="DE")

        self.assertEqual(len(result), 2)
        self.assertEqual(get_distinct_id(result[0]), "person2")
        self.assertEqual(get_event_count(result[0]), 2)
        self.assertEqual(get_distinct_id(result[1]), "person3")
        self.assertEqual(get_event_count(result[1]), 1)

        result = self._get_actors(trends_query=source_query, day="2023-05-01", breakdown="UK")

        self.assertEqual(len(result), 0)

    @skip("fails, as other returns all breakdowns, even those that should be display with the breakdown_limit")
    def test_trends_breakdown_others_persons(self):
        self._create_events()
        source_query = TrendsQuery(
            series=[EventsNode(event="$pageview")],
            dateRange=DateRange(date_from="-7d"),
            breakdownFilter=BreakdownFilter(breakdown="$browser", breakdown_limit=1),
        )

        result = self._get_actors(trends_query=source_query, day="2023-04-29", breakdown="Chrome")

        self.assertEqual(len(result), 1)
        self.assertEqual(get_distinct_id(result[0]), "person1")
        self.assertEqual(get_event_count(result[0]), 2)

        result = self._get_actors(
            trends_query=source_query, day="2023-04-29", breakdown="$$_posthog_breakdown_other_$$"
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(get_distinct_id(result[0]), "person2")
        self.assertEqual(get_event_count(result[0]), 2)

    def test_trends_breakdown_null_persons(self):
        self._create_events()
        source_query = TrendsQuery(
            series=[EventsNode(event="$pageview")],
            dateRange=DateRange(date_from="-7d"),
            breakdownFilter=BreakdownFilter(breakdown="$browser", breakdown_limit=1),
        )

        result = self._get_actors(trends_query=source_query, day="2023-05-06", breakdown="Chrome")

        self.assertEqual(len(result), 0)

        result = self._get_actors(trends_query=source_query, day="2023-05-06", breakdown="$$_posthog_breakdown_null_$$")

        self.assertEqual(len(result), 1)
        self.assertEqual(get_distinct_id(result[0]), "person1")
        self.assertEqual(get_event_count(result[0]), 1)

    def test_trends_breakdown_hogql_persons(self):
        self._create_events()
        source_query = TrendsQuery(
            series=[EventsNode(event="$pageview")],
            dateRange=DateRange(date_from="-7d"),
            breakdownFilter=BreakdownFilter(breakdown="properties.some_property", breakdown_type=BreakdownType.hogql),
        )

        result = self._get_actors(trends_query=source_query, day="2023-05-01", breakdown=20)

        self.assertEqual(len(result), 1)
        self.assertEqual(get_distinct_id(result[0]), "person1")
        self.assertEqual(get_event_count(result[0]), 1)

        result = self._get_actors(trends_query=source_query, day="2023-05-01", breakdown=10)

        self.assertEqual(len(result), 0)

    def test_trends_cohort_breakdown_persons(self):
        self._create_events()
        cohort = _create_cohort(
            team=self.team,
            name="DE users",
            groups=[{"properties": [{"key": "$geoip_country_code", "value": "DE", "type": "person"}]}],
        )
        source_query = TrendsQuery(
            series=[EventsNode(event="$pageview")],
            dateRange=DateRange(date_from="-7d"),
            breakdownFilter=BreakdownFilter(breakdown=[cohort.pk], breakdown_type=BreakdownType.cohort),
        )

        result = self._get_actors(trends_query=source_query, day="2023-05-01", breakdown=cohort.pk)

        self.assertEqual(len(result), 2)
        self.assertEqual(get_distinct_id(result[0]), "person2")
        self.assertEqual(get_event_count(result[0]), 2)
        self.assertEqual(get_distinct_id(result[1]), "person3")
        self.assertEqual(get_event_count(result[1]), 1)

    @skip("fails, as cohort breakdown value is seemingly ignored")
    def test_trends_multi_cohort_breakdown_persons(self):
        self._create_events()
        cohort1 = _create_cohort(
            team=self.team,
            name="US users",
            groups=[{"properties": [{"key": "$geoip_country_code", "value": "US", "type": "person"}]}],
        )
        cohort2 = _create_cohort(
            team=self.team,
            name="DE users",
            groups=[{"properties": [{"key": "$geoip_country_code", "value": "DE", "type": "person"}]}],
        )
        source_query = TrendsQuery(
            series=[EventsNode(event="$pageview")],
            dateRange=DateRange(date_from="-7d"),
            breakdownFilter=BreakdownFilter(breakdown=[cohort1.pk, cohort2.pk], breakdown_type=BreakdownType.cohort),
        )

        result = self._get_actors(trends_query=source_query, day="2023-05-01", breakdown=cohort1.pk)

        self.assertEqual(len(result), 1)
        self.assertEqual(get_distinct_id(result[0]), "person1")
        self.assertEqual(get_event_count(result[0]), 2)

        result = self._get_actors(trends_query=source_query, day="2023-05-01", breakdown=cohort2.pk)

        self.assertEqual(len(result), 2)
        self.assertEqual(get_distinct_id(result[0]), "person2")
        self.assertEqual(get_event_count(result[0]), 2)
        self.assertEqual(get_distinct_id(result[1]), "person3")
        self.assertEqual(get_event_count(result[1]), 1)

    @skip("fails, as 'all' cohort can't be resolved")
    def test_trends_all_cohort_breakdown_persons(self):
        self._create_events()
        cohort1 = _create_cohort(
            team=self.team,
            name="US users",
            groups=[{"properties": [{"key": "$geoip_country_code", "value": "US", "type": "person"}]}],
        )
        source_query = TrendsQuery(
            series=[EventsNode(event="$pageview")],
            dateRange=DateRange(date_from="-7d"),
            breakdownFilter=BreakdownFilter(breakdown=[cohort1.pk, "all"], breakdown_type=BreakdownType.cohort),
        )

        result = self._get_actors(trends_query=source_query, day="2023-05-01", breakdown=cohort1.pk)

        self.assertEqual(len(result), 1)
        self.assertEqual(get_distinct_id(result[0]), "person1")
        self.assertEqual(get_event_count(result[0]), 2)

        result = self._get_actors(trends_query=source_query, day="2023-05-01", breakdown="all")

        self.assertEqual(len(result), 3)
        self.assertEqual(get_distinct_id(result[0]), "person1")
        self.assertEqual(get_event_count(result[0]), 2)
        self.assertEqual(get_distinct_id(result[1]), "person2")
        self.assertEqual(get_event_count(result[1]), 2)
        self.assertEqual(get_distinct_id(result[2]), "person3")
        self.assertEqual(get_event_count(result[2]), 1)

    def test_trends_math_weekly_active_persons(self):
        for i in range(17, 24):
            distinct_id = f"person_2023-04-{i}"
            _create_person(
                team_id=self.team.pk,
                distinct_ids=[distinct_id],
            )
            _create_event(
                event="$pageview",
                distinct_id=distinct_id,
                timestamp=f"2023-04-{i} 16:00",
                team=self.team,
            )
        source_query = TrendsQuery(
            series=[EventsNode(event="$pageview", math=BaseMathType.weekly_active)],
            dateRange=DateRange(date_from="-7d"),
        )

        result = self._get_actors(trends_query=source_query, day="2023-04-28")

        self.assertEqual(len(result), 2)
        self.assertEqual(
            {get_distinct_id(result[0]), get_distinct_id(result[1])}, {"person_2023-04-22", "person_2023-04-23"}
        )

    @skip("fails, as event_count isn't populated properly")
    def test_trends_math_property_sum_persons(self):
        self._create_events()
        source_query = TrendsQuery(
            series=[EventsNode(event="$pageview", math=PropertyMathType.sum, math_property="some_property")],
            dateRange=DateRange(date_from="-7d"),
        )

        result = self._get_actors(trends_query=source_query, day="2023-05-01")

        self.assertEqual(len(result), 3)
        self.assertEqual(get_distinct_id(result[0]), "person2")
        self.assertEqual(get_event_count(result[0]), 22)
        self.assertEqual(get_distinct_id(result[1]), "person1")
        self.assertEqual(get_event_count(result[1]), 20)
        self.assertEqual(get_distinct_id(result[2]), "person3")
        self.assertEqual(get_event_count(result[2]), 0)

    @skip("fails, as event_count isn't populated properly")
    def test_trends_math_count_per_actor_persons(self):
        self._create_events()
        source_query = TrendsQuery(
            series=[
                EventsNode(
                    event="$pageview", math=CountPerActorMathType.max_count_per_actor, math_property="some_property"
                )
            ],
            dateRange=DateRange(date_from="-7d"),
        )

        result = self._get_actors(trends_query=source_query, day="2023-05-01")

        self.assertEqual(len(result), 3)
        self.assertEqual(get_distinct_id(result[0]), "person2")
        self.assertEqual(get_event_count(result[0]), 22)
        self.assertEqual(get_distinct_id(result[1]), "person1")
        self.assertEqual(get_event_count(result[1]), 20)
        self.assertEqual(get_distinct_id(result[2]), "person3")
        self.assertEqual(get_event_count(result[2]), 0)

    def test_trends_math_group_persons(self):
        GroupTypeMapping.objects.create(team=self.team, group_type="Company", group_type_index=0)
        create_group(team_id=self.team.pk, group_type_index=0, group_key="Hooli")
        create_group(team_id=self.team.pk, group_type_index=0, group_key="Pied Piper")

        _create_event(
            event="$pageview",
            distinct_id="person1",
            timestamp="2023-05-01 16:00",
            properties={"$group_0": "Hooli"},
            team=self.team,
        )
        _create_event(
            event="$pageview",
            distinct_id="person1",
            timestamp="2023-05-01 17:00",
            properties={"$group_0": "Hooli"},
            team=self.team,
        )
        _create_event(
            event="$pageview",
            distinct_id="person1",
            timestamp="2023-05-01 18:00",
            properties={"$group_0": "Pied Piper"},
            team=self.team,
        )
        source_query = TrendsQuery(
            series=[
                EventsNode(event="$pageview", math="unique_group", math_group_type_index=MathGroupTypeIndex.number_0)
            ],
            dateRange=DateRange(date_from="-7d"),
        )

        result = self._get_actors(trends_query=source_query, day="2023-05-01")

        self.assertEqual(len(result), 2)
        self.assertEqual(get_group_name(result[0]), "Hooli")
        self.assertEqual(get_event_count(result[0]), 2)
        self.assertEqual(get_group_name(result[1]), "Pied Piper")
        self.assertEqual(get_event_count(result[1]), 1)

    def test_trends_math_group_persons_filters_empty(self):
        GroupTypeMapping.objects.create(team=self.team, group_type="Company", group_type_index=0)
        create_group(team_id=self.team.pk, group_type_index=0, group_key="Hooli")
        create_group(team_id=self.team.pk, group_type_index=0, group_key="")

        _create_event(
            event="$pageview",
            distinct_id="person1",
            timestamp="2023-05-01 16:00",
            properties={"$group_0": "Hooli"},
            team=self.team,
        )
        _create_event(
            event="$pageview",
            distinct_id="person1",
            timestamp="2023-05-01 17:00",
            team=self.team,
        )
        source_query = TrendsQuery(
            series=[
                EventsNode(event="$pageview", math="unique_group", math_group_type_index=MathGroupTypeIndex.number_0)
            ],
            dateRange=DateRange(date_from="-7d"),
        )

        result = self._get_actors(trends_query=source_query, day="2023-05-01")

        self.assertEqual(len(result), 1)
        self.assertEqual(get_group_name(result[0]), "Hooli")
        self.assertEqual(get_event_count(result[0]), 1)

    def test_trends_total_value_persons(self):
        self._create_events()
        source_query = TrendsQuery(
            series=[EventsNode(event="$pageview")],
            dateRange=DateRange(date_from="-7d"),
            trendsFilter=TrendsFilter(display=ChartDisplayType.BoldNumber),
        )

        with freeze_time("2023-05-01T20:00:00.000Z"):
            # note: total value actors should be called without day
            result = self._get_actors(trends_query=source_query)

        self.assertEqual(len(result), 3)
        self.assertEqual(get_event_count(result[0]), 4)
        self.assertEqual(get_event_count(result[1]), 4)
        self.assertEqual(get_distinct_id(result[2]), "person3")
        self.assertEqual(get_event_count(result[2]), 1)

    def test_trends_compare_persons(self):
        self._create_events()
        source_query = TrendsQuery(
            series=[EventsNode(event="$pageview")],
            dateRange=DateRange(date_from="-7d"),
            trendsFilter=TrendsFilter(compare=True),
        )

        result = self._get_actors(trends_query=source_query, day="2023-05-06", compare=Compare.current)

        self.assertEqual(len(result), 1)
        self.assertEqual(get_distinct_id(result[0]), "person1")
        self.assertEqual(get_event_count(result[0]), 1)

        result = self._get_actors(trends_query=source_query, day="2023-05-06", compare=Compare.previous)

        self.assertEqual(len(result), 2)
        self.assertEqual(get_distinct_id(result[0]), "person2")
        self.assertEqual(get_event_count(result[0]), 2)
        self.assertEqual(get_distinct_id(result[1]), "person1")
        self.assertEqual(get_event_count(result[1]), 1)
