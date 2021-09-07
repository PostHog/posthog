from rest_framework import status

from posthog.demo import create_demo_team
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.session_recording_event import SessionRecordingEvent
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

        # TODO: These assertions will no longer make sense when we fully remove these attributes from the model
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

        # TODO: These assertions will no longer make sense when we fully remove these attributes from the model
        self.assertNotIn("event_names", response_data)
        self.assertNotIn("event_properties", response_data)
        self.assertNotIn("event_properties_numerical", response_data)
        self.assertNotIn("event_names_with_usage", response_data)
        self.assertNotIn("event_properties_with_usage", response_data)

    def test_cant_retrieve_project_from_another_org(self):
        org = Organization.objects.create(name="New Org")
        team = Team.objects.create(organization=org, name="Default Project")

        response = self.client.get(f"/api/projects/{team.pk}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.json(), self.not_found_response())

    def test_cant_create_team_without_license_on_selfhosted(self):
        with self.settings(MULTI_TENANCY=False):
            response = self.client.post("/api/projects/", {"name": "Test"})
            self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
            self.assertEqual(Team.objects.count(), 1)
            response = self.client.post("/api/projects/", {"name": "Test"})
            self.assertEqual(Team.objects.count(), 1)

    def test_retention_invalid_properties(self):
        org = Organization.objects.create(name="New Org")
        team = Team.objects.create(organization=org, name="Default Project")

        properties = "invalid_json"
        response = self.client.get(f"/api/projects/{team.pk}/actions/retention", data={"properties": properties})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertDictEqual(
            response.json(), self.validation_error_response("Properties are unparsable!", "invalid_input")
        )

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

    def test_cant_update_project_from_another_org(self):
        org = Organization.objects.create(name="New Org")
        team = Team.objects.create(organization=org, name="Default Project")

        response = self.client.patch(f"/api/projects/{team.pk}/", {"timezone": "Africa/Accra"})
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.json(), self.not_found_response())

        team.refresh_from_db()
        self.assertEqual(team.timezone, "UTC")

    def test_filter_permission(self):

        response = self.client.patch(
            "/api/projects/%s/" % (self.user.team.pk if self.user.team else 0),
            {"test_account_filters": [{"key": "$current_url", "value": "test"}]},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response_data = response.json()
        self.assertEqual(response_data["name"], self.team.name)
        self.assertEqual(response_data["test_account_filters"], [{"key": "$current_url", "value": "test"}])

    def test_delete_team_own_second(self):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        team = create_demo_team(organization=self.organization)

        self.assertEqual(Team.objects.filter(organization=self.organization).count(), 2)

        response = self.client.delete(f"/api/projects/{team.id}")

        self.assertEqual(response.status_code, 204)
        self.assertEqual(Team.objects.filter(organization=self.organization).count(), 1)
