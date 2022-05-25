import json

from django.core.cache import cache
from rest_framework import status

from posthog.demo import create_demo_team
from posthog.models.dashboard import Dashboard
from posthog.models.organization import Organization, OrganizationMembership
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
        self.assertEqual(response_data["has_group_types"], False)

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
            f"/api/projects/{self.team.id}/", {"test_account_filters": [{"key": "$current_url", "value": "test"}]},
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

    def test_reset_token(self):
        self.team.api_token = "xyz"
        self.team.save()

        response = self.client.patch(f"/api/projects/{self.team.id}/reset_token/")
        response_data = response.json()

        self.team.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertNotEqual(response_data["api_token"], "xyz")
        self.assertEqual(response_data["api_token"], self.team.api_token)
        self.assertTrue(response_data["api_token"].startswith("phc_"))

    def test_update_primary_dashboard(self):
        d = Dashboard.objects.create(name="Test", team=self.team)

        # Can set it
        response = self.client.patch("/api/projects/@current/", {"primary_dashboard": d.id})
        response_data = response.json()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response_data["name"], self.team.name)
        self.assertEqual(response_data["primary_dashboard"], d.id)

    def test_cant_set_primary_dashboard_to_another_teams_dashboard(self):
        team_2 = Team.objects.create(organization=self.organization, name="Default Project")
        d = Dashboard.objects.create(name="Test", team=team_2)

        response = self.client.patch("/api/projects/@current/", {"primary_dashboard": d.id})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        response = self.client.get("/api/projects/@current/")
        response_data = response.json()
        self.assertEqual(response_data["primary_dashboard"], None)

    def test_update_timezone_remove_cache(self):
        # Seed cache with some insights
        self.client.post(
            f"/api/projects/{self.team.id}/insights/",
            data={"filters": {"events": json.dumps([{"id": "user signed up"}])}},
        )
        response = self.client.post(
            f"/api/projects/{self.team.id}/insights/", data={"filters": {"events": json.dumps([{"id": "$pageview"}])}},
        ).json()
        self.client.get(
            f"/api/projects/{self.team.id}/insights/trend/", data={"events": json.dumps([{"id": "$pageview"}])},
        )
        self.client.get(
            f"/api/projects/{self.team.id}/insights/trend/", data={"events": json.dumps([{"id": "user signed up"}])},
        )

        self.assertEqual(cache.get(response["filters_hash"])["result"][0]["count"], 0)
        self.client.patch(
            f"/api/projects/{self.team.id}/", {"timezone": "US/Pacific"},
        )
        # Verify cache was deleted
        self.assertEqual(cache.get(response["filters_hash"]), None)


def create_team(organization: Organization, name: str = "Test team") -> Team:
    """
    This is a helper that just creates a team. It currently uses the orm, but we
    could use either the api, or django admin to create, to get better parity
    with real world  scenarios.
    """
    return Team.objects.create(
        organization=organization, name=name, ingested_event=True, completed_snippet_onboarding=True, is_demo=True,
    )
