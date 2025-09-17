import json

from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    snapshot_clickhouse_queries,
)
from unittest.mock import patch

from django.core.cache import cache

from rest_framework import status

from posthog.constants import INSIGHT_FUNNELS
from posthog.models.group.util import create_group
from posthog.models.instance_setting import get_instance_setting
from posthog.models.person import Person


class TestFunnelPerson(ClickhouseTestMixin, APIBaseTest):
    def _create_sample_data(self, num, delete=False):
        create_group(
            team_id=self.team.pk,
            group_type_index=0,
            group_key="g0",
            properties={"slug": "g0", "name": "g0"},
        )

        for i in range(num):
            if delete:
                person = Person.objects.create(distinct_ids=[f"user_{i}"], team=self.team)
            else:
                _create_person(distinct_ids=[f"user_{i}"], team=self.team)
            _create_event(
                event="step one",
                distinct_id=f"user_{i}",
                team=self.team,
                timestamp="2021-05-01 00:00:00",
                properties={"$browser": "Chrome", "$group_0": "g0"},
            )
            _create_event(
                event="step two",
                distinct_id=f"user_{i}",
                team=self.team,
                timestamp="2021-05-03 00:00:00",
                properties={"$browser": "Chrome", "$group_0": "g0"},
            )
            _create_event(
                event="step three",
                distinct_id=f"user_{i}",
                team=self.team,
                timestamp="2021-05-05 00:00:00",
                properties={"$browser": "Chrome", "$group_0": "g0"},
            )
            if delete:
                person.delete()

    def test_basic_format(self):
        self._create_sample_data(5)
        request_data = {
            "insight": INSIGHT_FUNNELS,
            "interval": "day",
            "actions": json.dumps([]),
            "events": json.dumps(
                [
                    {"id": "step one", "order": 0},
                    {"id": "step two", "order": 1},
                    {"id": "step three", "order": 2},
                ]
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

    @snapshot_clickhouse_queries
    def test_funnel_actors_with_groups_search(self):
        self._create_sample_data(5)

        request_data = {
            "aggregation_group_type_index": 0,
            "search": "g0",
            "breakdown_attribution_type": "first_touch",
            "insight": INSIGHT_FUNNELS,
            "interval": "day",
            "actions": json.dumps([]),
            "events": json.dumps(
                [
                    {"id": "step one", "order": 0},
                    {"id": "step two", "order": 1},
                    {"id": "step three", "order": 2},
                ]
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
        self.assertEqual(1, len(j["results"][0]["people"]))
        self.assertEqual(1, j["results"][0]["count"])

    def test_basic_pagination(self):
        cache.clear()
        self._create_sample_data(110)
        request_data = {
            "insight": INSIGHT_FUNNELS,
            "interval": "day",
            "actions": json.dumps([]),
            "events": json.dumps(
                [
                    {"id": "step one", "order": 0},
                    {"id": "step two", "order": 1},
                    {"id": "step three", "order": 2},
                ]
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
        self.assertNotEqual(None, next)

        response = self.client.get(next)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        j = response.json()
        people = j["results"][0]["people"]
        next = j["next"]
        self.assertEqual(10, len(people))
        self.assertEqual(None, j["next"])

    def test_breakdown_basic_pagination(self):
        cache.clear()
        self._create_sample_data(110)
        request_data = {
            "insight": INSIGHT_FUNNELS,
            "interval": "day",
            "actions": json.dumps([]),
            "events": json.dumps(
                [
                    {"id": "step one", "order": 0},
                    {"id": "step two", "order": 1},
                    {"id": "step three", "order": 2},
                ]
            ),
            "properties": json.dumps([]),
            "funnel_window_days": 14,
            "funnel_step": 1,
            "filter_test_accounts": "false",
            "new_entity": json.dumps([]),
            "date_from": "2021-05-01",
            "date_to": "2021-05-10",
            "breakdown_type": "event",
            "breakdown": "$browser",
            "funnel_step_breakdown": "Chrome",
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
        self.assertEqual(10, len(people))
        self.assertEqual(None, j["next"])

    @patch("posthog.models.person.util.delete_person")
    def test_basic_pagination_with_deleted(self, delete_person_patch):
        if not get_instance_setting("PERSON_ON_EVENTS_ENABLED"):
            return

        cache.clear()
        self._create_sample_data(20, delete=True)
        request_data = {
            "insight": INSIGHT_FUNNELS,
            "interval": "day",
            "actions": json.dumps([]),
            "events": json.dumps(
                [
                    {"id": "step one", "order": 0},
                    {"id": "step two", "order": 1},
                    {"id": "step three", "order": 2},
                ]
            ),
            "properties": json.dumps([]),
            "funnel_window_days": 14,
            "funnel_step": 1,
            "filter_test_accounts": "false",
            "new_entity": json.dumps([]),
            "date_from": "2021-05-01",
            "date_to": "2021-05-10",
            "limit": 15,
        }

        response = self.client.get("/api/person/funnel/", data=request_data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        j = response.json()
        people = j["results"][0]["people"]
        next = j["next"]
        missing_persons = j["missing_persons"]
        self.assertEqual(0, len(people))
        self.assertEqual(15, missing_persons)
        self.assertIsNotNone(next)

        response = self.client.get(next)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        j = response.json()
        people = j["results"][0]["people"]
        next = j["next"]
        missing_persons = j["missing_persons"]
        self.assertEqual(0, len(people))
        self.assertEqual(5, missing_persons)
        self.assertIsNone(next)

    def test_breakdowns(self):
        request_data = {
            "insight": INSIGHT_FUNNELS,
            "interval": "day",
            "actions": json.dumps([]),
            "properties": json.dumps([]),
            "funnel_step": 1,
            "filter_test_accounts": "false",
            "new_entity": json.dumps([]),
            "events": json.dumps(
                [
                    {"id": "sign up", "order": 0},
                    {"id": "play movie", "order": 1},
                    {"id": "buy", "order": 2},
                ]
            ),
            "insight": INSIGHT_FUNNELS,
            "date_from": "2020-01-01",
            "date_to": "2020-01-08",
            "funnel_window_days": 7,
            "breakdown": "$browser",
            "funnel_step_breakdown": "Chrome",
        }

        # event
        _create_person(distinct_ids=["person1"], team_id=self.team.pk)
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

        _create_person(distinct_ids=["person2"], team_id=self.team.pk)
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

        _create_person(distinct_ids=["person3"], team_id=self.team.pk)
        _create_event(
            team=self.team,
            event="sign up",
            distinct_id="person3",
            properties={"key": "val", "$browser": "Safari"},
            timestamp="2020-01-02T14:00:00Z",
        )

        response = self.client.get("/api/person/funnel/", data=request_data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        j = response.json()

        people = j["results"][0]["people"]
        self.assertEqual(1, len(people))
        self.assertEqual(None, j["next"])

        response = self.client.get(
            "/api/person/funnel/",
            data={**request_data, "funnel_step_breakdown": "Safari"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        j = response.json()

        people = j["results"][0]["people"]
        self.assertEqual(2, len(people))
        self.assertEqual(None, j["next"])


class TestFunnelCorrelationActors(ClickhouseTestMixin, APIBaseTest):
    """
    Tests for /api/projects/:project_id/persons/funnel/correlation/
    """

    def test_pagination(self):
        cache.clear()

        for i in range(10):
            _create_person(distinct_ids=[f"user_{i}"], team_id=self.team.pk)
            _create_event(
                team=self.team,
                event="user signed up",
                distinct_id=f"user_{i}",
                timestamp="2020-01-02T14:00:00Z",
            )
            _create_event(
                team=self.team,
                event="positively_related",
                distinct_id=f"user_{i}",
                timestamp="2020-01-03T14:00:00Z",
            )
            _create_event(
                team=self.team,
                event="paid",
                distinct_id=f"user_{i}",
                timestamp="2020-01-04T14:00:00Z",
            )

        request_data = {
            "events": json.dumps(
                [
                    {"id": "user signed up", "type": "events", "order": 0},
                    {"id": "paid", "type": "events", "order": 1},
                ]
            ),
            "insight": INSIGHT_FUNNELS,
            "date_from": "2020-01-01",
            "date_to": "2020-01-14",
            "funnel_correlation_type": "events",
            "funnel_correlation_person_converted": "true",
            "funnel_correlation_person_limit": 4,
            "funnel_correlation_person_entity": json.dumps({"id": "positively_related", "type": "events"}),
        }

        response = self.client.get(
            f"/api/projects/{self.team.pk}/persons/funnel/correlation",
            data=request_data,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        j = response.json()

        first_person = j["results"][0]["people"][0]
        self.assertEqual(4, len(j["results"][0]["people"]))
        self.assertTrue("id" in first_person and "name" in first_person and "distinct_ids" in first_person)
        self.assertEqual(4, j["results"][0]["count"])

        next = j["next"]
        response = self.client.get(next)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        j = response.json()

        people = j["results"][0]["people"]
        next = j["next"]
        self.assertEqual(4, len(people))
        self.assertNotEqual(None, next)

        response = self.client.get(next)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        j = response.json()
        people = j["results"][0]["people"]
        next = j["next"]
        self.assertEqual(2, len(people))
        self.assertEqual(None, j["next"])
