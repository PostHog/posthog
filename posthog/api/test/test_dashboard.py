from .base import BaseTest, TransactionBaseTest
from posthog.models import Dashboard, Filter, DashboardItem
from posthog.api.action import calculate_trends
from posthog.decorators import TRENDS_ENDPOINT
from django.core.cache import cache
from django.utils.timezone import now
from freezegun import freeze_time
import json


class TestDashboard(TransactionBaseTest):
    TESTS_API = True

    def test_create_dashboard_item(self):
        dashboard = Dashboard.objects.create(
            team=self.team, share_token="testtoken", name="public dashboard"
        )
        response = self.client.post(
            "/api/dashboard_item/",
            {
                "dashboard": dashboard.pk,
                "name": "dashboard item",
                "last_refresh": now(),  # This happens when you duplicate a dashboard item, caused error
            },
            content_type="application/json",
        )
        dashboard_item = DashboardItem.objects.get()
        self.assertEqual(dashboard_item.name, "dashboard item")

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
            team=self.team,
            share_token="testtoken",
            name="public dashboard",
            is_shared=True,
        )
        response = self.client.get("/shared_dashboard/testtoken")
        self.assertIn(b"testtoken", response.content)

    def test_share_dashboard(self):
        dashboard = Dashboard.objects.create(team=self.team, name="dashboard")
        response = self.client.patch(
            "/api/dashboard/%s/" % dashboard.pk,
            {"name": "dashboard 2", "is_shared": True},
            content_type="application/json",
        )
        dashboard = Dashboard.objects.get(pk=dashboard.pk)
        self.assertIsNotNone(dashboard.share_token)

    def test_return_results(self):
        dashboard = Dashboard.objects.create(team=self.team, name="dashboard")
        filter_dict = {
            "events": [{"id": "$pageview"}],
            "properties": [{"key": "$browser", "value": "Mac OS X"}],
        }

        item = DashboardItem.objects.create(
            dashboard=dashboard,
            filters=Filter(data=filter_dict).to_dict(),
            team=self.team,
        )
        DashboardItem.objects.create(
            dashboard=dashboard,
            filters=Filter(data=filter_dict).to_dict(),
            team=self.team,
        )
        response = self.client.get("/api/dashboard/%s/" % dashboard.pk).json()
        self.assertEqual(response["items"][0]["result"], None)
        # cache results
        self.client.get(
            "/api/action/trends/?events=%s&properties=%s"
            % (json.dumps(filter_dict["events"]), json.dumps(filter_dict["properties"]))
        )

        with self.assertNumQueries(6):
            with freeze_time("2020-01-04T13:00:01Z"):
                response = self.client.get("/api/dashboard/%s/" % dashboard.pk).json()

        self.assertEqual(
            Dashboard.objects.get().last_accessed_at.isoformat(),
            "2020-01-04T13:00:01+00:00",
        )
        self.assertEqual(response["items"][0]["result"][0]["count"], 0)
