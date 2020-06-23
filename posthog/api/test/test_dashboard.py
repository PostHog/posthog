from .base import BaseTest, TransactionBaseTest
from posthog.models import Dashboard


class TestDashboard(TransactionBaseTest):
    TESTS_API = True

    def test_token_auth(self):
        self.client.logout()
        dashboard = Dashboard.objects.create(
            team=self.team, share_token="testtoken", name="public dashboard"
        )
        test_no_token = self.client.get("/api/dashboard/%s/" % (dashboard.pk))
        self.assertEqual(test_no_token.status_code, 403)
        response = self.client.get(
            "/api/dashboard/%s/?share_token=testtoken" % (dashboard.pk)
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["name"], "public dashboard")

    def test_shared_dashboard(self):
        self.client.logout()
        dashboard = Dashboard.objects.create(
            team=self.team, share_token="testtoken", name="public dashboard"
        )
        response = self.client.get("/shared_dashboard/testtoken")
        self.assertIn("bla", response)
