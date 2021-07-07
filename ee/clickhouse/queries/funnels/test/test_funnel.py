import operator
from uuid import uuid4

from ee.clickhouse.models.event import create_event
from ee.clickhouse.queries.funnels.funnel import ClickhouseFunnel, ClickhouseFunnelNew
from ee.clickhouse.queries.funnels.funnel_persons import ClickhouseFunnelPersons
from ee.clickhouse.util import ClickhouseTestMixin
from posthog.constants import INSIGHT_FUNNELS
from posthog.models.action import Action
from posthog.models.action_step import ActionStep
from posthog.models.filters import Filter
from posthog.models.person import Person
from posthog.queries.test.test_funnel import funnel_test_factory

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


def _create_person(**kwargs):
    person = Person.objects.create(**kwargs)
    return Person(id=person.uuid, uuid=person.uuid)


def _create_event(**kwargs):
    kwargs.update({"event_uuid": uuid4()})
    create_event(**kwargs)


class TestFunnel(ClickhouseTestMixin, funnel_test_factory(ClickhouseFunnel, _create_event, _create_person)):  # type: ignore
    pass


class TestFunnelNew(ClickhouseTestMixin, funnel_test_factory(ClickhouseFunnelNew, _create_event, _create_person)):  # type: ignore
    def _get_people_at_step(self, filter, funnel_step):
        person_filter = filter.with_data({"funnel_step": funnel_step})
        result = ClickhouseFunnelPersons(person_filter, self.team)._exec_query()
        return [row[0] for row in result]

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
        funnel = ClickhouseFunnelNew(filter, self.team)

        # event
        _create_person(distinct_ids=["user_1"], team_id=self.team.pk)
        _create_event(
            team=self.team, event="user signed up", distinct_id="user_1", timestamp="2020-01-02T14:00:00Z",
        )
        _create_event(
            team=self.team, event="paid", distinct_id="user_1", timestamp="2020-01-10T14:00:00Z",
        )

        with self.assertNumQueries(1):
            result = funnel.run()

        self.assertEqual(result[0]["name"], "user signed up")
        self.assertEqual(result[0]["count"], 1)
        self.assertEqual(len(result[0]["people"]), 1)

        self.assertEqual(result[1]["name"], "paid")
        self.assertEqual(result[1]["count"], 1)
        self.assertEqual(len(result[1]["people"]), 1)

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
        funnel = ClickhouseFunnelNew(filter, self.team)

        # event
        person1_stopped_after_two_signups = _create_person(distinct_ids=["stopped_after_signup1"], team_id=self.team.pk)
        _create_event(team=self.team, event="user signed up", distinct_id="stopped_after_signup1")
        _create_event(team=self.team, event="user signed up", distinct_id="stopped_after_signup1")

        person2_stopped_after_signup = _create_person(distinct_ids=["stopped_after_signup2"], team_id=self.team.pk)
        _create_event(team=self.team, event="user signed up", distinct_id="stopped_after_signup2")

        result = funnel.run()

        self.assertEqual(result[0]["name"], "user signed up")
        self.assertEqual(result[0]["count"], 2)
        self.assertEqual(len(result[0]["people"]), 2)
        self.assertEqual(result[1]["count"], 1)
        self.assertEqual(len(result[1]["people"]), 1)

        self.assertCountEqual(
            self._get_people_at_step(filter, 1),
            [person1_stopped_after_two_signups.uuid, person2_stopped_after_signup.uuid],
        )

        self.assertCountEqual(
            self._get_people_at_step(filter, 2), [person1_stopped_after_two_signups.uuid],
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
        funnel = ClickhouseFunnelNew(filter, self.team)

        # event
        person1_stopped_after_signup = _create_person(distinct_ids=["stopped_after_signup1"], team_id=self.team.pk)
        _create_event(team=self.team, event="user signed up", distinct_id="stopped_after_signup1")

        person2_stopped_after_one_pageview = _create_person(
            distinct_ids=["stopped_after_pageview1"], team_id=self.team.pk
        )
        _create_event(team=self.team, event="user signed up", distinct_id="stopped_after_pageview1")
        _create_event(team=self.team, event="$pageview", distinct_id="stopped_after_pageview1")

        person3_stopped_after_two_pageview = _create_person(
            distinct_ids=["stopped_after_pageview2"], team_id=self.team.pk
        )
        _create_event(team=self.team, event="user signed up", distinct_id="stopped_after_pageview2")
        _create_event(team=self.team, event="$pageview", distinct_id="stopped_after_pageview2")
        _create_event(team=self.team, event="blaah blaa", distinct_id="stopped_after_pageview2")
        _create_event(team=self.team, event="$pageview", distinct_id="stopped_after_pageview2")

        person4_stopped_after_three_pageview = _create_person(
            distinct_ids=["stopped_after_pageview3"], team_id=self.team.pk
        )
        _create_event(team=self.team, event="user signed up", distinct_id="stopped_after_pageview3")
        _create_event(team=self.team, event="$pageview", distinct_id="stopped_after_pageview3")
        _create_event(team=self.team, event="blaah blaa", distinct_id="stopped_after_pageview3")
        _create_event(team=self.team, event="$pageview", distinct_id="stopped_after_pageview3")
        _create_event(team=self.team, event="$pageview", distinct_id="stopped_after_pageview3")
        _create_event(team=self.team, event="blaah blaa", distinct_id="stopped_after_pageview3")

        person5_stopped_after_many_pageview = _create_person(
            distinct_ids=["stopped_after_pageview4"], team_id=self.team.pk
        )
        _create_event(team=self.team, event="user signed up", distinct_id="stopped_after_pageview4")
        _create_event(team=self.team, event="$pageview", distinct_id="stopped_after_pageview4")
        _create_event(team=self.team, event="$pageview", distinct_id="stopped_after_pageview4")
        _create_event(team=self.team, event="$pageview", distinct_id="stopped_after_pageview4")
        _create_event(team=self.team, event="$pageview", distinct_id="stopped_after_pageview4")

        result = funnel.run()

        self.assertEqual(result[0]["name"], "user signed up")
        self.assertEqual(result[1]["name"], "$pageview")
        self.assertEqual(result[4]["name"], "$pageview")
        self.assertEqual(result[0]["count"], 5)
        self.assertEqual(len(result[0]["people"]), 5)
        self.assertEqual(result[1]["count"], 4)
        self.assertEqual(len(result[1]["people"]), 4)
        self.assertEqual(result[2]["count"], 3)
        self.assertEqual(len(result[2]["people"]), 3)
        self.assertEqual(result[3]["count"], 2)
        self.assertEqual(len(result[3]["people"]), 2)
        self.assertEqual(result[4]["count"], 1)
        self.assertEqual(len(result[4]["people"]), 1)
        # check ordering of people in every step
        self.assertCountEqual(
            self._get_people_at_step(filter, 1),
            [
                person1_stopped_after_signup.uuid,
                person2_stopped_after_one_pageview.uuid,
                person3_stopped_after_two_pageview.uuid,
                person4_stopped_after_three_pageview.uuid,
                person5_stopped_after_many_pageview.uuid,
            ],
        )

        self.assertCountEqual(
            self._get_people_at_step(filter, 2),
            [
                person2_stopped_after_one_pageview.uuid,
                person3_stopped_after_two_pageview.uuid,
                person4_stopped_after_three_pageview.uuid,
                person5_stopped_after_many_pageview.uuid,
            ],
        )

        self.assertCountEqual(
            self._get_people_at_step(filter, 3),
            [
                person3_stopped_after_two_pageview.uuid,
                person4_stopped_after_three_pageview.uuid,
                person5_stopped_after_many_pageview.uuid,
            ],
        )

        self.assertCountEqual(
            self._get_people_at_step(filter, 4),
            [person4_stopped_after_three_pageview.uuid, person5_stopped_after_many_pageview.uuid],
        )

        self.assertCountEqual(
            self._get_people_at_step(filter, 5), [person5_stopped_after_many_pageview.uuid],
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
        funnel = ClickhouseFunnelNew(filter, self.team)

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
        self.assertEqual(len(result[0]["people"]), 5)
        self.assertEqual(result[1]["count"], 4)
        self.assertEqual(len(result[1]["people"]), 4)
        self.assertEqual(result[2]["count"], 1)
        self.assertEqual(len(result[2]["people"]), 1)
        self.assertEqual(result[3]["count"], 1)
        self.assertEqual(len(result[3]["people"]), 1)
        self.assertEqual(result[4]["count"], 1)
        self.assertEqual(len(result[4]["people"]), 1)
        # check ordering of people in every step
        self.assertCountEqual(
            self._get_people_at_step(filter, 1),
            [
                person1_stopped_after_signup.uuid,
                person2_stopped_after_one_pageview.uuid,
                person3_stopped_after_two_pageview.uuid,
                person4_stopped_after_three_pageview.uuid,
                person5_stopped_after_many_pageview.uuid,
            ],
        )

        self.assertCountEqual(
            self._get_people_at_step(filter, 2),
            [
                person2_stopped_after_one_pageview.uuid,
                person3_stopped_after_two_pageview.uuid,
                person4_stopped_after_three_pageview.uuid,
                person5_stopped_after_many_pageview.uuid,
            ],
        )

        self.assertCountEqual(
            self._get_people_at_step(filter, 3), [person5_stopped_after_many_pageview.uuid],
        )

        self.assertCountEqual(
            self._get_people_at_step(filter, 4), [person5_stopped_after_many_pageview.uuid],
        )

        self.assertCountEqual(
            self._get_people_at_step(filter, 5), [person5_stopped_after_many_pageview.uuid],
        )

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
        funnel = ClickhouseFunnelNew(filter, self.team)

        # event
        person1_stopped_after_two_signups = _create_person(distinct_ids=["stopped_after_signup1"], team_id=self.team.pk)
        _create_event(team=self.team, event="sign up", distinct_id="stopped_after_signup1", properties={"key": "val"})
        _create_event(team=self.team, event="sign up", distinct_id="stopped_after_signup1", properties={"key": "val"})

        person2_stopped_after_signup = _create_person(distinct_ids=["stopped_after_signup2"], team_id=self.team.pk)
        _create_event(team=self.team, event="sign up", distinct_id="stopped_after_signup2", properties={"key": "val"})

        result = funnel.run()

        self.assertEqual(result[0]["name"], "sign up")
        self.assertEqual(result[0]["count"], 2)
        self.assertEqual(len(result[0]["people"]), 2)
        self.assertEqual(result[1]["count"], 1)
        self.assertEqual(len(result[1]["people"]), 1)
        # check ordering of people in first step
        self.assertCountEqual(
            self._get_people_at_step(filter, 1),
            [person1_stopped_after_two_signups.uuid, person2_stopped_after_signup.uuid],
        )

        self.assertCountEqual(
            self._get_people_at_step(filter, 2), [person1_stopped_after_two_signups.uuid],
        )

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

        filter = Filter(data=filters)
        funnel = ClickhouseFunnelNew(filter, self.team)

        # event
        person1_stopped_after_two_signups = _create_person(distinct_ids=["stopped_after_signup1"], team_id=self.team.pk)
        _create_event(team=self.team, event="user signed up", distinct_id="stopped_after_signup1")
        _create_event(team=self.team, event="user signed up", distinct_id="stopped_after_signup1")
        _create_event(team=self.team, event="sign up", distinct_id="stopped_after_signup1", properties={"key": "val"})
        _create_event(team=self.team, event="sign up", distinct_id="stopped_after_signup1", properties={"key": "val"})

        person2_stopped_after_signup = _create_person(distinct_ids=["stopped_after_signup2"], team_id=self.team.pk)
        _create_event(team=self.team, event="user signed up", distinct_id="stopped_after_signup2")
        _create_event(team=self.team, event="user signed up", distinct_id="stopped_after_signup2")
        _create_event(team=self.team, event="sign up", distinct_id="stopped_after_signup2", properties={"key": "val"})

        person3 = _create_person(distinct_ids=["person3"], team_id=self.team.pk)
        _create_event(team=self.team, event="user signed up", distinct_id="person3")
        _create_event(team=self.team, event="sign up", distinct_id="person3", properties={"key": "val"})
        _create_event(team=self.team, event="user signed up", distinct_id="person3")
        _create_event(team=self.team, event="sign up", distinct_id="person3", properties={"key": "val"})

        person4 = _create_person(distinct_ids=["person4"], team_id=self.team.pk)
        _create_event(team=self.team, event="user signed up", distinct_id="person4")
        _create_event(team=self.team, event="sign up", distinct_id="person4", properties={"key": "val"})
        _create_event(team=self.team, event="user signed up", distinct_id="person4")

        person5 = _create_person(distinct_ids=["person5"], team_id=self.team.pk)
        _create_event(team=self.team, event="sign up", distinct_id="person5", properties={"key": "val"})

        result = funnel.run()

        self.assertEqual(result[0]["name"], "user signed up")
        self.assertEqual(result[0]["count"], 4)
        self.assertEqual(result[1]["count"], 4)
        self.assertEqual(result[2]["count"], 3)
        self.assertEqual(result[3]["count"], 1)

        # check ordering of people in steps
        self.assertCountEqual(
            self._get_people_at_step(filter, 1),
            [person1_stopped_after_two_signups.uuid, person2_stopped_after_signup.uuid, person3.uuid, person4.uuid],
        )

        self.assertCountEqual(
            self._get_people_at_step(filter, 2),
            [person1_stopped_after_two_signups.uuid, person2_stopped_after_signup.uuid, person3.uuid, person4.uuid],
        )

        self.assertCountEqual(
            self._get_people_at_step(filter, 3),
            [person1_stopped_after_two_signups.uuid, person2_stopped_after_signup.uuid, person3.uuid,],
        )

        self.assertCountEqual(self._get_people_at_step(filter, 4), [person1_stopped_after_two_signups.uuid,])

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
        funnel = ClickhouseFunnelNew(filter, self.team)

        # event
        person1_stopped_after_signup = _create_person(distinct_ids=["stopped_after_signup1"], team_id=self.team.pk)
        _create_event(team=self.team, event="user signed up", distinct_id="stopped_after_signup1")

        person2_stopped_after_one_pageview = _create_person(
            distinct_ids=["stopped_after_pageview1"], team_id=self.team.pk
        )
        _create_event(team=self.team, event="user signed up", distinct_id="stopped_after_pageview1")
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="stopped_after_pageview1",
            properties={"$current_url": "aloha.com"},
        )

        person3_stopped_after_two_pageview = _create_person(
            distinct_ids=["stopped_after_pageview2"], team_id=self.team.pk
        )
        _create_event(team=self.team, event="user signed up", distinct_id="stopped_after_pageview2")
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="stopped_after_pageview2",
            properties={"$current_url": "aloha.com"},
        )
        _create_event(
            team=self.team,
            event="blaah blaa",
            distinct_id="stopped_after_pageview2",
            properties={"$current_url": "aloha.com"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="stopped_after_pageview2",
            properties={"$current_url": "aloha2.com"},
        )

        person4_stopped_after_three_pageview = _create_person(
            distinct_ids=["stopped_after_pageview3"], team_id=self.team.pk
        )
        _create_event(team=self.team, event="user signed up", distinct_id="stopped_after_pageview3")
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="stopped_after_pageview3",
            properties={"$current_url": "aloha.com"},
        )
        _create_event(team=self.team, event="blaah blaa", distinct_id="stopped_after_pageview3")
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="stopped_after_pageview3",
            properties={"$current_url": "aloha2.com"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="stopped_after_pageview3",
            properties={"$current_url": "aloha2.com"},
        )
        _create_event(team=self.team, event="blaah blaa", distinct_id="stopped_after_pageview3")

        person5_stopped_after_many_pageview = _create_person(
            distinct_ids=["stopped_after_pageview4"], team_id=self.team.pk
        )
        _create_event(team=self.team, event="user signed up", distinct_id="stopped_after_pageview4")
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="stopped_after_pageview4",
            properties={"$current_url": "aloha.com"},
        )
        _create_event(team=self.team, event="blaah blaa", distinct_id="stopped_after_pageview4")
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="stopped_after_pageview4",
            properties={"$current_url": "aloha2.com"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="stopped_after_pageview4",
            properties={"$current_url": "aloha.com"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="stopped_after_pageview4",
            properties={"$current_url": "aloha2.com"},
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
            self._get_people_at_step(filter, 1),
            [
                person1_stopped_after_signup.uuid,
                person2_stopped_after_one_pageview.uuid,
                person3_stopped_after_two_pageview.uuid,
                person4_stopped_after_three_pageview.uuid,
                person5_stopped_after_many_pageview.uuid,
            ],
        )

        self.assertCountEqual(
            self._get_people_at_step(filter, 2),
            [
                person2_stopped_after_one_pageview.uuid,
                person3_stopped_after_two_pageview.uuid,
                person4_stopped_after_three_pageview.uuid,
                person5_stopped_after_many_pageview.uuid,
            ],
        )

        self.assertCountEqual(
            self._get_people_at_step(filter, 3),
            [
                person3_stopped_after_two_pageview.uuid,
                person4_stopped_after_three_pageview.uuid,
                person5_stopped_after_many_pageview.uuid,
            ],
        )

        self.assertCountEqual(
            self._get_people_at_step(filter, 4),
            [person4_stopped_after_three_pageview.uuid, person5_stopped_after_many_pageview.uuid],
        )

        self.assertCountEqual(
            self._get_people_at_step(filter, 5), [],
        )

    def test_funnel_step_conversion_times(self):

        filters = {
            "events": [{"id": "sign up", "order": 0}, {"id": "play movie", "order": 1}, {"id": "buy", "order": 2},],
            "insight": INSIGHT_FUNNELS,
            "date_from": "2020-01-01",
            "date_to": "2020-01-08",
            "funnel_window_days": 7,
        }

        filter = Filter(data=filters)
        funnel = ClickhouseFunnelNew(filter, self.team)

        # event
        person1 = _create_person(distinct_ids=["person1"], team_id=self.team.pk)
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

        person2 = _create_person(distinct_ids=["person2"], team_id=self.team.pk)
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

        person3 = _create_person(distinct_ids=["person3"], team_id=self.team.pk)
        _create_event(
            team=self.team,
            event="sign up",
            distinct_id="person3",
            properties={"key": "val"},
            timestamp="2020-01-02T14:00:00Z",
        )
        _create_event(
            team=self.team,
            event="play movie",
            distinct_id="person3",
            properties={"key": "val"},
            timestamp="2020-01-02T16:00:00Z",
        )
        _create_event(
            team=self.team,
            event="buy",
            distinct_id="person3",
            properties={"key": "val"},
            timestamp="2020-01-02T17:00:00Z",
        )

        result = funnel.run()
        self.assertEqual(result[0]["average_conversion_time"], None)
        self.assertEqual(result[1]["average_conversion_time"], 6000)
        self.assertEqual(result[2]["average_conversion_time"], 5400)

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
        funnel = ClickhouseFunnelNew(filter, self.team)

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

        result = funnel.run()
        self.assertEqual(
            result[0],
            [
                {
                    "action_id": "sign up",
                    "name": "sign up",
                    "order": 0,
                    "people": [person1.uuid],
                    "count": 1,
                    "type": "events",
                    "average_conversion_time": None,
                    "breakdown": "Chrome",
                },
                {
                    "action_id": "play movie",
                    "name": "play movie",
                    "order": 1,
                    "people": [person1.uuid],
                    "count": 1,
                    "type": "events",
                    "average_conversion_time": 3600.0,
                    "breakdown": "Chrome",
                },
                {
                    "action_id": "buy",
                    "name": "buy",
                    "order": 2,
                    "people": [person1.uuid],
                    "count": 1,
                    "type": "events",
                    "average_conversion_time": 7200.0,
                    "breakdown": "Chrome",
                },
            ],
        )
        self.assertEqual(
            result[1],
            [
                {
                    "action_id": "sign up",
                    "name": "sign up",
                    "order": 0,
                    "people": [person2.uuid],
                    "count": 1,
                    "type": "events",
                    "average_conversion_time": None,
                    "breakdown": "Safari",
                },
                {
                    "action_id": "play movie",
                    "name": "play movie",
                    "order": 1,
                    "people": [person2.uuid],
                    "count": 1,
                    "type": "events",
                    "average_conversion_time": 7200.0,
                    "breakdown": "Safari",
                },
                {
                    "action_id": "buy",
                    "name": "buy",
                    "order": 2,
                    "people": [],
                    "count": 0,
                    "type": "events",
                    "average_conversion_time": None,
                    "breakdown": "Safari",
                },
            ],
        )

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
        funnel = ClickhouseFunnelNew(filter, self.team)

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
                    "people": [person1.uuid],
                    "count": 1,
                    "type": "events",
                    "average_conversion_time": None,
                    "breakdown": "Chrome",
                },
                {
                    "action_id": "play movie",
                    "name": "play movie",
                    "order": 1,
                    "people": [person1.uuid],
                    "count": 1,
                    "type": "events",
                    "average_conversion_time": 3600.0,
                    "breakdown": "Chrome",
                },
                {
                    "action_id": "buy",
                    "name": "buy",
                    "order": 2,
                    "people": [person1.uuid],
                    "count": 1,
                    "type": "events",
                    "average_conversion_time": 7200.0,
                    "breakdown": "Chrome",
                },
            ],
        )
        self.assertEqual(
            result[1],
            [
                {
                    "action_id": "sign up",
                    "name": "sign up",
                    "order": 0,
                    "people": [person2.uuid],
                    "count": 1,
                    "type": "events",
                    "average_conversion_time": None,
                    "breakdown": "Safari",
                },
                {
                    "action_id": "play movie",
                    "name": "play movie",
                    "order": 1,
                    "people": [person2.uuid],
                    "count": 1,
                    "type": "events",
                    "average_conversion_time": 7200.0,
                    "breakdown": "Safari",
                },
                {
                    "action_id": "buy",
                    "name": "buy",
                    "order": 2,
                    "people": [],
                    "count": 0,
                    "type": "events",
                    "average_conversion_time": None,
                    "breakdown": "Safari",
                },
            ],
        )

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
        funnel = ClickhouseFunnelNew(filter, self.team)

        for num in range(10):
            for i in range(num):
                _create_person(distinct_ids=[f"person_{num}_{i}"], team_id=self.team.pk)
                _create_event(
                    team=self.team,
                    event="sign up",
                    distinct_id=f"person_{num}_{i}",
                    properties={"key": "val", "some_breakdown_val": f"{num}"},
                    timestamp="2020-01-01T12:00:00Z",
                )
                _create_event(
                    team=self.team,
                    event="play movie",
                    distinct_id=f"person_{num}_{i}",
                    properties={"key": "val", "some_breakdown_val": f"{num}"},
                    timestamp="2020-01-01T13:00:00Z",
                )
                _create_event(
                    team=self.team,
                    event="buy",
                    distinct_id=f"person_{num}_{i}",
                    properties={"key": "val", "some_breakdown_val": f"{num}"},
                    timestamp="2020-01-01T15:00:00Z",
                )

        result = funnel.run()

        # assert that we give 5 at a time at most and that those values are the most popular ones
        breakdown_vals = sorted([res[0]["breakdown"] for res in result])
        self.assertEqual(["5", "6", "7", "8", "9"], breakdown_vals)
