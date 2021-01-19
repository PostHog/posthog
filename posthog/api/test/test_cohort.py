from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from posthog.models import Person
from posthog.models.cohort import Cohort
from posthog.test.base import BaseTest


class TestCohort(BaseTest):
    TESTS_API = True

    @patch("posthoganalytics.capture")
    @patch("posthog.tasks.calculate_cohort.calculate_cohort.delay")
    def test_creating_update_and_calculating(self, patch_calculate_cohort, patch_capture):
        self.team.app_urls = ["http://somewebsite.com"]
        self.team.save()
        Person.objects.create(team=self.team, properties={"team_id": 5})
        Person.objects.create(team=self.team, properties={"team_id": 6})

        # Make sure the endpoint works with and without the trailing slash
        response = self.client.post(
            "/api/cohort",
            data={"name": "whatever", "groups": [{"properties": {"team_id": 5}}]},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["created_by"]["id"], self.user.pk)
        self.assertEqual(patch_calculate_cohort.call_count, 1)

        # Assert analytics are sent
        patch_capture.assert_called_with(
            self.user.distinct_id,
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
            "/api/cohort/%s/" % response.json()["id"],
            data={"name": "whatever2", "groups": [{"properties": {"team_id": 6}}]},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["name"], "whatever2")
        self.assertEqual(patch_calculate_cohort.call_count, 2)

        # Assert analytics are sent
        patch_capture.assert_called_with(
            self.user.distinct_id,
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

    @patch("posthog.tasks.calculate_cohort.calculate_cohort_from_csv.delay")
    def test_static_cohort_csv_upload(self, patch_calculate_cohort_from_csv):
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

        response = self.client.post("/api/cohort/", {"name": "test", "csv": csv, "is_static": True},)
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(patch_calculate_cohort_from_csv.call_count, 1)

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
        response = client.patch("/api/cohort/%s/" % response.json()["id"], {"name": "test", "csv": csv,})
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(patch_calculate_cohort_from_csv.call_count, 2)
