from datetime import datetime
from unittest.case import skip
from unittest.mock import patch

from freezegun.api import freeze_time
from rest_framework.exceptions import ValidationError

from ee.clickhouse.materialized_columns import materialize
from ee.clickhouse.queries.funnels.funnel import ClickhouseFunnel
from ee.clickhouse.queries.funnels.funnel_persons import ClickhouseFunnelActors
from ee.clickhouse.queries.funnels.test.breakdown_cases import (
    assert_funnel_results_equal,
    funnel_breakdown_test_factory,
)
from ee.clickhouse.queries.funnels.test.conversion_time_cases import funnel_conversion_time_test_factory
from ee.clickhouse.test.test_journeys import journeys_for
from ee.clickhouse.util import ClickhouseTestMixin, snapshot_clickhouse_queries
from posthog.constants import INSIGHT_FUNNELS
from posthog.models import Element
from posthog.models.action import Action
from posthog.models.action_step import ActionStep
from posthog.models.cohort import Cohort
from posthog.models.filters import Filter
from posthog.queries.test.test_funnel import funnel_test_factory
from posthog.test.base import _create_event, _create_person, test_with_materialized_columns

FORMAT_TIME = "%Y-%m-%d 00:00:00"
MAX_STEP_COLUMN = 0
COUNT_COLUMN = 1
PERSON_ID_COLUMN = 2


def _create_action(**kwargs):
    team = kwargs.pop("team")
    name = kwargs.pop("name")
    properties = kwargs.pop("properties", {})
    action = Action.objects.create(team=team, name=name)
    ActionStep.objects.create(action=action, event=name, properties=properties)
    return action


class TestFunnelBreakdown(ClickhouseTestMixin, funnel_breakdown_test_factory(ClickhouseFunnel, ClickhouseFunnelActors, _create_event, _create_action, _create_person)):  # type: ignore
    maxDiff = None
    pass


class TestFunnelConversionTime(ClickhouseTestMixin, funnel_conversion_time_test_factory(ClickhouseFunnel, ClickhouseFunnelActors, _create_event, _create_person)):  # type: ignore
    maxDiff = None
    pass


