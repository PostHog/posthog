from datetime import datetime
from typing import cast

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, _create_person
from unittest.mock import Mock, patch

from posthog.schema import FunnelsQuery

from posthog.constants import INSIGHT_FUNNELS, FunnelOrderType
from posthog.hogql_queries.insights.funnels.funnels_query_runner import FunnelsQueryRunner
from posthog.hogql_queries.insights.funnels.test.breakdown_cases import (
    assert_funnel_results_equal,
    funnel_breakdown_group_test_factory,
    funnel_breakdown_test_factory,
)
from posthog.hogql_queries.insights.funnels.test.conversion_time_cases import funnel_conversion_time_test_factory
from posthog.hogql_queries.insights.funnels.test.test_funnel import PseudoFunnelActors
from posthog.hogql_queries.legacy_compatibility.filter_to_query import filter_to_query
from posthog.models.action import Action
from posthog.models.filters import Filter
from posthog.models.instance_setting import override_instance_config
from posthog.test.test_journeys import journeys_for

FORMAT_TIME = "%Y-%m-%d 00:00:00"


def _create_action(**kwargs):
    team = kwargs.pop("team")
    name = kwargs.pop("name")
    properties = kwargs.pop("properties", {})
    action = Action.objects.create(team=team, name=name, steps_json=[{"event": name, "properties": properties}])
    return action


class BaseTestFunnelStrictStepsBreakdown(
    ClickhouseTestMixin,
    funnel_breakdown_test_factory(  # type: ignore
        FunnelOrderType.STRICT,
        PseudoFunnelActors,
        _create_action,
        _create_person,
    ),
):
    __test__ = False
    maxDiff = None

    def test_basic_funnel_default_funnel_days_breakdown_event(self):
        # TODO: This test and the one below it fail, only for strict funnels. Figure out why and how to fix
        pass

    def test_basic_funnel_default_funnel_days_breakdown_action(self):
        pass

    def test_basic_funnel_default_funnel_days_breakdown_action_materialized(self):
        pass

    def test_strict_breakdown_events_with_multiple_properties(self):
        filters = {
            "insight": INSIGHT_FUNNELS,
            "funnel_order_type": "strict",
            "events": [{"id": "sign up", "order": 0}, {"id": "play movie", "order": 1}],
            "date_from": "2020-01-01",
            "date_to": "2020-01-08",
            "funnel_window_days": 7,
            "breakdown_type": "event",
            "breakdown": "$browser",
        }

        people = journeys_for(
            {
                "person1": [
                    {
                        "event": "sign up",
                        "timestamp": datetime(2020, 1, 1, 12),
                        "properties": {"$browser": "Chrome"},
                    },
                    {
                        "event": "blah",
                        "timestamp": datetime(2020, 1, 1, 13),
                        "properties": {"$browser": "Chrome"},
                    },
                    {
                        "event": "play movie",
                        "timestamp": datetime(2020, 1, 1, 14),
                        "properties": {"$browser": "Chrome"},
                    },
                ],
                "person2": [
                    {
                        "event": "sign up",
                        "timestamp": datetime(2020, 1, 2, 13),
                        "properties": {"$browser": "Safari"},
                    },
                    {
                        "event": "play movie",
                        "timestamp": datetime(2020, 1, 2, 14),
                        "properties": {"$browser": "Safari"},
                    },
                ],
            },
            self.team,
        )

        query = cast(FunnelsQuery, filter_to_query(filters))
        results = FunnelsQueryRunner(query=query, team=self.team).calculate().results

        assert_funnel_results_equal(
            results[0],
            [
                {
                    "action_id": "sign up",
                    "name": "sign up",
                    "custom_name": None,
                    "order": 0,
                    "people": [],
                    "count": 1,
                    "type": "events",
                    "average_conversion_time": None,
                    "median_conversion_time": None,
                    "breakdown": ["Safari"],
                    "breakdown_value": ["Safari"],
                },
                {
                    "action_id": "play movie",
                    "name": "play movie",
                    "custom_name": None,
                    "order": 1,
                    "people": [],
                    "count": 1,
                    "type": "events",
                    "average_conversion_time": 3600,
                    "median_conversion_time": 3600,
                    "breakdown": ["Safari"],
                    "breakdown_value": ["Safari"],
                },
            ],
        )
        self.assertCountEqual(self._get_actor_ids_at_step(filters, 1, ["Safari"]), [people["person2"].uuid])
        self.assertCountEqual(self._get_actor_ids_at_step(filters, 2, ["Safari"]), [people["person2"].uuid])

        assert_funnel_results_equal(
            results[1],
            [
                {
                    "action_id": "sign up",
                    "name": "sign up",
                    "custom_name": None,
                    "order": 0,
                    "people": [],
                    "count": 1,
                    "type": "events",
                    "average_conversion_time": None,
                    "median_conversion_time": None,
                    "breakdown": ["Chrome"],
                    "breakdown_value": ["Chrome"],
                },
                {
                    "action_id": "play movie",
                    "name": "play movie",
                    "custom_name": None,
                    "order": 1,
                    "people": [],
                    "count": 0,
                    "type": "events",
                    "average_conversion_time": None,
                    "median_conversion_time": None,
                    "breakdown": ["Chrome"],
                    "breakdown_value": ["Chrome"],
                },
            ],
        )
        self.assertCountEqual(self._get_actor_ids_at_step(filters, 1, ["Chrome"]), [people["person1"].uuid])
        self.assertCountEqual(self._get_actor_ids_at_step(filters, 2, ["Chrome"]), [])


