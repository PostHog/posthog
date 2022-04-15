import json
import urllib.parse
from unittest.mock import patch

from django.core.cache import cache
from rest_framework import status

from ee.clickhouse.util import ClickhouseTestMixin
from posthog.constants import FUNNEL_PATH_AFTER_STEP, INSIGHT_FUNNELS, INSIGHT_PATHS
from posthog.models.cohort import Cohort
from posthog.models.person import Person
from posthog.tasks.calculate_cohort import insert_cohort_from_insight_filter
from posthog.test.base import APIBaseTest, _create_event, _create_person


class TestPathPerson(ClickhouseTestMixin, APIBaseTest):
    def _create_sample_data(self, num, delete=False):
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
                properties={"$browser": "Chrome"},
            )
            if i % 2 == 0:
                _create_event(
                    event="step two",
                    distinct_id=f"user_{i}",
                    team=self.team,
                    timestamp="2021-05-01 00:10:00",
                    properties={"$browser": "Chrome"},
                )
            _create_event(
                event="step three",
                distinct_id=f"user_{i}",
                team=self.team,
                timestamp="2021-05-01 00:20:00",
                properties={"$browser": "Chrome"},
            )
            if delete:
                person.delete()

    def test_basic_format(self):
        self._create_sample_data(5)
        request_data = {
            "insight": INSIGHT_PATHS,
            "filter_test_accounts": "false",
            "date_from": "2021-05-01",
            "date_to": "2021-05-10",
        }

        response = self.client.get("/api/person/path/", data=request_data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        j = response.json()
        first_person = j["results"][0]["people"][0]
        self.assertEqual(5, len(j["results"][0]["people"]))
        self.assertTrue("id" in first_person and "name" in first_person and "distinct_ids" in first_person)
        self.assertEqual(5, j["results"][0]["count"])

    @patch("posthog.tasks.calculate_cohort.insert_cohort_from_insight_filter.delay")
    def test_create_paths_cohort(self, _insert_cohort_from_insight_filter):
        self._create_sample_data(5)

        params = {
            "insight": INSIGHT_PATHS,
            "filter_test_accounts": "false",
            "date_from": "2021-05-01",
            "date_to": "2021-05-10",
        }

        response = self.client.post(
            f"/api/projects/{self.team.id}/cohorts/?{urllib.parse.urlencode(params)}",
            {"name": "test", "is_static": True},
        ).json()

        cohort_id = response["id"]

        _insert_cohort_from_insight_filter.assert_called_once_with(
            cohort_id,
            {"insight": "PATHS", "filter_test_accounts": "false", "date_from": "2021-05-01", "date_to": "2021-05-10"},
        )

        insert_cohort_from_insight_filter(
            cohort_id, params,
        )

        cohort = Cohort.objects.get(pk=cohort_id)
        people = Person.objects.filter(cohort__id=cohort.pk)
        self.assertEqual(cohort.errors_calculating, 0)
        self.assertEqual(people.count(), 5)

    def test_basic_format_with_path_start_key_constraints(self):
        self._create_sample_data(5)
        request_data = {
            "insight": INSIGHT_PATHS,
            "filter_test_accounts": "false",
            "date_from": "2021-05-01",
            "date_to": "2021-05-10",
            "path_start_key": "2_step two",
        }

        response = self.client.get("/api/person/path/", data=request_data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        j = response.json()
        first_person = j["results"][0]["people"][0]
        self.assertEqual(3, len(j["results"][0]["people"]))
        self.assertTrue("id" in first_person and "name" in first_person and "distinct_ids" in first_person)
        self.assertEqual(3, j["results"][0]["count"])

    def test_basic_format_with_start_point_constraints(self):
        self._create_sample_data(7)
        request_data = {
            "insight": INSIGHT_PATHS,
            "filter_test_accounts": "false",
            "date_from": "2021-05-01",
            "date_to": "2021-05-10",
            "path_start_key": "1_step two",
            "start_point": "step two",
        }

        response = self.client.get("/api/person/path/", data=request_data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        j = response.json()
        first_person = j["results"][0]["people"][0]
        self.assertEqual(4, len(j["results"][0]["people"]))
        self.assertTrue("id" in first_person and "name" in first_person and "distinct_ids" in first_person)
        self.assertEqual(4, j["results"][0]["count"])

    def test_basic_pagination(self):
        self._create_sample_data(20)
        request_data = {
            "insight": INSIGHT_PATHS,
            "filter_test_accounts": "false",
            "date_from": "2021-05-01",
            "date_to": "2021-05-10",
            "limit": 15,
        }

        response = self.client.get("/api/person/path/", data=request_data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        j = response.json()
        people = j["results"][0]["people"]
        next = j["next"]

        self.assertEqual(15, len(people))
        self.assertNotEqual(None, next)

        response = self.client.get(next)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        j = response.json()
        people = j["results"][0]["people"]
        next = j["next"]
        self.assertEqual(5, len(people))
        self.assertEqual(None, j["next"])

    @patch("ee.clickhouse.models.person.delete_person")
    def test_basic_pagination_with_deleted(self, delete_person_patch):
        cache.clear()
        self._create_sample_data(110, delete=True)
        request_data = {
            "insight": INSIGHT_PATHS,
            "filter_test_accounts": "false",
            "date_from": "2021-05-01",
            "date_to": "2021-05-10",
        }

        response = self.client.get("/api/person/path/", data=request_data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        j = response.json()
        people = j["results"][0]["people"]
        next = j["next"]
        self.assertEqual(0, len(people))
        self.assertIsNone(next)

    def test_basic_format_with_funnel_path_post(self):
        self._create_sample_data(7)
        request_data = {
            "insight": INSIGHT_PATHS,
            "funnel_paths": FUNNEL_PATH_AFTER_STEP,
            "filter_test_accounts": "false",
            "date_from": "2021-05-01",
            "date_to": "2021-05-07",
            "path_start_key": "1_step two",
            "path_end_key": "2_step three",
        }

        funnel_filter = {
            "insight": INSIGHT_FUNNELS,
            "interval": "day",
            "date_from": "2021-05-01 00:00:00",
            "date_to": "2021-05-07 00:00:00",
            "funnel_window_interval": 7,
            "funnel_window_interval_unit": "day",
            "funnel_step": 2,
            "events": [
                {"id": "step one", "order": 0},
                {"id": "step two", "order": 1},
                {"id": "step three", "order": 2},
            ],
        }

        post_response = self.client.post("/api/person/path/", data={**request_data, "funnel_filter": funnel_filter})
        self.assertEqual(post_response.status_code, status.HTTP_200_OK)
        post_j = post_response.json()
        self.assertEqual(4, len(post_j["results"][0]["people"]))

    def test_basic_format_with_funnel_path_get(self):
        self._create_sample_data(7)
        request_data = {
            "insight": INSIGHT_PATHS,
            "funnel_paths": FUNNEL_PATH_AFTER_STEP,
            "filter_test_accounts": "false",
            "date_from": "2021-05-01",
            "date_to": "2021-05-07",
            "path_start_key": "1_step two",
            "path_end_key": "2_step three",
        }

        funnel_filter = {
            "insight": INSIGHT_FUNNELS,
            "interval": "day",
            "date_from": "2021-05-01 00:00:00",
            "date_to": "2021-05-07 00:00:00",
            "funnel_window_interval": 7,
            "funnel_window_interval_unit": "day",
            "funnel_step": 2,
            "events": [
                {"id": "step one", "order": 0},
                {"id": "step two", "order": 1},
                {"id": "step three", "order": 2},
            ],
        }

        get_response = self.client.get(
            "/api/person/path/", data={**request_data, "funnel_filter": json.dumps(funnel_filter)}
        )
        self.assertEqual(get_response.status_code, status.HTTP_200_OK)
        get_j = get_response.json()
        self.assertEqual(4, len(get_j["results"][0]["people"]))
