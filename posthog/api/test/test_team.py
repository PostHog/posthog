from posthog.models.team import Team

from .base import APIBaseTest


class TestTeamAPI(APIBaseTest):
    def test_no_create_team_without_license_selfhosted(self):
        with self.settings(MULTI_TENANCY=False):
            response = self.client.post("/api/projects/", {"name": "Test"})
            self.assertEqual(response.status_code, 403)
            self.assertEqual(Team.objects.count(), 1)
            response = self.client.post("/api/projects/", {"name": "Test"})
            self.assertEqual(Team.objects.count(), 1)
