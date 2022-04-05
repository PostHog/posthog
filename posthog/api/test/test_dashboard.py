import json
from typing import List
from unittest import skip

from dateutil import parser
from django.db import DEFAULT_DB_ALIAS, connection, connections
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from django.utils.timezone import now
from freezegun import freeze_time
from rest_framework import status

from posthog.models import Dashboard, Filter, Insight, Team, User
from posthog.models.dashboard import DashboardInsight
from posthog.models.organization import Organization
from posthog.test.base import APIBaseTest, QueryMatchingTest, snapshot_postgres_queries
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
        response = self.client.post(
            f"/api/projects/{self.team.id}/insights/",
            {
                "dashboard": dashboard.pk,
                "name": "dashboard item",
                "last_refresh": now(),  # This happens when you duplicate a dashboard item, caused error
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        dashboard_item = Insight.objects.get()
        self.assertEqual(dashboard_item.name, "dashboard item")
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

    @skip("dashboard load is n+1 despite prefetches")
    def test_adding_insights_is_not_nplus1_for_gets(self):
        dashboard = Dashboard.objects.create(team=self.team, name="dashboard")
        filter_dict = {
            "events": [{"id": "$pageview"}],
            "properties": [{"key": "$browser", "value": "Mac OS X"}],
        }
        filter = Filter(data=filter_dict)

        query_counts: List[int] = []

        query_counts.append(self._get_dashboard_counting_queries(dashboard))

        # add insights to the dashboard and count how manh queries to read the dashboard afterwards
        Insight.objects.create(
            dashboard=dashboard, filters=filter_dict, team=self.team,
        )
        query_counts.append(self._get_dashboard_counting_queries(dashboard))

        Insight.objects.create(
            dashboard=dashboard, filters=filter.to_dict(), team=self.team,
        )
        query_counts.append(self._get_dashboard_counting_queries(dashboard))

        Insight.objects.create(
            dashboard=dashboard, filters=filter.to_dict(), team=self.team,
        )
        query_counts.append(self._get_dashboard_counting_queries(dashboard))

        Insight.objects.create(
            dashboard=dashboard, filters=filter.to_dict(), team=self.team,
        )
        query_counts.append(self._get_dashboard_counting_queries(dashboard))

        # query count is the expected value
        self.assertEqual(query_counts[0], 11)
        # adding more insights _does_ change the query count
        # with or without these changes each additional insight adds about 4 queries
        self.assertTrue(all(x == query_counts[0] for x in query_counts))

    def _get_dashboard_counting_queries(self, dashboard: Dashboard) -> int:
        db_connection = connections[DEFAULT_DB_ALIAS]

        with CaptureQueriesContext(db_connection) as capture_query_context:
            response = self.client.get(f"/api/projects/{self.team.id}/dashboards/%s/" % dashboard.pk)
            self.assertEqual(response.status_code, status.HTTP_200_OK)

            query_count = len(capture_query_context.captured_queries)
            if isinstance(query_count, int):
                return query_count
            else:
                self.fail(f"'{query_count}' should have been an int")

    def test_return_cached_results(self):
        dashboard = Dashboard.objects.create(team=self.team, name="dashboard")
        filter_dict = {
            "events": [{"id": "$pageview"}],
            "properties": [{"key": "$browser", "value": "Mac OS X"}],
        }
        filter = Filter(data=filter_dict)

        # create two insights on the dashboard
        first_insight = Insight.objects.create(dashboard=dashboard, filters=filter_dict, team=self.team,)
        second_insight = Insight.objects.create(dashboard=dashboard, filters=filter.to_dict(), team=self.team,)
        response = self.client.get(f"/api/projects/{self.team.id}/dashboards/%s/" % dashboard.pk).json()
        self.assertEqual([i["id"] for i in response["items"]], [first_insight.id, second_insight.id])

        # cache results
        response = self.client.get(
            f"/api/projects/{self.team.id}/insights/trend/?events=%s&properties=%s"
            % (json.dumps(filter_dict["events"]), json.dumps(filter_dict["properties"]))
        )
        self.assertEqual(response.status_code, 200)
        first_insight = Insight.objects.get(pk=first_insight.pk)
        self.assertAlmostEqual(first_insight.last_refresh, now(), delta=timezone.timedelta(seconds=5))
        self.assertEqual(first_insight.filters_hash, generate_cache_key(f"{filter.toJSON()}_{self.team.pk}"))

        with self.assertNumQueries(17):
            # Django session, PostHog user, PostHog team, PostHog org membership, PostHog dashboard,
            # PostHog dashboard item, PostHog team, PostHog dashboard item UPDATE, PostHog team,
            # PostHog dashboard item UPDATE, PostHog dashboard UPDATE, PostHog dashboard item, Posthog org tags
            # PostHog DashboardInsight
            response = self.client.get(f"/api/projects/{self.team.id}/dashboards/%s/" % dashboard.pk).json()

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
            Insight.objects.create(
                dashboard=dashboard, filters=Filter(data=filter_dict).to_dict(), team=self.team, last_refresh=now()
            )

        with freeze_time("2020-01-20T13:00:01Z"):
            response = self.client.get(f"/api/projects/{self.team.id}/dashboards/%s/" % dashboard.pk).json()

        self.assertEqual(response["items"][0]["result"], None)
        self.assertEqual(response["items"][0]["last_refresh"], None)

    def test_refresh_cache(self):
        dashboard = Dashboard.objects.create(team=self.team, name="dashboard")

        with freeze_time("2020-01-04T13:00:01Z"):
            # Pretend we cached something a while ago, but we won't have anything in the redis cache
            item_default: Insight = Insight.objects.create(
                dashboard=dashboard,
                filters=Filter(
                    data={"events": [{"id": "$pageview"}], "properties": [{"key": "$browser", "value": "Mac OS X"}],}
                ).to_dict(),
                team=self.team,
                last_refresh=now(),
                order=0,
            )
            item_trends: Insight = Insight.objects.create(
                dashboard=dashboard,
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
        dashboard = Dashboard.objects.create(name="Default", pinned=True, team=self.team, filters={"date_from": "-14d"})
        self.client.post(
            f"/api/projects/{self.team.id}/insights/",
            {"filters": {"hello": "test", "date_from": "-7d"}, "dashboard": dashboard.pk, "name": "some_item"},
            format="json",
        )
        response = self.client.get(f"/api/projects/{self.team.id}/dashboards/{dashboard.pk}/").json()
        self.assertEqual(len(response["items"]), 1)
        self.assertEqual(response["items"][0]["name"], "some_item")
        self.assertEqual(response["items"][0]["filters"]["date_from"], "-14d")

        # creating the insight added it to the dashboard insights collection
        dashboard.refresh_from_db()
        self.assertEqual(dashboard.insights.count(), 1)
        first = dashboard.insights.first()
        if first is None:  # to satisfy mypy
            self.fail("this must be an insight by now")
        self.assertEqual(first.name, "some_item")

        item_response = self.client.get(f"/api/projects/{self.team.id}/insights/").json()
        self.assertEqual(item_response["results"][0]["name"], "some_item")

        # delete
        self.client.patch(
            f"/api/projects/{self.team.id}/insights/{item_response['results'][0]['id']}/", {"deleted": "true"}
        )
        items_response = self.client.get(f"/api/projects/{self.team.id}/insights/").json()
        self.assertEqual(len(items_response["results"]), 0)

    def test_dashboard_does_not_show_soft_deleted_insights(self):
        dashboard = Dashboard.objects.create(name="Default", pinned=True, team=self.team, filters={"date_from": "-14d"})
        response = self.client.post(
            f"/api/projects/{self.team.id}/insights/",
            {"filters": {"hello": "test", "date_from": "-7d"}, "dashboard": dashboard.pk, "name": "some_item"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        insight_id = response.json()["id"]

        response = self.client.get(f"/api/projects/{self.team.id}/dashboards/{dashboard.pk}/").json()
        self.assertEqual(len(response["items"]), 1)

        response = self.client.patch(
            f"/api/projects/{self.team.id}/insights/{insight_id}",
            {
                "filters": {"hello": "test", "date_from": "-7d"},
                "dashboard": dashboard.pk,
                "name": "some_item",
                "deleted": True,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response = self.client.get(f"/api/projects/{self.team.id}/dashboards/{dashboard.pk}/").json()
        self.assertEqual(len(response["items"]), 0)

    def test_dashboard_items_deduplicates_between_items_and_insights(self):
        """
        If an insight is linked to a dashboard by the deprecated relation
        _and_ the new one
        the dashboard's items API property doesn't add it twice

        so, if the insights attached to the dashboard are set up as:

        old_relation = ["both", "old"]
        new_relation = ["both", "new"]

        the items property on the API will union and de-deuplicate across them, holding:

        ["both", "old", "new"]
        """
        dashboard: Dashboard = Dashboard.objects.create(
            name="Default", pinned=True, team=self.team, filters={"date_from": "-14d"}
        )
        insight_on_both_relations: Insight = Insight.objects.create(
            short_id="both", filters={"hello": "test"}, team=self.team, created_by=self.user
        )
        DashboardInsight.objects.create(dashboard=dashboard, insight=insight_on_both_relations)
        dashboard.items.add(insight_on_both_relations)

        insight_on_old_relation = Insight.objects.create(
            short_id="old", filters={"hello": "test"}, team=self.team, created_by=self.user
        )
        dashboard.items.add(insight_on_old_relation)

        insight_on_new_relation = Insight.objects.create(
            short_id="new", filters={"hello": "test"}, team=self.team, created_by=self.user
        )
        DashboardInsight.objects.create(dashboard=dashboard, insight=insight_on_new_relation)

        response = self.client.get(f"/api/projects/{self.team.id}/dashboards/{dashboard.pk}/").json()
        self.assertEqual(len(response["items"]), 3)
        self.assertEqual(sorted([i["short_id"] for i in response["items"]]), sorted(["both", "new", "old"]))

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
        dashboard = Dashboard.objects.create(name="asdasd", pinned=True, team=self.team)
        response = self.client.post(
            f"/api/projects/{self.team.id}/insights/",
            {"filters": {"hello": "test"}, "dashboard": dashboard.pk, "name": "another"},
            format="json",
        ).json()

        self.client.patch(
            f"/api/projects/{self.team.id}/insights/layouts/",
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
        items_response = self.client.get(f"/api/projects/{self.team.id}/insights/{response['id']}/").json()
        self.assertTrue("lg" in items_response["layouts"])

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
        Insight.objects.create(
            dashboard=existing_dashboard, filters={"name": "test1"}, team=self.team, last_refresh=now(),
        )
        Insight.objects.create(
            dashboard=existing_dashboard, filters={"name": "test2"}, team=self.team, last_refresh=now(),
        )
        response = self.client.post(
            f"/api/projects/{self.team.id}/dashboards/", {"name": "another", "use_dashboard": existing_dashboard.id}
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["creation_mode"], "duplicate")

        self.assertEqual(len(response.json()["items"]), len(existing_dashboard.items.all()))

        existing_dashboard_item_id_set = set(map(lambda x: x.id, existing_dashboard.items.all()))
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
        dashboard = Dashboard.objects.create(team=self.team, name="dashboard")
        filter_dict = {
            "events": [{"id": "$pageview"}],
            "properties": [{"key": "$browser", "value": "Mac OS X"}],
            "date_from": "-7d",
        }
        filter = Filter(data=filter_dict)

        item = Insight.objects.create(dashboard=dashboard, filters=filter_dict, team=self.team,)
        Insight.objects.create(
            dashboard=dashboard, filters=filter.to_dict(), team=self.team,
        )
        self.client.get(
            f"/api/projects/{self.team.id}/insights/trend/?events=%s&properties=%s&date_from=-7d"
            % (json.dumps(filter_dict["events"]), json.dumps(filter_dict["properties"]))
        )
        patch_response = self.client.patch(
            f"/api/projects/{self.team.id}/dashboards/%s/" % dashboard.pk,
            {"filters": {"date_from": "-24h"}},
            format="json",
        ).json()
        self.assertEqual(patch_response["items"][0]["result"], None)

        # cache results
        response = self.client.get(
            f"/api/projects/{self.team.id}/insights/trend/?events=%s&properties=%s&date_from=-24h"
            % (json.dumps(filter_dict["events"]), json.dumps(filter_dict["properties"]))
        )
        self.assertEqual(response.status_code, 200)
        item = Insight.objects.get(pk=item.pk)
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
        Insight.objects.create(
            dashboard=dashboard, filters={"events": [{"id": "$pageview"}]}, team=self.team, last_refresh=now(),
        )
        response = self.client.get(f"/api/projects/{self.team.id}/dashboards/{dashboard.pk}").json()
        self.assertEqual(response["items"][0]["filters"], {"events": [{"id": "$pageview"}], "insight": "TRENDS"})

    def test_retrieve_dashboard_different_team(self):
        team2 = Team.objects.create(organization=Organization.objects.create(name="a"))
        dashboard = Dashboard.objects.create(team=team2, name="dashboard", created_by=self.user)
        response = self.client.get(f"/api/projects/{team2.id}/dashboards/{dashboard.id}")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN, response.content)
