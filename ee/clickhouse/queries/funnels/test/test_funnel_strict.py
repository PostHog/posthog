from datetime import datetime, timedelta
from uuid import uuid4

from ee.clickhouse.client import sync_execute
from ee.clickhouse.models.event import create_event
from ee.clickhouse.queries.funnels.funnel_strict import ClickhouseFunnelStrict
from ee.clickhouse.queries.funnels.funnel_strict_persons import ClickhouseFunnelStrictPersons
from ee.clickhouse.util import ClickhouseTestMixin
from posthog.constants import INSIGHT_FUNNELS
from posthog.models.action import Action
from posthog.models.action_step import ActionStep
from posthog.models.filters import Filter
from posthog.models.person import Person
from posthog.test.base import APIBaseTest

FORMAT_TIME = "%Y-%m-%d 00:00:00"


def _create_action(**kwargs):
    team = kwargs.pop("team")
    name = kwargs.pop("name")
    properties = kwargs.pop("properties", {})
    action = Action.objects.create(team=team, name=name)
    ActionStep.objects.create(action=action, event=name, properties=properties)
    return action


def _create_person(**kwargs):
    person = Person.objects.create(**kwargs)
    return Person(id=person.uuid, uuid=person.uuid)


def _create_event(**kwargs):
    kwargs.update({"event_uuid": uuid4()})
    create_event(**kwargs)


