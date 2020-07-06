from .base import BaseTest
from posthog.models import Dashboard, DashboardItem


class TestDashboard(BaseTest):
    TESTS_API = True

    def test_dashboard(self):
        # create
        self.client.post(
            "/api/dashboard/", data={"name": "Default", "pinned": "true"}, content_type="application/json",
        )

        # retrieve
        response = self.client.get("/api/dashboard/").json()
        self.assertEqual(response['results'][0]['id'], 1)
        self.assertEqual(response['results'][0]['name'], 'Default')

        # delete
        self.client.patch("/api/dashboard/1/", data={"deleted": "true"}, content_type="application/json")
        response = self.client.get("/api/dashboard/").json()
        self.assertEqual(len(response['results']), 0)

    def test_dashboard_items(self):
        dashboard = Dashboard.objects.create(name="Default", pinned=True, team=self.team)
        self.client.post(
            "/api/dashboard_item/", data={"filters": {"hello": "test"}, "dashboard": dashboard.pk, "name": "some_item"}, content_type="application/json",
        )
        response = self.client.get("/api/dashboard/2/").json()
        self.assertEqual(len(response['items']), 1)
        self.assertEqual(response['items'][0]["name"], "some_item")

        item_response = self.client.get("/api/dashboard_item/1/").json()
        self.assertEqual(item_response["name"], "some_item")

        # delete
        self.client.patch("/api/dashboard_item/1/", data={"deleted": "true"}, content_type="application/json")
        items_response = self.client.get("/api/dashboard_item/").json()
        self.assertEqual(len(items_response['results']), 0)
