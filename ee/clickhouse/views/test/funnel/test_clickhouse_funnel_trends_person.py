import json
from uuid import uuid4

from rest_framework import status

from ee.clickhouse.models.event import create_event
from ee.clickhouse.util import ClickhouseTestMixin
from posthog.constants import INSIGHT_FUNNELS, FunnelOrderType, FunnelVizType
from posthog.models.person import Person
from posthog.test.base import APIBaseTest


def _create_person(**kwargs):
    person = Person.objects.create(**kwargs)
    return Person(id=person.uuid, uuid=person.uuid)


def _create_event(**kwargs):
    kwargs.update({"event_uuid": uuid4()})
    create_event(**kwargs)


class TestFunnelTrendsPerson(ClickhouseTestMixin, APIBaseTest):
    def test_basic_format(self):
        user_a = _create_person(distinct_ids=["user a"], team=self.team)

        _create_event(event="step one", distinct_id="user a", team=self.team, timestamp="2021-06-07 19:00:00")

        common_request_data = {
            "insight": INSIGHT_FUNNELS,
            "funnel_viz_type": FunnelVizType.TRENDS,
            "interval": "day",
            "date_from": "2021-06-07",
            "date_to": "2021-06-13 23:59:59",
            "funnel_window_days": 7,
            "events": json.dumps(
                [{"id": "step one", "order": 0}, {"id": "step two", "order": 1}, {"id": "step three", "order": 2},]
            ),
            "properties": json.dumps([]),
            "funnel_window_days": 7,
            "new_entity": json.dumps([]),
        }

        # 1 user who dropped off starting 2021-06-07
        response_1 = self.client.get(
            "/api/person/funnel/",
            data={**common_request_data, "entrance_period_start": "2021-06-07", "drop_off": True,},
        )
        response_1_data = response_1.json()

        self.assertEqual(response_1.status_code, status.HTTP_200_OK)
        self.assertEqual([person["id"] for person in response_1_data["results"][0]["people"]], [str(user_a.uuid)])

        # No users converted 2021-06-07
        response_2 = self.client.get(
            "/api/person/funnel/",
            data={**common_request_data, "entrance_period_start": "2021-06-07 00:00", "drop_off": False,},
        )
        response_2_data = response_2.json()

        self.assertEqual(response_2.status_code, status.HTTP_200_OK)
        self.assertEqual([person["id"] for person in response_2_data["results"][0]["people"]], [])

        # No users dropped off starting 2021-06-08
        response_3 = self.client.get(
            "/api/person/funnel/",
            data={**common_request_data, "entrance_period_start": "2021-06-08", "drop_off": True,},
        )
        response_3_data = response_3.json()

        self.assertEqual(response_3.status_code, status.HTTP_200_OK)
        self.assertEqual([person["id"] for person in response_3_data["results"][0]["people"]], [])

    def test_strict_order(self):
        user_a = _create_person(distinct_ids=["user a"], team=self.team)
        user_b = _create_person(distinct_ids=["user b"], team=self.team)

        _create_event(event="step one", distinct_id="user a", team=self.team, timestamp="2021-06-07 19:00:00")
        _create_event(event="step two", distinct_id="user a", team=self.team, timestamp="2021-06-07 19:00:01")
        _create_event(event="step one", distinct_id="user a", team=self.team, timestamp="2021-06-07 19:00:02")
        _create_event(event="step three", distinct_id="user a", team=self.team, timestamp="2021-06-07 19:00:03")

        _create_event(event="step one", distinct_id="user b", team=self.team, timestamp="2021-06-07 19:00:00")
        _create_event(event="step two", distinct_id="user b", team=self.team, timestamp="2021-06-07 19:00:01")
        _create_event(event="step three", distinct_id="user b", team=self.team, timestamp="2021-06-07 19:00:03")

        common_request_data = {
            "insight": INSIGHT_FUNNELS,
            "funnel_viz_type": FunnelVizType.TRENDS,
            "interval": "day",
            "date_from": "2021-06-07",
            "date_to": "2021-06-13 23:59:59",
            "funnel_window_days": 7,
            "funnel_order_type": FunnelOrderType.STRICT,
            "events": json.dumps(
                [{"id": "step one", "order": 0}, {"id": "step two", "order": 1}, {"id": "step three", "order": 2},]
            ),
            "properties": json.dumps([]),
            "funnel_window_days": 7,
            "new_entity": json.dumps([]),
        }

        # 1 user who dropped off
        response_1 = self.client.get(
            "/api/person/funnel/",
            data={**common_request_data, "entrance_period_start": "2021-06-07", "drop_off": True,},
        )
        response_1_data = response_1.json()

        self.assertEqual(response_1.status_code, status.HTTP_200_OK)
        self.assertEqual([person["id"] for person in response_1_data["results"][0]["people"]], [str(user_a.uuid)])

        # 1 user who successfully converted
        response_1 = self.client.get(
            "/api/person/funnel/",
            data={**common_request_data, "entrance_period_start": "2021-06-07", "drop_off": False,},
        )
        response_1_data = response_1.json()

        self.assertEqual(response_1.status_code, status.HTTP_200_OK)
        self.assertEqual([person["id"] for person in response_1_data["results"][0]["people"]], [str(user_b.uuid)])

    def test_unordered(self):
        user_a = _create_person(distinct_ids=["user a"], team=self.team)
        user_b = _create_person(distinct_ids=["user b"], team=self.team)

        _create_event(event="step one", distinct_id="user a", team=self.team, timestamp="2021-06-07 19:00:00")
        _create_event(event="step three", distinct_id="user a", team=self.team, timestamp="2021-06-07 19:00:03")

        _create_event(event="step one", distinct_id="user b", team=self.team, timestamp="2021-06-07 19:00:00")
        _create_event(event="step three", distinct_id="user b", team=self.team, timestamp="2021-06-07 19:00:01")
        _create_event(event="step two", distinct_id="user b", team=self.team, timestamp="2021-06-07 19:00:02")

        common_request_data = {
            "insight": INSIGHT_FUNNELS,
            "funnel_viz_type": FunnelVizType.TRENDS,
            "interval": "day",
            "date_from": "2021-06-07",
            "date_to": "2021-06-13 23:59:59",
            "funnel_window_days": 7,
            "funnel_order_type": FunnelOrderType.UNORDERED,
            "events": json.dumps(
                [{"id": "step one", "order": 0}, {"id": "step two", "order": 1}, {"id": "step three", "order": 2},]
            ),
            "properties": json.dumps([]),
            "funnel_window_days": 7,
            "new_entity": json.dumps([]),
        }

        # 1 user who dropped off
        response_1 = self.client.get(
            "/api/person/funnel/",
            data={**common_request_data, "entrance_period_start": "2021-06-07", "drop_off": True,},
        )
        response_1_data = response_1.json()

        self.assertEqual(response_1.status_code, status.HTTP_200_OK)
        self.assertEqual([person["id"] for person in response_1_data["results"][0]["people"]], [str(user_a.uuid)])

        # 1 user who successfully converted
        response_1 = self.client.get(
            "/api/person/funnel/",
            data={**common_request_data, "entrance_period_start": "2021-06-07", "drop_off": False,},
        )
        response_1_data = response_1.json()

        self.assertEqual(response_1.status_code, status.HTTP_200_OK)
        self.assertEqual([person["id"] for person in response_1_data["results"][0]["people"]], [str(user_b.uuid)])
