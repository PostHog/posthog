from rest_framework import status

from posthog.models.team import Team

from .base import APIBaseTest


class TestTeamAPI(APIBaseTest):
    def test_retrieve_project(self):

        response = self.client.get("/api/projects/@current/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response_data = response.json()
        self.assertEqual(response_data["name"], self.team.name)
        self.assertEqual(response_data["timezone"], "UTC")

    def test_no_create_team_without_license_selfhosted(self):
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
