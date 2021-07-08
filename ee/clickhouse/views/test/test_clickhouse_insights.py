from uuid import uuid4

from ee.clickhouse.models.event import create_event
from ee.clickhouse.util import ClickhouseTestMixin
from posthog.api.test.test_insight import insight_test_factory
from posthog.models.person import Person
from posthog.test.base import APIBaseTest


def _create_person(**kwargs):
    person = Person.objects.create(**kwargs)
    return Person(id=person.uuid)


def _create_event(**kwargs):
    kwargs.update({"event_uuid": uuid4()})
    create_event(**kwargs)


class ClickhouseTestInsights(
    ClickhouseTestMixin, insight_test_factory(_create_event, _create_person)  # type: ignore
):
    pass


class ClickhouseTestFunnelTypes(ClickhouseTestMixin, APIBaseTest):
    def test_funnel_unordered_basic_post(self):
        _create_person(distinct_ids=["1"], team=self.team)
        _create_event(team=self.team, event="step one", distinct_id="1")
        _create_event(team=self.team, event="step two", distinct_id="1")

        _create_person(distinct_ids=["2"], team=self.team)
        _create_event(team=self.team, event="step two", distinct_id="2")
        _create_event(team=self.team, event="step one", distinct_id="2")

        response = self.client.post(
            "/api/insight/funnel/",
            {
                "events": [
                    {"id": "step one", "type": "events", "order": 0},
                    {"id": "step two", "type": "events", "order": 1},
                ],
                "funnel_window_days": 14,
                "funnel_order_type": "unordered",
            },
        ).json()

        self.assertEqual(len(response["result"]), 2)
        self.assertEqual(response["result"][0]["name"], "step one")
        self.assertEqual(response["result"][1]["name"], "step two")
        self.assertEqual(response["result"][0]["count"], 2)
        self.assertEqual(response["result"][1]["count"], 2)

    def test_funnel_trends_basic_post(self):
        _create_person(distinct_ids=["user_one"], team=self.team)
        _create_person(distinct_ids=["user_two"], team=self.team)
        # user_one, funnel steps: one, two three
        _create_event(event="step one", distinct_id="user_one", team=self.team, timestamp="2021-05-01 01:00:00")
        _create_event(event="step two", distinct_id="user_one", team=self.team, timestamp="2021-05-03 00:00:00")
        _create_event(event="step three", distinct_id="user_one", team=self.team, timestamp="2021-05-05 00:00:00")

        # user_two, funnel steps: one, two
        _create_event(event="step one", distinct_id="user_two", team=self.team, timestamp="2021-05-02 00:00:00")
        _create_event(event="step two", distinct_id="user_two", team=self.team, timestamp="2021-05-04 00:00:00")
        _create_event(event="step three", distinct_id="user_two", team=self.team, timestamp="2021-05-05 00:00:00")

        response = self.client.post(
            "/api/insight/funnel/",
            {
                "events": [
                    {"id": "step one", "type": "events", "order": 0},
                    {"id": "step two", "type": "events", "order": 1},
                    {"id": "step three", "type": "events", "order": 2},
                ],
                "funnel_window_days": 7,
                "date_from": "2021-05-01 00:00:00",
                "date_to": "2021-05-07 23:59:59",
                "funnel_viz_type": "trends",
            },
        ).json()

        self.assertEqual(len(response["result"]), 1)
        self.assertEqual(response["result"][0]["count"], 7)
        self.assertEqual(response["result"][0]["data"], [100, 100, 0, 0, 0, 0, 0])

    def test_funnel_time_to_convert_auto_bins(self):
        _create_person(distinct_ids=["user a"], team=self.team)
        _create_person(distinct_ids=["user b"], team=self.team)
        _create_person(distinct_ids=["user c"], team=self.team)

        _create_event(event="step one", distinct_id="user a", team=self.team, timestamp="2021-06-08 18:00:00")
        _create_event(event="step two", distinct_id="user a", team=self.team, timestamp="2021-06-08 19:00:00")
        # Converted from 0 to 1 in 3600 s
        _create_event(event="step three", distinct_id="user a", team=self.team, timestamp="2021-06-08 21:00:00")

        _create_event(event="step one", distinct_id="user b", team=self.team, timestamp="2021-06-09 13:00:00")
        _create_event(event="step two", distinct_id="user b", team=self.team, timestamp="2021-06-09 13:37:00")
        # Converted from 0 to 1 in 2200 s

        _create_event(event="step one", distinct_id="user c", team=self.team, timestamp="2021-06-11 07:00:00")
        _create_event(event="step two", distinct_id="user c", team=self.team, timestamp="2021-06-12 06:00:00")
        # Converted from 0 to 1 in 82_800 s

        response = self.client.post(
            "/api/insight/funnel/",
            {
                "insight": "funnels",
                "funnel_viz_type": "time_to_convert",
                "interval": "day",
                "date_from": "2021-06-07 00:00:00",
                "date_to": "2021-06-13 23:59:59",
                "funnel_to_step": 1,
                "funnel_window_days": 7,
                "events": [
                    {"id": "step one", "order": 0},
                    {"id": "step two", "order": 1},
                    {"id": "step three", "order": 2},
                ],
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(), {"result": [[2220.0, 2], [29080.0, 0], [55940.0, 0], [82800.0, 1],]},
        )
