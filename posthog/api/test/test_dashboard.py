import json

from dateutil import parser
from django.utils import timezone
from django.utils.timezone import now
from freezegun import freeze_time
from rest_framework import status

from posthog.models import Dashboard, DashboardItem, Filter, User
from posthog.models.organization import OrganizationMembership
from posthog.test.base import APIBaseTest
from posthog.utils import generate_cache_key


class TestDashboard(APIBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def test_retrieve_dashboard(self):
        dashboard = Dashboard.objects.create(
            team=self.team, name="private dashboard", created_by=self.user, tags=["deprecated"]
        )
        response = self.client.get(f"/api/dashboard/{dashboard.id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response_data = response.json()
        self.assertEqual(response_data["name"], "private dashboard")
        self.assertEqual(response_data["description"], "")
        self.assertEqual(response_data["tags"], ["deprecated"])
        self.assertEqual(response_data["created_by"]["distinct_id"], self.user.distinct_id)
        self.assertEqual(response_data["created_by"]["first_name"], self.user.first_name)
        self.assertEqual(response_data["creation_mode"], "default")

    def test_create_basic_dashboard(self):
        response = self.client.post("/api/dashboard/", {"name": "My new dashboard"})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        response_data = response.json()
        self.assertEqual(response_data["name"], "My new dashboard")
        self.assertEqual(response_data["description"], "")
        self.assertEqual(response_data["tags"], [])
        self.assertEqual(response_data["creation_mode"], "default")

        instance = Dashboard.objects.get(id=response_data["id"])
        self.assertEqual(instance.name, "My new dashboard")

    def test_update_dashboard(self):
        dashboard = Dashboard.objects.create(
            team=self.team, name="private dashboard", created_by=self.user, creation_mode="template",
        )
        response = self.client.patch(
            f"/api/dashboard/{dashboard.id}",
            {
                "name": "dashboard new name",
                "creation_mode": "duplicate",
                "tags": ["official", "engineering"],
                "description": "Internal system metrics.",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response_data = response.json()
        self.assertEqual(response_data["name"], "dashboard new name")
        self.assertEqual(response_data["created_by"]["distinct_id"], self.user.distinct_id)
        self.assertEqual(response_data["creation_mode"], "template")
        self.assertEqual(response_data["description"], "Internal system metrics.")
        self.assertEqual(response_data["tags"], ["official", "engineering"])

        dashboard.refresh_from_db()
        self.assertEqual(dashboard.name, "dashboard new name")
        self.assertEqual(dashboard.tags, ["official", "engineering"])

    def test_create_dashboard_item(self):
        dashboard = Dashboard.objects.create(team=self.team, share_token="testtoken", name="public dashboard")
        response = self.client.post(
            "/api/dashboard_item/",
            {
                "dashboard": dashboard.pk,
                "name": "dashboard item",
                "last_refresh": now(),  # This happens when you duplicate a dashboard item, caused error
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        dashboard_item = DashboardItem.objects.get()
        self.assertEqual(dashboard_item.name, "dashboard item")
        # Short ID is automatically generated
        self.assertRegex(dashboard_item.short_id, r"[0-9A-Za-z_-]{8}")

    def test_token_auth(self):
        self.client.logout()
        dashboard = Dashboard.objects.create(team=self.team, share_token="testtoken", name="public dashboard")
        test_no_token = self.client.get(f"/api/dashboard/{dashboard.pk}/")
        self.assertEqual(test_no_token.status_code, status.HTTP_403_FORBIDDEN)
        response = self.client.get(f"/api/dashboard/{dashboard.pk}/?share_token=testtoken")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["name"], "public dashboard")

    def test_shared_dashboard(self):
        self.client.logout()
        Dashboard.objects.create(
            team=self.team, share_token="testtoken", name="public dashboard", is_shared=True,
        )
        response = self.client.get("/shared_dashboard/testtoken")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_share_dashboard(self):
        dashboard = Dashboard.objects.create(team=self.team, name="dashboard")
        response = self.client.patch("/api/dashboard/%s/" % dashboard.pk, {"name": "dashboard 2", "is_shared": True},)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
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
        response = self.client.get(
            "/api/insight/trend/?events=%s&properties=%s"
            % (json.dumps(filter_dict["events"]), json.dumps(filter_dict["properties"]))
        )
        self.assertEqual(response.status_code, 200)
        item = DashboardItem.objects.get(pk=item.pk)
        self.assertAlmostEqual(item.last_refresh, now(), delta=timezone.timedelta(seconds=5))
        self.assertEqual(item.filters_hash, generate_cache_key("{}_{}".format(filter.toJSON(), self.team.pk)))

        with self.assertNumQueries(12):
            # Django session, PostHog user, PostHog team, PostHog org membership, PostHog dashboard,
            # PostHog dashboard item, PostHog team, PostHog dashboard item UPDATE, PostHog team,
            # PostHog dashboard item UPDATE, PostHog dashboard UPDATE, PostHog dashboard item
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
            DashboardItem.objects.create(
                dashboard=dashboard, filters=Filter(data=filter_dict).to_dict(), team=self.team, last_refresh=now()
            )

        with freeze_time("2020-01-20T13:00:01Z"):
            response = self.client.get("/api/dashboard/%s/" % dashboard.pk).json()

        self.assertEqual(response["items"][0]["result"], None)
        self.assertEqual(response["items"][0]["last_refresh"], None)

    def test_refresh_cache(self):
        dashboard = Dashboard.objects.create(team=self.team, name="dashboard")

        with freeze_time("2020-01-04T13:00:01Z"):
            # Pretend we cached something a while ago, but we won't have anything in the redis cache
            item_default: DashboardItem = DashboardItem.objects.create(
                dashboard=dashboard,
                filters=Filter(
                    data={"events": [{"id": "$pageview"}], "properties": [{"key": "$browser", "value": "Mac OS X"}],}
                ).to_dict(),
                team=self.team,
                last_refresh=now(),
            )
            item_sessions: DashboardItem = DashboardItem.objects.create(
                dashboard=dashboard,
                filters=Filter(
                    data={
                        "display": "ActionsLineGraph",
                        "events": [{"id": "$pageview", "type": "events", "order": 0, "properties": []}],
                        "filters": [],
                        "insight": "SESSIONS",
                        "interval": "day",
                        "pagination": {},
                        "session": "avg",
                    }
                ).to_dict(),
                team=self.team,
                last_refresh=now(),
            )

        with freeze_time("2020-01-20T13:00:01Z"):
            response = self.client.get("/api/dashboard/%s?refresh=true" % dashboard.pk)

            self.assertEqual(response.status_code, 200)

            response_data = response.json()
            self.assertIsNotNone(response_data["items"][0]["result"])
            self.assertIsNotNone(response_data["items"][0]["last_refresh"])
            self.assertEqual(response_data["items"][0]["result"][0]["count"], 0)

            item_default.refresh_from_db()
            item_sessions.refresh_from_db()

            self.assertEqual(parser.isoparse(response_data["items"][0]["last_refresh"]), item_default.last_refresh)
            self.assertEqual(parser.isoparse(response_data["items"][1]["last_refresh"]), item_sessions.last_refresh)

            self.assertAlmostEqual(item_default.last_refresh, now(), delta=timezone.timedelta(seconds=5))
            self.assertAlmostEqual(item_sessions.last_refresh, now(), delta=timezone.timedelta(seconds=5))

    def test_dashboard_endpoints(self):
        # create
        response = self.client.post("/api/dashboard/", {"name": "Default", "pinned": "true"},)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["name"], "Default")
        self.assertEqual(response.json()["creation_mode"], "default")
        self.assertEqual(response.json()["pinned"], True)

        # retrieve
        response = self.client.get("/api/dashboard/").json()
        pk = Dashboard.objects.first().pk  # type: ignore
        self.assertEqual(response["results"][0]["id"], pk)  # type: ignore
        self.assertEqual(response["results"][0]["name"], "Default")  # type: ignore

        # delete (soft)
        self.client.patch(
            f"/api/dashboard/{pk}/", {"deleted": "true"},
        )
        response = self.client.get("/api/dashboard/").json()
        self.assertEqual(len(response["results"]), 0)

    def test_dashboard_items(self):
        dashboard = Dashboard.objects.create(name="Default", pinned=True, team=self.team, filters={"date_from": "-14d"})
        self.client.post(
            "/api/dashboard_item/",
            {"filters": {"hello": "test", "date_from": "-7d"}, "dashboard": dashboard.pk, "name": "some_item"},
            format="json",
        )
        response = self.client.get("/api/dashboard/{}/".format(dashboard.pk)).json()
        self.assertEqual(len(response["items"]), 1)
        self.assertEqual(response["items"][0]["name"], "some_item")
        self.assertEqual(response["items"][0]["filters"]["date_from"], "-14d")

        item_response = self.client.get("/api/dashboard_item/").json()
        self.assertEqual(item_response["results"][0]["name"], "some_item")

        # delete
        self.client.patch("/api/dashboard_item/{}/".format(item_response["results"][0]["id"]), {"deleted": "true"})
        items_response = self.client.get("/api/dashboard_item/").json()
        self.assertEqual(len(items_response["results"]), 0)

    def test_dashboard_items_history_per_user(self):
        test_user = User.objects.create_and_join(self.organization, "test@test.com", None)

        DashboardItem.objects.create(filters={"hello": "test"}, team=self.team, created_by=test_user)

        # Make sure the endpoint works with and without the trailing slash
        self.client.post("/api/dashboard_item", {"filters": {"hello": "test"}}, format="json").json()

        response = self.client.get("/api/dashboard_item/?user=true").json()
        self.assertEqual(response["count"], 1)

    def test_dashboard_items_history_saved(self):

        self.client.post("/api/dashboard_item/", {"filters": {"hello": "test"}, "saved": True}, format="json").json()

        self.client.post("/api/dashboard_item/", {"filters": {"hello": "test"}}, format="json").json()

        response = self.client.get("/api/dashboard_item/?user=true&saved=true").json()
        self.assertEqual(response["count"], 1)

    def test_dashboard_item_layout(self):
        dashboard = Dashboard.objects.create(name="asdasd", pinned=True, team=self.team)
        response = self.client.post(
            "/api/dashboard_item/",
            {"filters": {"hello": "test"}, "dashboard": dashboard.pk, "name": "another"},
            format="json",
        ).json()

        self.client.patch(
            "/api/dashboard_item/layouts/",
            {
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
            format="json",
        )
        items_response = self.client.get("/api/dashboard_item/{}/".format(response["id"])).json()
        self.assertTrue("lg" in items_response["layouts"])

    def test_dashboard_from_template(self):
        response = self.client.post("/api/dashboard/", {"name": "another", "use_template": "DEFAULT_APP"})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertGreater(DashboardItem.objects.count(), 1)
        self.assertEqual(response.json()["creation_mode"], "template")

    def test_return_cached_results_dashboard_has_filters(self):
        # Regression test, we were
        dashboard = Dashboard.objects.create(team=self.team, name="dashboard")
        filter_dict = {
            "events": [{"id": "$pageview"}],
            "properties": [{"key": "$browser", "value": "Mac OS X"}],
            "date_from": "-7d",
        }
        filter = Filter(data=filter_dict)

        item = DashboardItem.objects.create(dashboard=dashboard, filters=filter_dict, team=self.team,)
        DashboardItem.objects.create(
            dashboard=dashboard, filters=filter.to_dict(), team=self.team,
        )
        self.client.get(
            "/api/insight/trend/?events=%s&properties=%s&date_from=-7d"
            % (json.dumps(filter_dict["events"]), json.dumps(filter_dict["properties"]))
        )
        patch_response = self.client.patch(
            "/api/dashboard/%s/" % dashboard.pk, {"filters": {"date_from": "-24h"}}, format="json",
        ).json()
        self.assertEqual(patch_response["items"][0]["result"], None)

        # cache results
        response = self.client.get(
            "/api/insight/trend/?events=%s&properties=%s&date_from=-24h"
            % (json.dumps(filter_dict["events"]), json.dumps(filter_dict["properties"]))
        )
        self.assertEqual(response.status_code, 200)
        item = DashboardItem.objects.get(pk=item.pk)
        # Expecting this to only have one day as per the dashboard filter
        response = self.client.get("/api/dashboard/%s/" % dashboard.pk).json()
        self.assertEqual(len(response["items"][0]["result"][0]["days"]), 2)  # type: ignore

    def test_invalid_properties(self):
        properties = "invalid_json"

        response = self.client.get(f"/api/insight/trend/?properties={properties}")

        self.assertEqual(response.status_code, 400)
        self.assertDictEqual(
            response.json(), self.validation_error_response("Properties are unparsable!", "invalid_input")
        )
