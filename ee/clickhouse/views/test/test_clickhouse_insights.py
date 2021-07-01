import json
from uuid import uuid4

from ee.clickhouse.models.event import create_event
from ee.clickhouse.util import ClickhouseTestMixin
from posthog.api.test.test_insight import insight_test_factory
from posthog.constants import INSIGHT_FUNNELS
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
