from rest_framework import status

from posthog.models.team import Team
from posthog.test.base import APIBaseTest


class TestTeamAPI(APIBaseTest):
    def test_list_projects(self):

        response = self.client.get("/api/projects/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Listing endpoint always uses the simplified serializer
        response_data = response.json()
        self.assertEqual(len(response_data["results"]), 1)
        self.assertEqual(response_data["results"][0]["name"], self.team.name)
        self.assertNotIn("test_account_filters", response_data["results"][0])
        self.assertNotIn("data_attributes", response_data["results"][0])
        self.assertNotIn("event_names", response_data["results"][0])
        self.assertNotIn("event_properties", response_data["results"][0])
        self.assertNotIn("event_properties_numerical", response_data["results"][0])

    def test_retrieve_project(self):

        response = self.client.get("/api/projects/@current/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response_data = response.json()
        self.assertEqual(response_data["name"], self.team.name)
        self.assertEqual(response_data["timezone"], "UTC")
        self.assertEqual(response_data["is_demo"], False)
        self.assertEqual(response_data["slack_incoming_webhook"], self.team.slack_incoming_webhook)
        self.assertIn("event_names", response_data)
        self.assertIn("event_properties", response_data)
        self.assertIn("event_properties_numerical", response_data)

    def test_retrieve_project_with_basic_data(self):

        response = self.client.get("/api/projects/@current/?basic=1")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response_data = response.json()
        self.assertEqual(response_data["name"], self.team.name)
        self.assertEqual(response_data["organization"], str(self.organization.pk))
        self.assertEqual(response_data["uuid"], str(self.team.uuid))
        self.assertEqual(response_data["completed_snippet_onboarding"], self.team.completed_snippet_onboarding)
        self.assertEqual(response_data["ingested_event"], self.team.ingested_event)
        self.assertNotIn("test_account_filters", response_data)
        self.assertNotIn("data_attributes", response_data)
        self.assertNotIn("event_names", response_data)
        self.assertNotIn("event_properties", response_data)
        self.assertNotIn("event_properties_numerical", response_data)

    def test_cant_create_team_without_license_on_selfhosted(self):
        with self.settings(MULTI_TENANCY=False):
            response = self.client.post("/api/projects/", {"name": "Test"})
            self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
            self.assertEqual(Team.objects.count(), 1)
            response = self.client.post("/api/projects/", {"name": "Test"})
            self.assertEqual(Team.objects.count(), 1)

    def test_updating_project_with_basic_query_string_has_no_effect(self):
        response = self.client.patch(
            "/api/projects/@current/?basic=1", {"slack_incoming_webhook": "https://slack.posthog.com"}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response_data = response.json()
        self.assertEqual(response_data["name"], self.team.name)
        self.assertEqual(response_data["slack_incoming_webhook"], "https://slack.posthog.com")

        self.team.refresh_from_db()
        self.assertEqual(self.team.slack_incoming_webhook, "https://slack.posthog.com")

    def test_update_project_timezone(self):

        response = self.client.patch("/api/projects/@current/", {"timezone": "Europe/Istanbul"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response_data = response.json()
        self.assertEqual(response_data["name"], self.team.name)
        self.assertEqual(response_data["timezone"], "Europe/Istanbul")

        self.team.refresh_from_db()
        self.assertEqual(self.team.timezone, "Europe/Istanbul")

    def test_cannot_set_invalid_timezone_for_project(self):
        response = self.client.patch("/api/projects/@current/", {"timezone": "America/I_Dont_Exist"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            {
                "type": "validation_error",
                "code": "invalid_choice",
                "detail": '"America/I_Dont_Exist" is not a valid choice.',
                "attr": "timezone",
            },
        )

        self.team.refresh_from_db()
        self.assertNotEqual(self.team.timezone, "America/I_Dont_Exist")
