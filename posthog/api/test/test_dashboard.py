from .base import BaseTest, TransactionBaseTest
from posthog.models import Dashboard, Filter, DashboardItem
from posthog.api.action import calculate_trends
from posthog.decorators import TRENDS_ENDPOINT
from posthog.tasks.update_cache import update_cache
from django.core.cache import cache


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
        filter_dict = {
            "events": [{"id": "$pageview"}],
            "properties": [{"key": "$browser", "value": "Mac OS X"}],
        }
        update_cache.apply(
            TRENDS_ENDPOINT,
            {"filter": filter_dict, "params": {}, "team_id": self.team.pk},
        )
        item = DashboardItem.objects.create(
            dashboard=dashboard, filters=filter_dict, team=self.team
        )

        import ipdb

        ipdb.set_trace()
        response = self.client.get("/shared_dashboard/testtoken")
        self.assertIn("bla", response)
