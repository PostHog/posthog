from typing import Optional, Union
from unittest.case import skip

from django.test import override_settings
from django.utils import timezone

from posthog.hogql_queries.actors_query_runner import ActorsQueryRunner
from posthog.models import Team, Cohort, GroupTypeMapping
from posthog.models.group.util import create_group
from posthog.schema import (
    ActorsQuery,
    BaseMathType,
    BreakdownFilter,
    BreakdownType,
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


# def _create_action(**kwargs):
#     team = kwargs.pop("team")
#     name = kwargs.pop("name")
#     properties = kwargs.pop("properties", {})
#     action = Action.objects.create(team=team, name=name)
#     ActionStep.objects.create(action=action, event=name, properties=properties)
#     return action


def _create_cohort(**kwargs):
    team = kwargs.pop("team")
    name = kwargs.pop("name")
    groups = kwargs.pop("groups")
    cohort = Cohort.objects.create(team=team, name=name, groups=groups, last_calculation=timezone.now())
    cohort.calculate_people_ch(pending_version=0)
    return cohort


# - [x] test_trends_single_series_persons
# - [x] test_trends_multiple_series_persons
# - [x] test_trends_event_breakdown_persons
# - [x] test_trends_person_breakdown_persons
# - [x] test_trends_cohort_breakdown_persons
# - [x] test_trends_mau_persons
# - [x] test_trends_group_persons
# - [ ] test_trends_formula_persons
# - [ ] test_trends_formula_with_breakdown_persons
# - [ ] test_trends_total_value_persons
# - [ ] test_trends_total_value_breakdown_persons
# - [ ] test_trends_compare_persons
# other breakdown
# null breakdown
# hogql breakdown
# sampling
# out of date range?
# property math,
# count math
# interval


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

    def _create_event(self, **kwargs):
        _create_event(**kwargs)

    #     props = kwargs.get("properties")
    #     if props is not None:
    #         for key, value in props.items():
    #             prop_def_exists = PropertyDefinition.objects.filter(team=self.team, name=key).exists()
    #             if prop_def_exists is False:
    #                 if isinstance(value, str):
    #                     type = "String"
    #                 elif isinstance(value, bool):
    #                     type = "Boolean"
    #                 elif isinstance(value, int):
    #                     type = "Numeric"
    #                 else:
    #                     type = "String"

    #                 PropertyDefinition.objects.create(
    #                     team=self.team,
    #                     name=key,
    #                     property_type=type,
    #                     type=PropertyDefinition.Type.EVENT,
    #                 )

    def _create_person(self, **kwargs):
        person = _create_person(**kwargs)
        #     props = kwargs.get("properties")
        #     if props is not None:
        #         for key, value in props.items():
        #             prop_def_exists = PropertyDefinition.objects.filter(team=self.team, name=key).exists()
        #             if prop_def_exists is False:
        #                 if isinstance(value, str):
        #                     type = "String"
        #                 elif isinstance(value, bool):
        #                     type = "Boolean"
        #                 elif isinstance(value, int):
        #                     type = "Numeric"
        #                 else:
        #                     type = "String"

        #                 PropertyDefinition.objects.create(
        #                     team=self.team,
        #                     name=key,
        #                     property_type=type,
        #                     type=PropertyDefinition.Type.PERSON,
        #                 )
        return person

    def _create_group(self, **kwargs):
        create_group(**kwargs)

    #     props = kwargs.get("properties")
    #     index = kwargs.get("group_type_index")

    #     if props is not None:
    #         for key, value in props.items():
    #             prop_def_exists = PropertyDefinition.objects.filter(team=self.team, name=key).exists()
    #             if prop_def_exists is False:
    #                 if isinstance(value, str):
    #                     type = "String"
    #                 elif isinstance(value, bool):
    #                     type = "Boolean"
    #                 elif isinstance(value, int):
    #                     type = "Numeric"
    #                 else:
    #                     type = "String"

    #                 PropertyDefinition.objects.create(
    #                     team=self.team,
    #                     name=key,
    #                     property_type=type,
    #                     group_type_index=index,
    #                     type=PropertyDefinition.Type.GROUP,
    #                 )

    def _create_events(self):
        person1 = self._create_person(
            team_id=self.team.pk,
            distinct_ids=["person1"],
            properties={"$geoip_country_code": "US"},
        )
        person2 = self._create_person(
            team_id=self.team.pk,
            distinct_ids=["person2"],
            properties={"$geoip_country_code": "DE"},
        )
        person3 = self._create_person(
            team_id=self.team.pk,
            distinct_ids=["person3"],
            properties={"$geoip_country_code": "DE"},
        )

        # freeze_without_time = ["2019-12-24", "2020-01-01", "2020-01-02"]
        #     freeze_with_time = [
        #         "2019-12-24 03:45:34",
        #         "2020-01-01 00:06:34",
        #         "2020-01-02 16:34:34",
        #     ]

        # freeze_args = freeze_without_time
        #     if use_time:
        #         freeze_args = freeze_with_time

        # with freeze_time("2024-04-29 16:34:12"):
        self._create_event(
            event="$pageview",
            distinct_id="person1",
            timestamp="2024-04-29 16:00",
            properties={"$browser": "Chrome"},
            team=self.team,
        )
        self._create_event(
            event="$pageleave",
            distinct_id="person1",
            timestamp="2024-04-29 17:00",
            properties={"$browser": "Chrome"},
            team=self.team,
        )
        self._create_event(
            event="$pageview",
            distinct_id="person2",
            timestamp="2024-04-29 17:00",
            properties={"$browser": "Safari"},
            team=self.team,
        )
        self._create_event(
            event="$pageview",
            distinct_id="person2",
            timestamp="2024-04-29 18:00",
            properties={"$browser": "Safari"},
            team=self.team,
        )

        self._create_event(
            event="$pageview",
            distinct_id="person1",
            timestamp="2024-05-01 16:00",
            properties={"$browser": "Chrome", "some_property": 20},
            team=self.team,
        )
        self._create_event(
            event="$pageview",
            distinct_id="person1",
            timestamp="2024-05-01 17:00",
            properties={"$browser": "Chrome"},
            team=self.team,
        )
        self._create_event(
            event="$pageview",
            distinct_id="person1",
            timestamp="2024-05-01 18:00",
            properties={"$browser": "Chrome"},
            team=self.team,
        )
        self._create_event(
            event="$pageview",
            distinct_id="person2",
            timestamp="2024-05-01 16:00",
            properties={"$browser": "Safari", "some_property": 22},
            team=self.team,
        )
        self._create_event(
            event="$pageview",
            distinct_id="person2",
            timestamp="2024-05-01 17:00",
            properties={"$browser": "Safari"},
            team=self.team,
        )
        self._create_event(
            event="$pageview",
            distinct_id="person3",
            timestamp="2024-05-01 16:00",
            properties={"$browser": "Safari"},
            team=self.team,
        )

    #     with freeze_time(freeze_args[1]):
    #         self._create_event(
    #             team=self.team,
    #             event="sign up",
    #             distinct_id="blabla",
    #             properties={"$some_property": "value", "$bool_prop": False},
    #         )
    #         self._create_event(
    #             team=self.team,
    #             event="sign up",
    #             distinct_id="anonymous_id",
    #             properties={"$bool_prop": False},
    #         )
    #         self._create_event(team=self.team, event="sign up", distinct_id="blabla")
    #     with freeze_time(freeze_args[2]):
    #         self._create_event(
    #             team=self.team,
    #             event="sign up",
    #             distinct_id="blabla",
    #             properties={
    #                 "$some_property": "other_value",
    #                 "$some_numerical_prop": 80,
    #             },
    #         )
    #         self._create_event(team=self.team, event="no events", distinct_id="blabla")

    #     _create_action(team=self.team, name="no events")
    #     sign_up_action = _create_action(team=self.team, name="sign up")

    #     flush_persons_and_events()

    #     return sign_up_action, person

    # def _create_breakdown_events(self):
    #     freeze_without_time = ["2020-01-02"]

    #     with freeze_time(freeze_without_time[0]):
    #         for i in range(25):
    #             self._create_event(
    #                 team=self.team,
    #                 event="sign up",
    #                 distinct_id="blabla",
    #                 properties={"$some_property": i},
    #             )
    #     _create_action(team=self.team, name="sign up")

    # def _create_breakdown_url_events(self):
    #     freeze_without_time = ["2020-01-02"]

    #     with freeze_time(freeze_without_time[0]):
    #         self._create_event(
    #             team=self.team,
    #             event="sign up",
    #             distinct_id="blabla",
    #             properties={"$current_url": "http://hogflix/first"},
    #         )
    #         self._create_event(
    #             team=self.team,
    #             event="sign up",
    #             distinct_id="blabla",
    #             properties={"$current_url": "http://hogflix/first/"},
    #         )
    #         self._create_event(
    #             team=self.team,
    #             event="sign up",
    #             distinct_id="blabla",
    #             properties={"$current_url": "http://hogflix/second"},
    #         )

    # def _create_event_count_per_actor_events(self):
    #     self._create_person(
    #         team_id=self.team.pk,
    #         distinct_ids=["blabla", "anonymous_id"],
    #         properties={"fruit": "mango"},
    #     )
    #     self._create_person(team_id=self.team.pk, distinct_ids=["tintin"], properties={"fruit": "mango"})
    #     self._create_person(team_id=self.team.pk, distinct_ids=["murmur"], properties={})  # No fruit here
    #     self._create_person(
    #         team_id=self.team.pk,
    #         distinct_ids=["reeree"],
    #         properties={"fruit": "tomato"},
    #     )

    #     with freeze_time("2020-01-01 00:06:02"):
    #         self._create_event(
    #             team=self.team,
    #             event="viewed video",
    #             distinct_id="anonymous_id",
    #             properties={"color": "red", "$group_0": "bouba"},
    #         )
    #         self._create_event(
    #             team=self.team,
    #             event="viewed video",
    #             distinct_id="blabla",
    #             properties={"$group_0": "bouba"},
    #         )  # No color here
    #         self._create_event(
    #             team=self.team,
    #             event="viewed video",
    #             distinct_id="reeree",
    #             properties={"color": "blue", "$group_0": "bouba"},
    #         )
    #         self._create_event(
    #             team=self.team,
    #             event="sign up",
    #             distinct_id="tintin",
    #             properties={"$group_0": "kiki"},
    #         )

    #     with freeze_time("2020-01-03 19:06:34"):
    #         self._create_event(
    #             team=self.team,
    #             event="sign up",
    #             distinct_id="murmur",
    #             properties={"$group_0": "kiki"},
    #         )

    #     with freeze_time("2020-01-04 23:17:00"):
    #         self._create_event(
    #             team=self.team,
    #             event="viewed video",
    #             distinct_id="tintin",
    #             properties={"color": "red", "$group_0": "kiki"},
    #         )

    #     with freeze_time("2020-01-05 19:06:34"):
    #         self._create_event(
    #             team=self.team,
    #             event="viewed video",
    #             distinct_id="blabla",
    #             properties={"color": "blue", "$group_0": "bouba"},
    #         )
    #         self._create_event(
    #             team=self.team,
    #             event="viewed video",
    #             distinct_id="tintin",
    #             properties={"color": "red"},
    #         )  # No group here
    #         self._create_event(
    #             team=self.team,
    #             event="viewed video",
    #             distinct_id="tintin",
    #             properties={"color": "red", "$group_0": "bouba"},
    #         )
    #         self._create_event(
    #             team=self.team,
    #             event="viewed video",
    #             distinct_id="tintin",
    #             properties={"color": "blue", "$group_0": "kiki"},
    #         )

    def test_trends_single_series_persons(self):
        self._create_events()
        source_query = TrendsQuery(
            series=[EventsNode(event="$pageview")],
            dateRange=DateRange(date_from="-7d"),
        )

        result = self._get_actors(trends_query=source_query, day="2024-04-29")

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

        result = self._get_actors(trends_query=source_query, day="2024-04-29")

        self.assertEqual(len(result), 2)
        self.assertEqual(get_distinct_id(result[0]), "person2")
        self.assertEqual(get_event_count(result[0]), 2)
        self.assertEqual(get_distinct_id(result[1]), "person1")
        self.assertEqual(get_event_count(result[1]), 1)

        result = self._get_actors(trends_query=source_query, day="2024-04-29", series=1)

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

        result = self._get_actors(trends_query=source_query, day="2024-05-01", breakdown="Safari")

        self.assertEqual(len(result), 2)
        self.assertEqual(get_distinct_id(result[0]), "person2")
        self.assertEqual(get_event_count(result[0]), 2)
        self.assertEqual(get_distinct_id(result[1]), "person3")
        self.assertEqual(get_event_count(result[1]), 1)

        result = self._get_actors(trends_query=source_query, day="2024-05-01", breakdown="Firefox")

        self.assertEqual(len(result), 0)

    def test_trends_person_breakdown_persons(self):
        self._create_events()
        source_query = TrendsQuery(
            series=[EventsNode(event="$pageview")],
            dateRange=DateRange(date_from="-7d"),
            breakdownFilter=BreakdownFilter(breakdown="$geoip_country_code", breakdown_type=BreakdownType.person),
        )

        result = self._get_actors(trends_query=source_query, day="2024-05-01", breakdown="DE")

        self.assertEqual(len(result), 2)
        self.assertEqual(get_distinct_id(result[0]), "person2")
        self.assertEqual(get_event_count(result[0]), 2)
        self.assertEqual(get_distinct_id(result[1]), "person3")
        self.assertEqual(get_event_count(result[1]), 1)

        result = self._get_actors(trends_query=source_query, day="2024-05-01", breakdown="UK")

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

        result = self._get_actors(trends_query=source_query, day="2024-05-01", breakdown=cohort.pk)

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

        result = self._get_actors(trends_query=source_query, day="2024-05-01", breakdown=cohort1.pk)

        self.assertEqual(len(result), 1)
        self.assertEqual(get_distinct_id(result[0]), "person1")
        self.assertEqual(get_event_count(result[0]), 2)

        result = self._get_actors(trends_query=source_query, day="2024-05-01", breakdown=cohort2.pk)

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

        result = self._get_actors(trends_query=source_query, day="2024-05-01", breakdown=cohort1.pk)

        self.assertEqual(len(result), 1)
        self.assertEqual(get_distinct_id(result[0]), "person1")
        self.assertEqual(get_event_count(result[0]), 2)

        result = self._get_actors(trends_query=source_query, day="2024-05-01", breakdown="all")

        self.assertEqual(len(result), 3)
        self.assertEqual(get_distinct_id(result[0]), "person1")
        self.assertEqual(get_event_count(result[0]), 2)
        self.assertEqual(get_distinct_id(result[1]), "person2")
        self.assertEqual(get_event_count(result[1]), 2)
        self.assertEqual(get_distinct_id(result[2]), "person3")
        self.assertEqual(get_event_count(result[2]), 1)

    @skip("fails in resolver")
    def test_trends_math_monthly_active_persons(self):
        self._create_events()
        source_query = TrendsQuery(
            series=[EventsNode(event="$pageview", math=BaseMathType.monthly_active)],
            dateRange=DateRange(date_from="-7d"),
        )

        result = self._get_actors(trends_query=source_query, day="2024-05-05")

        self.assertEqual(len(result), 99)
        # self.assertEqual(get_distinct_id(result[0]), "person2")
        # self.assertEqual(get_event_count(result[0]), 2)
        # self.assertEqual(get_distinct_id(result[1]), "person3")
        # self.assertEqual(get_event_count(result[1]), 1)

    @skip("fails, as event_count isn't populated properly")
    def test_trends_math_property_sum_persons(self):
        self._create_events()
        source_query = TrendsQuery(
            series=[EventsNode(event="$pageview", math=PropertyMathType.sum, math_property="some_property")],
            dateRange=DateRange(date_from="-7d"),
        )

        result = self._get_actors(trends_query=source_query, day="2024-05-01")

        self.assertEqual(len(result), 3)
        self.assertEqual(get_distinct_id(result[0]), "person2")
        self.assertEqual(get_event_count(result[0]), 22)
        self.assertEqual(get_distinct_id(result[1]), "person1")
        self.assertEqual(get_event_count(result[1]), 20)
        self.assertEqual(get_distinct_id(result[2]), "person3")
        self.assertEqual(get_event_count(result[2]), 0)

    @skip("fails in resolver")
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

        result = self._get_actors(trends_query=source_query, day="2024-05-01")

        self.assertEqual(len(result), 3)
        self.assertEqual(get_distinct_id(result[0]), "person2")
        self.assertEqual(get_event_count(result[0]), 22)
        self.assertEqual(get_distinct_id(result[1]), "person1")
        self.assertEqual(get_event_count(result[1]), 20)
        self.assertEqual(get_distinct_id(result[2]), "person3")
        self.assertEqual(get_event_count(result[2]), 0)

    def test_trends_math_group_persons(self):
        GroupTypeMapping.objects.create(team=self.team, group_type="Company", group_type_index=0)
        self._create_group(team_id=self.team.pk, group_type_index=0, group_key="Hooli")
        self._create_group(team_id=self.team.pk, group_type_index=0, group_key="Pied Piper")

        self._create_event(
            event="$pageview",
            distinct_id="person1",
            timestamp="2024-05-01 16:00",
            properties={"$group_0": "Hooli"},
            team=self.team,
        )
        self._create_event(
            event="$pageview",
            distinct_id="person1",
            timestamp="2024-05-01 17:00",
            properties={"$group_0": "Hooli"},
            team=self.team,
        )
        self._create_event(
            event="$pageview",
            distinct_id="person1",
            timestamp="2024-05-01 18:00",
            properties={"$group_0": "Pied Piper"},
            team=self.team,
        )
        source_query = TrendsQuery(
            series=[
                EventsNode(event="$pageview", math="unique_group", math_group_type_index=MathGroupTypeIndex.number_0)
            ],
            dateRange=DateRange(date_from="-7d"),
        )

        result = self._get_actors(trends_query=source_query, day="2024-05-01")

        self.assertEqual(len(result), 2)
        self.assertEqual(get_group_name(result[0]), "Hooli")
        self.assertEqual(get_event_count(result[0]), 2)
        self.assertEqual(get_group_name(result[1]), "Pied Piper")
        self.assertEqual(get_event_count(result[1]), 1)

    def test_trends_formula_persons(self):
        self._create_events()
        source_query = TrendsQuery(
            series=[EventsNode(event="$pageview"), EventsNode(event="$pageleave")],
            dateRange=DateRange(date_from="-7d"),
            trendsFilter=TrendsFilter(formula="A+B"),
        )

        result = self._get_actors(trends_query=source_query, day="2024-04-29")

        self.assertEqual(len(result), 2)
        self.assertEqual(get_distinct_id(result[0]), "person2")
        self.assertEqual(get_event_count(result[0]), 2)
        self.assertEqual(get_distinct_id(result[1]), "person1")
        self.assertEqual(get_event_count(result[1]), 2)


# breakdown: Optional[Union[str, int]] = (None,)
# compare: Optional[Compare] = (None,)
# day: Optional[Union[str, int]] = (None,)
# interval: Optional[int] = (None,)
# series: Optional[int] = (None,)
# status: Optional[str] = (None,)
# offset: Optional[int] = (None,)
