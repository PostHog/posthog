from re import DEBUG

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

    def test_webhook_bad_url(self):
        response = self.client.patch("/api/projects/@current", {"incoming_webhook": "blabla"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.data,
            {"detail": "Invalid webhook URL.", "attr": None, "code": "invalid_input", "type": "validation_error"},
        )

    def test_webhook_bad_url_full(self):
        response = self.client.patch("/api/projects/@current", {"incoming_webhook": "http://localhost/bla"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(),
            {"detail": "Invalid webhook URL.", "attr": None, "code": "invalid_input", "type": "validation_error"},
        )
