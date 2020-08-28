import json

from django.core.cache import cache
from django.utils.timezone import now
from freezegun import freeze_time

from posthog.models import Dashboard, DashboardItem, Filter, User

from .base import BaseTest, TransactionBaseTest


class TestDashboard(TransactionBaseTest):
    TESTS_API = True

    def test_create_dashboard_item(self):
        dashboard = Dashboard.objects.create(team=self.team, share_token="testtoken", name="public dashboard")
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
        dashboard = Dashboard.objects.create(team=self.team, share_token="testtoken", name="public dashboard")
        test_no_token = self.client.get("/api/dashboard/%s/" % (dashboard.pk))
        self.assertEqual(test_no_token.status_code, 403)
        response = self.client.get("/api/dashboard/%s/?share_token=testtoken" % (dashboard.pk))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["name"], "public dashboard")

    def test_shared_dashboard(self):
        self.client.logout()
        dashboard = Dashboard.objects.create(
            team=self.team, share_token="testtoken", name="public dashboard", is_shared=True,
        )
        response = self.client.get("/shared_dashboard/testtoken")
        self.assertEqual(response.status_code, 200)

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
            dashboard=dashboard, filters=Filter(data=filter_dict).to_dict(), team=self.team,
        )
        DashboardItem.objects.create(
            dashboard=dashboard, filters=Filter(data=filter_dict).to_dict(), team=self.team,
        )
        response = self.client.get("/api/dashboard/%s/" % dashboard.pk).json()
        self.assertEqual(response["items"][0]["result"], None)
        # cache results
        self.client.get(
            "/api/action/trends/?events=%s&properties=%s"
            % (json.dumps(filter_dict["events"]), json.dumps(filter_dict["properties"]))
        )

        with self.assertNumQueries(7):
            with freeze_time("2020-01-04T13:00:01Z"):
                response = self.client.get("/api/dashboard/%s/" % dashboard.pk).json()

        self.assertEqual(
            Dashboard.objects.get().last_accessed_at.isoformat(), "2020-01-04T13:00:01+00:00",
        )
        self.assertEqual(response["items"][0]["result"][0]["count"], 0)

    def test_dashboard(self):
        # create
        self.client.post(
            "/api/dashboard/", data={"name": "Default", "pinned": "true"}, content_type="application/json",
        )

        # retrieve
        response = self.client.get("/api/dashboard/").json()
        pk = Dashboard.objects.all()[0].pk

        self.assertEqual(response["results"][0]["id"], pk)
        self.assertEqual(response["results"][0]["name"], "Default")

        # delete
        self.client.patch(
            "/api/dashboard/{}/".format(pk), data={"deleted": "true"}, content_type="application/json",
        )
        response = self.client.get("/api/dashboard/").json()
        self.assertEqual(len(response["results"]), 0)

    def test_dashboard_items(self):
        dashboard = Dashboard.objects.create(name="Default", pinned=True, team=self.team)
        dashboard_item = self.client.post(
            "/api/dashboard_item/",
            data={"filters": {"hello": "test"}, "dashboard": dashboard.pk, "name": "some_item",},
            content_type="application/json",
        )
        response = self.client.get("/api/dashboard/{}/".format(dashboard.pk)).json()
        self.assertEqual(len(response["items"]), 1)
        self.assertEqual(response["items"][0]["name"], "some_item")

        item_response = self.client.get("/api/dashboard_item/").json()
        self.assertEqual(item_response["results"][0]["name"], "some_item")

        # delete
        self.client.patch(
            "/api/dashboard_item/{}/".format(item_response["results"][0]["id"]),
            data={"deleted": "true"},
            content_type="application/json",
        )
        items_response = self.client.get("/api/dashboard_item/").json()
        self.assertEqual(len(items_response["results"]), 0)

    def test_dashboard_items_history_per_user(self):
        test_user = User.objects.create(email="test@test.com")

        item = DashboardItem.objects.create(filters={"hello": "test"}, team=self.team, created_by=test_user)

        self.client.post(
            "/api/dashboard_item/", data={"filters": {"hello": "test"}}, content_type="application/json",
        ).json()

        response = self.client.get("/api/dashboard_item/?user=true").json()
        self.assertEqual(response["count"], 1)

    def test_dashboard_items_history_saved(self):

        self.client.post(
            "/api/dashboard_item/", data={"filters": {"hello": "test"}, "saved": True}, content_type="application/json",
        ).json()

        self.client.post(
            "/api/dashboard_item/", data={"filters": {"hello": "test"}}, content_type="application/json",
        ).json()

        response = self.client.get("/api/dashboard_item/?user=true&saved=true").json()
        self.assertEqual(response["count"], 1)

    def test_dashboard_item_layout(self):
        dashboard = Dashboard.objects.create(name="asdasd", pinned=True, team=self.team)
        response = self.client.post(
            "/api/dashboard_item/",
            data={"filters": {"hello": "test"}, "dashboard": dashboard.pk, "name": "another",},
            content_type="application/json",
        ).json()

        self.client.patch(
            "/api/dashboard_item/layouts/",
            data={
                "items": [
                    {
                        "id": response["id"],
                        "layouts": {
                            "lg": {"x": "0", "y": "0", "w": "6", "h": "5"},
                            "sm": {"w": "7", "h": "5", "x": "0", "y": "0", "moved": "False", "static": "False",},
                            "xs": {"x": "0", "y": "0", "w": "6", "h": "5"},
                            "xxs": {"x": "0", "y": "0", "w": "2", "h": "5"},
                        },
                    }
                ]
            },
            content_type="application/json",
        )
        items_response = self.client.get("/api/dashboard_item/{}/".format(response["id"])).json()
        self.assertTrue("lg" in items_response["layouts"])
