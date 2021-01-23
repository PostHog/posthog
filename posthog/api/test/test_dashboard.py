import json

from django.utils import timezone
from django.utils.timezone import now
from freezegun import freeze_time

from posthog.models import Dashboard, DashboardItem, Filter, User
from posthog.test.base import TransactionBaseTest
from posthog.utils import generate_cache_key


class TestDashboard(TransactionBaseTest):
    TESTS_API = True

    def test_get_dashboard(self):
        dashboard = Dashboard.objects.create(team=self.team, name="private dashboard", created_by=self.user)
        response = self.client.get(f"/api/dashboard/{dashboard.id}", content_type="application/json",)
        self.assertEqual(response.json()["name"], "private dashboard")
        self.assertEqual(response.json()["created_by"]["distinct_id"], self.user.distinct_id)
        self.assertEqual(response.json()["created_by"]["first_name"], self.user.first_name)

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
        test_no_token = self.client.get(f"/api/dashboard/{dashboard.pk}/")
        self.assertEqual(test_no_token.status_code, 403)
        response = self.client.get(f"/api/dashboard/{dashboard.pk}/?share_token=testtoken")
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

    def test_return_cached_results(self):
        dashboard = Dashboard.objects.create(team=self.team, name="dashboard")
        filter_dict = {
            "events": [{"id": "$pageview"}],
            "properties": [{"key": "$browser", "value": "Mac OS X"}],
        }
        filter = Filter(data=filter_dict)

        item = DashboardItem.objects.create(dashboard=dashboard, filters=filter_dict, team=self.team,)
        DashboardItem.objects.create(
            dashboard=dashboard, filters=filter.to_dict(), team=self.team,
        )
        response = self.client.get("/api/dashboard/%s/" % dashboard.pk).json()
        self.assertEqual(response["items"][0]["result"], None)

        # cache results
        self.client.get(
            "/api/action/trends/?events=%s&properties=%s"
            % (json.dumps(filter_dict["events"]), json.dumps(filter_dict["properties"]))
        )
        item = DashboardItem.objects.get(pk=item.pk)
        self.assertAlmostEqual(item.last_refresh, now(), delta=timezone.timedelta(seconds=5))
        self.assertEqual(item.filters_hash, generate_cache_key("{}_{}".format(filter.toJSON(), self.team.pk)))

        with self.assertNumQueries(8):
            response = self.client.get("/api/dashboard/%s/" % dashboard.pk).json()

        self.assertAlmostEqual(Dashboard.objects.get().last_accessed_at, now(), delta=timezone.timedelta(seconds=5))
        self.assertEqual(response["items"][0]["result"][0]["count"], 0)

    def test_no_cache_available(self):
        dashboard = Dashboard.objects.create(team=self.team, name="dashboard")
        filter_dict = {
            "events": [{"id": "$pageview"}],
            "properties": [{"key": "$browser", "value": "Mac OS X"}],
        }

        with freeze_time("2020-01-04T13:00:01Z"):
            # Pretend we cached something a while ago, but we won't have anything in the redis cache
            item = DashboardItem.objects.create(
                dashboard=dashboard, filters=Filter(data=filter_dict).to_dict(), team=self.team, last_refresh=now()
            )

        with freeze_time("2020-01-20T13:00:01Z"):
            response = self.client.get("/api/dashboard/%s/" % dashboard.pk).json()

        self.assertEqual(response["items"][0]["result"], None)
        self.assertEqual(response["items"][0]["last_refresh"], None)

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
        test_user = User.objects.create_and_join(self.organization, "test@test.com", None)

        item = DashboardItem.objects.create(filters={"hello": "test"}, team=self.team, created_by=test_user)

        # Make sure the endpoint works with and without the trailing slash
        self.client.post(
            "/api/dashboard_item", data={"filters": {"hello": "test"}}, content_type="application/json",
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

    def test_dashboard_from_template(self):
        response = self.client.post(
            "/api/dashboard/", data={"name": "another", "use_template": "DEFAULT_APP"}, content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertGreater(DashboardItem.objects.count(), 1)
