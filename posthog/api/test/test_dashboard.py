import json
from typing import Any, Dict, List, Literal, Optional, Tuple

from dateutil import parser
from django.db import connection
from django.utils import timezone
from django.utils.timezone import now
from freezegun import freeze_time
from rest_framework import status

from posthog.models import Dashboard, DashboardTile, Filter, Insight, Team, User
from posthog.models.organization import Organization
from posthog.test.base import APIBaseTest, QueryMatchingTest, snapshot_postgres_queries
from posthog.test.db_test_helpers import capture_db_queries
from posthog.utils import generate_cache_key


class TestDashboard(APIBaseTest, QueryMatchingTest):
    CLASS_DATA_LEVEL_SETUP = False

    @snapshot_postgres_queries
    def test_retrieve_dashboard_list(self):
        dashboard_names = ["a dashboard", "b dashboard"]
        for dashboard_name in dashboard_names:
            self.client.post(f"/api/projects/{self.team.id}/dashboards/", {"name": dashboard_name})

        response = self.client.get(f"/api/projects/{self.team.id}/dashboards/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        self.assertEqual([dashboard["name"] for dashboard in response_data["results"]], dashboard_names)

    @snapshot_postgres_queries
    def test_retrieve_dashboard_list_query_count_does_not_increase_with_the_dashboard_count(self):
        self.client.post(f"/api/projects/{self.team.id}/dashboards/", {"name": "a dashboard"})

        # Get the query count when there is only a single dashboard
        start_query_count = len(connection.queries)
        self.client.get(f"/api/projects/{self.team.id}/dashboards/")
        expected_query_count = len(connection.queries) - start_query_count

        self.client.post(f"/api/projects/{self.team.id}/dashboards/", {"name": "b dashboard"})
        self.client.post(f"/api/projects/{self.team.id}/dashboards/", {"name": "c dashboard"})

        # Verify that the query count is the same when there are multiple dashboards
        with self.assertNumQueries(expected_query_count):
            self.client.get(f"/api/projects/{self.team.id}/dashboards/")

    @snapshot_postgres_queries
    def test_retrieve_dashboard(self):
        dashboard = Dashboard.objects.create(team=self.team, name="private dashboard", created_by=self.user)

        response = self.client.get(f"/api/projects/{self.team.id}/dashboards/{dashboard.id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response_data = response.json()
        self.assertEqual(response_data["name"], "private dashboard")
        self.assertEqual(response_data["description"], "")
        self.assertEqual(response_data["created_by"]["distinct_id"], self.user.distinct_id)
        self.assertEqual(response_data["created_by"]["first_name"], self.user.first_name)
        self.assertEqual(response_data["creation_mode"], "default")
        self.assertEqual(response_data["restriction_level"], Dashboard.RestrictionLevel.EVERYONE_IN_PROJECT_CAN_EDIT)
        self.assertEqual(
            response_data["effective_privilege_level"], Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT
        )

    def test_create_basic_dashboard(self):
        response = self.client.post(f"/api/projects/{self.team.id}/dashboards/", {"name": "My new dashboard"})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        response_data = response.json()
        self.assertEqual(response_data["name"], "My new dashboard")
        self.assertEqual(response_data["description"], "")
        self.assertEqual(response_data["tags"], [])
        self.assertEqual(response_data["creation_mode"], "default")
        self.assertEqual(response_data["restriction_level"], Dashboard.RestrictionLevel.EVERYONE_IN_PROJECT_CAN_EDIT)
        self.assertEqual(
            response_data["effective_privilege_level"], Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT
        )

        instance = Dashboard.objects.get(id=response_data["id"])
        self.assertEqual(instance.name, "My new dashboard")

    def test_update_dashboard(self):
        dashboard = Dashboard.objects.create(
            team=self.team, name="private dashboard", created_by=self.user, creation_mode="template",
        )
        response = self.client.patch(
            f"/api/projects/{self.team.id}/dashboards/{dashboard.id}",
            {"name": "dashboard new name", "creation_mode": "duplicate", "description": "Internal system metrics.",},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response_data = response.json()
        self.assertEqual(response_data["name"], "dashboard new name")
        self.assertEqual(response_data["created_by"]["distinct_id"], self.user.distinct_id)
        self.assertEqual(response_data["creation_mode"], "template")
        self.assertEqual(response_data["description"], "Internal system metrics.")
        self.assertEqual(response_data["restriction_level"], Dashboard.RestrictionLevel.EVERYONE_IN_PROJECT_CAN_EDIT)
        self.assertEqual(
            response_data["effective_privilege_level"], Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT
        )

        dashboard.refresh_from_db()
        self.assertEqual(dashboard.name, "dashboard new name")

    def test_create_dashboard_item(self):
        dashboard = Dashboard.objects.create(team=self.team, share_token="testtoken", name="public dashboard")
        self._create_insight(
            {
                "dashboards": [dashboard.pk],
                "name": "dashboard item",
                "last_refresh": now(),  # This happens when you duplicate a dashboard item, caused error,
            }
        )

        dashboard_item = Insight.objects.get()
        self.assertEqual(dashboard_item.name, "dashboard item")
        self.assertEqual(list(dashboard_item.dashboards.all()), [dashboard])
        # Short ID is automatically generated
        self.assertRegex(dashboard_item.short_id, r"[0-9A-Za-z_-]{8}")

    def test_share_token_lookup_is_shared_true(self):
        _, other_team, _ = User.objects.bootstrap("X", "y@x.com", None)
        dashboard = Dashboard.objects.create(
            team=other_team, share_token="testtoken", name="public dashboard", is_shared=True
        )
        # Project-based endpoint while logged in, but not belonging to the same org
        response = self.client.get(f"/api/projects/{self.team.id}/dashboards/{dashboard.pk}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        # Project-based endpoint while logged out
        self.client.logout()
        response = self.client.get(f"/api/projects/{self.team.id}/dashboards/{dashboard.pk}/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        # Shared dashboards endpoint while logged out
        response = self.client.get(f"/api/shared_dashboards/testtoken")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["name"], "public dashboard")

    def test_share_token_lookup_is_shared_false(self):
        _, other_team, _ = User.objects.bootstrap("X", "y@x.com", None)
        Dashboard.objects.create(team=other_team, share_token="testtoken", name="public dashboard", is_shared=False)
        # Shared dashboards endpoint while logged out (dashboards should be unavailable as it's not shared)
        response = self.client.get(f"/api/shared_dashboards/testtoken")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_shared_dashboard(self):
        self.client.logout()
        Dashboard.objects.create(
            team=self.team, share_token="testtoken", name="public dashboard", is_shared=True,
        )
        response = self.client.get("/shared_dashboard/testtoken")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_share_dashboard(self):
        dashboard = Dashboard.objects.create(team=self.team, name="dashboard")
        response = self.client.patch(
            f"/api/projects/{self.team.id}/dashboards/%s/" % dashboard.pk, {"name": "dashboard 2", "is_shared": True},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        dashboard = Dashboard.objects.get(pk=dashboard.pk)
        self.assertIsNotNone(dashboard.share_token)

    def test_return_cached_results_bleh(self):
        dashboard = Dashboard.objects.create(team=self.team, name="dashboard")
        filter_dict = {
            "events": [{"id": "$pageview"}],
            "properties": [{"key": "$browser", "value": "Mac OS X"}],
        }
        filter = Filter(data=filter_dict)

        item = Insight.objects.create(filters=filter_dict, team=self.team,)
        DashboardTile.objects.create(dashboard=dashboard, insight=item)
        item2 = Insight.objects.create(filters=filter.to_dict(), team=self.team,)
        DashboardTile.objects.create(dashboard=dashboard, insight=item2)
        response = self.client.get(f"/api/projects/{self.team.id}/dashboards/%s/" % dashboard.pk).json()
        self.assertEqual(response["items"][0]["result"], None)

        # cache results
        response = self.client.get(
            f"/api/projects/{self.team.id}/insights/trend/?events=%s&properties=%s"
            % (json.dumps(filter_dict["events"]), json.dumps(filter_dict["properties"]))
        )
        self.assertEqual(response.status_code, 200)
        item = Insight.objects.get(pk=item.pk)
        self.assertAlmostEqual(item.last_refresh, now(), delta=timezone.timedelta(seconds=5))
        self.assertEqual(item.filters_hash, generate_cache_key(f"{filter.toJSON()}_{self.team.pk}"))

        response = self.client.get(f"/api/projects/{self.team.id}/dashboards/%s/" % dashboard.pk).json()

        self.assertAlmostEqual(Dashboard.objects.get().last_accessed_at, now(), delta=timezone.timedelta(seconds=5))
        self.assertEqual(response["items"][0]["result"][0]["count"], 0)

    def _get_dashboard_counting_queries(self, dashboard_id: int) -> Tuple[int, List[Dict[str, str]]]:
        with capture_db_queries() as capture_query_context:
            response = self.client.get(f"/api/projects/{self.team.id}/dashboards/{dashboard_id}/")
            self.assertEqual(response.status_code, status.HTTP_200_OK)

            query_count = len(capture_query_context.captured_queries)
            return query_count, capture_query_context.captured_queries

    @snapshot_postgres_queries
    def test_adding_insights_is_not_nplus1_for_gets(self):
        dashboard_id, _ = self._create_dashboard({"name": "dashboard"})
        dashboard_two_id, _ = self._create_dashboard({"name": "dashboard two"})
        filter_dict = {
            "events": [{"id": "$pageview"}],
            "properties": [{"key": "$browser", "value": "Mac OS X"}],
            "insight": "TRENDS",
        }

        query_counts: List[int] = []
        queries: List[List[Dict[str, str]]] = []

        count, qs = self._get_dashboard_counting_queries(dashboard_id)
        query_counts.append(count)
        queries.append(qs)

        # add insights to the dashboard and count how many queries to read the dashboard afterwards
        for i in range(5):
            self._create_insight({"filters": filter_dict, "dashboards": [dashboard_id]})
            count, qs = self._get_dashboard_counting_queries(dashboard_id)
            query_counts.append(count)
            queries.append(qs)

        # fewer queries when loading dashboard with no insights
        self.assertLess(query_counts[0], query_counts[1])
        # then only climbs by two queries for each additional insight
        self.assertTrue(
            all(j - i == 2 for i, j in zip(query_counts[2:], query_counts[3:])),
            f"received: {query_counts} for queries: \n\n {queries}",
        )

    def test_no_cache_available(self):
        dashboard = Dashboard.objects.create(team=self.team, name="dashboard")
        filter_dict = {
            "events": [{"id": "$pageview"}],
            "properties": [{"key": "$browser", "value": "Mac OS X"}],
        }

        with freeze_time("2020-01-04T13:00:01Z"):
            # Pretend we cached something a while ago, but we won't have anything in the redis cache
            insight = Insight.objects.create(
                filters=Filter(data=filter_dict).to_dict(), team=self.team, last_refresh=now()
            )
            DashboardTile.objects.create(dashboard=dashboard, insight=insight)

        with freeze_time("2020-01-20T13:00:01Z"):
            response = self.client.get(f"/api/projects/{self.team.id}/dashboards/%s/" % dashboard.pk).json()

        self.assertEqual(response["items"][0]["result"], None)
        self.assertEqual(response["items"][0]["last_refresh"], None)

    def test_refresh_cache(self):
        dashboard = Dashboard.objects.create(team=self.team, name="dashboard")

        with freeze_time("2020-01-04T13:00:01Z"):
            # Pretend we cached something a while ago, but we won't have anything in the redis cache
            item_default: Insight = Insight.objects.create(
                filters=Filter(
                    data={"events": [{"id": "$pageview"}], "properties": [{"key": "$browser", "value": "Mac OS X"}],}
                ).to_dict(),
                team=self.team,
                last_refresh=now(),
                order=0,
            )
            DashboardTile.objects.create(dashboard=dashboard, insight=item_default)
            item_trends: Insight = Insight.objects.create(
                filters=Filter(
                    data={
                        "display": "ActionsLineGraph",
                        "events": [{"id": "$pageview", "type": "events", "order": 0, "properties": []}],
                        "filters": [],
                        "interval": "day",
                        "pagination": {},
                        "session": "avg",
                    }
                ).to_dict(),
                team=self.team,
                last_refresh=now(),
                order=1,
            )
        DashboardTile.objects.create(dashboard=dashboard, insight=item_trends)

        with freeze_time("2020-01-20T13:00:01Z"):
            response = self.client.get(f"/api/projects/{self.team.id}/dashboards/%s?refresh=true" % dashboard.pk)

            self.assertEqual(response.status_code, 200)

            response_data = response.json()
            self.assertIsNotNone(response_data["items"][0]["result"])
            self.assertIsNotNone(response_data["items"][0]["last_refresh"])
            self.assertEqual(response_data["items"][0]["result"][0]["count"], 0)

            item_default.refresh_from_db()
            item_trends.refresh_from_db()

            self.assertEqual(parser.isoparse(response_data["items"][0]["last_refresh"]), item_default.last_refresh)
            self.assertEqual(parser.isoparse(response_data["items"][1]["last_refresh"]), item_trends.last_refresh)

            self.assertAlmostEqual(item_default.last_refresh, now(), delta=timezone.timedelta(seconds=5))
            self.assertAlmostEqual(item_trends.last_refresh, now(), delta=timezone.timedelta(seconds=5))

    def test_dashboard_endpoints(self):
        # create
        response = self.client.post(f"/api/projects/{self.team.id}/dashboards/", {"name": "Default", "pinned": "true"},)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["name"], "Default")
        self.assertEqual(response.json()["creation_mode"], "default")
        self.assertEqual(response.json()["pinned"], True)

        # retrieve
        response = self.client.get(f"/api/projects/{self.team.id}/dashboards/").json()
        pk = Dashboard.objects.first().pk  # type: ignore
        self.assertEqual(response["results"][0]["id"], pk)  # type: ignore
        self.assertEqual(response["results"][0]["name"], "Default")  # type: ignore

        # soft-delete
        self.client.patch(
            f"/api/projects/{self.team.id}/dashboards/{pk}/", {"deleted": True},
        )
        response = self.client.get(f"/api/projects/{self.team.id}/dashboards/").json()
        self.assertEqual(len(response["results"]), 0)

        # restore after soft-deletion
        self.client.patch(
            f"/api/projects/{self.team.id}/dashboards/{pk}/", {"deleted": False},
        )
        response = self.client.get(f"/api/projects/{self.team.id}/dashboards/").json()
        self.assertEqual(len(response["results"]), 1)

    def test_dashboard_items(self):
        dashboard_id, _ = self._create_dashboard({"filters": {"date_from": "-14d"}})
        insight_id, _ = self._create_insight(
            {"filters": {"hello": "test", "date_from": "-7d"}, "dashboards": [dashboard_id], "name": "some_item"}
        )

        response = self.client.get(f"/api/projects/{self.team.id}/dashboards/{dashboard_id}/").json()
        self.assertEqual(len(response["items"]), 1)
        self.assertEqual(response["items"][0]["name"], "some_item")
        self.assertEqual(response["items"][0]["filters"]["date_from"], "-14d")

        item_response = self.client.get(f"/api/projects/{self.team.id}/insights/").json()
        self.assertEqual(item_response["results"][0]["name"], "some_item")

        # delete
        self.client.patch(
            f"/api/projects/{self.team.id}/insights/{item_response['results'][0]['id']}/", {"deleted": "true"}
        )
        items_response = self.client.get(f"/api/projects/{self.team.id}/insights/").json()
        self.assertEqual(len(items_response["results"]), 0)

    def test_dashboard_filtering_on_properties(self):
        dashboard_id, _ = self._create_dashboard({"filters": {"date_from": "-24h"}})
        response = self.client.patch(
            f"/api/projects/{self.team.id}/dashboards/{dashboard_id}/",
            data={"filters": {"date_from": "-24h", "properties": [{"key": "prop", "value": "val"}]}},
        ).json()

        self.assertEqual(response["filters"]["properties"], [{"key": "prop", "value": "val"}])

        insight_id, _ = self._create_insight(
            {"filters": {"hello": "test", "date_from": "-7d"}, "dashboards": [dashboard_id], "name": "some_item"}
        )

        response = self.client.get(f"/api/projects/{self.team.id}/dashboards/{dashboard_id}/").json()
        self.assertEqual(len(response["items"]), 1)
        self.assertEqual(response["items"][0]["name"], "some_item")
        self.assertEqual(response["items"][0]["filters"]["properties"], [{"key": "prop", "value": "val"}])

    def test_dashboard_filter_is_applied_even_if_insight_is_created_before_dashboard(self):
        insight_id, _ = self._create_insight({"filters": {"hello": "test", "date_from": "-7d"}, "name": "some_item"})

        dashboard_id, _ = self._create_dashboard({"filters": {"date_from": "-14d"}})

        # add the insight to the dashboard
        self.client.patch(f"/api/projects/{self.team.id}/insights/{insight_id}", {"dashboards": [dashboard_id]})

        response = self.client.get(f"/api/projects/{self.team.id}/dashboards/{dashboard_id}/").json()
        self.assertEqual(response["items"][0]["filters"]["date_from"], "-14d")

        # which doesn't change the insight's filter
        response = self.client.get(f"/api/projects/{self.team.id}/insights/{insight_id}/").json()
        self.assertEqual(response["filters"]["date_from"], "-7d")

    def test_dashboard_items_history_per_user(self):
        test_user = User.objects.create_and_join(self.organization, "test@test.com", None)

        Insight.objects.create(filters={"hello": "test"}, team=self.team, created_by=test_user)

        # Make sure the endpoint works with and without the trailing slash
        self.client.post(f"/api/projects/{self.team.id}/insights", {"filters": {"hello": "test"}}, format="json").json()

        response = self.client.get(f"/api/projects/{self.team.id}/insights/?user=true").json()
        self.assertEqual(response["count"], 1)

    def test_dashboard_items_history_saved(self):

        self.client.post(
            f"/api/projects/{self.team.id}/insights/", {"filters": {"hello": "test"}, "saved": True}, format="json"
        ).json()

        self.client.post(
            f"/api/projects/{self.team.id}/insights/", {"filters": {"hello": "test"}}, format="json"
        ).json()

        response = self.client.get(f"/api/projects/{self.team.id}/insights/?user=true&saved=true").json()
        self.assertEqual(response["count"], 1)

    def test_dashboard_item_layout(self):
        dashboard_id, _ = self._create_dashboard({"name": "asdasd", "pinned": True})

        insight_id, _ = self._create_insight(
            {"filters": {"hello": "test"}, "dashboards": [dashboard_id], "name": "another"},
        )

        # layouts used to live on insights, but moved onto the relation from a dashboard to its insights
        response = self.client.patch(
            f"/api/projects/{self.team.id}/dashboards/{dashboard_id}",
            {
                "tile_layouts": [
                    {
                        "id": insight_id,
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
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        dashboard_json = self.client.get(
            f"/api/projects/{self.team.id}/dashboards/{dashboard_id}/", {"refresh": False}
        ).json()
        first_tile_layouts = dashboard_json["items"][0]["layouts"]
        self.assertTrue("lg" in first_tile_layouts)

    def test_dashboard_from_template(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/dashboards/", {"name": "another", "use_template": "DEFAULT_APP"}
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertGreater(Insight.objects.count(), 1)
        self.assertEqual(response.json()["creation_mode"], "template")

    def test_dashboard_creation_validation(self):
        existing_dashboard = Dashboard.objects.create(team=self.team, name="existing dashboard", created_by=self.user)

        # invalid - both use_template and use_dashboard are set
        response = self.client.post(
            f"/api/projects/{self.team.id}/dashboards",
            {"name": "another", "use_template": "DEFAULT_APP", "use_dashboard": 1,},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        # invalid - use_template is set and use_dashboard empty string
        response = self.client.post(
            f"/api/projects/{self.team.id}/dashboards",
            {"name": "another", "use_template": "DEFAULT_APP", "use_dashboard": "",},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        # valid - use_template empty and use_dashboard is not set
        response = self.client.post(
            f"/api/projects/{self.team.id}/dashboards", {"name": "another", "use_template": "",},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # valid - only use_template is set
        response = self.client.post(
            f"/api/projects/{self.team.id}/dashboards", {"name": "another", "use_template": "DEFAULT_APP",},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # valid - only use_dashboard is set
        response = self.client.post(
            f"/api/projects/{self.team.id}/dashboards", {"name": "another", "use_dashboard": existing_dashboard.id,},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # valid - use_dashboard is set and use_template empty string
        response = self.client.post(
            f"/api/projects/{self.team.id}/dashboards",
            {"name": "another", "use_template": "", "use_dashboard": existing_dashboard.id,},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # valid - both use_template and use_dashboard are not set
        response = self.client.post(f"/api/projects/{self.team.id}/dashboards", {"name": "another",},)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_dashboard_creation_mode(self):
        # template
        response = self.client.post(
            f"/api/projects/{self.team.id}/dashboards/", {"name": "another", "use_template": "DEFAULT_APP"}
        )
        self.assertEqual(response.json()["creation_mode"], "template")

        # duplicate
        existing_dashboard = Dashboard.objects.create(team=self.team, name="existing dashboard", created_by=self.user)
        response = self.client.post(
            f"/api/projects/{self.team.id}/dashboards/", {"name": "another", "use_dashboard": existing_dashboard.id}
        )
        self.assertEqual(response.json()["creation_mode"], "duplicate")

        # default
        response = self.client.post(f"/api/projects/{self.team.id}/dashboards/", {"name": "another"})
        self.assertEqual(response.json()["creation_mode"], "default")

    def test_dashboard_duplication(self):
        existing_dashboard = Dashboard.objects.create(team=self.team, name="existing dashboard", created_by=self.user)
        insight1 = Insight.objects.create(filters={"name": "test1"}, team=self.team, last_refresh=now(),)
        DashboardTile.objects.create(dashboard=existing_dashboard, insight=insight1)
        insight2 = Insight.objects.create(filters={"name": "test2"}, team=self.team, last_refresh=now(),)
        DashboardTile.objects.create(dashboard=existing_dashboard, insight=insight2)
        response = self.client.post(
            f"/api/projects/{self.team.id}/dashboards/", {"name": "another", "use_dashboard": existing_dashboard.id}
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["creation_mode"], "duplicate")

        self.assertEqual(len(response.json()["items"]), len(existing_dashboard.insights.all()))

        existing_dashboard_item_id_set = set(map(lambda x: x.id, existing_dashboard.insights.all()))
        response_item_id_set = set(map(lambda x: x.get("id", None), response.json()["items"]))
        # check both sets are disjoint to verify that the new items' ids are different than the existing items
        self.assertTrue(existing_dashboard_item_id_set.isdisjoint(response_item_id_set))

        for item in response.json()["items"]:
            self.assertNotEqual(item.get("dashboard", None), existing_dashboard.pk)

    def test_invalid_dashboard_duplication(self):
        # pass a random number (non-existent dashboard id) as use_dashboard
        response = self.client.post(
            f"/api/projects/{self.team.id}/dashboards/", {"name": "another", "use_dashboard": 12345}
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_duplication_fail_for_different_team(self):
        another_team = Team.objects.create(organization=self.organization)
        another_team_dashboard = Dashboard.objects.create(team=another_team, name="Another Team's Dashboard")
        response = self.client.post(
            f"/api/projects/{self.team.id}/dashboards/",
            {"name": "another", "use_dashboard": another_team_dashboard.id,},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_return_cached_results_dashboard_has_filters(self):
        # Regression test, we were

        # create a dashboard with no filters
        dashboard: Dashboard = Dashboard.objects.create(team=self.team, name="dashboard")

        filter_dict = {
            "events": [{"id": "$pageview"}],
            "properties": [{"key": "$browser", "value": "Mac OS X"}],
            "date_from": "-7d",
        }

        # create two insights with a -7d date from filter
        insight_one_id, _ = self._create_insight({"filters": filter_dict, "dashboards": [dashboard.pk]})
        insight_two_id, _ = self._create_insight({"filters": filter_dict, "dashboards": [dashboard.pk]})

        insight_one_original_filter_hash = self._get_insight(insight_one_id)["filters_hash"]
        insight_two_original_filter_hash = self._get_insight(insight_two_id)["filters_hash"]

        self.assertEqual(insight_one_original_filter_hash, insight_two_original_filter_hash)

        # cache insight results for trends with a -7d date from
        response = self.client.get(
            f"/api/projects/{self.team.id}/insights/trend/?events=%s&properties=%s&date_from=-7d"
            % (json.dumps(filter_dict["events"]), json.dumps(filter_dict["properties"]))
        )
        self.assertEqual(response.status_code, 200)

        # set a filter on the dashboard
        patch_response = self.client.patch(
            f"/api/projects/{self.team.id}/dashboards/%s/" % dashboard.pk,
            {"filters": {"date_from": "-24h"}},
            format="json",
        )
        self.assertEqual(patch_response.status_code, status.HTTP_200_OK)
        patch_response_json = patch_response.json()
        self.assertEqual(patch_response_json["items"][0]["result"], None)
        dashboard.refresh_from_db()
        self.assertEqual(dashboard.filters, {"date_from": "-24h"})

        # doesn't change the filters hash on the Insight itself
        self.assertEqual(insight_one_original_filter_hash, Insight.objects.get(pk=insight_one_id).filters_hash)
        self.assertEqual(insight_two_original_filter_hash, Insight.objects.get(pk=insight_two_id).filters_hash)

        # the updated filters_hashes are from the dashboard tiles
        tile_one = DashboardTile.objects.filter(insight__id=insight_one_id).first()
        if tile_one is None:
            breakpoint()
        self.assertEqual(
            patch_response_json["items"][0]["filters_hash"],
            tile_one.filters_hash
            if tile_one is not None
            else f"should have been able to load a single tile for {insight_one_id}",
        )
        tile_two = DashboardTile.objects.filter(insight__id=insight_two_id).first()
        self.assertEqual(
            patch_response_json["items"][1]["filters_hash"],
            tile_two.filters_hash
            if tile_two is not None
            else f"should have been able to load a single tile for {insight_two_id}",
        )

        # cache results
        response = self.client.get(
            f"/api/projects/{self.team.id}/insights/trend/?events=%s&properties=%s&date_from=-24h"
            % (json.dumps(filter_dict["events"]), json.dumps(filter_dict["properties"]))
        )
        self.assertEqual(response.status_code, 200)

        # Expecting this to only have one day as per the dashboard filter
        response = self.client.get(f"/api/projects/{self.team.id}/dashboards/%s/" % dashboard.pk).json()
        self.assertEqual(len(response["items"][0]["result"][0]["days"]), 2)  # type: ignore

    def test_invalid_properties(self):
        properties = "invalid_json"

        response = self.client.get(f"/api/projects/{self.team.id}/insights/trend/?properties={properties}")

        self.assertEqual(response.status_code, 400, response.content)
        self.assertDictEqual(
            response.json(),
            self.validation_error_response("Properties are unparsable!", "invalid_input"),
            response.content,
        )

    def test_insights_with_no_insight_set(self):
        # We were saving some insights on the default dashboard with no insight
        dashboard = Dashboard.objects.create(team=self.team, name="Dashboard", created_by=self.user)
        item = Insight.objects.create(filters={"events": [{"id": "$pageview"}]}, team=self.team, last_refresh=now(),)
        DashboardTile.objects.create(insight=item, dashboard=dashboard)
        response = self.client.get(f"/api/projects/{self.team.id}/dashboards/{dashboard.pk}").json()
        self.assertEqual(response["items"][0]["filters"], {"events": [{"id": "$pageview"}], "insight": "TRENDS"})

    def test_retrieve_dashboard_different_team(self):
        team2 = Team.objects.create(organization=Organization.objects.create(name="a"))
        dashboard = Dashboard.objects.create(team=team2, name="dashboard", created_by=self.user)
        response = self.client.get(f"/api/projects/{team2.id}/dashboards/{dashboard.id}")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN, response.content)

    def test_patch_api_as_form_data(self):
        dashboard = Dashboard.objects.create(team=self.team, name="dashboard", created_by=self.user)
        response = self.client.patch(
            f"/api/projects/{self.team.id}/dashboards/{dashboard.pk}/",
            data="name=replaced",
            content_type="application/x-www-form-urlencoded",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["name"], "replaced")

    def test_can_soft_delete_insight_after_soft_deleting_dashboard(self) -> None:
        filter_dict = {
            "events": [{"id": "$pageview"}],
            "properties": [{"key": "$browser", "value": "Mac OS X"}],
            "insight": "TRENDS",
        }

        dashboard_id, _ = self._create_dashboard({"name": "dashboard"})
        insight_id, _ = self._create_insight({"filters": filter_dict, "dashboards": [dashboard_id]})

        self._soft_delete(dashboard_id, "dashboards")

        insight_json = self._get_insight(insight_id=insight_id)
        self.assertEqual(insight_json["dashboards"], [])

        self._soft_delete(insight_id, "insights")

    def test_can_soft_delete_dashboard_after_soft_deleting_insight(self) -> None:
        filter_dict = {
            "events": [{"id": "$pageview"}],
            "properties": [{"key": "$browser", "value": "Mac OS X"}],
            "insight": "TRENDS",
        }

        dashboard_id, _ = self._create_dashboard({"name": "dashboard"})
        insight_id, _ = self._create_insight({"filters": filter_dict, "dashboards": [dashboard_id]})

        self._soft_delete(insight_id, "insights")

        self._get_insight(insight_id=insight_id, expected_status=status.HTTP_404_NOT_FOUND)

        dashboard_json = self.client.get(f"/api/projects/{self.team.id}/dashboards/{dashboard_id}").json()
        self.assertEqual(len(dashboard_json["items"]), 0)

        self._soft_delete(dashboard_id, "dashboards")

    def test_hard_delete_is_forbidden(self) -> None:
        dashboard_id, _ = self._create_dashboard({"name": "dashboard"})
        api_response = self.client.delete(f"/api/projects/{self.team.id}/dashboards/{dashboard_id}")
        self.assertEqual(api_response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        self.assertEqual(
            self.client.get(f"/api/projects/{self.team.id}/dashboards/{dashboard_id}").status_code, status.HTTP_200_OK,
        )

    def test_soft_delete_can_be_reversed_with_patch(self) -> None:
        dashboard_id, _ = self._create_dashboard({"name": "dashboard"})

        self._soft_delete(dashboard_id, "dashboards")

        update_response = self.client.patch(
            f"/api/projects/{self.team.id}/dashboards/{dashboard_id}", {"deleted": False}
        )
        self.assertEqual(update_response.status_code, status.HTTP_200_OK)

        self.assertEqual(
            self.client.get(f"/api/projects/{self.team.id}/dashboards/{dashboard_id}").status_code, status.HTTP_200_OK
        )

    def _soft_delete(
        self,
        model_id: int,
        model_type: Literal["insights", "dashboards"],
        expected_get_status: int = status.HTTP_404_NOT_FOUND,
    ) -> None:
        api_response = self.client.patch(f"/api/projects/{self.team.id}/{model_type}/{model_id}", {"deleted": True})
        self.assertEqual(api_response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            self.client.get(f"/api/projects/{self.team.id}/{model_type}/{model_id}").status_code, expected_get_status,
        )

    def _create_dashboard(self, data: Dict[str, Any], team_id: Optional[int] = None) -> Tuple[int, Dict[str, Any]]:
        if team_id is None:
            team_id = self.team.id
        response = self.client.post(f"/api/projects/{team_id}/dashboards/", data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        response_json = response.json()
        return response_json["id"], response_json

    def _get_insight(
        self, insight_id: int, team_id: Optional[int] = None, expected_status: int = status.HTTP_200_OK
    ) -> Dict[str, Any]:
        if team_id is None:
            team_id = self.team.id

        response = self.client.get(f"/api/projects/{team_id}/insights/{insight_id}")
        self.assertEqual(response.status_code, expected_status)

        response_json = response.json()
        return response_json

    def _create_insight(
        self, data: Dict[str, Any], team_id: Optional[int] = None, expected_status: int = status.HTTP_201_CREATED
    ) -> Tuple[int, Dict[str, Any]]:
        if team_id is None:
            team_id = self.team.id

        if "filters" not in data:
            data["filters"] = {"events": [{"id": "$pageview"}]}

        response = self.client.post(f"/api/projects/{team_id}/insights", data=data,)
        self.assertEqual(response.status_code, expected_status)

        response_json = response.json()
        return response_json.get("id", None), response_json
