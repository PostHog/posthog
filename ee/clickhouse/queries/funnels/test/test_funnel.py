from uuid import uuid4

from ee.clickhouse.models.event import create_event
from ee.clickhouse.queries.funnels.funnel import ClickhouseFunnel
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

        with self.assertNumQueries(1):
            result = funnel.run()

        self.assertEqual(result[0]["name"], "user signed up")
        self.assertEqual(result[0]["count"], 2)

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
            "funnel_window_days": 14,
        }

        filter = Filter(data=filters)
        funnel = ClickhouseFunnel(filter, self.team)

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

        with self.assertNumQueries(1):
            result = funnel.run()

        self.assertEqual(result[0]["name"], "user signed up")
        self.assertEqual(result[1]["name"], "$pageview")
        self.assertEqual(result[4]["name"], "$pageview")
        self.assertEqual(result[0]["count"], 5)

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
            "funnel_window_days": 14,
        }

        filter = Filter(data=filters)
        funnel = ClickhouseFunnel(filter, self.team)

        # event
        person1_stopped_after_two_signups = _create_person(distinct_ids=["stopped_after_signup1"], team_id=self.team.pk)
        _create_event(team=self.team, event="sign up", distinct_id="stopped_after_signup1", properties={"key": "val"})
        _create_event(team=self.team, event="sign up", distinct_id="stopped_after_signup1", properties={"key": "val"})

        person2_stopped_after_signup = _create_person(distinct_ids=["stopped_after_signup2"], team_id=self.team.pk)
        _create_event(team=self.team, event="sign up", distinct_id="stopped_after_signup2", properties={"key": "val"})

        with self.assertNumQueries(1):
            result = funnel.run()

        self.assertEqual(result[0]["name"], "sign up")
        self.assertEqual(result[0]["count"], 2)

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
        funnel = ClickhouseFunnel(filter, self.team)

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

        with self.assertNumQueries(1):
            result = funnel.run()

        self.assertEqual(result[0]["name"], "user signed up")

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
                {
                    "id": "$pageview",
                    "order": 4,
                },  # TODO(nk): does this supercede the above event? i.e. order 3 is subset of order 4? doesn't make sense to allow this in a funnel
            ],
            "insight": INSIGHT_FUNNELS,
            "funnel_window_days": 14,
        }

        filter = Filter(data=filters)
        funnel = ClickhouseFunnel(filter, self.team)

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

        with self.assertNumQueries(1):
            result = funnel.run()

        self.assertEqual(result[0]["name"], "user signed up")
        self.assertEqual(result[1]["name"], "$pageview")
        self.assertEqual(result[4]["name"], "$pageview")
        self.assertEqual(result[0]["count"], 5)

    def test_funnel_step_conversion_times(self):

        filters = {
            "events": [{"id": "sign up", "order": 0}, {"id": "play movie", "order": 1}, {"id": "buy", "order": 2},],
            "insight": INSIGHT_FUNNELS,
            "date_from": "2020-01-01",
            "date_to": "2020-01-08",
            "funnel_window_days": 7,
        }

        filter = Filter(data=filters)
        funnel = ClickhouseFunnel(filter, self.team)

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