class BaseTestStrictFunnelGroupBreakdown(
    ClickhouseTestMixin,
    funnel_breakdown_group_test_factory(  # type: ignore
        FunnelOrderType.STRICT,
        PseudoFunnelActors,
    ),
):
    __test__ = False


class BaseTestFunnelStrictStepsConversionTime(
    ClickhouseTestMixin,
    funnel_conversion_time_test_factory(FunnelOrderType.ORDERED, PseudoFunnelActors),  # type: ignore
):
    maxDiff = None
    __test__ = False


class BaseTestFunnelStrictSteps(ClickhouseTestMixin, APIBaseTest):
    maxDiff = None
    __test__ = False

    def _get_actor_ids_at_step(self, filter, funnel_step, breakdown_value=None):
        filter = Filter(data=filter, team=self.team)
        person_filter = filter.shallow_clone({"funnel_step": funnel_step, "funnel_step_breakdown": breakdown_value})
        _, serialized_result, _ = PseudoFunnelActors(person_filter, self.team).get_actors()

        return [val["id"] for val in serialized_result]

    def test_basic_strict_funnel(self):
        filters = {
            "insight": INSIGHT_FUNNELS,
            "funnel_order_type": "strict",
            "events": [
                {"id": "user signed up", "order": 0},
                {"id": "$pageview", "order": 1},
                {"id": "insight viewed", "order": 2},
            ],
        }

        person1_stopped_after_signup = _create_person(
            distinct_ids=["stopped_after_signup1"],
            team_id=self.team.pk,
            properties={"test": "okay"},
        )
        _create_event(team=self.team, event="user signed up", distinct_id="stopped_after_signup1")

        person2_stopped_after_one_pageview = _create_person(
            distinct_ids=["stopped_after_pageview1"], team_id=self.team.pk
        )
        _create_event(team=self.team, event="$pageview", distinct_id="stopped_after_pageview1")
        _create_event(
            team=self.team,
            event="user signed up",
            distinct_id="stopped_after_pageview1",
        )

        person3_stopped_after_insight_view = _create_person(
            distinct_ids=["stopped_after_insightview"], team_id=self.team.pk
        )
        _create_event(
            team=self.team,
            event="user signed up",
            distinct_id="stopped_after_insightview",
        )
        _create_event(team=self.team, event="$pageview", distinct_id="stopped_after_insightview")
        _create_event(team=self.team, event="blaah blaa", distinct_id="stopped_after_insightview")
        _create_event(
            team=self.team,
            event="insight viewed",
            distinct_id="stopped_after_insightview",
        )

        person4_stopped_after_insight_view_not_strict_order = _create_person(
            distinct_ids=["stopped_after_insightview2"], team_id=self.team.pk
        )
        _create_event(
            team=self.team,
            event="insight viewed",
            distinct_id="stopped_after_insightview2",
        )
        _create_event(team=self.team, event="blaah blaa", distinct_id="stopped_after_insightview2")
        _create_event(team=self.team, event="$pageview", distinct_id="stopped_after_insightview2")
        _create_event(
            team=self.team,
            event="user signed up",
            distinct_id="stopped_after_insightview2",
        )

        person5_stopped_after_insight_view_random = _create_person(
            distinct_ids=["stopped_after_insightview3"], team_id=self.team.pk
        )
        _create_event(team=self.team, event="$pageview", distinct_id="stopped_after_insightview3")
        _create_event(
            team=self.team,
            event="user signed up",
            distinct_id="stopped_after_insightview3",
        )
        _create_event(team=self.team, event="blaah blaa", distinct_id="stopped_after_insightview3")
        _create_event(team=self.team, event="$pageview", distinct_id="stopped_after_insightview3")
        _create_event(
            team=self.team,
            event="insight viewed",
            distinct_id="stopped_after_insightview3",
        )

        person6 = _create_person(distinct_ids=["person6"], team_id=self.team.pk)
        _create_event(team=self.team, event="blaah blaa", distinct_id="person6")
        _create_event(team=self.team, event="user signed up", distinct_id="person6")
        _create_event(team=self.team, event="blaah blaa", distinct_id="person6")
        _create_event(team=self.team, event="$pageview", distinct_id="person6")

        person7 = _create_person(distinct_ids=["person7"], team_id=self.team.pk)
        _create_event(team=self.team, event="blaah blaa", distinct_id="person7")
        _create_event(team=self.team, event="user signed up", distinct_id="person7")
        _create_event(team=self.team, event="$pageview", distinct_id="person7")
        _create_event(team=self.team, event="insight viewed", distinct_id="person7")
        _create_event(team=self.team, event="blaah blaa", distinct_id="person7")

        _create_person(distinct_ids=["stopped_after_insightview6"], team_id=self.team.pk)
        _create_event(
            team=self.team,
            event="insight viewed",
            distinct_id="stopped_after_insightview6",
        )
        _create_event(team=self.team, event="$pageview", distinct_id="stopped_after_insightview6")

        query = cast(FunnelsQuery, filter_to_query(filters))
        results = FunnelsQueryRunner(query=query, team=self.team).calculate().results

        self.assertEqual(results[0]["name"], "user signed up")
        self.assertEqual(results[1]["name"], "$pageview")
        self.assertEqual(results[2]["name"], "insight viewed")
        self.assertEqual(results[0]["count"], 7)

        self.assertCountEqual(
            self._get_actor_ids_at_step(filters, 1),
            [
                person1_stopped_after_signup.uuid,
                person2_stopped_after_one_pageview.uuid,
                person3_stopped_after_insight_view.uuid,
                person4_stopped_after_insight_view_not_strict_order.uuid,
                person5_stopped_after_insight_view_random.uuid,
                person6.uuid,
                person7.uuid,
            ],
        )

        self.assertCountEqual(
            self._get_actor_ids_at_step(filters, 2),
            [person3_stopped_after_insight_view.uuid, person7.uuid],
        )

        self.assertCountEqual(self._get_actor_ids_at_step(filters, 3), [person7.uuid])

        with override_instance_config("AGGREGATE_BY_DISTINCT_IDS_TEAMS", f"{self.team.pk}"):
            results = FunnelsQueryRunner(query=query, team=self.team).calculate().results
            self.assertEqual(results[0]["name"], "user signed up")
            self.assertEqual(results[1]["name"], "$pageview")
            self.assertEqual(results[2]["name"], "insight viewed")
            self.assertEqual(results[0]["count"], 7)

    def test_advanced_strict_funnel(self):
        sign_up_action = _create_action(
            name="sign up",
            team=self.team,
            properties=[{"key": "key", "type": "event", "value": ["val"], "operator": "exact"}],
        )

        view_action = _create_action(
            name="pageview",
            team=self.team,
            properties=[{"key": "key", "type": "event", "value": ["val"], "operator": "exact"}],
        )

        filters = {
            "insight": INSIGHT_FUNNELS,
            "funnel_order_type": "strict",
            "events": [
                {"id": "user signed up", "type": "events", "order": 0},
                {"id": "$pageview", "type": "events", "order": 2},
            ],
            "actions": [
                {"id": sign_up_action.id, "math": "dau", "order": 1},
                {"id": view_action.id, "math": "weekly_active", "order": 3},
            ],
        }

        person1_stopped_after_signup = _create_person(distinct_ids=["stopped_after_signup1"], team_id=self.team.pk)
        _create_event(team=self.team, event="user signed up", distinct_id="stopped_after_signup1")

        person2_stopped_after_one_pageview = _create_person(
            distinct_ids=["stopped_after_pageview1"], team_id=self.team.pk
        )
        _create_event(
            team=self.team,
            event="user signed up",
            distinct_id="stopped_after_pageview1",
        )
        _create_event(team=self.team, event="$pageview", distinct_id="stopped_after_pageview1")

        person3_stopped_after_insight_view = _create_person(
            distinct_ids=["stopped_after_insightview"], team_id=self.team.pk
        )
        _create_event(
            team=self.team,
            event="user signed up",
            distinct_id="stopped_after_insightview",
        )
        _create_event(
            team=self.team,
            event="sign up",
            distinct_id="stopped_after_insightview",
            properties={"key": "val"},
        )
        _create_event(
            team=self.team,
            event="sign up",
            distinct_id="stopped_after_insightview",
            properties={"key": "val2"},
        )
        _create_event(team=self.team, event="$pageview", distinct_id="stopped_after_insightview")
        _create_event(team=self.team, event="blaah blaa", distinct_id="stopped_after_insightview")
        _create_event(
            team=self.team,
            event="insight viewed",
            distinct_id="stopped_after_insightview",
        )

        person4 = _create_person(distinct_ids=["person4"], team_id=self.team.pk)
        _create_event(team=self.team, event="blaah blaa", distinct_id="person4")
        _create_event(team=self.team, event="user signed up", distinct_id="person4")
        _create_event(
            team=self.team,
            event="sign up",
            distinct_id="person4",
            properties={"key": "val"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="person4",
            properties={"key": "val"},
        )
        _create_event(team=self.team, event="blaah blaa", distinct_id="person4")

        person5 = _create_person(distinct_ids=["person5"], team_id=self.team.pk)
        _create_event(team=self.team, event="blaah blaa", distinct_id="person5")
        _create_event(team=self.team, event="user signed up", distinct_id="person5")
        _create_event(
            team=self.team,
            event="sign up",
            distinct_id="person5",
            properties={"key": "val"},
        )
        _create_event(team=self.team, event="$pageview", distinct_id="person5")
        _create_event(team=self.team, event="blaah blaa", distinct_id="person5")

        person6 = _create_person(distinct_ids=["person6"], team_id=self.team.pk)
        _create_event(team=self.team, event="blaah blaa", distinct_id="person6")
        _create_event(team=self.team, event="user signed up", distinct_id="person6")
        _create_event(
            team=self.team,
            event="sign up",
            distinct_id="person6",
            properties={"key": "val"},
        )
        _create_event(team=self.team, event="$pageview", distinct_id="person6")
        _create_event(
            team=self.team,
            event="pageview",
            distinct_id="person6",
            properties={"key": "val1"},
        )

        person7 = _create_person(distinct_ids=["person7"], team_id=self.team.pk)
        _create_event(team=self.team, event="blaah blaa", distinct_id="person7")
        _create_event(team=self.team, event="user signed up", distinct_id="person7")
        _create_event(
            team=self.team,
            event="sign up",
            distinct_id="person7",
            properties={"key": "val"},
        )
        _create_event(team=self.team, event="$pageview", distinct_id="person7")
        _create_event(team=self.team, event="user signed up", distinct_id="person7")
        _create_event(
            team=self.team,
            event="pageview",
            distinct_id="person7",
            properties={"key": "val"},
        )

        person8 = _create_person(distinct_ids=["person8"], team_id=self.team.pk)
        _create_event(team=self.team, event="blaah blaa", distinct_id="person8")
        _create_event(team=self.team, event="user signed up", distinct_id="person8")
        _create_event(team=self.team, event="user signed up", distinct_id="person8")
        _create_event(
            team=self.team,
            event="sign up",
            distinct_id="person8",
            properties={"key": "val"},
        )
        _create_event(team=self.team, event="$pageview", distinct_id="person8")
        _create_event(
            team=self.team,
            event="pageview",
            distinct_id="person8",
            properties={"key": "val"},
        )

        query = cast(FunnelsQuery, filter_to_query(filters))
        results = FunnelsQueryRunner(query=query, team=self.team).calculate().results

        self.assertEqual(results[0]["name"], "user signed up")
        self.assertEqual(results[1]["name"], "sign up")
        self.assertEqual(results[2]["name"], "$pageview")
        self.assertEqual(results[3]["name"], "pageview")
        self.assertEqual(results[0]["count"], 8)

        self.assertCountEqual(
            self._get_actor_ids_at_step(filters, 1),
            [
                person1_stopped_after_signup.uuid,
                person2_stopped_after_one_pageview.uuid,
                person3_stopped_after_insight_view.uuid,
                person4.uuid,
                person5.uuid,
                person6.uuid,
                person7.uuid,
                person8.uuid,
            ],
        )

        self.assertCountEqual(
            self._get_actor_ids_at_step(filters, 2),
            [
                person3_stopped_after_insight_view.uuid,
                person4.uuid,
                person5.uuid,
                person6.uuid,
                person7.uuid,
                person8.uuid,
            ],
        )

        self.assertCountEqual(
            self._get_actor_ids_at_step(filters, 3),
            [person4.uuid, person5.uuid, person6.uuid, person7.uuid, person8.uuid],
        )

        self.assertCountEqual(self._get_actor_ids_at_step(filters, 4), [person8.uuid])

    def test_basic_strict_funnel_conversion_times(self):
        filters = {
            "insight": INSIGHT_FUNNELS,
            "funnel_order_type": "strict",
            "events": [
                {"id": "user signed up", "order": 0},
                {"id": "$pageview", "order": 1},
                {"id": "insight viewed", "order": 2},
            ],
            "date_from": "2021-05-01 00:00:00",
            "date_to": "2021-05-07 23:59:59",
        }

        person1_stopped_after_signup = _create_person(distinct_ids=["stopped_after_signup1"], team_id=self.team.pk)
        _create_event(
            team=self.team,
            event="user signed up",
            distinct_id="stopped_after_signup1",
            timestamp="2021-05-02 00:00:00",
        )

        person2_stopped_after_one_pageview = _create_person(
            distinct_ids=["stopped_after_pageview1"], team_id=self.team.pk
        )
        _create_event(
            team=self.team,
            event="user signed up",
            distinct_id="stopped_after_pageview1",
            timestamp="2021-05-02 00:00:00",
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="stopped_after_pageview1",
            timestamp="2021-05-02 01:00:00",
        )

        person3_stopped_after_insight_view = _create_person(
            distinct_ids=["stopped_after_insightview"], team_id=self.team.pk
        )
        _create_event(
            team=self.team,
            event="user signed up",
            distinct_id="stopped_after_insightview",
            timestamp="2021-05-02 00:00:00",
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="stopped_after_insightview",
            timestamp="2021-05-02 02:00:00",
        )
        _create_event(
            team=self.team,
            event="insight viewed",
            distinct_id="stopped_after_insightview",
            timestamp="2021-05-02 04:00:00",
        )

        query = cast(FunnelsQuery, filter_to_query(filters))
        results = FunnelsQueryRunner(query=query, team=self.team).calculate().results

        self.assertEqual(results[0]["name"], "user signed up")
        self.assertEqual(results[1]["name"], "$pageview")
        self.assertEqual(results[2]["name"], "insight viewed")
        self.assertEqual(results[0]["count"], 3)

        self.assertEqual(results[1]["average_conversion_time"], 5400)
        # 1 hour for Person 2, 2 hours for Person 3, average = 1.5 hours

        self.assertEqual(results[2]["average_conversion_time"], 7200)
        # 2 hours for Person 3

        self.assertCountEqual(
            self._get_actor_ids_at_step(filters, 1),
            [
                person1_stopped_after_signup.uuid,
                person2_stopped_after_one_pageview.uuid,
                person3_stopped_after_insight_view.uuid,
            ],
        )

        self.assertCountEqual(
            self._get_actor_ids_at_step(filters, 2),
            [
                person2_stopped_after_one_pageview.uuid,
                person3_stopped_after_insight_view.uuid,
            ],
        )

        self.assertCountEqual(
            self._get_actor_ids_at_step(filters, 3),
            [person3_stopped_after_insight_view.uuid],
        )


@patch("posthoganalytics.feature_enabled", new=Mock(return_value=False))
class TestFunnelStrictStepsBreakdown(BaseTestFunnelStrictStepsBreakdown):
    __test__ = True


@patch("posthoganalytics.feature_enabled", new=Mock(return_value=False))
class TestFunnelStrictSteps(BaseTestFunnelStrictSteps):
    __test__ = True


@patch("posthoganalytics.feature_enabled", new=Mock(return_value=False))
class TestStrictFunnelGroupBreakdown(BaseTestStrictFunnelGroupBreakdown):
    __test__ = True


@patch("posthoganalytics.feature_enabled", new=Mock(return_value=False))
class TestFunnelStrictStepsConversionTime(BaseTestFunnelStrictStepsConversionTime):
    __test__ = True
