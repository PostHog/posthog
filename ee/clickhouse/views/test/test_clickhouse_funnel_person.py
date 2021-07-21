import json
from unittest.mock import patch
from uuid import uuid4

from django.core.cache import cache
from rest_framework import status

from ee.clickhouse.models.event import create_event
from ee.clickhouse.util import ClickhouseTestMixin
from posthog.constants import INSIGHT_FUNNELS
from posthog.models.person import Person
from posthog.test.base import APIBaseTest


def _create_person(**kwargs):
    person = Person.objects.create(**kwargs)
    return person


def _create_event(**kwargs):
    kwargs.update({"event_uuid": uuid4()})
    create_event(**kwargs)


class TestFunnelPerson(ClickhouseTestMixin, APIBaseTest):
    def _create_sample_data(self, num, delete=False):
        for i in range(num):
            person = _create_person(distinct_ids=[f"user_{i}"], team=self.team)
            _create_event(event="step one", distinct_id=f"user_{i}", team=self.team, timestamp="2021-05-01 00:00:00")
            _create_event(event="step two", distinct_id=f"user_{i}", team=self.team, timestamp="2021-05-03 00:00:00")
            _create_event(event="step three", distinct_id=f"user_{i}", team=self.team, timestamp="2021-05-05 00:00:00")
            if delete:
                person.delete()

    def test_basic_format(self):
        self._create_sample_data(5)
        request_data = {
            "insight": INSIGHT_FUNNELS,
            "interval": "day",
            "actions": json.dumps([]),
            "events": json.dumps(
                [{"id": "step one", "order": 0}, {"id": "step two", "order": 1}, {"id": "step three", "order": 2},]
            ),
            "properties": json.dumps([]),
            "funnel_window_days": 14,
            "funnel_step": 1,
            "filter_test_accounts": "false",
            "new_entity": json.dumps([]),
            "date_from": "2021-05-01",
            "date_to": "2021-05-10",
        }

        response = self.client.get("/api/person/funnel/", data=request_data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        j = response.json()
        first_person = j["results"][0]["people"][0]
        self.assertEqual(5, len(j["results"][0]["people"]))
        self.assertTrue("id" in first_person and "name" in first_person and "distinct_ids" in first_person)
        self.assertEqual(5, j["results"][0]["count"])

    def test_basic_pagination(self):
        cache.clear()
        self._create_sample_data(250)
        request_data = {
            "insight": INSIGHT_FUNNELS,
            "interval": "day",
            "actions": json.dumps([]),
            "events": json.dumps(
                [{"id": "step one", "order": 0}, {"id": "step two", "order": 1}, {"id": "step three", "order": 2},]
            ),
            "properties": json.dumps([]),
            "funnel_window_days": 14,
            "funnel_step": 1,
            "filter_test_accounts": "false",
            "new_entity": json.dumps([]),
            "date_from": "2021-05-01",
            "date_to": "2021-05-10",
        }

        response = self.client.get("/api/person/funnel/", data=request_data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        j = response.json()
        people = j["results"][0]["people"]
        next = j["next"]
        self.assertEqual(100, len(people))

        response = self.client.get(next)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        j = response.json()
        people = j["results"][0]["people"]
        next = j["next"]
        self.assertEqual(100, len(people))
        self.assertNotEqual(None, next)

        response = self.client.get(next)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        j = response.json()
        people = j["results"][0]["people"]
        self.assertEqual(50, len(people))
        self.assertEqual(None, j["next"])

    @patch("ee.clickhouse.models.person.delete_person")
    def test_basic_pagination_with_deleted(self, delete_person_patch):
        cache.clear()
        self._create_sample_data(250, delete=True)
        request_data = {
            "insight": INSIGHT_FUNNELS,
            "interval": "day",
            "actions": json.dumps([]),
            "events": json.dumps(
                [{"id": "step one", "order": 0}, {"id": "step two", "order": 1}, {"id": "step three", "order": 2},]
            ),
            "properties": json.dumps([]),
            "funnel_window_days": 14,
            "funnel_step": 1,
            "filter_test_accounts": "false",
            "new_entity": json.dumps([]),
            "date_from": "2021-05-01",
            "date_to": "2021-05-10",
        }

        response = self.client.get("/api/person/funnel/", data=request_data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        j = response.json()
        people = j["results"][0]["people"]
        next = j["next"]
        self.assertEqual(0, len(people))
        self.assertNotEqual(None, next)

        response = self.client.get(next)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        j = response.json()
        people = j["results"][0]["people"]
        next = j["next"]
        self.assertEqual(0, len(people))
        self.assertNotEqual(None, next)

        response = self.client.get(next)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        j = response.json()
        people = j["results"][0]["people"]
        self.assertEqual(0, len(people))
        self.assertEqual(None, j["next"])
