import json
from typing import Any, Dict, List
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test.client import Client
from rest_framework.test import APIClient

from posthog.models import Person
from posthog.models.cohort import Cohort
from posthog.test.base import APIBaseTest


class TestCohort(APIBaseTest):
    @patch("posthog.api.cohort.report_user_action")
    @patch("posthog.tasks.calculate_cohort.calculate_cohort.delay")
    def test_creating_update_and_calculating(self, patch_calculate_cohort, patch_capture):
        self.team.app_urls = ["http://somewebsite.com"]
        self.team.save()
        Person.objects.create(team=self.team, properties={"team_id": 5})
        Person.objects.create(team=self.team, properties={"team_id": 6})

        # Make sure the endpoint works with and without the trailing slash
        response = self.client.post(
            f"/api/projects/{self.team.id}/cohorts",
            data={"name": "whatever", "groups": [{"properties": {"team_id": 5}}]},
        )
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["created_by"]["id"], self.user.pk)
        self.assertEqual(patch_calculate_cohort.call_count, 1)

        # Assert analytics are sent
        patch_capture.assert_called_with(
            self.user,
            "cohort created",
            {
                "name_length": 8,
                "person_count_precalc": 0,
                "groups_count": 1,
                "action_groups_count": 0,
                "properties_groups_count": 1,
                "deleted": False,
            },
        )

        response = self.client.patch(
            f"/api/projects/{self.team.id}/cohorts/{response.json()['id']}",
            data={
                "name": "whatever2",
                "description": "A great cohort!",
                "groups": [{"properties": {"team_id": 6}}],
                "created_by": "something something",
                "last_calculation": "some random date",
                "errors_calculating": 100,
                "deleted": False,
            },
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertDictContainsSubset({"name": "whatever2", "description": "A great cohort!"}, response.json())
        self.assertEqual(patch_calculate_cohort.call_count, 2)

        # Assert analytics are sent
        patch_capture.assert_called_with(
            self.user,
            "cohort updated",
            {
                "name_length": 9,
                "person_count_precalc": 0,
                "groups_count": 1,
                "action_groups_count": 0,
                "properties_groups_count": 1,
                "deleted": False,
                "updated_by_creator": True,
            },
        )

    @patch("posthog.tasks.calculate_cohort.calculate_cohort_from_list.delay")
    def test_static_cohort_csv_upload(self, patch_calculate_cohort_from_list):
        self.team.app_urls = ["http://somewebsite.com"]
        self.team.save()
        Person.objects.create(team=self.team, properties={"email": "email@example.org"})
        Person.objects.create(team=self.team, distinct_ids=["123"])
        Person.objects.create(team=self.team, distinct_ids=["456"])

        csv = SimpleUploadedFile(
            "example.csv",
            str.encode(
                """
User ID,
email@example.org,
123
"""
            ),
            content_type="application/csv",
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/cohorts/",
            {"name": "test", "csv": csv, "is_static": True},
            format="multipart",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(patch_calculate_cohort_from_list.call_count, 1)
        self.assertFalse(response.json()["is_calculating"], False)
        self.assertFalse(Cohort.objects.get(pk=response.json()["id"]).is_calculating)

        csv = SimpleUploadedFile(
            "example.csv",
            str.encode(
                """
User ID,
456
"""
            ),
            content_type="application/csv",
        )

        #  A weird issue with pytest client, need to user Rest framework's one
        #  see https://stackoverflow.com/questions/39906956/patch-and-put-dont-work-as-expected-when-pytest-is-interacting-with-rest-framew
        client = APIClient()
        client.force_login(self.user)
        response = client.patch(
            f"/api/projects/{self.team.id}/cohorts/{response.json()['id']}",
            {"name": "test", "csv": csv},
            format="multipart",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(patch_calculate_cohort_from_list.call_count, 2)
        self.assertFalse(response.json()["is_calculating"], False)
        self.assertFalse(Cohort.objects.get(pk=response.json()["id"]).is_calculating)

        # Only change name without updating CSV
        response = client.patch(
            f"/api/projects/{self.team.id}/cohorts/{response.json()['id']}", {"name": "test2"}, format="multipart"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(patch_calculate_cohort_from_list.call_count, 2)
        self.assertFalse(response.json()["is_calculating"], False)
        self.assertFalse(Cohort.objects.get(pk=response.json()["id"]).is_calculating)
        self.assertEqual(Cohort.objects.get(pk=response.json()["id"]).name, "test2")

    @patch("posthog.tasks.calculate_cohort.calculate_cohort_from_list.delay")
    @patch("posthog.tasks.calculate_cohort.calculate_cohort.delay")
    def test_static_cohort_to_dynamic_cohort(self, patch_calculate_cohort, patch_calculate_cohort_from_list):
        self.team.app_urls = ["http://somewebsite.com"]
        self.team.save()
        person = Person.objects.create(team=self.team, properties={"email": "email@example.org"})
        person1 = Person.objects.create(team=self.team, distinct_ids=["123"])
        Person.objects.create(team=self.team, distinct_ids=["456"])

        csv = SimpleUploadedFile(
            "example.csv",
            str.encode(
                """
User ID,
email@example.org,
123
"""
            ),
            content_type="application/csv",
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/cohorts/",
            {"name": "test", "csv": csv, "is_static": True},
            format="multipart",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(patch_calculate_cohort_from_list.call_count, 1)
        self.assertFalse(response.json()["is_calculating"], False)
        self.assertFalse(Cohort.objects.get(pk=response.json()["id"]).is_calculating)

        response = self.client.patch(
            f"/api/projects/{self.team.id}/cohorts/{response.json()['id']}",
            {"is_static": False, "groups": [{"properties": [{"key": "email", "value": "email@example.org"}]}]},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(patch_calculate_cohort.call_count, 1)


def create_cohort(client: Client, team_id: int, name: str, groups: List[Dict[str, Any]]):
    return client.post(f"/api/projects/{team_id}/cohorts", {"name": name, "groups": json.dumps(groups)})


def create_cohort_ok(client: Client, team_id: int, name: str, groups: List[Dict[str, Any]]):
    response = create_cohort(client=client, team_id=team_id, name=name, groups=groups)
    assert response.status_code == 201, response.content
    return response.json()