class TestFunnelStrictSteps(ClickhouseTestMixin, APIBaseTest):

    maxDiff = None

    def _get_people_at_step(self, filter, funnel_step, breakdown_value=None):
        person_filter = filter.with_data({"funnel_step": funnel_step, "funnel_step_breakdown": breakdown_value})
        result = ClickhouseFunnelStrictPersons(person_filter, self.team)._exec_query()
        return [row[0] for row in result]

    def test_basic_strict_funnel(self):
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

        funnel = ClickhouseFunnelStrict(filter, self.team)

        person1_stopped_after_signup = _create_person(distinct_ids=["stopped_after_signup1"], team_id=self.team.pk)
        _create_event(team=self.team, event="user signed up", distinct_id="stopped_after_signup1")

        person2_stopped_after_one_pageview = _create_person(
            distinct_ids=["stopped_after_pageview1"], team_id=self.team.pk
        )
        _create_event(team=self.team, event="$pageview", distinct_id="stopped_after_pageview1")
        _create_event(team=self.team, event="user signed up", distinct_id="stopped_after_pageview1")

        person3_stopped_after_insight_view = _create_person(
            distinct_ids=["stopped_after_insightview"], team_id=self.team.pk
        )
        _create_event(team=self.team, event="user signed up", distinct_id="stopped_after_insightview")
        _create_event(team=self.team, event="$pageview", distinct_id="stopped_after_insightview")
        _create_event(team=self.team, event="blaah blaa", distinct_id="stopped_after_insightview")
        _create_event(team=self.team, event="insight viewed", distinct_id="stopped_after_insightview")

        person4_stopped_after_insight_view_not_strict_order = _create_person(
            distinct_ids=["stopped_after_insightview2"], team_id=self.team.pk
        )
        _create_event(team=self.team, event="insight viewed", distinct_id="stopped_after_insightview2")
        _create_event(team=self.team, event="blaah blaa", distinct_id="stopped_after_insightview2")
        _create_event(team=self.team, event="$pageview", distinct_id="stopped_after_insightview2")
        _create_event(team=self.team, event="user signed up", distinct_id="stopped_after_insightview2")

        person5_stopped_after_insight_view_random = _create_person(
            distinct_ids=["stopped_after_insightview3"], team_id=self.team.pk
        )
        _create_event(team=self.team, event="$pageview", distinct_id="stopped_after_insightview3")
        _create_event(team=self.team, event="user signed up", distinct_id="stopped_after_insightview3")
        _create_event(team=self.team, event="blaah blaa", distinct_id="stopped_after_insightview3")
        _create_event(team=self.team, event="$pageview", distinct_id="stopped_after_insightview3")
        _create_event(team=self.team, event="insight viewed", distinct_id="stopped_after_insightview3")

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

        person8_didnot_signup = _create_person(distinct_ids=["stopped_after_insightview6"], team_id=self.team.pk)
        _create_event(team=self.team, event="insight viewed", distinct_id="stopped_after_insightview6")
        _create_event(team=self.team, event="$pageview", distinct_id="stopped_after_insightview6")

        result = funnel.run()

        self.assertEqual(result[0]["name"], "user signed up")
        self.assertEqual(result[1]["name"], "$pageview")
        self.assertEqual(result[2]["name"], "insight viewed")
        self.assertEqual(result[0]["count"], 7)

        self.assertCountEqual(
            self._get_people_at_step(filter, 1),
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
            self._get_people_at_step(filter, 2), [person3_stopped_after_insight_view.uuid, person7.uuid,],
        )

        self.assertCountEqual(
            self._get_people_at_step(filter, 3), [person7.uuid],
        )

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
            "events": [
                {"id": "user signed up", "type": "events", "order": 0},
                {"id": "$pageview", "type": "events", "order": 2},
            ],
            "actions": [
                {"id": sign_up_action.id, "math": "dau", "order": 1},
                {"id": view_action.id, "math": "wau", "order": 3},
            ],
            "insight": INSIGHT_FUNNELS,
        }

        filter = Filter(data=filters)
        funnel = ClickhouseFunnelStrict(filter, self.team)

        person1_stopped_after_signup = _create_person(distinct_ids=["stopped_after_signup1"], team_id=self.team.pk)
        _create_event(team=self.team, event="user signed up", distinct_id="stopped_after_signup1")

        person2_stopped_after_one_pageview = _create_person(
            distinct_ids=["stopped_after_pageview1"], team_id=self.team.pk
        )
        _create_event(team=self.team, event="user signed up", distinct_id="stopped_after_pageview1")
        _create_event(team=self.team, event="$pageview", distinct_id="stopped_after_pageview1")

        person3_stopped_after_insight_view = _create_person(
            distinct_ids=["stopped_after_insightview"], team_id=self.team.pk
        )
        _create_event(team=self.team, event="user signed up", distinct_id="stopped_after_insightview")
        _create_event(
            team=self.team, event="sign up", distinct_id="stopped_after_insightview", properties={"key": "val"}
        )
        _create_event(
            team=self.team, event="sign up", distinct_id="stopped_after_insightview", properties={"key": "val2"}
        )
        _create_event(team=self.team, event="$pageview", distinct_id="stopped_after_insightview")
        _create_event(team=self.team, event="blaah blaa", distinct_id="stopped_after_insightview")
        _create_event(team=self.team, event="insight viewed", distinct_id="stopped_after_insightview")

        person4 = _create_person(distinct_ids=["person4"], team_id=self.team.pk)
        _create_event(team=self.team, event="blaah blaa", distinct_id="person4")
        _create_event(team=self.team, event="user signed up", distinct_id="person4")
        _create_event(team=self.team, event="sign up", distinct_id="person4", properties={"key": "val"})
        _create_event(team=self.team, event="$pageview", distinct_id="person4", properties={"key": "val"})
        _create_event(team=self.team, event="blaah blaa", distinct_id="person4")

        person5 = _create_person(distinct_ids=["person5"], team_id=self.team.pk)
        _create_event(team=self.team, event="blaah blaa", distinct_id="person5")
        _create_event(team=self.team, event="user signed up", distinct_id="person5")
        _create_event(team=self.team, event="sign up", distinct_id="person5", properties={"key": "val"})
        _create_event(team=self.team, event="$pageview", distinct_id="person5")
        _create_event(team=self.team, event="blaah blaa", distinct_id="person5")

        person6 = _create_person(distinct_ids=["person6"], team_id=self.team.pk)
        _create_event(team=self.team, event="blaah blaa", distinct_id="person6")
        _create_event(team=self.team, event="user signed up", distinct_id="person6")
        _create_event(team=self.team, event="sign up", distinct_id="person6", properties={"key": "val"})
        _create_event(team=self.team, event="$pageview", distinct_id="person6")
        _create_event(team=self.team, event="pageview", distinct_id="person6", properties={"key": "val1"})

        person7 = _create_person(distinct_ids=["person7"], team_id=self.team.pk)
        _create_event(team=self.team, event="blaah blaa", distinct_id="person7")
        _create_event(team=self.team, event="user signed up", distinct_id="person7")
        _create_event(team=self.team, event="sign up", distinct_id="person7", properties={"key": "val"})
        _create_event(team=self.team, event="$pageview", distinct_id="person7")
        _create_event(team=self.team, event="user signed up", distinct_id="person7")
        _create_event(team=self.team, event="pageview", distinct_id="person7", properties={"key": "val"})

        person8 = _create_person(distinct_ids=["person8"], team_id=self.team.pk)
        _create_event(team=self.team, event="blaah blaa", distinct_id="person8")
        _create_event(team=self.team, event="user signed up", distinct_id="person8")
        _create_event(team=self.team, event="user signed up", distinct_id="person8")
        _create_event(team=self.team, event="sign up", distinct_id="person8", properties={"key": "val"})
        _create_event(team=self.team, event="$pageview", distinct_id="person8")
        _create_event(team=self.team, event="pageview", distinct_id="person8", properties={"key": "val"})

        result = funnel.run()

        self.assertEqual(result[0]["name"], "user signed up")
        self.assertEqual(result[1]["name"], "sign up")
        self.assertEqual(result[2]["name"], "$pageview")
        self.assertEqual(result[3]["name"], "pageview")
        self.assertEqual(result[0]["count"], 8)

        self.assertCountEqual(
            self._get_people_at_step(filter, 1),
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
            self._get_people_at_step(filter, 2),
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
            self._get_people_at_step(filter, 3),
            [person4.uuid, person5.uuid, person6.uuid, person7.uuid, person8.uuid,],
        )

        self.assertCountEqual(
            self._get_people_at_step(filter, 4), [person8.uuid,],
        )

    def test_basic_strict_funnel_conversion_times(self):
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
            }
        )

        funnel = ClickhouseFunnelStrict(filter, self.team)

        person1_stopped_after_signup = _create_person(distinct_ids=["stopped_after_signup1"], team_id=self.team.pk)
        _create_event(
            team=self.team, event="user signed up", distinct_id="stopped_after_signup1", timestamp="2021-05-02 00:00:00"
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
            team=self.team, event="$pageview", distinct_id="stopped_after_pageview1", timestamp="2021-05-02 01:00:00"
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
            team=self.team, event="$pageview", distinct_id="stopped_after_insightview", timestamp="2021-05-02 02:00:00"
        )
        _create_event(
            team=self.team,
            event="insight viewed",
            distinct_id="stopped_after_insightview",
            timestamp="2021-05-02 04:00:00",
        )

        result = funnel.run()

        self.assertEqual(result[0]["name"], "user signed up")
        self.assertEqual(result[1]["name"], "$pageview")
        self.assertEqual(result[2]["name"], "insight viewed")
        self.assertEqual(result[0]["count"], 3)

        self.assertEqual(result[1]["average_conversion_time"], 5400)
        # 1 hour for Person 2, 2 hours for Person 3, average = 1.5 hours

        self.assertEqual(result[2]["average_conversion_time"], 7200)
        # 2 hours for Person 3

        self.assertCountEqual(
            self._get_people_at_step(filter, 1),
            [
                person1_stopped_after_signup.uuid,
                person2_stopped_after_one_pageview.uuid,
                person3_stopped_after_insight_view.uuid,
            ],
        )

        self.assertCountEqual(
            self._get_people_at_step(filter, 2),
            [person2_stopped_after_one_pageview.uuid, person3_stopped_after_insight_view.uuid],
        )

        self.assertCountEqual(
            self._get_people_at_step(filter, 3), [person3_stopped_after_insight_view.uuid],
        )

    def test_funnel_step_breakdown_event(self):

        filters = {
            "events": [{"id": "sign up", "order": 0}, {"id": "play movie", "order": 1}, {"id": "buy", "order": 2},],
            "insight": INSIGHT_FUNNELS,
            "date_from": "2020-01-01",
            "date_to": "2020-01-08",
            "funnel_window_days": 7,
            "breakdown_type": "event",
            "breakdown": "$browser",
        }

        filter = Filter(data=filters)
        funnel = ClickhouseFunnelStrict(filter, self.team)

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
            event="play movie",
            distinct_id="person1",
            properties={"key": "val", "$browser": "Chrome"},
            timestamp="2020-01-01T13:00:00Z",
        )
        _create_event(
            team=self.team,
            event="buy",
            distinct_id="person1",
            properties={"key": "val", "$browser": "Chrome"},
            timestamp="2020-01-01T15:00:00Z",
        )

        person2 = _create_person(distinct_ids=["person2"], team_id=self.team.pk)
        _create_event(
            team=self.team,
            event="sign up",
            distinct_id="person2",
            properties={"key": "val", "$browser": "Safari"},
            timestamp="2020-01-02T14:00:00Z",
        )
        _create_event(
            team=self.team,
            event="play movie",
            distinct_id="person2",
            properties={"key": "val", "$browser": "Safari"},
            timestamp="2020-01-02T16:00:00Z",
        )

        person3 = _create_person(distinct_ids=["person3"], team_id=self.team.pk)
        _create_event(
            team=self.team,
            event="sign up",
            distinct_id="person3",
            properties={"key": "val", "$browser": "Safari"},
            timestamp="2020-01-02T14:00:00Z",
        )
        _create_event(
            team=self.team,
            event="blah",
            distinct_id="person3",
            properties={"key": "val", "$browser": "Safari"},
            timestamp="2020-01-02T15:00:00Z",
        )
        _create_event(
            team=self.team,
            event="play movie",
            distinct_id="person3",
            properties={"key": "val", "$browser": "Safari"},
            timestamp="2020-01-02T16:00:00Z",
        )

        result = funnel.run()
        self.assertEqual(
            result[0],
            [
                {
                    "action_id": "sign up",
                    "name": "sign up",
                    "order": 0,
                    "people": [],
                    "count": 1,
                    "type": "events",
                    "average_conversion_time": None,
                    "breakdown": '"Chrome"',
                },
                {
                    "action_id": "play movie",
                    "name": "play movie",
                    "order": 1,
                    "people": [],
                    "count": 1,
                    "type": "events",
                    "average_conversion_time": 3600.0,
                    "breakdown": '"Chrome"',
                },
                {
                    "action_id": "buy",
                    "name": "buy",
                    "order": 2,
                    "people": [],
                    "count": 1,
                    "type": "events",
                    "average_conversion_time": 7200.0,
                    "breakdown": '"Chrome"',
                },
            ],
        )
        self.assertCountEqual(self._get_people_at_step(filter, 1, '"Chrome"'), [person1.uuid])
        self.assertCountEqual(self._get_people_at_step(filter, 2, '"Chrome"'), [person1.uuid])
        self.assertEqual(
            result[1],
            [
                {
                    "action_id": "sign up",
                    "name": "sign up",
                    "order": 0,
                    "people": [],
                    "count": 2,
                    "type": "events",
                    "average_conversion_time": None,
                    "breakdown": '"Safari"',
                },
                {
                    "action_id": "play movie",
                    "name": "play movie",
                    "order": 1,
                    "people": [],
                    "count": 1,
                    "type": "events",
                    "average_conversion_time": 7200.0,
                    "breakdown": '"Safari"',
                },
                {
                    "action_id": "buy",
                    "name": "buy",
                    "order": 2,
                    "people": [],
                    "count": 0,
                    "type": "events",
                    "average_conversion_time": None,
                    "breakdown": '"Safari"',
                },
            ],
        )

        self.assertCountEqual(self._get_people_at_step(filter, 1, '"Safari"'), [person2.uuid, person3.uuid])
        self.assertCountEqual(self._get_people_at_step(filter, 2, '"Safari"'), [person2.uuid])

    def test_funnel_step_breakdown_person(self):

        filters = {
            "events": [{"id": "sign up", "order": 0}, {"id": "play movie", "order": 1}, {"id": "buy", "order": 2},],
            "insight": INSIGHT_FUNNELS,
            "date_from": "2020-01-01",
            "date_to": "2020-01-08",
            "funnel_window_days": 7,
            "breakdown_type": "person",
            "breakdown": "$browser",
        }

        filter = Filter(data=filters)
        funnel = ClickhouseFunnelStrict(filter, self.team)

        # event
        person1 = _create_person(distinct_ids=["person1"], team_id=self.team.pk, properties={"$browser": "Chrome"})
        _create_event(
            team=self.team,
            event="sign up",
            distinct_id="person1",
            properties={"key": "val"},
            timestamp="2020-01-01T12:00:00Z",
        )
        _create_event(
            team=self.team,
            event="play movie",
            distinct_id="person1",
            properties={"key": "val"},
            timestamp="2020-01-01T13:00:00Z",
        )
        _create_event(
            team=self.team,
            event="buy",
            distinct_id="person1",
            properties={"key": "val"},
            timestamp="2020-01-01T15:00:00Z",
        )

        person2 = _create_person(distinct_ids=["person2"], team_id=self.team.pk, properties={"$browser": "Safari"})
        _create_event(
            team=self.team,
            event="sign up",
            distinct_id="person2",
            properties={"key": "val"},
            timestamp="2020-01-02T14:00:00Z",
        )
        _create_event(
            team=self.team,
            event="play movie",
            distinct_id="person2",
            properties={"key": "val"},
            timestamp="2020-01-02T16:00:00Z",
        )

        result = funnel.run()
        self.assertEqual(
            result[0],
            [
                {
                    "action_id": "sign up",
                    "name": "sign up",
                    "order": 0,
                    "people": [],
                    "count": 1,
                    "type": "events",
                    "average_conversion_time": None,
                    "breakdown": '"Chrome"',
                },
                {
                    "action_id": "play movie",
                    "name": "play movie",
                    "order": 1,
                    "people": [],
                    "count": 1,
                    "type": "events",
                    "average_conversion_time": 3600.0,
                    "breakdown": '"Chrome"',
                },
                {
                    "action_id": "buy",
                    "name": "buy",
                    "order": 2,
                    "people": [],
                    "count": 1,
                    "type": "events",
                    "average_conversion_time": 7200.0,
                    "breakdown": '"Chrome"',
                },
            ],
        )
        self.assertCountEqual(self._get_people_at_step(filter, 1, '"Chrome"'), [person1.uuid])
        self.assertCountEqual(self._get_people_at_step(filter, 2, '"Chrome"'), [person1.uuid])

        self.assertEqual(
            result[1],
            [
                {
                    "action_id": "sign up",
                    "name": "sign up",
                    "order": 0,
                    "people": [],
                    "count": 1,
                    "type": "events",
                    "average_conversion_time": None,
                    "breakdown": '"Safari"',
                },
                {
                    "action_id": "play movie",
                    "name": "play movie",
                    "order": 1,
                    "people": [],
                    "count": 1,
                    "type": "events",
                    "average_conversion_time": 7200.0,
                    "breakdown": '"Safari"',
                },
                {
                    "action_id": "buy",
                    "name": "buy",
                    "order": 2,
                    "people": [],
                    "count": 0,
                    "type": "events",
                    "average_conversion_time": None,
                    "breakdown": '"Safari"',
                },
            ],
        )
        self.assertCountEqual(self._get_people_at_step(filter, 1, '"Safari"'), [person2.uuid])
        self.assertCountEqual(self._get_people_at_step(filter, 3, '"Safari"'), [])

    def test_funnel_step_breakdown_limit(self):

        filters = {
            "events": [{"id": "sign up", "order": 0}, {"id": "play movie", "order": 1}, {"id": "buy", "order": 2},],
            "insight": INSIGHT_FUNNELS,
            "date_from": "2020-01-01",
            "date_to": "2020-01-08",
            "funnel_window_days": 7,
            "breakdown_type": "event",
            "breakdown": "some_breakdown_val",
        }

        filter = Filter(data=filters)
        funnel = ClickhouseFunnelStrict(filter, self.team)

        for num in range(10):
            for i in range(num):
                _create_person(distinct_ids=[f"person_{num}_{i}"], team_id=self.team.pk)
                _create_event(
                    team=self.team,
                    event="sign up",
                    distinct_id=f"person_{num}_{i}",
                    properties={"key": "val", "some_breakdown_val": num},
                    timestamp="2020-01-01T12:00:00Z",
                )
                _create_event(
                    team=self.team,
                    event="play movie",
                    distinct_id=f"person_{num}_{i}",
                    properties={"key": "val", "some_breakdown_val": num},
                    timestamp="2020-01-01T13:00:00Z",
                )
                _create_event(
                    team=self.team,
                    event="buy",
                    distinct_id=f"person_{num}_{i}",
                    properties={"key": "val", "some_breakdown_val": num},
                    timestamp="2020-01-01T15:00:00Z",
                )

        result = funnel.run()

        # assert that we give 5 at a time at most and that those values are the most popular ones
        breakdown_vals = sorted([res[0]["breakdown"] for res in result])
        self.assertEqual(["5", "6", "7", "8", "9"], breakdown_vals)
