from datetime import datetime

from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    snapshot_clickhouse_queries,
)

from rest_framework.exceptions import ValidationError

from posthog.constants import INSIGHT_FUNNELS
from posthog.models.action import Action
from posthog.models.filters import Filter
from posthog.queries.funnels.funnel_unordered import ClickhouseFunnelUnordered
from posthog.queries.funnels.funnel_unordered_persons import ClickhouseFunnelUnorderedActors
from posthog.queries.funnels.test.breakdown_cases import (
    FunnelStepResult,
    assert_funnel_results_equal,
    funnel_breakdown_test_factory,
)
from posthog.queries.funnels.test.conversion_time_cases import funnel_conversion_time_test_factory
from posthog.test.test_journeys import journeys_for

FORMAT_TIME = "%Y-%m-%d 00:00:00"


def _create_action(**kwargs):
    team = kwargs.pop("team")
    name = kwargs.pop("name")
    properties = kwargs.pop("properties", {})
    action = Action.objects.create(team=team, name=name, steps_json=[{"event": name, "properties": properties}])
    return action


class TestFunnelUnorderedStepsBreakdown(
    ClickhouseTestMixin,
    funnel_breakdown_test_factory(  # type: ignore
        ClickhouseFunnelUnordered,
        ClickhouseFunnelUnorderedActors,
        _create_event,
        _create_action,
        _create_person,
    ),
):
    maxDiff = None

    def test_funnel_step_breakdown_event_single_person_events_with_multiple_properties(self):
        # overriden from factory

        filters = {
            "events": [{"id": "sign up", "order": 0}, {"id": "play movie", "order": 1}],
            "insight": INSIGHT_FUNNELS,
            "date_from": "2020-01-01",
            "date_to": "2020-01-08",
            "funnel_window_days": 7,
            "breakdown_type": "event",
            "breakdown": "$browser",
            "breakdown_attribution_type": "all_events",
        }

        filter = Filter(data=filters)
        funnel = ClickhouseFunnelUnordered(filter, self.team)

        # event
        person1 = _create_person(distinct_ids=["person1"], team_id=self.team.pk)
        _create_event(
            team=self.team,
            event="sign up",
            distinct_id="person1",
            properties={"key": "val", "$browser": "Chrome"},
            timestamp="2020-01-01T12:00:00Z",
        )
        _create_event(
            team=self.team,
            event="sign up",
            distinct_id="person1",
            properties={"key": "val", "$browser": "Safari"},
            timestamp="2020-01-02T13:00:00Z",
        )
        _create_event(
            team=self.team,
            event="play movie",
            distinct_id="person1",
            properties={"key": "val", "$browser": "Safari"},
            timestamp="2020-01-02T14:00:00Z",
        )

        result = funnel.run()

        assert_funnel_results_equal(
            result[0],
            [
                {
                    "action_id": None,
                    "name": "Completed 1 step",
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
                    "action_id": None,
                    "name": "Completed 2 steps",
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
        self.assertCountEqual(self._get_actor_ids_at_step(filter, 1, ["Safari"]), [person1.uuid])
        self.assertCountEqual(self._get_actor_ids_at_step(filter, 2, ["Safari"]), [person1.uuid])

        assert_funnel_results_equal(
            result[1],
            [
                {
                    "action_id": None,
                    "name": "Completed 1 step",
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
                    "action_id": None,
                    "name": "Completed 2 steps",
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
        self.assertCountEqual(self._get_actor_ids_at_step(filter, 1, ["Chrome"]), [person1.uuid])
        self.assertCountEqual(self._get_actor_ids_at_step(filter, 2, ["Chrome"]), [])

    def test_funnel_step_breakdown_with_step_attribution(self):
        # overridden from factory, since with no order, step one is step zero, and vice versa

        filters = {
            "events": [{"id": "sign up", "order": 0}, {"id": "buy", "order": 1}],
            "insight": INSIGHT_FUNNELS,
            "date_from": "2020-01-01",
            "date_to": "2020-01-08",
            "funnel_window_days": 7,
            "breakdown_type": "event",
            "breakdown": ["$browser"],
            "breakdown_attribution_type": "step",
            "breakdown_attribution_value": "0",
            "funnel_order_type": "unordered",
        }

        filter = Filter(data=filters)
        funnel = ClickhouseFunnelUnordered(filter, self.team)

        # event
        events_by_person = {
            "person1": [
                {
                    "event": "sign up",
                    "timestamp": datetime(2020, 1, 1, 12),
                    "properties": {"$browser": "Chrome"},
                },
                {"event": "buy", "timestamp": datetime(2020, 1, 1, 13)},
            ],
            "person2": [
                {"event": "sign up", "timestamp": datetime(2020, 1, 1, 13)},
                {
                    "event": "buy",
                    "timestamp": datetime(2020, 1, 2, 13),
                    "properties": {"$browser": "Safari"},
                },
            ],
            "person3": [
                {
                    "event": "sign up",
                    "timestamp": datetime(2020, 1, 2, 14),
                    "properties": {"$browser": "Mac"},
                },
                {"event": "buy", "timestamp": datetime(2020, 1, 2, 15)},
            ],
            "person4": [
                {
                    "event": "sign up",
                    "timestamp": datetime(2020, 1, 2, 15),
                    "properties": {"$browser": 0},
                },
                # step attribution means alakazam is valid when step = 1
                {
                    "event": "buy",
                    "timestamp": datetime(2020, 1, 2, 16),
                    "properties": {"$browser": "alakazam"},
                },
            ],
        }
        people = journeys_for(events_by_person, self.team)

        result = funnel.run()
        result = sorted(result, key=lambda res: res[0]["breakdown"])

        self.assertEqual(len(result), 6)

        self.assertCountEqual(self._get_actor_ids_at_step(filter, 1, "Mac"), [people["person3"].uuid])

    def test_funnel_step_breakdown_with_step_one_attribution(self):
        # overridden from factory, since with no order, step one is step zero, and vice versa
        filters = {
            "events": [{"id": "sign up", "order": 0}, {"id": "buy", "order": 1}],
            "insight": INSIGHT_FUNNELS,
            "date_from": "2020-01-01",
            "date_to": "2020-01-08",
            "funnel_window_days": 7,
            "breakdown_type": "event",
            "breakdown": ["$browser"],
            "breakdown_attribution_type": "step",
            "breakdown_attribution_value": "1",
            "funnel_order_type": "unordered",
        }

        filter = Filter(data=filters)
        funnel = ClickhouseFunnelUnordered(filter, self.team)

        # event
        events_by_person = {
            "person1": [
                {
                    "event": "sign up",
                    "timestamp": datetime(2020, 1, 1, 12),
                    "properties": {"$browser": "Chrome"},
                },
                {"event": "buy", "timestamp": datetime(2020, 1, 1, 13)},
            ],
            "person2": [
                {"event": "sign up", "timestamp": datetime(2020, 1, 1, 13)},
                {
                    "event": "buy",
                    "timestamp": datetime(2020, 1, 2, 13),
                    "properties": {"$browser": "Safari"},
                },
            ],
            "person3": [
                {
                    "event": "sign up",
                    "timestamp": datetime(2020, 1, 2, 14),
                    "properties": {"$browser": "Mac"},
                },
                {"event": "buy", "timestamp": datetime(2020, 1, 2, 15)},
            ],
            "person4": [
                {
                    "event": "sign up",
                    "timestamp": datetime(2020, 1, 2, 15),
                    "properties": {"$browser": 0},
                },
                # step attribution means alakazam is valid when step = 1
                {
                    "event": "buy",
                    "timestamp": datetime(2020, 1, 2, 16),
                    "properties": {"$browser": "alakazam"},
                },
            ],
        }
        people = journeys_for(events_by_person, self.team)

        result = funnel.run()
        result = sorted(result, key=lambda res: res[0]["breakdown"])

        self.assertEqual(len(result), 6)
        # unordered, so everything is step one too.

        self._assert_funnel_breakdown_result_is_correct(
            result[0],
            [
                FunnelStepResult(name="Completed 1 step", breakdown=[""], count=3),
                FunnelStepResult(
                    name="Completed 2 steps",
                    breakdown=[""],
                    count=2,
                    average_conversion_time=3600,
                    median_conversion_time=3600,
                ),
            ],
        )

        self.assertCountEqual(
            self._get_actor_ids_at_step(filter, 1, ""),
            [people["person1"].uuid, people["person2"].uuid, people["person3"].uuid],
        )
        self.assertCountEqual(
            self._get_actor_ids_at_step(filter, 2, ""),
            [people["person1"].uuid, people["person3"].uuid],
        )

        self._assert_funnel_breakdown_result_is_correct(
            result[1],
            [
                FunnelStepResult(name="Completed 1 step", breakdown=["0"], count=1),
                FunnelStepResult(name="Completed 2 steps", breakdown=["0"], count=0),
            ],
        )

        self.assertCountEqual(self._get_actor_ids_at_step(filter, 1, "0"), [people["person4"].uuid])

    def test_funnel_step_breakdown_with_step_one_attribution_incomplete_funnel(self):
        # overridden from factory, since with no order, step one is step zero, and vice versa

        filters = {
            "events": [{"id": "sign up", "order": 0}, {"id": "buy", "order": 1}],
            "insight": INSIGHT_FUNNELS,
            "date_from": "2020-01-01",
            "date_to": "2020-01-08",
            "funnel_window_days": 7,
            "breakdown_type": "event",
            "breakdown": ["$browser"],
            "breakdown_attribution_type": "step",
            "breakdown_attribution_value": "1",
            "funnel_order_type": "unordered",
        }

        filter = Filter(data=filters)
        funnel = ClickhouseFunnelUnordered(filter, self.team)

        # event
        events_by_person = {
            "person1": [
                {
                    "event": "sign up",
                    "timestamp": datetime(2020, 1, 1, 12),
                    "properties": {"$browser": "Chrome"},
                },
                {"event": "buy", "timestamp": datetime(2020, 1, 1, 13)},
            ],
            "person2": [
                {"event": "sign up", "timestamp": datetime(2020, 1, 1, 13)},
                # {"event": "buy", "timestamp": datetime(2020, 1, 2, 13), "properties": {"$browser": "Safari"}}
            ],
            "person3": [
                {
                    "event": "sign up",
                    "timestamp": datetime(2020, 1, 2, 14),
                    "properties": {"$browser": "Mac"},
                },
                # {"event": "buy", "timestamp": datetime(2020, 1, 2, 15)}
            ],
            "person4": [
                {
                    "event": "sign up",
                    "timestamp": datetime(2020, 1, 2, 15),
                    "properties": {"$browser": 0},
                },
                # step attribution means alakazam is valid when step = 1
                {
                    "event": "buy",
                    "timestamp": datetime(2020, 1, 2, 16),
                    "properties": {"$browser": "alakazam"},
                },
            ],
        }
        people = journeys_for(events_by_person, self.team)

        result = funnel.run()
        result = sorted(result, key=lambda res: res[0]["breakdown"])

        # Breakdown by step_1 means funnel items that never reach step_1 are NULLed out
        self.assertEqual(len(result), 4)
        # Chrome and Mac and Safari goes away

        self._assert_funnel_breakdown_result_is_correct(
            result[0],
            [
                FunnelStepResult(name="Completed 1 step", breakdown=[""], count=1),
                FunnelStepResult(
                    name="Completed 2 steps",
                    breakdown=[""],
                    count=1,
                    average_conversion_time=3600,
                    median_conversion_time=3600,
                ),
            ],
        )

        self.assertCountEqual(self._get_actor_ids_at_step(filter, 1, ""), [people["person1"].uuid])

        self._assert_funnel_breakdown_result_is_correct(
            result[1],
            [
                FunnelStepResult(name="Completed 1 step", breakdown=["0"], count=1),
                FunnelStepResult(name="Completed 2 steps", breakdown=["0"], count=0),
            ],
        )

        self.assertCountEqual(self._get_actor_ids_at_step(filter, 1, "0"), [people["person4"].uuid])

        self._assert_funnel_breakdown_result_is_correct(
            result[2],
            [
                FunnelStepResult(name="Completed 1 step", breakdown=["Chrome"], count=1),
                FunnelStepResult(name="Completed 2 steps", breakdown=["Chrome"], count=0),
            ],
        )

        self.assertCountEqual(self._get_actor_ids_at_step(filter, 1, "Chrome"), [people["person1"].uuid])

        self._assert_funnel_breakdown_result_is_correct(
            result[3],
            [
                FunnelStepResult(name="Completed 1 step", breakdown=["alakazam"], count=1),
                FunnelStepResult(
                    name="Completed 2 steps",
                    breakdown=["alakazam"],
                    count=1,
                    average_conversion_time=3600,
                    median_conversion_time=3600,
                ),
            ],
        )

        self.assertCountEqual(self._get_actor_ids_at_step(filter, 1, "alakazam"), [people["person4"].uuid])

    def test_funnel_step_non_array_breakdown_with_step_one_attribution_incomplete_funnel(self):
        # overridden from factory, since with no order, step one is step zero, and vice versa

        filters = {
            "events": [{"id": "sign up", "order": 0}, {"id": "buy", "order": 1}],
            "insight": INSIGHT_FUNNELS,
            "date_from": "2020-01-01",
            "date_to": "2020-01-08",
            "funnel_window_days": 7,
            "breakdown_type": "event",
            "breakdown": "$browser",
            "breakdown_attribution_type": "step",
            "breakdown_attribution_value": "1",
            "funnel_order_type": "unordered",
        }

        filter = Filter(data=filters)
        funnel = ClickhouseFunnelUnordered(filter, self.team)

        # event
        events_by_person = {
            "person1": [
                {
                    "event": "sign up",
                    "timestamp": datetime(2020, 1, 1, 12),
                    "properties": {"$browser": "Chrome"},
                },
                {"event": "buy", "timestamp": datetime(2020, 1, 1, 13)},
            ],
            "person2": [
                {"event": "sign up", "timestamp": datetime(2020, 1, 1, 13)},
                # {"event": "buy", "timestamp": datetime(2020, 1, 2, 13), "properties": {"$browser": "Safari"}}
            ],
            "person3": [
                {
                    "event": "sign up",
                    "timestamp": datetime(2020, 1, 2, 14),
                    "properties": {"$browser": "Mac"},
                },
                # {"event": "buy", "timestamp": datetime(2020, 1, 2, 15)}
            ],
            "person4": [
                {
                    "event": "sign up",
                    "timestamp": datetime(2020, 1, 2, 15),
                    "properties": {"$browser": 0},
                },
                # step attribution means alakazam is valid when step = 1
                {
                    "event": "buy",
                    "timestamp": datetime(2020, 1, 2, 16),
                    "properties": {"$browser": "alakazam"},
                },
            ],
        }
        people = journeys_for(events_by_person, self.team)

        result = funnel.run()
        result = sorted(result, key=lambda res: res[0]["breakdown"])

        # Breakdown by step_1 means funnel items that never reach step_1 are NULLed out
        self.assertEqual(len(result), 4)
        # Chrome and Mac and Safari goes away

        self._assert_funnel_breakdown_result_is_correct(
            result[0],
            [
                FunnelStepResult(name="Completed 1 step", breakdown=[""], count=1),
                FunnelStepResult(
                    name="Completed 2 steps",
                    breakdown=[""],
                    count=1,
                    average_conversion_time=3600,
                    median_conversion_time=3600,
                ),
            ],
        )

        self.assertCountEqual(self._get_actor_ids_at_step(filter, 1, ""), [people["person1"].uuid])

        self._assert_funnel_breakdown_result_is_correct(
            result[1],
            [
                FunnelStepResult(name="Completed 1 step", breakdown=["0"], count=1),
                FunnelStepResult(name="Completed 2 steps", breakdown=["0"], count=0),
            ],
        )

        self.assertCountEqual(self._get_actor_ids_at_step(filter, 1, "0"), [people["person4"].uuid])

        self._assert_funnel_breakdown_result_is_correct(
            result[2],
            [
                FunnelStepResult(name="Completed 1 step", breakdown=["Chrome"], count=1),
                FunnelStepResult(name="Completed 2 steps", breakdown=["Chrome"], count=0),
            ],
        )

        self.assertCountEqual(self._get_actor_ids_at_step(filter, 1, "Chrome"), [people["person1"].uuid])

        self._assert_funnel_breakdown_result_is_correct(
            result[3],
            [
                FunnelStepResult(name="Completed 1 step", breakdown=["alakazam"], count=1),
                FunnelStepResult(
                    name="Completed 2 steps",
                    breakdown=["alakazam"],
                    count=1,
                    average_conversion_time=3600,
                    median_conversion_time=3600,
                ),
            ],
        )

        self.assertCountEqual(self._get_actor_ids_at_step(filter, 1, "alakazam"), [people["person4"].uuid])

    @snapshot_clickhouse_queries
    def test_funnel_breakdown_correct_breakdown_props_are_chosen_for_step(self):
        # No person querying here, so snapshots are more legible
        # overridden from factory, since we need to add `funnel_order_type`

        filters = {
            "events": [
                {"id": "sign up", "order": 0},
                {
                    "id": "buy",
                    "properties": [{"type": "event", "key": "$version", "value": "xyz"}],
                    "order": 1,
                },
            ],
            "insight": INSIGHT_FUNNELS,
            "date_from": "2020-01-01",
            "date_to": "2020-01-08",
            "funnel_window_days": 7,
            "breakdown_type": "event",
            "breakdown": "$browser",
            "breakdown_attribution_type": "step",
            "breakdown_attribution_value": "1",
            "funnel_order_type": "unordered",
        }

        filter = Filter(data=filters)
        funnel = ClickhouseFunnelUnordered(filter, self.team)

        # event
        events_by_person = {
            "person1": [
                {
                    "event": "sign up",
                    "timestamp": datetime(2020, 1, 1, 12),
                    "properties": {"$browser": "Chrome", "$version": "xyz"},
                },
                {
                    "event": "buy",
                    "timestamp": datetime(2020, 1, 1, 13),
                    "properties": {"$browser": "Chrome"},
                },
                # discarded because doesn't meet criteria
            ],
            "person2": [
                {"event": "sign up", "timestamp": datetime(2020, 1, 1, 13)},
                {
                    "event": "buy",
                    "timestamp": datetime(2020, 1, 2, 13),
                    "properties": {"$browser": "Safari", "$version": "xyz"},
                },
            ],
            "person3": [
                {
                    "event": "sign up",
                    "timestamp": datetime(2020, 1, 2, 14),
                    "properties": {"$browser": "Mac"},
                },
                {
                    "event": "buy",
                    "timestamp": datetime(2020, 1, 2, 15),
                    "properties": {"$version": "xyz", "$browser": "Mac"},
                },
            ],
            # no properties dude, doesn't make it to step 1, and since breakdown on step 1, is discarded completely
            "person5": [
                {"event": "sign up", "timestamp": datetime(2020, 1, 2, 15)},
                {"event": "buy", "timestamp": datetime(2020, 1, 2, 16)},
            ],
        }
        journeys_for(events_by_person, self.team)

        result = funnel.run()
        result = sorted(result, key=lambda res: res[0]["breakdown"])

        self.assertEqual(len(result), 3)

        self.assertCountEqual([res[0]["breakdown"] for res in result], [[""], ["Mac"], ["Safari"]])


class TestFunnelUnorderedStepsConversionTime(
    ClickhouseTestMixin,
    funnel_conversion_time_test_factory(  # type: ignore
        ClickhouseFunnelUnordered,
        ClickhouseFunnelUnorderedActors,
        _create_event,
        _create_person,
    ),
):
    maxDiff = None
    pass


class TestFunnelUnorderedSteps(ClickhouseTestMixin, APIBaseTest):
    def _get_actor_ids_at_step(self, filter, funnel_step, breakdown_value=None):
        person_filter = filter.shallow_clone({"funnel_step": funnel_step, "funnel_step_breakdown": breakdown_value})
        _, serialized_result, _ = ClickhouseFunnelUnorderedActors(person_filter, self.team).get_actors()

        return [val["id"] for val in serialized_result]

    def test_basic_unordered_funnel(self):
        filter = Filter(
            data={
                "insight": INSIGHT_FUNNELS,
                "events": [
                    {"id": "user signed up", "order": 0},
                    {"id": "$pageview", "order": 1},
                    {"id": "insight viewed", "order": 2},
                ],
            }
        )

        funnel = ClickhouseFunnelUnordered(filter, self.team)

        person1_stopped_after_signup = _create_person(distinct_ids=["stopped_after_signup1"], team_id=self.team.pk)
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

        person4_stopped_after_insight_view_reverse_order = _create_person(
            distinct_ids=["stopped_after_insightview2"], team_id=self.team.pk
        )
        _create_event(
            team=self.team,
            event="insight viewed",
            distinct_id="stopped_after_insightview2",
        )
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
        _create_event(
            team=self.team,
            event="insight viewed",
            distinct_id="stopped_after_insightview3",
        )

        person6_did_only_insight_view = _create_person(
            distinct_ids=["stopped_after_insightview4"], team_id=self.team.pk
        )
        _create_event(team=self.team, event="blaah blaa", distinct_id="stopped_after_insightview4")
        _create_event(
            team=self.team,
            event="insight viewed",
            distinct_id="stopped_after_insightview4",
        )

        person7_did_only_pageview = _create_person(distinct_ids=["stopped_after_insightview5"], team_id=self.team.pk)
        _create_event(team=self.team, event="$pageview", distinct_id="stopped_after_insightview5")
        _create_event(team=self.team, event="blaah blaa", distinct_id="stopped_after_insightview5")

        person8_didnot_signup = _create_person(distinct_ids=["stopped_after_insightview6"], team_id=self.team.pk)
        _create_event(
            team=self.team,
            event="insight viewed",
            distinct_id="stopped_after_insightview6",
        )
        _create_event(team=self.team, event="$pageview", distinct_id="stopped_after_insightview6")

        result = funnel.run()

        self.assertEqual(result[0]["name"], "Completed 1 step")
        self.assertEqual(result[0]["count"], 8)
        self.assertEqual(result[1]["name"], "Completed 2 steps")
        self.assertEqual(result[1]["count"], 5)
        self.assertEqual(result[2]["name"], "Completed 3 steps")
        self.assertEqual(result[2]["count"], 3)

        self.assertCountEqual(
            self._get_actor_ids_at_step(filter, 1),
            [
                person1_stopped_after_signup.uuid,
                person2_stopped_after_one_pageview.uuid,
                person3_stopped_after_insight_view.uuid,
                person4_stopped_after_insight_view_reverse_order.uuid,
                person5_stopped_after_insight_view_random.uuid,
                person6_did_only_insight_view.uuid,
                person7_did_only_pageview.uuid,
                person8_didnot_signup.uuid,
            ],
        )

        self.assertCountEqual(
            self._get_actor_ids_at_step(filter, 2),
            [
                person2_stopped_after_one_pageview.uuid,
                person3_stopped_after_insight_view.uuid,
                person4_stopped_after_insight_view_reverse_order.uuid,
                person5_stopped_after_insight_view_random.uuid,
                person8_didnot_signup.uuid,
            ],
        )

        self.assertCountEqual(
            self._get_actor_ids_at_step(filter, -2),
            [
                person1_stopped_after_signup.uuid,
                person6_did_only_insight_view.uuid,
                person7_did_only_pageview.uuid,
            ],
        )

        self.assertCountEqual(
            self._get_actor_ids_at_step(filter, 3),
            [
                person3_stopped_after_insight_view.uuid,
                person4_stopped_after_insight_view_reverse_order.uuid,
                person5_stopped_after_insight_view_random.uuid,
            ],
        )

        self.assertCountEqual(
            self._get_actor_ids_at_step(filter, -3),
            [person2_stopped_after_one_pageview.uuid, person8_didnot_signup.uuid],
        )

    def test_big_multi_step_unordered_funnel(self):
        filter = Filter(
            data={
                "insight": INSIGHT_FUNNELS,
                "events": [
                    {"id": "user signed up", "order": 0},
                    {"id": "$pageview", "order": 1},
                    {"id": "insight viewed", "order": 2},
                    {"id": "crying", "order": 3},
                ],
            }
        )

        person1_stopped_after_signup = _create_person(distinct_ids=["stopped_after_signup1"], team_id=self.team.pk)
        _create_event(team=self.team, event="user signed up", distinct_id="stopped_after_signup1")

        person2_stopped_after_one_pageview = _create_person(
            distinct_ids=["stopped_after_pageview1"], team_id=self.team.pk
        )
        _create_event(team=self.team, event="$pageview", distinct_id="stopped_after_pageview1")
        _create_event(team=self.team, event="crying", distinct_id="stopped_after_pageview1")

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

        person4_stopped_after_insight_view_reverse_order = _create_person(
            distinct_ids=["stopped_after_insightview2"], team_id=self.team.pk
        )
        _create_event(
            team=self.team,
            event="insight viewed",
            distinct_id="stopped_after_insightview2",
        )
        _create_event(team=self.team, event="crying", distinct_id="stopped_after_insightview2")
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
        _create_event(team=self.team, event="crying", distinct_id="stopped_after_insightview3")
        _create_event(
            team=self.team,
            event="insight viewed",
            distinct_id="stopped_after_insightview3",
        )

        person6_did_only_insight_view = _create_person(
            distinct_ids=["stopped_after_insightview4"], team_id=self.team.pk
        )
        _create_event(team=self.team, event="blaah blaa", distinct_id="stopped_after_insightview4")
        _create_event(
            team=self.team,
            event="insight viewed",
            distinct_id="stopped_after_insightview4",
        )

        person7_did_only_pageview = _create_person(distinct_ids=["stopped_after_insightview5"], team_id=self.team.pk)
        _create_event(team=self.team, event="$pageview", distinct_id="stopped_after_insightview5")
        _create_event(team=self.team, event="blaah blaa", distinct_id="stopped_after_insightview5")

        person8_didnot_signup = _create_person(distinct_ids=["stopped_after_insightview6"], team_id=self.team.pk)
        _create_event(
            team=self.team,
            event="insight viewed",
            distinct_id="stopped_after_insightview6",
        )
        _create_event(team=self.team, event="$pageview", distinct_id="stopped_after_insightview6")

        funnel = ClickhouseFunnelUnordered(filter, self.team)
        result = funnel.run()

        self.assertEqual(result[0]["name"], "Completed 1 step")
        self.assertEqual(result[0]["count"], 8)
        self.assertEqual(result[1]["name"], "Completed 2 steps")
        self.assertEqual(result[1]["count"], 5)
        self.assertEqual(result[2]["name"], "Completed 3 steps")
        self.assertEqual(result[2]["count"], 3)
        self.assertEqual(result[3]["name"], "Completed 4 steps")
        self.assertEqual(result[3]["count"], 1)

        self.assertCountEqual(
            self._get_actor_ids_at_step(filter, 1),
            [
                person1_stopped_after_signup.uuid,
                person2_stopped_after_one_pageview.uuid,
                person3_stopped_after_insight_view.uuid,
                person4_stopped_after_insight_view_reverse_order.uuid,
                person5_stopped_after_insight_view_random.uuid,
                person6_did_only_insight_view.uuid,
                person7_did_only_pageview.uuid,
                person8_didnot_signup.uuid,
            ],
        )

        self.assertCountEqual(
            self._get_actor_ids_at_step(filter, 2),
            [
                person2_stopped_after_one_pageview.uuid,
                person3_stopped_after_insight_view.uuid,
                person4_stopped_after_insight_view_reverse_order.uuid,
                person5_stopped_after_insight_view_random.uuid,
                person8_didnot_signup.uuid,
            ],
        )

        self.assertCountEqual(
            self._get_actor_ids_at_step(filter, 3),
            [
                person3_stopped_after_insight_view.uuid,
                person4_stopped_after_insight_view_reverse_order.uuid,
                person5_stopped_after_insight_view_random.uuid,
            ],
        )

        self.assertCountEqual(
            self._get_actor_ids_at_step(filter, 4),
            [person5_stopped_after_insight_view_random.uuid],
        )

    def test_basic_unordered_funnel_conversion_times(self):
        filter = Filter(
            data={
                "insight": INSIGHT_FUNNELS,
                "events": [
                    {"id": "user signed up", "order": 0},
                    {"id": "$pageview", "order": 1},
                    {"id": "insight viewed", "order": 2},
                ],
                "date_from": "2021-05-01 00:00:00",
                "date_to": "2021-05-07 23:59:59",
                "funnel_window_days": "1",
            }
        )

        funnel = ClickhouseFunnelUnordered(filter, self.team)

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
            event="$pageview",
            distinct_id="stopped_after_pageview1",
            timestamp="2021-05-02 00:00:00",
        )
        _create_event(
            team=self.team,
            event="user signed up",
            distinct_id="stopped_after_pageview1",
            timestamp="2021-05-02 01:00:00",
        )

        person3_stopped_after_insight_view = _create_person(
            distinct_ids=["stopped_after_insightview"], team_id=self.team.pk
        )
        _create_event(
            team=self.team,
            event="insight viewed",
            distinct_id="stopped_after_insightview",
            timestamp="2021-05-02 00:00:00",
        )
        _create_event(
            team=self.team,
            event="user signed up",
            distinct_id="stopped_after_insightview",
            timestamp="2021-05-02 02:00:00",
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="stopped_after_insightview",
            timestamp="2021-05-02 04:00:00",
        )

        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="stopped_after_insightview",
            timestamp="2021-05-03 00:00:00",
        )
        _create_event(
            team=self.team,
            event="insight viewed",
            distinct_id="stopped_after_insightview",
            timestamp="2021-05-03 03:00:00",
        )
        _create_event(
            team=self.team,
            event="user signed up",
            distinct_id="stopped_after_insightview",
            timestamp="2021-05-03 06:00:00",
        )
        # Person 3 completes the funnel 2 times:
        # First time: 2 hours + 2 hours = total 4 hours.
        # Second time: 3 hours + 3 hours = total 6 hours.

        result = funnel.run()

        self.assertEqual(result[0]["name"], "Completed 1 step")
        self.assertEqual(result[1]["name"], "Completed 2 steps")
        self.assertEqual(result[2]["name"], "Completed 3 steps")
        self.assertEqual(result[0]["count"], 3)

        self.assertEqual(result[1]["average_conversion_time"], 6300)
        # 1 hour for Person 2, (2+3)/2 hours for Person 3, total = 3.5 hours, average = 3.5/2 = 1.75 hours

        self.assertEqual(result[2]["average_conversion_time"], 9000)
        # (2+3)/2 hours for Person 3 = 2.5 hours

        self.assertCountEqual(
            self._get_actor_ids_at_step(filter, 1),
            [
                person1_stopped_after_signup.uuid,
                person2_stopped_after_one_pageview.uuid,
                person3_stopped_after_insight_view.uuid,
            ],
        )

        self.assertCountEqual(
            self._get_actor_ids_at_step(filter, 2),
            [
                person2_stopped_after_one_pageview.uuid,
                person3_stopped_after_insight_view.uuid,
            ],
        )

        self.assertCountEqual(
            self._get_actor_ids_at_step(filter, 3),
            [person3_stopped_after_insight_view.uuid],
        )

    def test_single_event_unordered_funnel(self):
        filter = Filter(
            data={
                "insight": INSIGHT_FUNNELS,
                "events": [{"id": "user signed up", "order": 0}],
                "date_from": "2021-05-01 00:00:00",
                "date_to": "2021-05-07 23:59:59",
            }
        )

        funnel = ClickhouseFunnelUnordered(filter, self.team)

        _create_person(distinct_ids=["stopped_after_signup1"], team_id=self.team.pk)
        _create_event(
            team=self.team,
            event="user signed up",
            distinct_id="stopped_after_signup1",
            timestamp="2021-05-02 00:00:00",
        )

        _create_person(distinct_ids=["stopped_after_pageview1"], team_id=self.team.pk)
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="stopped_after_pageview1",
            timestamp="2021-05-02 00:00:00",
        )
        _create_event(
            team=self.team,
            event="user signed up",
            distinct_id="stopped_after_pageview1",
            timestamp="2021-05-02 01:00:00",
        )

        result = funnel.run()

        self.assertEqual(result[0]["name"], "Completed 1 step")
        self.assertEqual(result[0]["count"], 2)

    def test_funnel_exclusions_invalid_params(self):
        filters = {
            "events": [
                {"id": "user signed up", "type": "events", "order": 0},
                {"id": "paid", "type": "events", "order": 1},
                {"id": "blah", "type": "events", "order": 2},
            ],
            "insight": INSIGHT_FUNNELS,
            "funnel_window_days": 14,
            "exclusions": [
                {
                    "id": "x",
                    "type": "events",
                    "funnel_from_step": 1,
                    "funnel_to_step": 1,
                }
            ],
        }
        filter = Filter(data=filters)
        self.assertRaises(ValidationError, lambda: ClickhouseFunnelUnordered(filter, self.team).run())

        # partial windows not allowed for unordered
        filter = filter.shallow_clone(
            {
                "exclusions": [
                    {
                        "id": "x",
                        "type": "events",
                        "funnel_from_step": 0,
                        "funnel_to_step": 1,
                    }
                ]
            }
        )
        self.assertRaises(ValidationError, lambda: ClickhouseFunnelUnordered(filter, self.team).run())

    def test_funnel_exclusions_full_window(self):
        filters = {
            "events": [
                {"id": "user signed up", "type": "events", "order": 0},
                {"id": "paid", "type": "events", "order": 1},
            ],
            "insight": INSIGHT_FUNNELS,
            "funnel_window_days": 14,
            "date_from": "2021-05-01 00:00:00",
            "date_to": "2021-05-14 00:00:00",
            "exclusions": [
                {
                    "id": "x",
                    "type": "events",
                    "funnel_from_step": 0,
                    "funnel_to_step": 1,
                }
            ],
        }
        filter = Filter(data=filters)
        funnel = ClickhouseFunnelUnordered(filter, self.team)

        # event 1
        person1 = _create_person(distinct_ids=["person1"], team_id=self.team.pk)
        _create_event(
            team=self.team,
            event="user signed up",
            distinct_id="person1",
            timestamp="2021-05-01 01:00:00",
        )
        _create_event(
            team=self.team,
            event="paid",
            distinct_id="person1",
            timestamp="2021-05-01 02:00:00",
        )

        # event 2
        person2 = _create_person(distinct_ids=["person2"], team_id=self.team.pk)
        _create_event(
            team=self.team,
            event="user signed up",
            distinct_id="person2",
            timestamp="2021-05-01 03:00:00",
        )
        _create_event(
            team=self.team,
            event="x",
            distinct_id="person2",
            timestamp="2021-05-01 03:30:00",
        )
        _create_event(
            team=self.team,
            event="paid",
            distinct_id="person2",
            timestamp="2021-05-01 04:00:00",
        )

        # event 3
        person3 = _create_person(distinct_ids=["person3"], team_id=self.team.pk)
        _create_event(
            team=self.team,
            event="user signed up",
            distinct_id="person3",
            timestamp="2021-05-01 05:00:00",
        )
        _create_event(
            team=self.team,
            event="paid",
            distinct_id="person3",
            timestamp="2021-05-01 06:00:00",
        )

        result = funnel.run()

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["name"], "Completed 1 step")
        self.assertEqual(result[0]["count"], 3)
        self.assertEqual(result[1]["name"], "Completed 2 steps")
        self.assertEqual(result[1]["count"], 2)

        self.assertCountEqual(
            self._get_actor_ids_at_step(filter, 1),
            [person1.uuid, person2.uuid, person3.uuid],
        )
        self.assertCountEqual(self._get_actor_ids_at_step(filter, 2), [person1.uuid, person3.uuid])

    def test_advanced_funnel_multiple_exclusions_between_steps(self):
        filters = {
            "events": [
                {"id": "user signed up", "type": "events", "order": 0},
                {"id": "$pageview", "type": "events", "order": 1},
                {"id": "insight viewed", "type": "events", "order": 2},
                {"id": "invite teammate", "type": "events", "order": 3},
                {"id": "pageview2", "type": "events", "order": 4},
            ],
            "date_from": "2021-05-01 00:00:00",
            "date_to": "2021-05-14 00:00:00",
            "insight": INSIGHT_FUNNELS,
            "exclusions": [
                {
                    "id": "x",
                    "type": "events",
                    "funnel_from_step": 0,
                    "funnel_to_step": 4,
                },
                {
                    "id": "y",
                    "type": "events",
                    "funnel_from_step": 0,
                    "funnel_to_step": 4,
                },
            ],
        }

        person1 = _create_person(distinct_ids=["person1"], team_id=self.team.pk)
        _create_event(
            team=self.team,
            event="user signed up",
            distinct_id="person1",
            timestamp="2021-05-01 01:00:00",
        )
        _create_event(
            team=self.team,
            event="x",
            distinct_id="person1",
            timestamp="2021-05-01 02:00:00",
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="person1",
            timestamp="2021-05-01 03:00:00",
        )
        _create_event(
            team=self.team,
            event="insight viewed",
            distinct_id="person1",
            timestamp="2021-05-01 04:00:00",
        )
        _create_event(
            team=self.team,
            event="y",
            distinct_id="person1",
            timestamp="2021-05-01 04:30:00",
        )
        _create_event(
            team=self.team,
            event="invite teammate",
            distinct_id="person1",
            timestamp="2021-05-01 05:00:00",
        )
        _create_event(
            team=self.team,
            event="pageview2",
            distinct_id="person1",
            timestamp="2021-05-01 06:00:00",
        )

        person2 = _create_person(distinct_ids=["person2"], team_id=self.team.pk)
        _create_event(
            team=self.team,
            event="user signed up",
            distinct_id="person2",
            timestamp="2021-05-01 01:00:00",
        )
        _create_event(
            team=self.team,
            event="y",
            distinct_id="person2",
            timestamp="2021-05-01 01:30:00",
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="person2",
            timestamp="2021-05-01 02:00:00",
        )
        _create_event(
            team=self.team,
            event="insight viewed",
            distinct_id="person2",
            timestamp="2021-05-01 04:00:00",
        )
        _create_event(
            team=self.team,
            event="y",
            distinct_id="person2",
            timestamp="2021-05-01 04:30:00",
        )
        _create_event(
            team=self.team,
            event="invite teammate",
            distinct_id="person2",
            timestamp="2021-05-01 05:00:00",
        )
        _create_event(
            team=self.team,
            event="x",
            distinct_id="person2",
            timestamp="2021-05-01 05:30:00",
        )
        _create_event(
            team=self.team,
            event="pageview2",
            distinct_id="person2",
            timestamp="2021-05-01 06:00:00",
        )

        person3 = _create_person(distinct_ids=["person3"], team_id=self.team.pk)
        _create_event(
            team=self.team,
            event="user signed up",
            distinct_id="person3",
            timestamp="2021-05-01 01:00:00",
        )
        _create_event(
            team=self.team,
            event="x",
            distinct_id="person3",
            timestamp="2021-05-01 01:30:00",
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="person3",
            timestamp="2021-05-01 02:00:00",
        )
        _create_event(
            team=self.team,
            event="insight viewed",
            distinct_id="person3",
            timestamp="2021-05-01 04:00:00",
        )
        _create_event(
            team=self.team,
            event="invite teammate",
            distinct_id="person3",
            timestamp="2021-05-01 05:00:00",
        )
        _create_event(
            team=self.team,
            event="x",
            distinct_id="person3",
            timestamp="2021-05-01 05:30:00",
        )
        _create_event(
            team=self.team,
            event="pageview2",
            distinct_id="person3",
            timestamp="2021-05-01 06:00:00",
        )

        person4 = _create_person(distinct_ids=["person4"], team_id=self.team.pk)
        _create_event(
            team=self.team,
            event="user signed up",
            distinct_id="person4",
            timestamp="2021-05-01 01:00:00",
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="person4",
            timestamp="2021-05-01 02:00:00",
        )
        _create_event(
            team=self.team,
            event="insight viewed",
            distinct_id="person4",
            timestamp="2021-05-01 04:00:00",
        )
        _create_event(
            team=self.team,
            event="invite teammate",
            distinct_id="person4",
            timestamp="2021-05-01 05:00:00",
        )
        _create_event(
            team=self.team,
            event="pageview2",
            distinct_id="person4",
            timestamp="2021-05-01 06:00:00",
        )

        person5 = _create_person(distinct_ids=["person5"], team_id=self.team.pk)
        _create_event(
            team=self.team,
            event="user signed up",
            distinct_id="person5",
            timestamp="2021-05-01 01:00:00",
        )
        _create_event(
            team=self.team,
            event="x",
            distinct_id="person5",
            timestamp="2021-05-01 01:30:00",
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="person5",
            timestamp="2021-05-01 02:00:00",
        )
        _create_event(
            team=self.team,
            event="x",
            distinct_id="person5",
            timestamp="2021-05-01 02:30:00",
        )
        _create_event(
            team=self.team,
            event="insight viewed",
            distinct_id="person5",
            timestamp="2021-05-01 04:00:00",
        )
        _create_event(
            team=self.team,
            event="y",
            distinct_id="person5",
            timestamp="2021-05-01 04:30:00",
        )
        _create_event(
            team=self.team,
            event="invite teammate",
            distinct_id="person5",
            timestamp="2021-05-01 05:00:00",
        )
        _create_event(
            team=self.team,
            event="x",
            distinct_id="person5",
            timestamp="2021-05-01 05:30:00",
        )
        _create_event(
            team=self.team,
            event="pageview2",
            distinct_id="person5",
            timestamp="2021-05-01 06:00:00",
        )

        filter = Filter(data=filters)
        funnel = ClickhouseFunnelUnordered(filter, self.team)

        result = funnel.run()

        self.assertEqual(result[0]["name"], "Completed 1 step")
        self.assertEqual(result[0]["count"], 5)
        self.assertEqual(result[1]["count"], 2)
        self.assertEqual(result[2]["count"], 1)
        self.assertEqual(result[3]["count"], 1)
        self.assertEqual(result[4]["count"], 1)

        self.assertCountEqual(
            self._get_actor_ids_at_step(filter, 1),
            [person1.uuid, person2.uuid, person3.uuid, person4.uuid, person5.uuid],
        )
        self.assertCountEqual(self._get_actor_ids_at_step(filter, 2), [person1.uuid, person4.uuid])
        self.assertCountEqual(self._get_actor_ids_at_step(filter, 3), [person4.uuid])
        self.assertCountEqual(self._get_actor_ids_at_step(filter, 4), [person4.uuid])
        self.assertCountEqual(self._get_actor_ids_at_step(filter, 5), [person4.uuid])

    def test_funnel_unordered_all_events_with_properties(self):
        _create_person(distinct_ids=["user"], team=self.team)
        _create_event(event="user signed up", distinct_id="user", team=self.team)
        _create_event(
            event="added to card",
            distinct_id="user",
            properties={"is_saved": True},
            team=self.team,
        )

        filters = {
            "events": [
                {
                    "type": "events",
                    "id": "user signed up",
                    "order": 0,
                    "name": "user signed up",
                    "math": "total",
                },
                {
                    "type": "events",
                    "id": None,
                    "order": 1,
                    "name": "All events",
                    "math": "total",
                    "properties": [
                        {
                            "key": "is_saved",
                            "value": ["true"],
                            "operator": "exact",
                            "type": "event",
                        }
                    ],
                },
            ],
            "funnel_window_days": 14,
        }

        filter = Filter(data=filters)
        funnel = ClickhouseFunnelUnordered(filter, self.team)
        result = funnel.run()

        self.assertEqual(result[0]["count"], 1)
        self.assertEqual(result[1]["count"], 1)

    def test_funnel_unordered_entity_filters(self):
        _create_person(distinct_ids=["user"], team=self.team)
        _create_event(
            event="user signed up",
            distinct_id="user",
            properties={"prop_a": "some value"},
            team=self.team,
        )
        _create_event(
            event="user signed up",
            distinct_id="user",
            properties={"prop_b": "another value"},
            team=self.team,
        )

        filters = {
            "events": [
                {
                    "type": "events",
                    "id": "user signed up",
                    "order": 0,
                    "name": "user signed up",
                    "math": "total",
                    "properties": [
                        {
                            "key": "prop_a",
                            "value": ["some value"],
                            "operator": "exact",
                            "type": "event",
                        }
                    ],
                },
                {
                    "type": "events",
                    "id": "user signed up",
                    "order": 1,
                    "name": "user signed up",
                    "math": "total",
                    "properties": [
                        {
                            "key": "prop_b",
                            "value": "another",
                            "operator": "icontains",
                            "type": "event",
                        }
                    ],
                },
            ],
        }

        filter = Filter(data=filters)
        funnel = ClickhouseFunnelUnordered(filter, self.team)
        result = funnel.run()

        self.assertEqual(result[0]["count"], 1)
        self.assertEqual(result[1]["count"], 1)
