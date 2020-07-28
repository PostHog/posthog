from unittest.mock import patch

from posthog.models import Cohort, Person

from .base import BaseTest


class TestCohort(BaseTest):
    TESTS_API = True

    @patch("posthog.tasks.calculate_cohort.calculate_cohort.delay")
    def test_creating_update_and_calculating(self, patch_calculate_cohort):
        self.team.app_urls = ["http://somewebsite.com"]
        self.team.save()
        person1 = Person.objects.create(team=self.team, properties={"team_id": 5})
        person2 = Person.objects.create(team=self.team, properties={"team_id": 6})
        response = self.client.post(
            "/api/cohort/",
            data={"name": "whatever", "groups": [{"properties": {"team_id": 5}}]},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["created_by"]["id"], self.user.pk)
        self.assertEqual(patch_calculate_cohort.call_count, 1)

        response = self.client.patch(
            "/api/cohort/%s/" % response.json()["id"],
            data={"name": "whatever2", "groups": [{"properties": {"team_id": 6}}]},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["name"], "whatever2")
        self.assertEqual(patch_calculate_cohort.call_count, 2)