class TestClickhouseFunnel(ClickhouseTestMixin, funnel_test_factory(ClickhouseFunnel, _create_event, _create_person)):  # type: ignore

    maxDiff = None

    def _get_actor_ids_at_step(self, filter, funnel_step, breakdown_value=None):
        person_filter = filter.with_data({"funnel_step": funnel_step, "funnel_step_breakdown": breakdown_value})
        _, serialized_result = ClickhouseFunnelActors(person_filter, self.team).get_actors()

        return [val["id"] for val in serialized_result]

    def test_basic_funnel_default_funnel_days(self):
        filters = {
            "events": [
                {"id": "user signed up", "type": "events", "order": 0},
                {"id": "paid", "type": "events", "order": 1},
            ],
            "insight": INSIGHT_FUNNELS,
            "date_from": "2020-01-01",
            "date_to": "2020-01-14",
        }

        filter = Filter(data=filters)
        funnel = ClickhouseFunnel(filter, self.team)

        # event
        _create_person(distinct_ids=["user_1"], team_id=self.team.pk)
        _create_event(
            team=self.team, event="user signed up", distinct_id="user_1", timestamp="2020-01-02T14:00:00Z",
        )
        _create_event(
            team=self.team, event="paid", distinct_id="user_1", timestamp="2020-01-10T14:00:00Z",
        )

        result = funnel.run()

        self.assertEqual(result[0]["name"], "user signed up")
        self.assertEqual(result[0]["count"], 1)

        self.assertEqual(result[1]["name"], "paid")
        self.assertEqual(result[1]["count"], 1)

    def test_basic_funnel_with_repeat_steps(self):
        filters = {
            "events": [
                {"id": "user signed up", "type": "events", "order": 0},
                {"id": "user signed up", "type": "events", "order": 1},
            ],
            "insight": INSIGHT_FUNNELS,
            "funnel_window_days": 14,
        }

        filter = Filter(data=filters)
        funnel = ClickhouseFunnel(filter, self.team)

        # event
        person1_stopped_after_two_signups = _create_person(distinct_ids=["stopped_after_signup1"], team_id=self.team.pk)
        _create_event(team=self.team, event="user signed up", distinct_id="stopped_after_signup1")
        _create_event(team=self.team, event="user signed up", distinct_id="stopped_after_signup1")

        person2_stopped_after_signup = _create_person(distinct_ids=["stopped_after_signup2"], team_id=self.team.pk)
        _create_event(team=self.team, event="user signed up", distinct_id="stopped_after_signup2")

        result = funnel.run()
        self.assertEqual(result[0]["name"], "user signed up")
        self.assertEqual(result[0]["count"], 2)

        self.assertEqual(result[1]["count"], 1)

        self.assertCountEqual(
            self._get_actor_ids_at_step(filter, 1),
            [person1_stopped_after_two_signups.uuid, person2_stopped_after_signup.uuid],
        )

        self.assertCountEqual(
            self._get_actor_ids_at_step(filter, 2), [person1_stopped_after_two_signups.uuid],
        )

    @test_with_materialized_columns(["key"])
    def test_basic_funnel_with_derivative_steps(self):
        filters = {
            "events": [
                {"id": "user signed up", "type": "events", "order": 0, "properties": {"key": "val"}},
                {"id": "user signed up", "type": "events", "order": 1},
            ],
            "insight": INSIGHT_FUNNELS,
            "funnel_window_days": 14,
        }

        filter = Filter(data=filters)
        funnel = ClickhouseFunnel(filter, self.team)

        # event
        person1_stopped_after_two_signups = _create_person(distinct_ids=["stopped_after_signup1"], team_id=self.team.pk)
        _create_event(
            team=self.team, event="user signed up", distinct_id="stopped_after_signup1", properties={"key": "val"},
        )
        _create_event(team=self.team, event="user signed up", distinct_id="stopped_after_signup1")

        person2_stopped_after_signup = _create_person(distinct_ids=["stopped_after_signup2"], team_id=self.team.pk)
        _create_event(
            team=self.team, event="user signed up", distinct_id="stopped_after_signup2", properties={"key": "val"}
        )

        result = funnel.run()
        self.assertEqual(result[0]["name"], "user signed up")
        self.assertEqual(result[0]["count"], 2)

        self.assertEqual(result[1]["count"], 1)

        self.assertCountEqual(
            self._get_actor_ids_at_step(filter, 1),
            [person1_stopped_after_two_signups.uuid, person2_stopped_after_signup.uuid],
        )

        self.assertCountEqual(
            self._get_actor_ids_at_step(filter, 2), [person1_stopped_after_two_signups.uuid],
        )

    def test_basic_funnel_with_repeat_step_updated_param(self):
        people = journeys_for(
            {
                "stopped_after_signup1": [{"event": "user signed up"}, {"event": "user signed up"}],
                "stopped_after_signup2": [{"event": "user signed up"}],
            },
            self.team,
        )

        filters = {
            "events": [
                {"id": "user signed up", "type": "events", "order": 0},
                {"id": "user signed up", "type": "events", "order": 1},
            ],
            "insight": INSIGHT_FUNNELS,
            "funnel_window_interval": 14,
            "funnel_window_interval_unit": "day",
        }

        filter = Filter(data=filters)
        funnel = ClickhouseFunnel(filter, self.team)
        result = funnel.run()

        self.assertEqual(result[0]["name"], "user signed up")
        self.assertEqual(result[0]["count"], 2)

        self.assertEqual(result[1]["count"], 1)

        self.assertCountEqual(
            self._get_actor_ids_at_step(filter, 1),
            [people["stopped_after_signup1"].uuid, people["stopped_after_signup2"].uuid],
        )

        self.assertCountEqual(
            self._get_actor_ids_at_step(filter, 2), [people["stopped_after_signup1"].uuid],
        )

        filters = {
            "events": [
                {"id": "user signed up", "type": "events", "order": 0},
                {"id": "user signed up", "type": "events", "order": 1},
            ],
            "insight": INSIGHT_FUNNELS,
            "funnel_window_interval": 2,
            "funnel_window_interval_unit": "week",
        }

        filter = Filter(data=filters)
        funnel = ClickhouseFunnel(filter, self.team)
        result2 = funnel.run()

        assert_funnel_results_equal(result, result2)

        filters = {
            "events": [
                {"id": "user signed up", "type": "events", "order": 0},
                {"id": "user signed up", "type": "events", "order": 1},
            ],
            "insight": INSIGHT_FUNNELS,
            "funnel_window_days": 14,
            "funnel_window_interval": 1,
            "funnel_window_interval_unit": "hour",
        }

        filter = Filter(data=filters)
        funnel = ClickhouseFunnel(filter, self.team)
        result3 = funnel.run()

        assert_funnel_results_equal(result, result3)

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
                {"id": "x 1 name with numbers 2", "type": "events", "funnel_from_step": 0, "funnel_to_step": 1},
            ],
        }
        filter = Filter(data=filters)
        funnel = ClickhouseFunnel(filter, self.team)

        # event 1
        person1 = _create_person(distinct_ids=["person1"], team_id=self.team.pk)
        _create_event(team=self.team, event="user signed up", distinct_id="person1", timestamp="2021-05-01 01:00:00")
        _create_event(team=self.team, event="paid", distinct_id="person1", timestamp="2021-05-01 02:00:00")

        # event 2
        person2 = _create_person(distinct_ids=["person2"], team_id=self.team.pk)
        _create_event(team=self.team, event="user signed up", distinct_id="person2", timestamp="2021-05-01 03:00:00")
        _create_event(
            team=self.team, event="x 1 name with numbers 2", distinct_id="person2", timestamp="2021-05-01 03:30:00"
        )
        _create_event(team=self.team, event="paid", distinct_id="person2", timestamp="2021-05-01 04:00:00")

        # event 3
        person3 = _create_person(distinct_ids=["person3"], team_id=self.team.pk)
        _create_event(team=self.team, event="user signed up", distinct_id="person3", timestamp="2021-05-01 05:00:00")
        _create_event(team=self.team, event="paid", distinct_id="person3", timestamp="2021-05-01 06:00:00")

        result = funnel.run()
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["name"], "user signed up")
        self.assertEqual(result[0]["count"], 2)

        self.assertEqual(result[1]["name"], "paid")
        self.assertEqual(result[1]["count"], 2)

        self.assertCountEqual(
            self._get_actor_ids_at_step(filter, 1), [person1.uuid, person3.uuid],
        )
        self.assertCountEqual(
            self._get_actor_ids_at_step(filter, 2), [person1.uuid, person3.uuid],
        )

    def test_advanced_funnel_exclusions_between_steps(self):
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
            "exclusions": [{"id": "x", "type": "events", "funnel_from_step": 0, "funnel_to_step": 1},],
        }

        person1 = _create_person(distinct_ids=["person1"], team_id=self.team.pk)
        # this dude is discarded when funnel_from_step = 1
        # this dude is discarded when funnel_from_step = 2
        # this dude is discarded when funnel_from_step = 3
        _create_event(team=self.team, event="user signed up", distinct_id="person1", timestamp="2021-05-01 01:00:00")
        _create_event(team=self.team, event="$pageview", distinct_id="person1", timestamp="2021-05-01 02:00:00")
        _create_event(team=self.team, event="x", distinct_id="person1", timestamp="2021-05-01 03:00:00")
        _create_event(team=self.team, event="insight viewed", distinct_id="person1", timestamp="2021-05-01 04:00:00")
        _create_event(team=self.team, event="x", distinct_id="person1", timestamp="2021-05-01 04:30:00")
        _create_event(team=self.team, event="invite teammate", distinct_id="person1", timestamp="2021-05-01 05:00:00")
        _create_event(team=self.team, event="x", distinct_id="person1", timestamp="2021-05-01 05:30:00")
        _create_event(team=self.team, event="pageview2", distinct_id="person1", timestamp="2021-05-01 06:00:00")

        person2 = _create_person(distinct_ids=["person2"], team_id=self.team.pk)
        # this dude is discarded when funnel_from_step = 2
        # this dude is discarded when funnel_from_step = 3
        _create_event(team=self.team, event="user signed up", distinct_id="person2", timestamp="2021-05-01 01:00:00")
        _create_event(team=self.team, event="$pageview", distinct_id="person2", timestamp="2021-05-01 02:00:00")
        _create_event(team=self.team, event="insight viewed", distinct_id="person2", timestamp="2021-05-01 04:00:00")
        _create_event(team=self.team, event="x", distinct_id="person2", timestamp="2021-05-01 04:30:00")
        _create_event(team=self.team, event="invite teammate", distinct_id="person2", timestamp="2021-05-01 05:00:00")
        _create_event(team=self.team, event="x", distinct_id="person2", timestamp="2021-05-01 05:30:00")
        _create_event(team=self.team, event="pageview2", distinct_id="person2", timestamp="2021-05-01 06:00:00")

        person3 = _create_person(distinct_ids=["person3"], team_id=self.team.pk)
        # this dude is discarded when funnel_from_step = 0
        # this dude is discarded when funnel_from_step = 3
        _create_event(team=self.team, event="user signed up", distinct_id="person3", timestamp="2021-05-01 01:00:00")
        _create_event(team=self.team, event="x", distinct_id="person3", timestamp="2021-05-01 01:30:00")
        _create_event(team=self.team, event="$pageview", distinct_id="person3", timestamp="2021-05-01 02:00:00")
        _create_event(team=self.team, event="insight viewed", distinct_id="person3", timestamp="2021-05-01 04:00:00")
        _create_event(team=self.team, event="invite teammate", distinct_id="person3", timestamp="2021-05-01 05:00:00")
        _create_event(team=self.team, event="x", distinct_id="person3", timestamp="2021-05-01 05:30:00")
        _create_event(team=self.team, event="pageview2", distinct_id="person3", timestamp="2021-05-01 06:00:00")

        filter = Filter(data=filters)
        funnel = ClickhouseFunnel(filter, self.team)

        result = funnel.run()

        self.assertEqual(result[0]["name"], "user signed up")
        self.assertEqual(result[0]["count"], 2)

        self.assertEqual(result[4]["count"], 2)

        self.assertCountEqual(
            self._get_actor_ids_at_step(filter, 1), [person1.uuid, person2.uuid,],
        )

        filter = filter.with_data(
            {"exclusions": [{"id": "x", "type": "events", "funnel_from_step": 1, "funnel_to_step": 2}]}
        )
        funnel = ClickhouseFunnel(filter, self.team)

        result = funnel.run()

        self.assertEqual(result[0]["name"], "user signed up")
        self.assertEqual(result[0]["count"], 2)

        self.assertEqual(result[4]["count"], 2)

        self.assertCountEqual(
            self._get_actor_ids_at_step(filter, 1), [person2.uuid, person3.uuid,],
        )

        filter = filter.with_data(
            {"exclusions": [{"id": "x", "type": "events", "funnel_from_step": 2, "funnel_to_step": 3}]}
        )
        funnel = ClickhouseFunnel(filter, self.team)

        result = funnel.run()

        self.assertEqual(result[0]["name"], "user signed up")
        self.assertEqual(result[0]["count"], 1)

        self.assertEqual(result[4]["count"], 1)

        self.assertCountEqual(
            self._get_actor_ids_at_step(filter, 1), [person3.uuid,],
        )

        filter = filter.with_data(
            {"exclusions": [{"id": "x", "type": "events", "funnel_from_step": 3, "funnel_to_step": 4}]}
        )
        funnel = ClickhouseFunnel(filter, self.team)

        result = funnel.run()

        self.assertEqual(result[0]["name"], "user signed up")
        self.assertEqual(result[0]["count"], 0)

        self.assertEqual(result[4]["count"], 0)

        self.assertCountEqual(
            self._get_actor_ids_at_step(filter, 1), [],
        )

        #  bigger step window
        filter = filter.with_data(
            {"exclusions": [{"id": "x", "type": "events", "funnel_from_step": 1, "funnel_to_step": 3}]}
        )
        funnel = ClickhouseFunnel(filter, self.team)

        result = funnel.run()

        self.assertEqual(result[0]["name"], "user signed up")
        self.assertEqual(result[0]["count"], 1)

        self.assertEqual(result[4]["count"], 1)

        self.assertCountEqual(
            self._get_actor_ids_at_step(filter, 1), [person3.uuid],
        )

    def test_advanced_funnel_with_repeat_steps(self):
        filters = {
            "events": [
                {"id": "user signed up", "type": "events", "order": 0},
                {"id": "$pageview", "type": "events", "order": 1},
                {"id": "$pageview", "type": "events", "order": 2},
                {"id": "$pageview", "type": "events", "order": 3},
                {"id": "$pageview", "type": "events", "order": 4},
            ],
            "insight": INSIGHT_FUNNELS,
        }

        filter = Filter(data=filters)
        funnel = ClickhouseFunnel(filter, self.team)

        people = journeys_for(
            {
                "stopped_after_signup1": [{"event": "user signed up"}],
                "stopped_after_pageview1": [{"event": "user signed up"}, {"event": "$pageview"}],
                "stopped_after_pageview2": [
                    {"event": "user signed up"},
                    {"event": "$pageview"},
                    {"event": "blaah blaa"},
                    {"event": "$pageview"},
                ],
                "stopped_after_pageview3": [
                    {"event": "user signed up"},
                    {"event": "$pageview"},
                    {"event": "blaah blaa"},
                    {"event": "$pageview"},
                    {"event": "$pageview"},
                    {"event": "blaah blaa"},
                ],
                "stopped_after_pageview4": [
                    {"event": "user signed up"},
                    {"event": "$pageview"},
                    {"event": "$pageview"},
                    {"event": "$pageview"},
                    {"event": "$pageview"},
                ],
            },
            self.team,
        )

        result = funnel.run()

        self.assertEqual(result[0]["name"], "user signed up")
        self.assertEqual(result[1]["name"], "$pageview")
        self.assertEqual(result[4]["name"], "$pageview")
        self.assertEqual(result[0]["count"], 5)

        self.assertEqual(result[1]["count"], 4)

        self.assertEqual(result[2]["count"], 3)

        self.assertEqual(result[3]["count"], 2)

        self.assertEqual(result[4]["count"], 1)

        # check ordering of people in every step
        self.assertCountEqual(
            self._get_actor_ids_at_step(filter, 1),
            [
                people["stopped_after_signup1"].uuid,
                people["stopped_after_pageview1"].uuid,
                people["stopped_after_pageview2"].uuid,
                people["stopped_after_pageview3"].uuid,
                people["stopped_after_pageview4"].uuid,
            ],
        )

        self.assertCountEqual(
            self._get_actor_ids_at_step(filter, 2),
            [
                people["stopped_after_pageview1"].uuid,
                people["stopped_after_pageview2"].uuid,
                people["stopped_after_pageview3"].uuid,
                people["stopped_after_pageview4"].uuid,
            ],
        )

        self.assertCountEqual(
            self._get_actor_ids_at_step(filter, 3),
            [
                people["stopped_after_pageview2"].uuid,
                people["stopped_after_pageview3"].uuid,
                people["stopped_after_pageview4"].uuid,
            ],
        )

        self.assertCountEqual(
            self._get_actor_ids_at_step(filter, 4),
            [people["stopped_after_pageview3"].uuid, people["stopped_after_pageview4"].uuid,],
        )

        self.assertCountEqual(
            self._get_actor_ids_at_step(filter, 5), [people["stopped_after_pageview4"].uuid,],
        )

    def test_advanced_funnel_with_repeat_steps_out_of_order_events(self):
        filters = {
            "events": [
                {"id": "user signed up", "type": "events", "order": 0},
                {"id": "$pageview", "type": "events", "order": 1},
                {"id": "$pageview", "type": "events", "order": 2},
                {"id": "$pageview", "type": "events", "order": 3},
                {"id": "$pageview", "type": "events", "order": 4},
            ],
            "insight": INSIGHT_FUNNELS,
            "funnel_window_days": 14,
        }

        filter = Filter(data=filters)
        funnel = ClickhouseFunnel(filter, self.team)

        # event
        person1_stopped_after_signup = _create_person(
            distinct_ids=["random", "stopped_after_signup1"], team_id=self.team.pk
        )
        _create_event(team=self.team, event="$pageview", distinct_id="random")
        _create_event(team=self.team, event="user signed up", distinct_id="stopped_after_signup1")

        person2_stopped_after_one_pageview = _create_person(
            distinct_ids=["stopped_after_pageview1"], team_id=self.team.pk
        )
        _create_event(team=self.team, event="user signed up", distinct_id="stopped_after_pageview1")
        _create_event(team=self.team, event="$pageview", distinct_id="stopped_after_pageview1")

        person3_stopped_after_two_pageview = _create_person(
            distinct_ids=["stopped_after_pageview2"], team_id=self.team.pk
        )
        _create_event(team=self.team, event="$pageview", distinct_id="stopped_after_pageview2")
        _create_event(team=self.team, event="user signed up", distinct_id="stopped_after_pageview2")
        _create_event(team=self.team, event="blaah blaa", distinct_id="stopped_after_pageview2")
        _create_event(team=self.team, event="$pageview", distinct_id="stopped_after_pageview2")

        person4_stopped_after_three_pageview = _create_person(
            distinct_ids=["stopped_after_pageview3"], team_id=self.team.pk
        )
        _create_event(team=self.team, event="blaah blaa", distinct_id="stopped_after_pageview3")
        _create_event(team=self.team, event="$pageview", distinct_id="stopped_after_pageview3")
        _create_event(team=self.team, event="blaah blaa", distinct_id="stopped_after_pageview3")
        _create_event(team=self.team, event="$pageview", distinct_id="stopped_after_pageview3")
        _create_event(team=self.team, event="user signed up", distinct_id="stopped_after_pageview3")
        _create_event(team=self.team, event="$pageview", distinct_id="stopped_after_pageview3")

        person5_stopped_after_many_pageview = _create_person(
            distinct_ids=["stopped_after_pageview4"], team_id=self.team.pk
        )
        _create_event(team=self.team, event="user signed up", distinct_id="stopped_after_pageview4")
        _create_event(team=self.team, event="$pageview", distinct_id="stopped_after_pageview4")
        _create_event(team=self.team, event="blaah blaa", distinct_id="stopped_after_pageview4")
        _create_event(team=self.team, event="$pageview", distinct_id="stopped_after_pageview4")
        _create_event(team=self.team, event="$pageview", distinct_id="stopped_after_pageview4")
        _create_event(team=self.team, event="$pageview", distinct_id="stopped_after_pageview4")

        person6_stopped_after_many_pageview_without_signup = _create_person(
            distinct_ids=["stopped_after_pageview5"], team_id=self.team.pk
        )
        _create_event(team=self.team, event="$pageview", distinct_id="stopped_after_pageview5")
        _create_event(team=self.team, event="blaah blaa", distinct_id="stopped_after_pageview5")
        _create_event(team=self.team, event="$pageview", distinct_id="stopped_after_pageview5")
        _create_event(team=self.team, event="$pageview", distinct_id="stopped_after_pageview5")
        _create_event(team=self.team, event="$pageview", distinct_id="stopped_after_pageview5")

        result = funnel.run()

        self.assertEqual(result[0]["name"], "user signed up")
        self.assertEqual(result[1]["name"], "$pageview")
        self.assertEqual(result[4]["name"], "$pageview")
        self.assertEqual(result[0]["count"], 5)

        self.assertEqual(result[1]["count"], 4)

        self.assertEqual(result[2]["count"], 1)

        self.assertEqual(result[3]["count"], 1)

        self.assertEqual(result[4]["count"], 1)

        # check ordering of people in every step
        self.assertCountEqual(
            self._get_actor_ids_at_step(filter, 1),
            [
                person1_stopped_after_signup.uuid,
                person2_stopped_after_one_pageview.uuid,
                person3_stopped_after_two_pageview.uuid,
                person4_stopped_after_three_pageview.uuid,
                person5_stopped_after_many_pageview.uuid,
            ],
        )

        self.assertCountEqual(
            self._get_actor_ids_at_step(filter, 2),
            [
                person2_stopped_after_one_pageview.uuid,
                person3_stopped_after_two_pageview.uuid,
                person4_stopped_after_three_pageview.uuid,
                person5_stopped_after_many_pageview.uuid,
            ],
        )

        self.assertCountEqual(
            self._get_actor_ids_at_step(filter, 3), [person5_stopped_after_many_pageview.uuid],
        )

        self.assertCountEqual(
            self._get_actor_ids_at_step(filter, 4), [person5_stopped_after_many_pageview.uuid],
        )

        self.assertCountEqual(
            self._get_actor_ids_at_step(filter, 5), [person5_stopped_after_many_pageview.uuid],
        )

    @test_with_materialized_columns(["key"])
    def test_funnel_with_actions(self):

        sign_up_action = _create_action(
            name="sign up",
            team=self.team,
            properties=[{"key": "key", "type": "event", "value": ["val"], "operator": "exact"}],
        )

        filters = {
            "actions": [
                {"id": sign_up_action.id, "math": "dau", "order": 0},
                {"id": sign_up_action.id, "math": "wau", "order": 1},
            ],
            "insight": INSIGHT_FUNNELS,
        }

        filter = Filter(data=filters)
        funnel = ClickhouseFunnel(filter, self.team)

        # event
        person1_stopped_after_two_signups = _create_person(distinct_ids=["stopped_after_signup1"], team_id=self.team.pk)
        _create_event(team=self.team, event="sign up", distinct_id="stopped_after_signup1", properties={"key": "val"})
        _create_event(team=self.team, event="sign up", distinct_id="stopped_after_signup1", properties={"key": "val"})

        person2_stopped_after_signup = _create_person(distinct_ids=["stopped_after_signup2"], team_id=self.team.pk)
        _create_event(team=self.team, event="sign up", distinct_id="stopped_after_signup2", properties={"key": "val"})

        result = funnel.run()

        self.assertEqual(result[0]["name"], "sign up")
        self.assertEqual(result[0]["count"], 2)

        self.assertEqual(result[1]["count"], 1)

        # check ordering of people in first step
        self.assertCountEqual(
            self._get_actor_ids_at_step(filter, 1),
            [person1_stopped_after_two_signups.uuid, person2_stopped_after_signup.uuid],
        )

        self.assertCountEqual(
            self._get_actor_ids_at_step(filter, 2), [person1_stopped_after_two_signups.uuid],
        )

    @test_with_materialized_columns(["key"])
    @skip("Flaky funnel test")
    def test_funnel_with_actions_and_events(self):

        sign_up_action = _create_action(
            name="sign up",
            team=self.team,
            properties=[{"key": "key", "type": "event", "value": ["val"], "operator": "exact"}],
        )

        filters = {
            "events": [
                {"id": "user signed up", "type": "events", "order": 0},
                {"id": "user signed up", "type": "events", "order": 1},
            ],
            "actions": [
                {"id": sign_up_action.id, "math": "dau", "order": 2},
                {"id": sign_up_action.id, "math": "wau", "order": 3},
            ],
            "insight": INSIGHT_FUNNELS,
            "funnel_window_days": 14,
        }

        filter = Filter(data=filters, team=self.team)

        # event
        person1_stopped_after_two_signups = _create_person(distinct_ids=["stopped_after_signup1"], team_id=self.team.pk)
        _create_event(
            team=self.team, event="user signed up", distinct_id="stopped_after_signup1", timestamp="2021-05-01 00:00:00"
        )
        _create_event(
            team=self.team, event="user signed up", distinct_id="stopped_after_signup1", timestamp="2021-05-01 00:00:01"
        )
        _create_event(
            team=self.team,
            event="sign up",
            distinct_id="stopped_after_signup1",
            properties={"key": "val"},
            timestamp="2021-05-01 00:00:02",
        )
        _create_event(
            team=self.team,
            event="sign up",
            distinct_id="stopped_after_signup1",
            properties={"key": "val"},
            timestamp="2021-05-01 00:00:03",
        )

        person2_stopped_after_signup = _create_person(distinct_ids=["stopped_after_signup2"], team_id=self.team.pk)
        _create_event(
            team=self.team, event="user signed up", distinct_id="stopped_after_signup2", timestamp="2021-05-01 00:00:04"
        )
        _create_event(
            team=self.team, event="user signed up", distinct_id="stopped_after_signup2", timestamp="2021-05-01 00:00:05"
        )
        _create_event(
            team=self.team,
            event="sign up",
            distinct_id="stopped_after_signup2",
            properties={"key": "val"},
            timestamp="2021-05-01 00:00:06",
        )

        person3 = _create_person(distinct_ids=["person3"], team_id=self.team.pk)
        _create_event(team=self.team, event="user signed up", distinct_id="person3", timestamp="2021-05-01 00:00:07")
        _create_event(
            team=self.team,
            event="sign up",
            distinct_id="person3",
            properties={"key": "val"},
            timestamp="2021-05-01 00:00:08",
        )
        _create_event(team=self.team, event="user signed up", distinct_id="person3", timestamp="2021-05-01 00:00:09")
        _create_event(
            team=self.team,
            event="sign up",
            distinct_id="person3",
            properties={"key": "val"},
            timestamp="2021-05-01 00:00:10",
        )

        person4 = _create_person(distinct_ids=["person4"], team_id=self.team.pk)
        _create_event(team=self.team, event="user signed up", distinct_id="person4", timestamp="2021-05-01 00:00:11")
        _create_event(
            team=self.team,
            event="sign up",
            distinct_id="person4",
            properties={"key": "val"},
            timestamp="2021-05-01 00:00:12",
        )
        _create_event(team=self.team, event="user signed up", distinct_id="person4", timestamp="2021-05-01 00:00:13")

        person5 = _create_person(distinct_ids=["person5"], team_id=self.team.pk)
        _create_event(
            team=self.team,
            event="sign up",
            distinct_id="person5",
            properties={"key": "val"},
            timestamp="2021-05-01 00:00:14",
        )

        with freeze_time("2021-05-02"):
            result = ClickhouseFunnel(filter, self.team).run()

        self.assertEqual(result[0]["name"], "user signed up")
        self.assertEqual(result[0]["count"], 4)
        self.assertEqual(result[1]["count"], 4)
        self.assertEqual(result[2]["count"], 3)
        self.assertEqual(result[3]["count"], 1)

        # check ordering of people in steps
        self.assertCountEqual(
            self._get_actor_ids_at_step(filter, 1),
            [person1_stopped_after_two_signups.uuid, person2_stopped_after_signup.uuid, person3.uuid, person4.uuid],
        )

        self.assertCountEqual(
            self._get_actor_ids_at_step(filter, 2),
            [person1_stopped_after_two_signups.uuid, person2_stopped_after_signup.uuid, person3.uuid, person4.uuid],
        )

        self.assertCountEqual(
            self._get_actor_ids_at_step(filter, 3),
            [person1_stopped_after_two_signups.uuid, person2_stopped_after_signup.uuid, person3.uuid,],
        )

        self.assertCountEqual(self._get_actor_ids_at_step(filter, 4), [person1_stopped_after_two_signups.uuid,])

    @test_with_materialized_columns(["$current_url"])
    def test_funnel_with_matching_properties(self):
        filters = {
            "events": [
                {"id": "user signed up", "order": 0},
                {"id": "$pageview", "order": 1, "properties": {"$current_url": "aloha.com"}},
                {
                    "id": "$pageview",
                    "order": 2,
                    "properties": {"$current_url": "aloha2.com"},
                },  # different event to above
                {"id": "$pageview", "order": 3, "properties": {"$current_url": "aloha2.com"}},
                {"id": "$pageview", "order": 4,},
            ],
            "insight": INSIGHT_FUNNELS,
            "funnel_window_days": 14,
        }

        filter = Filter(data=filters)
        funnel = ClickhouseFunnel(filter, self.team)

        # event
        people = journeys_for(
            {
                "stopped_after_signup1": [{"event": "user signed up"}],
                "stopped_after_pageview1": [
                    {"event": "user signed up"},
                    {"event": "$pageview", "properties": {"$current_url": "aloha.com"}},
                ],
                "stopped_after_pageview2": [
                    {"event": "user signed up"},
                    {"event": "$pageview", "properties": {"$current_url": "aloha.com"}},
                    {"event": "blaah blaa", "properties": {"$current_url": "aloha.com"}},
                    {"event": "$pageview", "properties": {"$current_url": "aloha2.com"}},
                ],
                "stopped_after_pageview3": [
                    {"event": "user signed up"},
                    {"event": "$pageview", "properties": {"$current_url": "aloha.com"}},
                    {"event": "$pageview", "properties": {"$current_url": "aloha2.com"}},
                    {"event": "$pageview", "properties": {"$current_url": "aloha2.com"}},
                    {"event": "blaah blaa"},
                ],
                "stopped_after_pageview4": [
                    {"event": "user signed up"},
                    {"event": "$pageview", "properties": {"$current_url": "aloha.com"}},
                    {"event": "blaah blaa"},
                    {"event": "$pageview", "properties": {"$current_url": "aloha2.com"}},
                    {"event": "$pageview", "properties": {"$current_url": "aloha.com"}},
                    {"event": "$pageview", "properties": {"$current_url": "aloha2.com"}},
                ],
            },
            self.team,
        )

        result = funnel.run()

        self.assertEqual(result[0]["name"], "user signed up")
        self.assertEqual(result[1]["name"], "$pageview")
        self.assertEqual(result[4]["name"], "$pageview")
        self.assertEqual(result[0]["count"], 5)
        self.assertEqual(result[1]["count"], 4)
        self.assertEqual(result[2]["count"], 3)
        self.assertEqual(result[3]["count"], 2)
        self.assertEqual(result[4]["count"], 0)
        # check ordering of people in every step
        self.assertCountEqual(
            self._get_actor_ids_at_step(filter, 1),
            [
                people["stopped_after_signup1"].uuid,
                people["stopped_after_pageview1"].uuid,
                people["stopped_after_pageview2"].uuid,
                people["stopped_after_pageview3"].uuid,
                people["stopped_after_pageview4"].uuid,
            ],
        )

        self.assertCountEqual(
            self._get_actor_ids_at_step(filter, 2),
            [
                people["stopped_after_pageview1"].uuid,
                people["stopped_after_pageview2"].uuid,
                people["stopped_after_pageview3"].uuid,
                people["stopped_after_pageview4"].uuid,
            ],
        )

        self.assertCountEqual(
            self._get_actor_ids_at_step(filter, 3),
            [
                people["stopped_after_pageview2"].uuid,
                people["stopped_after_pageview3"].uuid,
                people["stopped_after_pageview4"].uuid,
            ],
        )

        self.assertCountEqual(
            self._get_actor_ids_at_step(filter, 4),
            [people["stopped_after_pageview3"].uuid, people["stopped_after_pageview4"].uuid,],
        )

        self.assertCountEqual(
            self._get_actor_ids_at_step(filter, 5), [],
        )

    def test_funnel_conversion_window(self):
        ids_to_compare = []
        for i in range(10):
            person = _create_person(distinct_ids=[f"user_{i}"], team=self.team)
            ids_to_compare.append(str(person.uuid))
            _create_event(event="step one", distinct_id=f"user_{i}", team=self.team, timestamp="2021-05-01 00:00:00")
            _create_event(event="step two", distinct_id=f"user_{i}", team=self.team, timestamp="2021-05-02 00:00:00")

        for i in range(10, 25):
            _create_person(distinct_ids=[f"user_{i}"], team=self.team)
            _create_event(event="step one", distinct_id=f"user_{i}", team=self.team, timestamp="2021-05-01 00:00:00")
            _create_event(event="step two", distinct_id=f"user_{i}", team=self.team, timestamp="2021-05-10 00:00:00")

        data = {
            "insight": INSIGHT_FUNNELS,
            "interval": "day",
            "date_from": "2021-05-01 00:00:00",
            "date_to": "2021-05-14 00:00:00",
            "funnel_window_days": 7,
            "events": [
                {"id": "step one", "order": 0},
                {"id": "step two", "order": 1},
                {"id": "step three", "order": 2},
            ],
        }

        filter = Filter(data={**data})
        results = ClickhouseFunnel(filter, self.team).run()

        self.assertEqual(results[0]["count"], 25)
        self.assertEqual(results[1]["count"], 10)
        self.assertEqual(results[2]["count"], 0)

        self.assertCountEqual([str(id) for id in self._get_actor_ids_at_step(filter, 2)], ids_to_compare)

    def test_funnel_exclusions_invalid_params(self):
        filters = {
            "events": [
                {"id": "user signed up", "type": "events", "order": 0},
                {"id": "paid", "type": "events", "order": 1},
            ],
            "insight": INSIGHT_FUNNELS,
            "funnel_window_days": 14,
            "date_from": "2021-05-01 00:00:00",
            "date_to": "2021-05-14 00:00:00",
            "exclusions": [{"id": "x", "type": "events", "funnel_from_step": 1, "funnel_to_step": 1},],
        }
        filter = Filter(data=filters)
        self.assertRaises(ValidationError, lambda: ClickhouseFunnel(filter, self.team))

        filter = filter.with_data(
            {"exclusions": [{"id": "x", "type": "events", "funnel_from_step": 1, "funnel_to_step": 2}]}
        )
        self.assertRaises(ValidationError, lambda: ClickhouseFunnel(filter, self.team))

        filter = filter.with_data(
            {"exclusions": [{"id": "x", "type": "events", "funnel_from_step": 2, "funnel_to_step": 1}]}
        )
        self.assertRaises(ValidationError, lambda: ClickhouseFunnel(filter, self.team))

        filter = filter.with_data(
            {"exclusions": [{"id": "x", "type": "events", "funnel_from_step": 0, "funnel_to_step": 2}]}
        )
        self.assertRaises(ValidationError, lambda: ClickhouseFunnel(filter, self.team))

    def test_funnel_exclusion_no_end_event(self):
        filters = {
            "events": [
                {"id": "user signed up", "type": "events", "order": 0},
                {"id": "paid", "type": "events", "order": 1},
            ],
            "insight": INSIGHT_FUNNELS,
            "funnel_window_days": 1,
            "date_from": "2021-05-01 00:00:00",
            "date_to": "2021-05-14 00:00:00",
            "exclusions": [{"id": "x", "type": "events", "funnel_from_step": 0, "funnel_to_step": 1},],
        }
        filter = Filter(data=filters)
        funnel = ClickhouseFunnel(filter, self.team)

        # event 1
        person1 = _create_person(distinct_ids=["person1"], team_id=self.team.pk)
        _create_event(team=self.team, event="user signed up", distinct_id="person1", timestamp="2021-05-01 01:00:00")
        _create_event(team=self.team, event="paid", distinct_id="person1", timestamp="2021-05-01 02:00:00")

        # event 2
        person2 = _create_person(distinct_ids=["person2"], team_id=self.team.pk)
        _create_event(team=self.team, event="user signed up", distinct_id="person2", timestamp="2021-05-01 03:00:00")
        _create_event(team=self.team, event="x", distinct_id="person2", timestamp="2021-05-01 03:30:00")
        _create_event(team=self.team, event="paid", distinct_id="person2", timestamp="2021-05-01 04:00:00")

        # event 3
        person3 = _create_person(distinct_ids=["person3"], team_id=self.team.pk)
        # should be discarded, even if nothing happened after x, since within conversion window
        _create_event(team=self.team, event="user signed up", distinct_id="person3", timestamp="2021-05-01 05:00:00")
        _create_event(team=self.team, event="x", distinct_id="person3", timestamp="2021-05-01 06:00:00")

        # event 4 - outside conversion window
        person4 = _create_person(distinct_ids=["person4"], team_id=self.team.pk)
        _create_event(team=self.team, event="user signed up", distinct_id="person4", timestamp="2021-05-01 07:00:00")
        _create_event(team=self.team, event="x", distinct_id="person4", timestamp="2021-05-02 08:00:00")

        result = funnel.run()
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["name"], "user signed up")
        self.assertEqual(result[0]["count"], 2)

        self.assertEqual(result[1]["name"], "paid")
        self.assertEqual(result[1]["count"], 1)

        self.assertCountEqual(
            self._get_actor_ids_at_step(filter, 1), [person1.uuid, person4.uuid],
        )
        self.assertCountEqual(
            self._get_actor_ids_at_step(filter, 2), [person1.uuid],
        )

    @test_with_materialized_columns(["key"])
    def test_funnel_exclusions_with_actions(self):

        sign_up_action = _create_action(
            name="sign up",
            team=self.team,
            properties=[{"key": "key", "type": "event", "value": ["val"], "operator": "exact"}],
        )

        filters = {
            "events": [
                {"id": "user signed up", "type": "events", "order": 0},
                {"id": "paid", "type": "events", "order": 1},
            ],
            "insight": INSIGHT_FUNNELS,
            "funnel_window_days": 14,
            "date_from": "2021-05-01 00:00:00",
            "date_to": "2021-05-14 00:00:00",
            "exclusions": [{"id": sign_up_action.id, "type": "actions", "funnel_from_step": 0, "funnel_to_step": 1},],
        }
        filter = Filter(data=filters)
        funnel = ClickhouseFunnel(filter, self.team)

        # event 1
        person1 = _create_person(distinct_ids=["person1"], team_id=self.team.pk)
        _create_event(team=self.team, event="user signed up", distinct_id="person1", timestamp="2021-05-01 01:00:00")
        _create_event(team=self.team, event="paid", distinct_id="person1", timestamp="2021-05-01 02:00:00")

        # event 2
        person2 = _create_person(distinct_ids=["person2"], team_id=self.team.pk)
        _create_event(team=self.team, event="user signed up", distinct_id="person2", timestamp="2021-05-01 03:00:00")
        _create_event(
            team=self.team,
            event="sign up",
            distinct_id="person2",
            properties={"key": "val"},
            timestamp="2021-05-01 03:30:00",
        )
        _create_event(team=self.team, event="paid", distinct_id="person2", timestamp="2021-05-01 04:00:00")

        # event 3
        person3 = _create_person(distinct_ids=["person3"], team_id=self.team.pk)
        _create_event(team=self.team, event="user signed up", distinct_id="person3", timestamp="2021-05-01 05:00:00")
        _create_event(team=self.team, event="paid", distinct_id="person3", timestamp="2021-05-01 06:00:00")

        result = funnel.run()
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["name"], "user signed up")
        self.assertEqual(result[0]["count"], 2)

        self.assertEqual(result[1]["name"], "paid")
        self.assertEqual(result[1]["count"], 2)

        self.assertCountEqual(
            self._get_actor_ids_at_step(filter, 1), [person1.uuid, person3.uuid],
        )
        self.assertCountEqual(
            self._get_actor_ids_at_step(filter, 2), [person1.uuid, person3.uuid],
        )

    def test_funnel_with_denormalised_properties(self):
        filters = {
            "events": [
                {
                    "id": "user signed up",
                    "type": "events",
                    "order": 0,
                    "properties": [{"key": "test_prop", "value": "hi"}],
                },
                {"id": "paid", "type": "events", "order": 1},
            ],
            "insight": INSIGHT_FUNNELS,
            "date_from": "2020-01-01",
            "properties": [{"key": "test_prop", "value": "hi"}],
            "date_to": "2020-01-14",
        }

        materialize("events", "test_prop")

        filter = Filter(data=filters)
        funnel = ClickhouseFunnel(filter, self.team)

        # event
        _create_person(distinct_ids=["user_1"], team_id=self.team.pk)
        _create_event(
            team=self.team,
            event="user signed up",
            distinct_id="user_1",
            timestamp="2020-01-02T14:00:00Z",
            properties={"test_prop": "hi"},
        )
        _create_event(
            team=self.team, event="paid", distinct_id="user_1", timestamp="2020-01-10T14:00:00Z",
        )

        self.assertNotIn("json", funnel.get_query().lower())
        result = funnel.run()

        self.assertEqual(result[0]["name"], "user signed up")
        self.assertEqual(result[0]["count"], 1)

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
                {"id": "x", "type": "events", "funnel_from_step": 0, "funnel_to_step": 1},
                {"id": "y", "type": "events", "funnel_from_step": 2, "funnel_to_step": 3},
            ],
        }

        person1 = _create_person(distinct_ids=["person1"], team_id=self.team.pk)
        _create_event(team=self.team, event="user signed up", distinct_id="person1", timestamp="2021-05-01 01:00:00")
        _create_event(team=self.team, event="x", distinct_id="person1", timestamp="2021-05-01 02:00:00")
        _create_event(team=self.team, event="$pageview", distinct_id="person1", timestamp="2021-05-01 03:00:00")
        _create_event(team=self.team, event="insight viewed", distinct_id="person1", timestamp="2021-05-01 04:00:00")
        _create_event(team=self.team, event="y", distinct_id="person1", timestamp="2021-05-01 04:30:00")
        _create_event(team=self.team, event="invite teammate", distinct_id="person1", timestamp="2021-05-01 05:00:00")
        _create_event(team=self.team, event="pageview2", distinct_id="person1", timestamp="2021-05-01 06:00:00")

        person2 = _create_person(distinct_ids=["person2"], team_id=self.team.pk)
        _create_event(team=self.team, event="user signed up", distinct_id="person2", timestamp="2021-05-01 01:00:00")
        _create_event(team=self.team, event="y", distinct_id="person2", timestamp="2021-05-01 01:30:00")
        _create_event(team=self.team, event="$pageview", distinct_id="person2", timestamp="2021-05-01 02:00:00")
        _create_event(team=self.team, event="insight viewed", distinct_id="person2", timestamp="2021-05-01 04:00:00")
        _create_event(team=self.team, event="y", distinct_id="person2", timestamp="2021-05-01 04:30:00")
        _create_event(team=self.team, event="invite teammate", distinct_id="person2", timestamp="2021-05-01 05:00:00")
        _create_event(team=self.team, event="x", distinct_id="person2", timestamp="2021-05-01 05:30:00")
        _create_event(team=self.team, event="pageview2", distinct_id="person2", timestamp="2021-05-01 06:00:00")

        person3 = _create_person(distinct_ids=["person3"], team_id=self.team.pk)
        _create_event(team=self.team, event="user signed up", distinct_id="person3", timestamp="2021-05-01 01:00:00")
        _create_event(team=self.team, event="x", distinct_id="person3", timestamp="2021-05-01 01:30:00")
        _create_event(team=self.team, event="$pageview", distinct_id="person3", timestamp="2021-05-01 02:00:00")
        _create_event(team=self.team, event="insight viewed", distinct_id="person3", timestamp="2021-05-01 04:00:00")
        _create_event(team=self.team, event="invite teammate", distinct_id="person3", timestamp="2021-05-01 05:00:00")
        _create_event(team=self.team, event="x", distinct_id="person3", timestamp="2021-05-01 05:30:00")
        _create_event(team=self.team, event="pageview2", distinct_id="person3", timestamp="2021-05-01 06:00:00")

        person4 = _create_person(distinct_ids=["person4"], team_id=self.team.pk)
        _create_event(team=self.team, event="user signed up", distinct_id="person4", timestamp="2021-05-01 01:00:00")
        _create_event(team=self.team, event="$pageview", distinct_id="person4", timestamp="2021-05-01 02:00:00")
        _create_event(team=self.team, event="insight viewed", distinct_id="person4", timestamp="2021-05-01 04:00:00")
        _create_event(team=self.team, event="invite teammate", distinct_id="person4", timestamp="2021-05-01 05:00:00")
        _create_event(team=self.team, event="pageview2", distinct_id="person4", timestamp="2021-05-01 06:00:00")

        filter = Filter(data=filters)
        funnel = ClickhouseFunnel(filter, self.team)

        result = funnel.run()

        self.assertEqual(result[0]["name"], "user signed up")
        self.assertEqual(result[0]["count"], 1)

        self.assertEqual(result[4]["count"], 1)

        self.assertCountEqual(
            self._get_actor_ids_at_step(filter, 1), [person4.uuid],
        )

        filter = filter.with_data(
            {
                "exclusions": [
                    {"id": "x", "type": "events", "funnel_from_step": 0, "funnel_to_step": 1},
                    {"id": "y", "type": "events", "funnel_from_step": 0, "funnel_to_step": 1},
                ],
            }
        )
        funnel = ClickhouseFunnel(filter, self.team)

        result = funnel.run()

        self.assertEqual(result[0]["name"], "user signed up")
        self.assertEqual(result[0]["count"], 1)

        self.assertEqual(result[4]["count"], 1)

        self.assertCountEqual(
            self._get_actor_ids_at_step(filter, 1), [person4.uuid],
        )

        filter = filter.with_data(
            {
                "exclusions": [
                    {"id": "x", "type": "events", "funnel_from_step": 0, "funnel_to_step": 1},
                    {"id": "y", "type": "events", "funnel_from_step": 0, "funnel_to_step": 1},
                ],
            }
        )
        funnel = ClickhouseFunnel(filter, self.team)

        result = funnel.run()

        self.assertEqual(result[0]["name"], "user signed up")
        self.assertEqual(result[0]["count"], 1)

        self.assertEqual(result[4]["count"], 1)

        self.assertCountEqual(
            self._get_actor_ids_at_step(filter, 1), [person4.uuid],
        )

        filter = filter.with_data(
            {
                "exclusions": [
                    {"id": "x", "type": "events", "funnel_from_step": 0, "funnel_to_step": 4},
                    {"id": "y", "type": "events", "funnel_from_step": 0, "funnel_to_step": 4},
                ],
            }
        )
        funnel = ClickhouseFunnel(filter, self.team)

        result = funnel.run()

        self.assertEqual(result[0]["name"], "user signed up")
        self.assertEqual(result[0]["count"], 1)

        self.assertEqual(result[4]["count"], 1)

        self.assertCountEqual(
            self._get_actor_ids_at_step(filter, 1), [person4.uuid],
        )

    def test_funnel_with_elements_chain(self):
        person1 = _create_person(distinct_ids=["test"], team_id=self.team.pk)
        _create_event(team=self.team, event="user signed up", distinct_id="test")
        _create_event(
            team=self.team,
            event="$autocapture",
            distinct_id="test",
            properties={"$current_url": "http://example.com/something_else"},
            elements=[Element(tag_name="img"), Element(tag_name="svg")],
        )

        person2 = _create_person(distinct_ids=["test2"], team_id=self.team.pk)
        _create_event(team=self.team, event="user signed up", distinct_id="test2")

        for tag_name in ["img", "svg"]:
            filters = {
                "events": [
                    {"id": "user signed up", "type": "events", "order": 0,},
                    {
                        "id": "$autocapture",
                        "name": "$autocapture",
                        "order": 1,
                        "properties": [
                            {"key": "tag_name", "value": [tag_name], "operator": "exact", "type": "element"}
                        ],
                        "type": "events",
                    },
                ],
                "insight": INSIGHT_FUNNELS,
            }

            filter = Filter(data=filters)
            result = ClickhouseFunnel(filter, self.team).run()

            self.assertEqual(len(result), 2)
            self.assertEqual(result[0]["name"], "user signed up")
            self.assertEqual(result[0]["count"], 2)

            self.assertEqual(result[1]["name"], "$autocapture")
            self.assertEqual(result[1]["count"], 1)

            self.assertCountEqual(
                self._get_actor_ids_at_step(filter, 1), [person1.uuid, person2.uuid],
            )
            self.assertCountEqual(
                self._get_actor_ids_at_step(filter, 2), [person1.uuid],
            )

    def test_breakdown_values_is_set_on_the_query_with_fewer_than_two_entities(self):
        """
        failing test for https://sentry.io/organizations/posthog/issues/2807609211/?project=1899813&referrer=slack
        """

        filter_with_breakdown = {
            "events": [{"id": "with one entity", "type": "events", "order": 0},],
            "breakdown": "something",
        }

        try:
            ClickhouseFunnel(Filter(data=filter_with_breakdown), self.team).run()
        except KeyError as ke:
            assert False, f"Should not have raised a key error: {ke}"

    @snapshot_clickhouse_queries
    def test_funnel_with_cohorts_step_filter(self):

        _create_person(distinct_ids=["user_1"], team_id=self.team.pk, properties={"email": "n@test.com"})
        _create_event(
            team=self.team, event="user signed up", distinct_id="user_1", timestamp="2020-01-02T14:00:00Z",
        )
        _create_event(
            team=self.team, event="paid", distinct_id="user_1", timestamp="2020-01-10T14:00:00Z",
        )

        _create_person(distinct_ids=["user_2"], team_id=self.team.pk)
        _create_event(
            team=self.team, event="user signed up", distinct_id="user_2", timestamp="2020-01-02T14:00:00Z",
        )
        _create_event(
            team=self.team, event="paid", distinct_id="user_2", timestamp="2020-01-10T14:00:00Z",
        )

        cohort = Cohort.objects.create(
            team=self.team,
            groups=[{"properties": [{"key": "email", "operator": "icontains", "value": ".com", "type": "person"}]}],
        )

        filters = {
            "events": [
                {
                    "id": "user signed up",
                    "type": "events",
                    "order": 0,
                    "properties": [{"type": "cohort", "key": "id", "value": cohort.pk}],
                },
                {"id": "paid", "type": "events", "order": 1},
            ],
            "insight": INSIGHT_FUNNELS,
            "date_from": "2020-01-01",
            "date_to": "2020-01-14",
        }

        result = ClickhouseFunnel(Filter(data=filters), self.team).run()

        self.assertEqual(result[0]["name"], "user signed up")
        self.assertEqual(result[0]["count"], 1)

        self.assertEqual(result[1]["name"], "paid")
        self.assertEqual(result[1]["count"], 1)

    @snapshot_clickhouse_queries
    def test_funnel_with_precalculated_cohort_step_filter(self):

        _create_person(distinct_ids=["user_1"], team_id=self.team.pk, properties={"email": "n@test.com"})
        _create_event(
            team=self.team, event="user signed up", distinct_id="user_1", timestamp="2020-01-02T14:00:00Z",
        )
        _create_event(
            team=self.team, event="paid", distinct_id="user_1", timestamp="2020-01-10T14:00:00Z",
        )

        _create_person(distinct_ids=["user_2"], team_id=self.team.pk)
        _create_event(
            team=self.team, event="user signed up", distinct_id="user_2", timestamp="2020-01-02T14:00:00Z",
        )
        _create_event(
            team=self.team, event="paid", distinct_id="user_2", timestamp="2020-01-10T14:00:00Z",
        )

        cohort = Cohort.objects.create(
            team=self.team,
            groups=[{"properties": [{"key": "email", "operator": "icontains", "value": ".com", "type": "person"}]}],
        )

        filters = {
            "events": [
                {
                    "id": "user signed up",
                    "type": "events",
                    "order": 0,
                    "properties": [{"type": "precalculated-cohort", "key": "id", "value": cohort.pk}],
                },
                {"id": "paid", "type": "events", "order": 1},
            ],
            "insight": INSIGHT_FUNNELS,
            "date_from": "2020-01-01",
            "date_to": "2020-01-14",
        }

        # converts to precalculated-cohort due to simplify filters
        cohort.calculate_people_ch(pending_version=0)

        with self.settings(USE_PRECALCULATED_CH_COHORT_PEOPLE=True):
            result = ClickhouseFunnel(Filter(data=filters), self.team).run()
            self.assertEqual(result[0]["name"], "user signed up")
            self.assertEqual(result[0]["count"], 1)

            self.assertEqual(result[1]["name"], "paid")
            self.assertEqual(result[1]["count"], 1)

    @snapshot_clickhouse_queries
    def test_funnel_with_static_cohort_step_filter(self):

        _create_person(distinct_ids=["user_1"], team_id=self.team.pk, properties={"email": "n@test.com"})
        _create_event(
            team=self.team, event="user signed up", distinct_id="user_1", timestamp="2020-01-02T14:00:00Z",
        )
        _create_event(
            team=self.team, event="paid", distinct_id="user_1", timestamp="2020-01-10T14:00:00Z",
        )

        _create_person(distinct_ids=["user_2"], team_id=self.team.pk)
        _create_event(
            team=self.team, event="user signed up", distinct_id="user_2", timestamp="2020-01-02T14:00:00Z",
        )
        _create_event(
            team=self.team, event="paid", distinct_id="user_2", timestamp="2020-01-10T14:00:00Z",
        )

        cohort = Cohort.objects.create(team=self.team, groups=[], is_static=True)
        cohort.insert_users_by_list(["user_2", "rando"])

        filters = {
            "events": [
                {
                    "id": "user signed up",
                    "type": "events",
                    "order": 0,
                    "properties": [{"type": "static-cohort", "key": "id", "value": cohort.pk}],
                },
                {"id": "paid", "type": "events", "order": 1},
            ],
            "insight": INSIGHT_FUNNELS,
            "date_from": "2020-01-01",
            "date_to": "2020-01-14",
        }

        result = ClickhouseFunnel(Filter(data=filters), self.team).run()

        self.assertEqual(result[0]["name"], "user signed up")
        self.assertEqual(result[0]["count"], 1)

        self.assertEqual(result[1]["name"], "paid")
        self.assertEqual(result[1]["count"], 1)

    @snapshot_clickhouse_queries
    @test_with_materialized_columns(["$current_url"], person_properties=["email", "age"])
    def test_funnel_with_property_groups(self):
        filters = {
            "date_from": "2020-01-01 00:00:00",
            "date_to": "2020-07-01 00:00:00",
            "events": [
                {"id": "user signed up", "order": 0},
                {"id": "$pageview", "order": 1, "properties": {"$current_url": "aloha.com"}},
                {
                    "id": "$pageview",
                    "order": 2,
                    "properties": {"$current_url": "aloha2.com"},
                },  # different event to above
            ],
            "insight": INSIGHT_FUNNELS,
            "funnel_window_days": 14,
            "properties": {
                "type": "OR",
                "values": [
                    {
                        "type": "AND",
                        "values": [
                            {"key": "email", "operator": "icontains", "value": ".com", "type": "person"},
                            {"key": "age", "operator": "exact", "value": "20", "type": "person"},
                        ],
                    },
                    {
                        "type": "OR",
                        "values": [
                            {"key": "email", "operator": "icontains", "value": ".org", "type": "person"},
                            {"key": "age", "operator": "exact", "value": "28", "type": "person"},
                        ],
                    },
                ],
            },
        }

        filter = Filter(data=filters)
        funnel = ClickhouseFunnel(filter, self.team)

        people = {}
        people["stopped_after_signup1"] = _create_person(
            distinct_ids=["stopped_after_signup1"],
            team_id=self.team.pk,
            properties={"email": "test@b.com", "age": "18"},
        )
        people["stopped_after_pageview1"] = _create_person(
            distinct_ids=["stopped_after_pageview1"],
            team_id=self.team.pk,
            properties={"email": "test@b.org", "age": "28"},
        )
        people["stopped_after_pageview2"] = _create_person(
            distinct_ids=["stopped_after_pageview2"],
            team_id=self.team.pk,
            properties={"email": "test2@b.com", "age": "28"},
        )
        people["stopped_after_pageview3"] = _create_person(
            distinct_ids=["stopped_after_pageview3"],
            team_id=self.team.pk,
            properties={"email": "test3@b.com", "age": "28"},
        )
        people["stopped_after_pageview4"] = _create_person(
            distinct_ids=["stopped_after_pageview4"],
            team_id=self.team.pk,
            properties={"email": "test4@b.org", "age": "18"},
        )

        # event
        journeys_for(
            {
                "stopped_after_signup1": [{"event": "user signed up", "timestamp": datetime(2020, 5, 1, 0)}],
                "stopped_after_pageview1": [{"event": "user signed up", "timestamp": datetime(2020, 5, 1, 0)},],
                "stopped_after_pageview2": [
                    {"event": "user signed up", "timestamp": datetime(2020, 5, 1, 0)},
                    {
                        "event": "$pageview",
                        "properties": {"$current_url": "aloha.com"},
                        "timestamp": datetime(2020, 5, 2, 0),
                    },
                ],
                "stopped_after_pageview3": [
                    {"event": "user signed up", "timestamp": datetime(2020, 5, 1, 0)},
                    {
                        "event": "$pageview",
                        "properties": {"$current_url": "aloha.com"},
                        "timestamp": datetime(2020, 5, 2, 0),
                    },
                    {
                        "event": "$pageview",
                        "properties": {"$current_url": "aloha2.com"},
                        "timestamp": datetime(2020, 5, 3, 0),
                    },
                ],
                "stopped_after_pageview4": [
                    # {"event": "user signed up"}, # no signup, so not in funnel
                    {
                        "event": "$pageview",
                        "properties": {"$current_url": "aloha.com"},
                        "timestamp": datetime(2020, 5, 2, 0),
                    },
                    {
                        "event": "$pageview",
                        "properties": {"$current_url": "aloha2.com"},
                        "timestamp": datetime(2020, 5, 3, 0),
                    },
                    {
                        "event": "$pageview",
                        "properties": {"$current_url": "aloha2.com"},
                        "timestamp": datetime(2020, 5, 4, 0),
                    },
                ],
            },
            self.team,
            create_people=False,
        )

        result = funnel.run()

        self.assertEqual(result[0]["name"], "user signed up")
        self.assertEqual(result[1]["name"], "$pageview")
        self.assertEqual(result[2]["name"], "$pageview")
        self.assertEqual(result[0]["count"], 3)
        self.assertEqual(result[1]["count"], 2)
        self.assertEqual(result[2]["count"], 1)
        # check ordering of people in every step
        self.assertCountEqual(
            self._get_actor_ids_at_step(filter, 1),
            [
                people["stopped_after_pageview1"].uuid,
                people["stopped_after_pageview2"].uuid,
                people["stopped_after_pageview3"].uuid,
            ],
        )

        self.assertCountEqual(
            self._get_actor_ids_at_step(filter, 2),
            [people["stopped_after_pageview2"].uuid, people["stopped_after_pageview3"].uuid,],
        )

        self.assertCountEqual(
            self._get_actor_ids_at_step(filter, 3), [people["stopped_after_pageview3"].uuid,],
        )

    @patch("posthoganalytics.feature_enabled", return_value=True)
    def test_timezones(self, patch_feature_enabled):
        self.team.timezone = "US/Pacific"
        self.team.save()

        filters = {
            "events": [
                {"id": "user signed up", "type": "events", "order": 0},
                {"id": "paid", "type": "events", "order": 1},
            ],
            "insight": INSIGHT_FUNNELS,
            "date_from": "2020-01-01",
            "date_to": "2020-01-14",
        }

        filter = Filter(data=filters)
        funnel = ClickhouseFunnel(filter, self.team)

        # event
        _create_person(distinct_ids=["user_1"], team_id=self.team.pk)
        #  this event shouldn't appear as in US/Pacific this would be the previous day
        _create_event(
            team=self.team, event="user signed up", distinct_id="user_1", timestamp="2020-01-01T01:00:00Z",
        )
        result = funnel.run()

        self.assertEqual(result[0]["name"], "user signed up")
        self.assertEqual(result[0]["count"], 0)
