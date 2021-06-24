from uuid import uuid4

from ee.clickhouse.models.event import create_event
from ee.clickhouse.queries.funnels.funnel import ClickhouseFunnelNew
from ee.clickhouse.util import ClickhouseTestMixin
from posthog.constants import INSIGHT_FUNNELS
from posthog.models.filters import Filter
from posthog.models.person import Person
from posthog.queries.test.test_funnel import funnel_test_factory

FORMAT_TIME = "%Y-%m-%d 00:00:00"
MAX_STEP_COLUMN = 0
COUNT_COLUMN = 1
PERSON_ID_COLUMN = 2


def _create_person(**kwargs):
    person = Person.objects.create(**kwargs)
    return Person(id=person.uuid, uuid=person.uuid)


def _create_event(**kwargs):
    kwargs.update({"event_uuid": uuid4()})
    create_event(**kwargs)


class TestFunnel(ClickhouseTestMixin, funnel_test_factory(ClickhouseFunnelNew, _create_event, _create_person)):  # type: ignore
    def test_basic_funnel_with_repeat_steps(self):
        filters = {
            "events": [
                {"id": "user signed up", "type": "events", "order": 0},
                {"id": "user signed up", "type": "events", "order": 1},
            ],
            "insight": INSIGHT_FUNNELS,
        }

        # if properties is not None:
        #     filters.update({"properties": properties})

        filter = Filter(data=filters)
        funnel = ClickhouseFunnelNew(filter, self.team)

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
        # check ordering of people in first step
        self.assertCountEqual(
            result[0]["people"], [person1_stopped_after_two_signups.uuid, person2_stopped_after_signup.uuid],
        )

        self.assertCountEqual(
            result[1]["people"], [person1_stopped_after_two_signups.uuid],
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

        # if properties is not None:
        #     filters.update({"properties": properties})

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
        _create_event(team=self.team, event="blaah blaa", distinct_id="stopped_after_pageview4")
        _create_event(team=self.team, event="$pageview", distinct_id="stopped_after_pageview4")
        _create_event(team=self.team, event="$pageview", distinct_id="stopped_after_pageview4")
        _create_event(team=self.team, event="$pageview", distinct_id="stopped_after_pageview4")

        with self.assertNumQueries(1):
            result = funnel.run()

        self.assertEqual(result[0]["name"], "user signed up")
        self.assertEqual(result[1]["name"], "$pageview")
        self.assertEqual(result[4]["name"], "$pageview")
        self.assertEqual(result[0]["count"], 5)
        # check ordering of people in every step
        self.assertCountEqual(
            result[0]["people"],
            [
                person1_stopped_after_signup.uuid,
                person2_stopped_after_one_pageview.uuid,
                person3_stopped_after_two_pageview.uuid,
                person4_stopped_after_three_pageview.uuid,
                person5_stopped_after_many_pageview.uuid,
            ],
        )

        self.assertCountEqual(
            result[1]["people"],
            [
                person2_stopped_after_one_pageview.uuid,
                person3_stopped_after_two_pageview.uuid,
                person4_stopped_after_three_pageview.uuid,
                person5_stopped_after_many_pageview.uuid,
            ],
        )

        self.assertCountEqual(
            result[2]["people"],
            [
                person3_stopped_after_two_pageview.uuid,
                person4_stopped_after_three_pageview.uuid,
                person5_stopped_after_many_pageview.uuid,
            ],
        )

        self.assertCountEqual(
            result[3]["people"], [person4_stopped_after_three_pageview.uuid, person5_stopped_after_many_pageview.uuid],
        )

        self.assertCountEqual(
            result[4]["people"], [person5_stopped_after_many_pageview.uuid],
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
        }

        # if properties is not None:
        #     filters.update({"properties": properties})

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

        with self.assertNumQueries(1):
            result = funnel.run()

        self.assertEqual(result[0]["name"], "user signed up")
        self.assertEqual(result[1]["name"], "$pageview")
        self.assertEqual(result[4]["name"], "$pageview")
        self.assertEqual(result[0]["count"], 5)
        # check ordering of people in every step
        self.assertCountEqual(
            result[0]["people"],
            [
                person1_stopped_after_signup.uuid,
                person2_stopped_after_one_pageview.uuid,
                person3_stopped_after_two_pageview.uuid,
                person4_stopped_after_three_pageview.uuid,
                person5_stopped_after_many_pageview.uuid,
            ],
        )

        self.assertCountEqual(
            result[1]["people"],
            [
                person2_stopped_after_one_pageview.uuid,
                person3_stopped_after_two_pageview.uuid,
                person4_stopped_after_three_pageview.uuid,
                person5_stopped_after_many_pageview.uuid,
            ],
        )

        self.assertCountEqual(
            result[2]["people"], [person5_stopped_after_many_pageview.uuid],
        )

        self.assertCountEqual(
            result[3]["people"], [person5_stopped_after_many_pageview.uuid],
        )

        self.assertCountEqual(
            result[4]["people"], [person5_stopped_after_many_pageview.uuid],
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
        }

        # if properties is not None:
        #     filters.update({"properties": properties})

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

        with self.assertNumQueries(1):
            result = funnel.run()

        self.assertEqual(result[0]["name"], "user signed up")
        self.assertEqual(result[1]["name"], "$pageview")
        self.assertEqual(result[4]["name"], "$pageview")
        self.assertEqual(result[0]["count"], 5)
        # check ordering of people in every step
        self.assertCountEqual(
            result[0]["people"],
            [
                person1_stopped_after_signup.uuid,
                person2_stopped_after_one_pageview.uuid,
                person3_stopped_after_two_pageview.uuid,
                person4_stopped_after_three_pageview.uuid,
                person5_stopped_after_many_pageview.uuid,
            ],
        )

        self.assertCountEqual(
            result[1]["people"],
            [
                person2_stopped_after_one_pageview.uuid,
                person3_stopped_after_two_pageview.uuid,
                person4_stopped_after_three_pageview.uuid,
                person5_stopped_after_many_pageview.uuid,
            ],
        )

        self.assertCountEqual(
            result[2]["people"], [person5_stopped_after_many_pageview.uuid],
        )

        self.assertCountEqual(
            result[3]["people"], [person5_stopped_after_many_pageview.uuid],
        )

        self.assertCountEqual(
            result[4]["people"], [person5_stopped_after_many_pageview.uuid],
        )
