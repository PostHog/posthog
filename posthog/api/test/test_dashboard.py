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
        dashboard_item = self.client.post(
            "/api/dashboard_item/", data={"filters": {"hello": "test"}, "dashboard": dashboard.pk, "name": "some_item"}, content_type="application/json",
        )
        response = self.client.get("/api/dashboard/{}/".format(dashboard.pk)).json()
        self.assertEqual(len(response['items']), 1)
        self.assertEqual(response['items'][0]["name"], "some_item")

        item_response = self.client.get("/api/dashboard_item/").json()
        self.assertEqual(item_response['results'][0]["name"], "some_item")

        # delete
        self.client.patch("/api/dashboard_item/{}/".format(item_response['results'][0]["id"]), data={"deleted": "true"}, content_type="application/json")
        items_response = self.client.get("/api/dashboard_item/").json()
        self.assertEqual(len(items_response['results']), 0)

    def test_dashboard_item_layout(self):
        dashboard = Dashboard.objects.create(name="asdasd", pinned=True, team=self.team)
        response = self.client.post(
            "/api/dashboard_item/", data={"filters": {"hello": "test"}, "dashboard": dashboard.pk, "name": "another"}, content_type="application/json",
        ).json()

        self.client.patch(
            "/api/dashboard_item/layouts/", data={"items": [{
                "id": response['id'],
                "layouts": {'lg': {'x': "0", 'y': "0", 'w': "6", 'h': "5"}, 'sm': {'w': "7", 'h': "5", 'x': "0", 'y': "0", 'moved': "False", 'static': "False"}, 'xs': {'x': "0", 'y': "0", 'w': "6", 'h': "5"}, 'xxs': {'x': "0", 'y': "0", 'w': "2", 'h': "5"}}
            }]}, content_type="application/json",
        )
        items_response = self.client.get("/api/dashboard_item/{}/".format(response['id'])).json()
        self.assertTrue('lg' in items_response['layouts'])
