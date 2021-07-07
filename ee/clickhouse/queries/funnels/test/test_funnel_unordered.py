from uuid import uuid4

from ee.clickhouse.models.event import create_event
from ee.clickhouse.queries.funnels.funnel_unordered import ClickhouseFunnelUnordered
from ee.clickhouse.queries.funnels.funnel_unordered_persons import ClickhouseFunnelUnorderedPersons
from ee.clickhouse.util import ClickhouseTestMixin
from posthog.constants import INSIGHT_FUNNELS
from posthog.models.filters import Filter
from posthog.models.person import Person
from posthog.test.base import APIBaseTest

FORMAT_TIME = "%Y-%m-%d 00:00:00"


def _create_person(**kwargs):
    person = Person.objects.create(**kwargs)
    return Person(id=person.uuid, uuid=person.uuid)


def _create_event(**kwargs):
    kwargs.update({"event_uuid": uuid4()})
    create_event(**kwargs)


class TestFunnelUnorderedSteps(ClickhouseTestMixin, APIBaseTest):
    def _get_people_at_step(self, filter, funnel_step):
        person_filter = filter.with_data({"funnel_step": funnel_step})
        result = ClickhouseFunnelUnorderedPersons(person_filter, self.team)._exec_query()
        return [row[0] for row in result]

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
        _create_event(team=self.team, event="user signed up", distinct_id="stopped_after_pageview1")

        person3_stopped_after_insight_view = _create_person(
            distinct_ids=["stopped_after_insightview"], team_id=self.team.pk
        )
        _create_event(team=self.team, event="user signed up", distinct_id="stopped_after_insightview")
        _create_event(team=self.team, event="$pageview", distinct_id="stopped_after_insightview")
        _create_event(team=self.team, event="blaah blaa", distinct_id="stopped_after_insightview")
        _create_event(team=self.team, event="insight viewed", distinct_id="stopped_after_insightview")

        person4_stopped_after_insight_view_reverse_order = _create_person(
            distinct_ids=["stopped_after_insightview2"], team_id=self.team.pk
        )
        _create_event(team=self.team, event="insight viewed", distinct_id="stopped_after_insightview2")
        _create_event(team=self.team, event="$pageview", distinct_id="stopped_after_insightview2")
        _create_event(team=self.team, event="user signed up", distinct_id="stopped_after_insightview2")

        person5_stopped_after_insight_view_random = _create_person(
            distinct_ids=["stopped_after_insightview3"], team_id=self.team.pk
        )
        _create_event(team=self.team, event="$pageview", distinct_id="stopped_after_insightview3")
        _create_event(team=self.team, event="user signed up", distinct_id="stopped_after_insightview3")
        _create_event(team=self.team, event="blaah blaa", distinct_id="stopped_after_insightview3")
        _create_event(team=self.team, event="insight viewed", distinct_id="stopped_after_insightview3")

        person6_did_only_insight_view = _create_person(
            distinct_ids=["stopped_after_insightview4"], team_id=self.team.pk
        )
        _create_event(team=self.team, event="blaah blaa", distinct_id="stopped_after_insightview4")
        _create_event(team=self.team, event="insight viewed", distinct_id="stopped_after_insightview4")

        person7_did_only_pageview = _create_person(distinct_ids=["stopped_after_insightview5"], team_id=self.team.pk)
        _create_event(team=self.team, event="$pageview", distinct_id="stopped_after_insightview5")
        _create_event(team=self.team, event="blaah blaa", distinct_id="stopped_after_insightview5")

        person8_didnot_signup = _create_person(distinct_ids=["stopped_after_insightview6"], team_id=self.team.pk)
        _create_event(team=self.team, event="insight viewed", distinct_id="stopped_after_insightview6")
        _create_event(team=self.team, event="$pageview", distinct_id="stopped_after_insightview6")

        result = funnel.run()

        self.assertEqual(result[0]["name"], "user signed up")
        self.assertEqual(result[0]["count"], 8)
        self.assertEqual(result[1]["name"], "$pageview")
        self.assertEqual(result[1]["count"], 5)
        self.assertEqual(result[2]["name"], "insight viewed")
        self.assertEqual(result[2]["count"], 3)

        self.assertCountEqual(
            self._get_people_at_step(filter, 1),
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
            self._get_people_at_step(filter, 2),
            [
                person2_stopped_after_one_pageview.uuid,
                person3_stopped_after_insight_view.uuid,
                person4_stopped_after_insight_view_reverse_order.uuid,
                person5_stopped_after_insight_view_random.uuid,
                person8_didnot_signup.uuid,
            ],
        )

        self.assertCountEqual(
            self._get_people_at_step(filter, -2),
            [person1_stopped_after_signup.uuid, person6_did_only_insight_view.uuid, person7_did_only_pageview.uuid,],
        )

        self.assertCountEqual(
            self._get_people_at_step(filter, 3),
            [
                person3_stopped_after_insight_view.uuid,
                person4_stopped_after_insight_view_reverse_order.uuid,
                person5_stopped_after_insight_view_random.uuid,
            ],
        )

        self.assertCountEqual(
            self._get_people_at_step(filter, -3),
            [person2_stopped_after_one_pageview.uuid, person8_didnot_signup.uuid,],
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

        funnel = ClickhouseFunnelUnordered(filter, self.team)

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
        _create_event(team=self.team, event="user signed up", distinct_id="stopped_after_insightview")
        _create_event(team=self.team, event="$pageview", distinct_id="stopped_after_insightview")
        _create_event(team=self.team, event="blaah blaa", distinct_id="stopped_after_insightview")
        _create_event(team=self.team, event="insight viewed", distinct_id="stopped_after_insightview")

        person4_stopped_after_insight_view_reverse_order = _create_person(
            distinct_ids=["stopped_after_insightview2"], team_id=self.team.pk
        )
        _create_event(team=self.team, event="insight viewed", distinct_id="stopped_after_insightview2")
        _create_event(team=self.team, event="crying", distinct_id="stopped_after_insightview2")
        _create_event(team=self.team, event="user signed up", distinct_id="stopped_after_insightview2")

        person5_stopped_after_insight_view_random = _create_person(
            distinct_ids=["stopped_after_insightview3"], team_id=self.team.pk
        )
        _create_event(team=self.team, event="$pageview", distinct_id="stopped_after_insightview3")
        _create_event(team=self.team, event="user signed up", distinct_id="stopped_after_insightview3")
        _create_event(team=self.team, event="crying", distinct_id="stopped_after_insightview3")
        _create_event(team=self.team, event="insight viewed", distinct_id="stopped_after_insightview3")

        person6_did_only_insight_view = _create_person(
            distinct_ids=["stopped_after_insightview4"], team_id=self.team.pk
        )
        _create_event(team=self.team, event="blaah blaa", distinct_id="stopped_after_insightview4")
        _create_event(team=self.team, event="insight viewed", distinct_id="stopped_after_insightview4")

        person7_did_only_pageview = _create_person(distinct_ids=["stopped_after_insightview5"], team_id=self.team.pk)
        _create_event(team=self.team, event="$pageview", distinct_id="stopped_after_insightview5")
        _create_event(team=self.team, event="blaah blaa", distinct_id="stopped_after_insightview5")

        person8_didnot_signup = _create_person(distinct_ids=["stopped_after_insightview6"], team_id=self.team.pk)
        _create_event(team=self.team, event="insight viewed", distinct_id="stopped_after_insightview6")
        _create_event(team=self.team, event="$pageview", distinct_id="stopped_after_insightview6")

        result = funnel.run()

        self.assertEqual(result[0]["name"], "user signed up")
        self.assertEqual(result[0]["count"], 8)
        self.assertEqual(result[1]["name"], "$pageview")
        self.assertEqual(result[1]["count"], 5)
        self.assertEqual(result[2]["name"], "insight viewed")
        self.assertEqual(result[2]["count"], 3)
        self.assertEqual(result[3]["name"], "crying")
        self.assertEqual(result[3]["count"], 1)

        self.assertCountEqual(
            self._get_people_at_step(filter, 1),
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
            self._get_people_at_step(filter, 2),
            [
                person2_stopped_after_one_pageview.uuid,
                person3_stopped_after_insight_view.uuid,
                person4_stopped_after_insight_view_reverse_order.uuid,
                person5_stopped_after_insight_view_random.uuid,
                person8_didnot_signup.uuid,
            ],
        )

        self.assertCountEqual(
            self._get_people_at_step(filter, 3),
            [
                person3_stopped_after_insight_view.uuid,
                person4_stopped_after_insight_view_reverse_order.uuid,
                person5_stopped_after_insight_view_random.uuid,
            ],
        )

        self.assertCountEqual(
            self._get_people_at_step(filter, 4), [person5_stopped_after_insight_view_random.uuid,],
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
            team=self.team, event="user signed up", distinct_id="stopped_after_signup1", timestamp="2021-05-02 00:00:00"
        )

        person2_stopped_after_one_pageview = _create_person(
            distinct_ids=["stopped_after_pageview1"], team_id=self.team.pk
        )
        _create_event(
            team=self.team, event="$pageview", distinct_id="stopped_after_pageview1", timestamp="2021-05-02 00:00:00"
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
            team=self.team, event="$pageview", distinct_id="stopped_after_insightview", timestamp="2021-05-02 04:00:00"
        )

        _create_event(
            team=self.team, event="$pageview", distinct_id="stopped_after_insightview", timestamp="2021-05-03 00:00:00"
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

        self.assertEqual(result[0]["name"], "user signed up")
        self.assertEqual(result[1]["name"], "$pageview")
        self.assertEqual(result[2]["name"], "insight viewed")
        self.assertEqual(result[0]["count"], 3)

        self.assertEqual(result[1]["average_conversion_time"], 6300)
        # 1 hour for Person 2, (2+3)/2 hours for Person 3, total = 3.5 hours, average = 3.5/2 = 1.75 hours

        self.assertEqual(result[2]["average_conversion_time"], 9000)
        # (2+3)/2 hours for Person 3 = 2.5 hours

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

    def test_single_event_unordered_funnel(self):
        filter = Filter(
            data={
                "insight": INSIGHT_FUNNELS,
                "events": [{"id": "user signed up", "order": 0},],
                "date_from": "2021-05-01 00:00:00",
                "date_to": "2021-05-07 23:59:59",
            }
        )

        funnel = ClickhouseFunnelUnordered(filter, self.team)

        person1_stopped_after_signup = _create_person(distinct_ids=["stopped_after_signup1"], team_id=self.team.pk)
        _create_event(
            team=self.team, event="user signed up", distinct_id="stopped_after_signup1", timestamp="2021-05-02 00:00:00"
        )

        person2_stopped_after_one_pageview = _create_person(
            distinct_ids=["stopped_after_pageview1"], team_id=self.team.pk
        )
        _create_event(
            team=self.team, event="$pageview", distinct_id="stopped_after_pageview1", timestamp="2021-05-02 00:00:00"
        )
        _create_event(
            team=self.team,
            event="user signed up",
            distinct_id="stopped_after_pageview1",
            timestamp="2021-05-02 01:00:00",
        )

        result = funnel.run()

        self.assertEqual(result[0]["name"], "user signed up")
        self.assertEqual(result[0]["count"], 2)
