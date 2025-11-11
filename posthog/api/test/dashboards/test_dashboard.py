import json

from freezegun import freeze_time
from posthog.test.base import APIBaseTest, FuzzyInt, QueryMatchingTest, snapshot_postgres_queries
from unittest import mock
from unittest.mock import ANY, MagicMock, patch

from django.test import override_settings
from django.utils import timezone
from django.utils.timezone import now

from dateutil.parser import isoparse
from rest_framework import status

from posthog.api.dashboards.dashboard import DashboardSerializer
from posthog.api.test.dashboards import DashboardAPI
from posthog.constants import AvailableFeature
from posthog.helpers.dashboard_templates import create_group_type_mapping_detail_dashboard
from posthog.hogql_queries.legacy_compatibility.filter_to_query import filter_to_query
from posthog.models import Dashboard, DashboardTile, Filter, Insight, Team, User
from posthog.models.file_system.file_system_view_log import FileSystemViewLog
from posthog.models.insight_variable import InsightVariable
from posthog.models.organization import Organization
from posthog.models.project import Project
from posthog.models.sharing_configuration import SharingConfiguration
from posthog.models.signals import mute_selected_signals
from posthog.test.test_utils import create_group_type_mapping_without_created_at

from ee.models.rbac.access_control import AccessControl

valid_template: dict = {
    "template_name": "Sign up conversion template with variables",
    "dashboard_description": "Use this template to see how many users sign up after visiting your pricing page.",
    "dashboard_filters": {},
    "tiles": [
        {
            "name": "Website Unique Users (Total)",
            "type": "INSIGHT",
            "color": "blue",
            "filters": {
                "events": [{"id": "$pageview", "math": "dau", "type": "events"}],
                "compare": True,
                "display": "BoldNumber",
                "insight": "TRENDS",
                "interval": "day",
                "date_from": "-30d",
            },
            "layouts": {
                "sm": {"h": 5, "i": "21", "w": 6, "x": 0, "y": 0, "minH": 5, "minW": 3},
                "xs": {"h": 5, "i": "21", "w": 1, "x": 0, "y": 0, "minH": 5, "minW": 1},
            },
            "description": "Shows the number of unique users that use your app every day.",
        },
    ],
    "variables": [],
    # purposely missing tags as they are not required
}


@override_settings(IN_UNIT_TESTING=True)
class TestDashboard(APIBaseTest, QueryMatchingTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization.available_product_features = [
            {
                "key": AvailableFeature.TAGGING,
                "name": AvailableFeature.TAGGING,
            },
            {
                "key": AvailableFeature.ADVANCED_PERMISSIONS,
                "name": AvailableFeature.ADVANCED_PERMISSIONS,
            },
        ]

        self.organization.save()
        self.dashboard_api = DashboardAPI(self.client, self.team, self.assertEqual)

    @snapshot_postgres_queries
    def test_retrieve_dashboard_list(self):
        dashboard_names = ["a dashboard", "b dashboard"]
        for dashboard_name in dashboard_names:
            self.dashboard_api.create_dashboard({"name": dashboard_name})

        with self.assertNumQueries(14):
            response_data = self.dashboard_api.list_dashboards()
        self.assertEqual(
            [dashboard["name"] for dashboard in response_data["results"]],
            dashboard_names,
        )

    def test_retrieve_dashboard_list_includes_other_environments(self):
        other_team_in_project = Team.objects.create(organization=self.organization, project=self.project)
        _, team_in_other_project = Project.objects.create_with_team(
            organization=self.organization, initiating_user=self.user
        )

        dashboard_a_id, _ = self.dashboard_api.create_dashboard({"name": "A"}, team_id=self.team.id)
        dashboard_b_id, _ = self.dashboard_api.create_dashboard({"name": "B"}, team_id=other_team_in_project.id)
        self.dashboard_api.create_dashboard({"name": "C"}, team_id=team_in_other_project.id)

        response_project_data = self.dashboard_api.list_dashboards(self.project.id)
        response_env_current_data = self.dashboard_api.list_dashboards(self.team.id, parent="environment")
        response_env_other_data = self.dashboard_api.list_dashboards(other_team_in_project.id, parent="environment")

        self.assertEqual(
            {dashboard["id"] for dashboard in response_project_data["results"]},
            {dashboard_a_id, dashboard_b_id},
        )
        self.assertEqual(
            {dashboard["id"] for dashboard in response_env_current_data["results"]},
            {dashboard_a_id, dashboard_b_id},
        )
        self.assertEqual(
            {dashboard["id"] for dashboard in response_env_other_data["results"]},
            {dashboard_a_id, dashboard_b_id},
        )

    def test_list_filter_by_tag(self):
        self.dashboard_api.create_dashboard({"name": "tagged", "tags": ["tag"]})
        self.dashboard_api.create_dashboard({"name": "also tagged", "tags": ["tag2"]})
        self.dashboard_api.create_dashboard({"name": "not tagged"})

        with self.assertNumQueries(14):
            response = self.dashboard_api.list_dashboards(
                expected_status=status.HTTP_200_OK, query_params={"tags": ["tag"]}
            )

        assert response["count"] == 1
        assert response["results"][0]["name"] == "tagged"

    def test_list_filter_by_multiple_tags(self):
        self.dashboard_api.create_dashboard({"name": "tagged", "tags": ["tag"]})
        self.dashboard_api.create_dashboard({"name": "also tagged", "tags": ["tag2"]})
        self.dashboard_api.create_dashboard({"name": "not tagged"})
        self.dashboard_api.create_dashboard({"name": "not with the right tag", "tags": ["wrong-tag"]})

        with self.assertNumQueries(14):
            response = self.dashboard_api.list_dashboards(
                expected_status=status.HTTP_200_OK, query_params={"tags": ["tag", "tag2"]}
            )

        assert response["count"] == 2
        dashboard_names = {dashboard["name"] for dashboard in response["results"]}
        assert dashboard_names == {"tagged", "also tagged"}

    def test_list_includes_last_viewed_at_from_filesystem_logs(self):
        dashboard_recent_id, _ = self.dashboard_api.create_dashboard({"name": "Recently viewed"})
        dashboard_unseen_id, _ = self.dashboard_api.create_dashboard({"name": "Never viewed"})

        other_team = Team.objects.create(organization=self.organization)

        with freeze_time("2024-01-01T12:00:00Z"):
            FileSystemViewLog.objects.create(
                team=self.team,
                user=self.user,
                type="dashboard",
                ref=str(dashboard_recent_id),
            )

        with freeze_time("2024-02-01T12:00:00Z"):
            FileSystemViewLog.objects.create(
                team=other_team,
                user=self.user,
                type="dashboard",
                ref=str(dashboard_unseen_id),
            )

        response = self.dashboard_api.list_dashboards(parent="environment")
        results_by_id = {dashboard["id"]: dashboard for dashboard in response["results"]}

        assert results_by_id[dashboard_recent_id]["last_viewed_at"] is not None
        assert isoparse(results_by_id[dashboard_recent_id]["last_viewed_at"]) == isoparse("2024-01-01T12:00:00+00:00")
        assert results_by_id[dashboard_unseen_id]["last_viewed_at"] is None

    @snapshot_postgres_queries
    def test_retrieve_dashboard(self):
        dashboard = Dashboard.objects.create(team=self.team, name="private dashboard", created_by=self.user)

        response_data = self.dashboard_api.get_dashboard(dashboard.pk)

        self.assertEqual(response_data["name"], "private dashboard")
        self.assertEqual(response_data["description"], "")
        self.assertEqual(response_data["created_by"]["distinct_id"], self.user.distinct_id)
        self.assertEqual(response_data["created_by"]["first_name"], self.user.first_name)
        self.assertEqual(response_data["creation_mode"], "default")
        self.assertEqual(
            response_data["restriction_level"],
            Dashboard.RestrictionLevel.EVERYONE_IN_PROJECT_CAN_EDIT,
        )
        self.assertEqual(
            response_data["effective_privilege_level"],
            Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT,
        )

    def test_create_basic_dashboard(self):
        # the front end sends an empty description even if not allowed to add one
        _, response_data = self.dashboard_api.create_dashboard({"name": "My new dashboard", "description": ""})

        self.assertEqual(response_data["name"], "My new dashboard")
        self.assertEqual(response_data["description"], "")
        self.assertEqual(response_data["tags"], [])
        self.assertEqual(response_data["creation_mode"], "default")
        self.assertEqual(
            response_data["restriction_level"],
            Dashboard.RestrictionLevel.EVERYONE_IN_PROJECT_CAN_EDIT,
        )
        self.assertEqual(
            response_data["effective_privilege_level"],
            Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT,
        )

        instance = Dashboard.objects.get(id=response_data["id"])
        self.assertEqual(instance.name, "My new dashboard")

    def test_update_dashboard(self):
        dashboard = Dashboard.objects.create(
            team=self.team,
            name="private dashboard",
            created_by=self.user,
            creation_mode="template",
        )
        _, response_data = self.dashboard_api.update_dashboard(
            dashboard.pk, {"name": "dashboard new name", "creation_mode": "duplicate"}
        )

        self.assertEqual(response_data["name"], "dashboard new name")
        self.assertEqual(response_data["created_by"]["distinct_id"], self.user.distinct_id)
        self.assertEqual(response_data["creation_mode"], "template")
        self.assertEqual(
            response_data["restriction_level"],
            Dashboard.RestrictionLevel.EVERYONE_IN_PROJECT_CAN_EDIT,
        )
        self.assertEqual(
            response_data["effective_privilege_level"],
            Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT,
        )

        dashboard.refresh_from_db()
        self.assertEqual(dashboard.name, "dashboard new name")

    def test_cannot_update_dashboard_with_invalid_filters(self):
        dashboard = Dashboard.objects.create(
            team=self.team,
            name="private dashboard",
            created_by=self.user,
            creation_mode="template",
        )
        self.dashboard_api.update_dashboard(
            dashboard.pk,
            {
                "filters": [
                    {
                        "key": "brand",
                        "value": ["1"],
                        "operator": "exact",
                        "type": "event",
                    }
                ]
            },
            expected_status=status.HTTP_400_BAD_REQUEST,
        )

        dashboard.refresh_from_db()
        self.assertEqual(dashboard.filters, {})

    def test_create_dashboard_item(self):
        dashboard = Dashboard.objects.create(team=self.team, name="public dashboard")
        self.dashboard_api.create_insight(
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

    def test_shared_dashboard(self):
        self.client.logout()
        dashboard = Dashboard.objects.create(team=self.team, name="public dashboard")
        SharingConfiguration.objects.create(team=self.team, dashboard=dashboard, access_token="testtoken", enabled=True)

        response = self.client.get("/shared_dashboard/testtoken")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_return_cached_results_bleh(self):
        dashboard = Dashboard.objects.create(team=self.team, name="dashboard")

        filter_dict = {
            "events": [{"id": "$pageview"}],
            "properties": [{"key": "$browser", "value": "Mac OS X"}],
        }

        item = Insight.objects.create(filters=Filter(data=filter_dict).to_dict(), team=self.team, short_id="item11")
        DashboardTile.objects.create(dashboard=dashboard, insight=item)
        item2 = Insight.objects.create(filters=Filter(data=filter_dict).to_dict(), team=self.team, short_id="item22")
        DashboardTile.objects.create(dashboard=dashboard, insight=item2)
        response = self.dashboard_api.get_dashboard(dashboard.pk, query_params={"refresh": False, "use_cache": True})
        self.assertEqual(response["tiles"][0]["insight"]["result"], None)

        # cache results
        response = self.client.get(f"/api/projects/{self.team.id}/insights/{item.pk}?refresh=true").json()

        response = self.client.get(f"/api/projects/{self.team.id}/insights/{item2.pk}?refresh=true").json()

        # Now the dashboard has data without having to refresh
        response = self.dashboard_api.get_dashboard(dashboard.pk, query_params={"refresh": False, "use_cache": True})
        self.assertAlmostEqual(
            Dashboard.objects.get().last_accessed_at,
            now(),
            delta=timezone.timedelta(seconds=5),
        )
        self.assertEqual(response["tiles"][0]["insight"]["result"][0]["count"], 0)

    # :KLUDGE: avoid making extra queries that are explicitly not cached in tests. Avoids false N+1-s.
    @override_settings(PERSON_ON_EVENTS_OVERRIDE=False, PERSON_ON_EVENTS_V2_OVERRIDE=False)
    @snapshot_postgres_queries
    def test_adding_insights_is_not_nplus1_for_gets(self):
        with mute_selected_signals():
            dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard"})
            filter_dict = {
                "events": [{"id": "$pageview"}],
                "properties": [{"key": "$browser", "value": "Mac OS X"}],
                "insight": "TRENDS",
            }

            baseline = 10

            with self.assertNumQueries(baseline + 10):
                self.dashboard_api.get_dashboard(dashboard_id, query_params={"no_items_field": "true"})

            self.dashboard_api.create_insight({"filters": filter_dict, "dashboards": [dashboard_id]})
            with self.assertNumQueries(baseline + 11 + 11):
                self.dashboard_api.get_dashboard(dashboard_id, query_params={"no_items_field": "true"})

            self.dashboard_api.create_insight({"filters": filter_dict, "dashboards": [dashboard_id]})
            with self.assertNumQueries(baseline + 11 + 11):
                self.dashboard_api.get_dashboard(dashboard_id, query_params={"no_items_field": "true"})

        self.dashboard_api.create_insight({"filters": filter_dict, "dashboards": [dashboard_id]})
        with self.assertNumQueries(baseline + 11 + 11):
            self.dashboard_api.get_dashboard(dashboard_id, query_params={"no_items_field": "true"})

    @snapshot_postgres_queries
    def test_listing_dashboards_is_not_nplus1(self) -> None:
        self.client.logout()

        self.organization.available_product_features = []
        self.organization.save()

        # Set up restricted access (equivalent of old access_control)
        AccessControl.objects.create(
            team=self.team,
            access_level="none",
            resource="project",
            resource_id=str(self.team.id),
        )

        user_with_collaboration = User.objects.create_and_join(
            self.organization, "no-collaboration-feature@posthog.com", None
        )

        # Grant access to the new user
        AccessControl.objects.create(
            team=self.team,
            access_level="member",
            resource="project",
            resource_id=str(self.team.id),
            organization_member=user_with_collaboration.organization_memberships.first(),
        )

        self.client.force_login(user_with_collaboration)

        with self.assertNumQueries(10):
            self.dashboard_api.list_dashboards()

        for i in range(5):
            dashboard_id, _ = self.dashboard_api.create_dashboard({"name": f"dashboard-{i}", "description": i})
            for j in range(3):
                self.dashboard_api.create_insight({"dashboards": [dashboard_id], "name": f"insight-{j}"})

            with self.assertNumQueries(FuzzyInt(11, 12)):
                self.dashboard_api.list_dashboards(query_params={"limit": 300})

    def test_listing_dashboards_does_not_include_tiles(self) -> None:
        dashboard_one_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard-1"})
        dashboard_two_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard-2"})
        self.dashboard_api.create_insight({"dashboards": [dashboard_two_id, dashboard_one_id], "name": f"insight"})

        assert len(self.dashboard_api.get_dashboard(dashboard_one_id)["tiles"]) == 1
        assert len(self.dashboard_api.get_dashboard(dashboard_two_id)["tiles"]) == 1

        response = self.dashboard_api.list_dashboards(query_params={"limit": 100})

        assert [r.get("items", None) for r in response["results"]] == [None, None]
        assert [r.get("tiles", None) for r in response["results"]] == [None, None]

    @snapshot_postgres_queries
    def test_loading_individual_dashboard_does_not_prefetch_all_possible_tiles(self) -> None:
        """
        this test only exists for the query snapshot
        which can be used to check if all dashboard tiles are being queried.
        look for a query on posthog_dashboard_tile with
        ```
            AND "posthog_dashboardtile"."dashboard_id" = 2
            AND "posthog_dashboardtile"."dashboard_id" IN (1,
         ```
        """
        dashboard_one_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard-1"})
        dashboard_two_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard-2"})
        self.dashboard_api.create_insight({"dashboards": [dashboard_two_id, dashboard_one_id], "name": f"insight"})
        self.dashboard_api.create_insight({"dashboards": [dashboard_one_id], "name": f"insight"})
        self.dashboard_api.create_insight({"dashboards": [dashboard_one_id], "name": f"insight"})
        self.dashboard_api.create_insight({"dashboards": [dashboard_one_id], "name": f"insight"})

        # so DB has 5 tiles, but we only load need to 1
        self.dashboard_api.get_dashboard(dashboard_one_id)

    def test_no_cache_available(self):
        dashboard = Dashboard.objects.create(team=self.team, name="dashboard")
        filter_dict = {
            "events": [{"id": "$pageview"}],
            "properties": [{"key": "$browser", "value": "Mac OS X"}],
        }

        with freeze_time("2020-01-04T13:00:01Z"):
            # Pretend we cached something a while ago, but we won't have anything in the redis cache
            insight = Insight.objects.create(
                filters=Filter(data=filter_dict).to_dict(),
                team=self.team,
                last_refresh=now(),
            )
            DashboardTile.objects.create(dashboard=dashboard, insight=insight)

        with freeze_time("2020-01-20T13:00:01Z"):
            response = self.dashboard_api.get_dashboard(dashboard.pk)

        self.assertEqual(response["tiles"][0]["insight"]["result"], None)
        self.assertEqual(response["tiles"][0]["last_refresh"], None)

    def test_refresh_cache(self):
        dashboard = Dashboard.objects.create(team=self.team, name="dashboard")

        with freeze_time("2020-01-04T13:00:01Z"):
            # Pretend we cached something a while ago, but we won't have anything in the redis cache
            item_default: Insight = Insight.objects.create(
                filters=Filter(
                    data={
                        "events": [{"id": "$pageview"}],
                        "properties": [{"key": "$browser", "value": "Mac OS X"}],
                    }
                ).to_dict(),
                team=self.team,
                order=0,
            )
            DashboardTile.objects.create(dashboard=dashboard, insight=item_default)
            item_trends: Insight = Insight.objects.create(
                filters=Filter(
                    data={
                        "display": "ActionsLineGraph",
                        "events": [
                            {
                                "id": "$pageview",
                                "type": "events",
                                "order": 0,
                                "properties": [],
                            }
                        ],
                        "filters": [],
                        "interval": "day",
                        "pagination": {},
                        "session": "avg",
                    }
                ).to_dict(),
                team=self.team,
                order=1,
            )
        DashboardTile.objects.create(dashboard=dashboard, insight=item_trends)

        with freeze_time("2020-01-20T13:00:01Z"):
            response_data = self.dashboard_api.get_dashboard(dashboard.pk, query_params={"refresh": True})

            self.assertEqual(response_data["tiles"][0]["is_cached"], False)
            self.assertIsNotNone(response_data["tiles"][0]["insight"]["result"])
            self.assertIsNotNone(response_data["tiles"][0]["insight"]["last_refresh"])
            self.assertIsNotNone(response_data["tiles"][0]["last_refresh"])
            self.assertEqual(response_data["tiles"][0]["insight"]["result"][0]["count"], 0)

            item_default.refresh_from_db()
            item_trends.refresh_from_db()

            self.assertEqual(
                isoparse(response_data["tiles"][0]["last_refresh"]),
                item_default.caching_state.last_refresh,
            )
            self.assertEqual(
                isoparse(response_data["tiles"][1]["last_refresh"]),
                item_default.caching_state.last_refresh,
            )

            self.assertAlmostEqual(
                item_default.caching_state.last_refresh,
                now(),
                delta=timezone.timedelta(seconds=5),
            )
            self.assertAlmostEqual(
                item_trends.caching_state.last_refresh,
                now(),
                delta=timezone.timedelta(seconds=5),
            )

    def test_dashboard_endpoints(self):
        # create
        _, response_json = self.dashboard_api.create_dashboard({"name": "Default", "pinned": "true"})
        self.assertEqual(response_json["name"], "Default")
        self.assertEqual(response_json["creation_mode"], "default")
        self.assertEqual(response_json["pinned"], True)

        # retrieve
        response = self.dashboard_api.list_dashboards()
        pk = Dashboard.objects.first().pk  # type: ignore
        self.assertEqual(response["results"][0]["id"], pk)
        self.assertEqual(response["results"][0]["name"], "Default")

        # soft-delete
        self.dashboard_api.soft_delete(pk, "dashboards")
        self.dashboard_api.get_dashboard(pk, expected_status=status.HTTP_404_NOT_FOUND)
        response = self.dashboard_api.list_dashboards()
        self.assertEqual(len(response["results"]), 0)

        # restore after soft-deletion
        self.dashboard_api.update_dashboard(pk, {"deleted": False})

        response = self.dashboard_api.list_dashboards()
        self.assertEqual(len(response["results"]), 1)

        self.dashboard_api.get_dashboard(pk, expected_status=status.HTTP_200_OK)

    def test_delete_does_not_delete_insights_by_default(self):
        dashboard_id, _ = self.dashboard_api.create_dashboard({"filters": {"date_from": "-14d"}})
        insight_id, _ = self.dashboard_api.create_insight(
            {
                "filters": {"hello": "test", "date_from": "-7d"},
                "dashboards": [dashboard_id],
                "name": "some_item",
            }
        )

        dashboard_before_delete = self.dashboard_api.get_dashboard(dashboard_id)
        assert len(dashboard_before_delete["tiles"]) == 1

        self.dashboard_api.soft_delete(dashboard_id, "dashboards")
        self.dashboard_api.get_dashboard(dashboard_id, expected_status=status.HTTP_404_NOT_FOUND)
        self.dashboard_api.get_insight(insight_id, self.team.id, expected_status=status.HTTP_200_OK)

        with self.assertRaises(DashboardTile.DoesNotExist):
            DashboardTile.objects.get(dashboard_id=dashboard_id, insight_id=insight_id)

        tile = DashboardTile.objects_including_soft_deleted.get(dashboard_id=dashboard_id, insight_id=insight_id)
        assert tile.deleted is True

    def test_delete_dashboard_can_delete_tiles(self):
        dashboard_one_id, _ = self.dashboard_api.create_dashboard({"filters": {"date_from": "-14d"}})
        dashboard_two_id, _ = self.dashboard_api.create_dashboard({"filters": {"date_from": "-14d"}})

        insight_on_one_dashboard_id, _ = self.dashboard_api.create_insight(
            {"name": "on one dashboard", "dashboards": [dashboard_one_id]}
        )

        insight_on_two_dashboards_id, _ = self.dashboard_api.create_insight(
            {
                "name": "on two dashboards",
                "dashboards": [dashboard_one_id, dashboard_two_id],
            }
        )

        dashboard_one_before_delete = self.dashboard_api.get_dashboard(dashboard_one_id)
        assert len(dashboard_one_before_delete["tiles"]) == 2

        dashboard_two_before_delete = self.dashboard_api.get_dashboard(dashboard_two_id)
        assert len(dashboard_two_before_delete["tiles"]) == 1

        self.dashboard_api.soft_delete(dashboard_one_id, "dashboards", {"delete_insights": True})

        self.dashboard_api.get_insight(
            insight_on_one_dashboard_id,
            self.team.id,
            expected_status=status.HTTP_404_NOT_FOUND,
        )
        self.dashboard_api.get_insight(
            insight_on_two_dashboards_id,
            self.team.id,
            expected_status=status.HTTP_200_OK,
        )

        dashboard_two_after_delete = self.dashboard_api.get_dashboard(dashboard_two_id)
        assert len(dashboard_two_after_delete["tiles"]) == 1

    def test_delete_dashboard_resets_group_type_detail_dashboard_if_needed(self):
        group_type = create_group_type_mapping_without_created_at(
            team=self.team, project_id=self.team.project_id, group_type="organization", group_type_index=0
        )

        dashboard = create_group_type_mapping_detail_dashboard(group_type, self.user)
        group_type.detail_dashboard = dashboard
        group_type.save()

        self.dashboard_api.soft_delete(dashboard.id, "dashboards", {"delete_insights": True})
        group_type.refresh_from_db()
        self.assertIsNone(group_type.detail_dashboard)

    def test_dashboard_items(self):
        dashboard_id, _ = self.dashboard_api.create_dashboard({"filters": {"date_from": "-14d"}})
        insight_id, _ = self.dashboard_api.create_insight(
            {
                "filters": {"hello": "test", "date_from": "-7d"},
                "dashboards": [dashboard_id],
                "name": "some_item",
            }
        )

        response = self.dashboard_api.get_dashboard(dashboard_id)
        self.assertEqual(len(response["tiles"]), 1)
        self.assertEqual(response["tiles"][0]["insight"]["name"], "some_item")
        self.assertEqual(response["tiles"][0]["insight"]["filters"]["date_from"], "-14d")

        item_response = self.client.get(f"/api/projects/{self.team.id}/insights/").json()
        self.assertEqual(item_response["results"][0]["name"], "some_item")

        # delete
        self.dashboard_api.soft_delete(insight_id, "insights")
        items_response = self.client.get(f"/api/projects/{self.team.id}/insights/").json()
        self.assertEqual(len(items_response["results"]), 0)

        excludes_deleted_insights_response = self.dashboard_api.get_dashboard(dashboard_id)
        self.assertEqual(len(excludes_deleted_insights_response["tiles"]), 0)
        self.assertEqual(len(excludes_deleted_insights_response["tiles"]), 0)

    def test_dashboard_insights_out_of_synch_with_tiles_are_not_shown(self):
        """
        regression test reported by customer, insight was deleted without deleting its tiles and was still shown
        """
        dashboard_id, _ = self.dashboard_api.create_dashboard({"filters": {"date_from": "-14d"}})
        insight_id, _ = self.dashboard_api.create_insight(
            {
                "filters": {"hello": "test", "date_from": "-7d"},
                "dashboards": [dashboard_id],
                "name": "some_item",
            }
        )
        out_of_synch_insight_id, _ = self.dashboard_api.create_insight(
            {
                "filters": {"hello": "test", "date_from": "-7d"},
                "dashboards": [dashboard_id],
                "name": "out of synch",
            }
        )

        response = self.dashboard_api.get_dashboard(dashboard_id)
        self.assertEqual(len(response["tiles"]), 2)

        Insight.objects.filter(id=out_of_synch_insight_id).update(deleted=True)
        assert DashboardTile.objects.get(insight_id=out_of_synch_insight_id).deleted is None

        excludes_deleted_insights_response = self.dashboard_api.get_dashboard(dashboard_id)
        self.assertEqual(len(excludes_deleted_insights_response["tiles"]), 1)

        # if loaded directly e.g. when shared/exported it doesn't use the ViewSet's queryset...
        # so delete filtering needs to be in more places
        dashboard = Dashboard.objects.get(id=dashboard_id)
        mock_view = MagicMock()
        mock_view.action = "retrieve"
        mock_request = MagicMock()
        mock_request.query_params.get.return_value = None
        mock_request.user = self.user

        # Create a proper user access control for the serializer
        from posthog.rbac.user_access_control import UserAccessControl

        user_access_control = UserAccessControl(self.user, organization_id=str(self.user.current_organization_id))

        dashboard_data = DashboardSerializer(
            dashboard,
            context={
                "view": mock_view,
                "request": mock_request,
                "get_team": lambda: self.team,
                "insight_variables": [],
                "user_access_control": user_access_control,
            },
        ).data
        assert len(dashboard_data["tiles"]) == 1

    def test_dashboard_insight_tiles_can_be_loaded_correct_context(self):
        dashboard_id, _ = self.dashboard_api.create_dashboard({"filters": {"date_from": "-14d"}})
        insight_id, _ = self.dashboard_api.create_insight(
            {
                "filters": {"hello": "test", "date_from": "-7d"},
                "dashboards": [dashboard_id],
                "name": "some_item",
            }
        )

        response = self.dashboard_api.get_dashboard(dashboard_id)
        self.assertEqual(len(response["tiles"]), 1)
        tile = response["tiles"][0]

        assert tile["insight"]["id"] == insight_id
        assert tile["insight"]["filters"]["date_from"] == "-14d"

    def test_dashboard_filtering_on_properties(self):
        dashboard_id, _ = self.dashboard_api.create_dashboard({"filters": {"date_from": "-24h"}})
        _, response = self.dashboard_api.update_dashboard(
            dashboard_id,
            {
                "filters": {
                    "date_from": "-24h",
                    "properties": [{"key": "prop", "value": "val"}],
                }
            },
        )

        self.assertEqual(response["filters"]["properties"], [{"key": "prop", "value": "val"}])

        insight_id, _ = self.dashboard_api.create_insight(
            {
                "filters": {"hello": "test", "date_from": "-7d"},
                "dashboards": [dashboard_id],
                "name": "some_item",
            }
        )

        response = self.dashboard_api.get_dashboard(dashboard_id)
        self.assertEqual(len(response["tiles"]), 1)
        self.assertEqual(response["tiles"][0]["insight"]["name"], "some_item")
        self.assertEqual(
            response["tiles"][0]["insight"]["filters"]["properties"],
            [{"key": "prop", "value": "val"}],
        )

    def test_dashboard_filter_is_applied_even_if_insight_is_created_before_dashboard(self):
        insight_id, _ = self.dashboard_api.create_insight(
            {"filters": {"hello": "test", "date_from": "-7d"}, "name": "some_item"}
        )

        dashboard_id, _ = self.dashboard_api.create_dashboard({"filters": {"date_from": "-14d"}})

        # add the insight to the dashboard
        self.dashboard_api.add_insight_to_dashboard([dashboard_id], insight_id)

        response = self.dashboard_api.get_dashboard(dashboard_id)
        self.assertEqual(response["tiles"][0]["insight"]["filters"]["date_from"], "-14d")

        # which doesn't change the insight's filter
        response = self.dashboard_api.get_insight(insight_id)
        self.assertEqual(response["filters"]["date_from"], "-7d")

    def test_dashboard_items_history_per_user(self):
        test_user = User.objects.create_and_join(self.organization, "test@test.com", None)

        Insight.objects.create(filters={"hello": "test"}, team=self.team, created_by=test_user)

        self.dashboard_api.create_insight({"filters": {"hello": "test"}})

        response = self.client.get(f"/api/projects/{self.team.id}/insights/?user=true").json()
        self.assertEqual(response["count"], 1)

    def test_dashboard_items_history_saved(self):
        self.dashboard_api.create_insight({"filters": {"hello": "test"}, "saved": True})
        self.dashboard_api.create_insight({"filters": {"hello": "test"}})

        response = self.client.get(f"/api/projects/{self.team.id}/insights/?user=true&saved=true").json()
        self.assertEqual(response["count"], 1)

    def test_dashboard_item_layout(self):
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "asdasd", "pinned": True})

        insight_id, _ = self.dashboard_api.create_insight(
            {
                "filters": {"hello": "test"},
                "dashboards": [dashboard_id],
                "name": "another",
            }
        )

        dashboard_json = self.dashboard_api.get_dashboard(dashboard_id)
        tiles = dashboard_json["tiles"]
        assert len(tiles) == 1

        # layouts used to live on insights, but moved onto the relation from a dashboard to its insights
        self.dashboard_api.set_tile_layout(dashboard_id, expected_tiles_to_update=1)

        dashboard_json = self.dashboard_api.get_dashboard(dashboard_id, query_params={"refresh": False})
        first_tile_layouts = dashboard_json["tiles"][0]["layouts"]

        self.assertTrue("sm" in first_tile_layouts)

    def test_dashboard_tile_color_can_be_set_for_new_or_existing_tiles(self):
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "asdasd", "pinned": True})

        insight_id, _ = self.dashboard_api.create_insight(
            {
                "filters": {"hello": "test"},
                "dashboards": [dashboard_id],
                "name": "another",
            }
        )

        dashboard_json = self.dashboard_api.get_dashboard(dashboard_id)
        tiles = dashboard_json["tiles"]
        assert len(tiles) == 1
        tile_id = tiles[0]["id"]

        self.dashboard_api.update_dashboard(
            dashboard_id,
            {
                "tiles": [
                    {
                        "id": tile_id,
                        "color": "red",
                        "is_cached": True,  # included to ensure we can update existing tiles with this readonly property
                    },
                    {
                        "id": tile_id + 1,
                        "color": "red",
                        "is_cached": True,  # included to ensure we can update new tiles with this readonly property
                        "text": {"body": "an example"},
                        "layouts": {},
                    },
                ]
            },
        )

        dashboard_json = self.dashboard_api.get_dashboard(dashboard_id, query_params={"refresh": False})
        assert dashboard_json["tiles"][0]["color"] == "red"

    @patch("posthog.api.dashboards.dashboard.report_user_action")
    def test_dashboard_from_template(self, mock_capture):
        _, response = self.dashboard_api.create_dashboard({"name": "another", "use_template": "DEFAULT_APP"})
        self.assertGreater(Insight.objects.count(), 1)
        self.assertEqual(response["creation_mode"], "template")

        # Assert analytics are sent
        mock_capture.assert_called_once_with(
            self.user,
            "dashboard created",
            {
                "$current_url": None,
                "$session_id": mock.ANY,
                "created_at": mock.ANY,
                "dashboard_id": None,
                "duplicated": False,
                "from_template": True,
                "has_description": False,
                "is_shared": False,
                "item_count": 6,
                "pinned": False,
                "tags_count": 0,
                "template_key": "DEFAULT_APP",
            },
        )

    def test_dashboard_creation_validation(self):
        existing_dashboard = Dashboard.objects.create(team=self.team, name="existing dashboard", created_by=self.user)

        # invalid - both use_template and use_dashboard are set
        self.dashboard_api.create_dashboard(
            {"name": "another", "use_template": "DEFAULT_APP", "use_dashboard": 1},
            expected_status=status.HTTP_400_BAD_REQUEST,
        )

        # invalid - use_template is set and use_dashboard empty string
        self.dashboard_api.create_dashboard(
            {"name": "another", "use_template": "DEFAULT_APP", "use_dashboard": ""},
            expected_status=status.HTTP_400_BAD_REQUEST,
        )

        # valid - use_template empty and use_dashboard is not set
        self.dashboard_api.create_dashboard(
            {"name": "another", "use_template": ""},
            expected_status=status.HTTP_201_CREATED,
        )

        # valid - only use_template is set
        self.dashboard_api.create_dashboard(
            {"name": "another", "use_template": "DEFAULT_APP"},
            expected_status=status.HTTP_201_CREATED,
        )

        # valid - only use_dashboard is set
        self.dashboard_api.create_dashboard(
            {"name": "another", "use_dashboard": existing_dashboard.id},
            expected_status=status.HTTP_201_CREATED,
        )

        # valid - use_dashboard is set and use_template empty string
        self.dashboard_api.create_dashboard(
            {
                "name": "another",
                "use_template": "",
                "use_dashboard": existing_dashboard.id,
            },
            expected_status=status.HTTP_201_CREATED,
        )

        # valid - both use_template and use_dashboard are not set
        self.dashboard_api.create_dashboard(
            {"name": "another"},
            expected_status=status.HTTP_201_CREATED,
        )

    def test_dashboard_creation_mode(self):
        # template
        _, response = self.dashboard_api.create_dashboard({"name": "another", "use_template": "DEFAULT_APP"})
        self.assertEqual(response["creation_mode"], "template")

        # duplicate
        existing_dashboard = Dashboard.objects.create(team=self.team, name="existing dashboard", created_by=self.user)
        _, response = self.dashboard_api.create_dashboard(
            {"name": "another", "use_dashboard": existing_dashboard.id},
        )
        self.assertEqual(response["creation_mode"], "duplicate")

        # default
        _, response = self.dashboard_api.create_dashboard(
            {"name": "another"},
        )
        self.assertEqual(response["creation_mode"], "default")

    def test_dashboard_duplication_does_not_duplicate_tiles_by_default(self):
        existing_dashboard = Dashboard.objects.create(team=self.team, name="existing dashboard", created_by=self.user)
        insight_one_id, _ = self.dashboard_api.create_insight(
            {"dashboards": [existing_dashboard.pk], "name": "the insight"}
        )
        _, dashboard_with_tiles = self.dashboard_api.create_text_tile(existing_dashboard.id)

        _, duplicate_response = self.dashboard_api.create_dashboard(
            {"name": "another", "use_dashboard": existing_dashboard.id}
        )

        after_duplication_insight_id = duplicate_response["tiles"][0]["insight"]["id"]
        assert after_duplication_insight_id == insight_one_id
        assert duplicate_response["tiles"][0]["insight"]["name"] == "the insight"

        after_duplication_tile_id = duplicate_response["tiles"][1]["text"]["id"]
        assert after_duplication_tile_id == dashboard_with_tiles["tiles"][1]["text"]["id"]

    def test_dashboard_duplication_without_tile_duplicate_excludes_soft_deleted_tiles(self):
        existing_dashboard = Dashboard.objects.create(team=self.team, name="existing dashboard", created_by=self.user)
        insight_one_id, _ = self.dashboard_api.create_insight(
            {"dashboards": [existing_dashboard.pk], "name": "the insight"}
        )
        _, dashboard_with_tiles = self.dashboard_api.create_text_tile(existing_dashboard.id)
        insight_two_id, _ = self.dashboard_api.create_insight(
            {"dashboards": [existing_dashboard.pk], "name": "the second insight"}
        )
        dashboard_json = self.dashboard_api.get_dashboard(existing_dashboard.pk)
        assert len(dashboard_json["tiles"]) == 3
        tile_to_delete = dashboard_json["tiles"][2]
        assert tile_to_delete["insight"]["id"] == insight_two_id

        self.dashboard_api.update_dashboard(
            existing_dashboard.pk,
            {"tiles": [{"id": tile_to_delete["id"], "deleted": True}]},
        )
        dashboard_json = self.dashboard_api.get_dashboard(existing_dashboard.pk)
        assert len(dashboard_json["tiles"]) == 2

        _, duplicate_response = self.dashboard_api.create_dashboard(
            {"name": "another", "use_dashboard": existing_dashboard.pk}
        )
        assert len(duplicate_response["tiles"]) == 2

    def test_dashboard_duplication_can_duplicate_tiles(self):
        existing_dashboard = Dashboard.objects.create(team=self.team, name="existing dashboard", created_by=self.user)
        insight_one_id, _ = self.dashboard_api.create_insight(
            {"dashboards": [existing_dashboard.pk], "name": "the insight"}
        )
        _, dashboard_with_tiles = self.dashboard_api.create_text_tile(existing_dashboard.id)

        _, duplicate_response = self.dashboard_api.create_dashboard(
            {
                "name": "another",
                "use_dashboard": existing_dashboard.id,
                "duplicate_tiles": True,
            }
        )

        after_duplication_insight_id = duplicate_response["tiles"][0]["insight"]["id"]
        assert after_duplication_insight_id != insight_one_id
        assert duplicate_response["tiles"][0]["insight"]["name"] == "the insight (Copy)"

        after_duplication_tile_id = duplicate_response["tiles"][1]["text"]["id"]
        assert after_duplication_tile_id != dashboard_with_tiles["tiles"][1]["text"]["id"]

    def test_dashboard_duplication_can_duplicate_tiles_without_editing_name_if_there_is_none(self) -> None:
        existing_dashboard = Dashboard.objects.create(team=self.team, name="existing dashboard", created_by=self.user)
        self.dashboard_api.create_insight({"dashboards": [existing_dashboard.pk], "name": None})
        self.dashboard_api.create_text_tile(existing_dashboard.pk)

        _, duplicate_response = self.dashboard_api.create_dashboard(
            {
                "name": "another",
                "use_dashboard": existing_dashboard.pk,
                "duplicate_tiles": True,
            }
        )

        assert duplicate_response is not None
        assert len(duplicate_response.get("tiles", [])) == 2

        insight_tile = next(tile for tile in duplicate_response["tiles"] if "insight" in tile)
        text_tile = next(tile for tile in duplicate_response["tiles"] if "text" in tile)

        # this test only needs to check that insight name is still None,
        # but it flaps in CI.
        # my guess was that the order of the response is not guaranteed
        # but even after lifting insight tile out specifically, it still flaps
        # it isn't clear from the error if insight_tile or insight_tile["insight"] is None
        with self.retry_assertion():
            assert insight_tile is not None
            assert insight_tile["insight"] is not None
            assert insight_tile["insight"]["name"] is None
            assert text_tile is not None

    def test_dashboard_duplication(self):
        existing_dashboard = Dashboard.objects.create(team=self.team, name="existing dashboard", created_by=self.user)
        insight1 = Insight.objects.create(filters={"name": "test1"}, team=self.team, last_refresh=now())
        tile1 = DashboardTile.objects.create(dashboard=existing_dashboard, insight=insight1)
        insight2 = Insight.objects.create(filters={"name": "test2"}, team=self.team, last_refresh=now())
        tile2 = DashboardTile.objects.create(dashboard=existing_dashboard, insight=insight2)
        _, response = self.dashboard_api.create_dashboard({"name": "another", "use_dashboard": existing_dashboard.pk})
        self.assertEqual(response["creation_mode"], "duplicate")

        self.assertEqual(len(response["tiles"]), len(existing_dashboard.insights.all()))

        existing_dashboard_item_id_set = {tile1.pk, tile2.pk}
        response_item_id_set = {x.get("id", None) for x in response["tiles"]}
        # check both sets are disjoint to verify that the new items' ids are different than the existing items

        self.assertTrue(existing_dashboard_item_id_set.isdisjoint(response_item_id_set))

        for item in response["tiles"]:
            self.assertNotEqual(item.get("dashboard", None), existing_dashboard.pk)

    def test_invalid_dashboard_duplication(self):
        # pass a random number (non-existent dashboard id) as use_dashboard
        self.dashboard_api.create_dashboard(
            {"name": "another", "use_dashboard": 12345},
            expected_status=status.HTTP_400_BAD_REQUEST,
        )

    def test_duplication_fail_for_different_team(self):
        another_team = Team.objects.create(organization=self.organization)
        another_team_dashboard = Dashboard.objects.create(team=another_team, name="Another Team's Dashboard")
        self.dashboard_api.create_dashboard(
            {"name": "another", "use_dashboard": another_team_dashboard.id},
            expected_status=status.HTTP_400_BAD_REQUEST,
        )

    def test_return_cached_results_dashboard_has_filters(self):
        # create a dashboard with no filters
        dashboard: Dashboard = Dashboard.objects.create(team=self.team, name="dashboard")

        filter_dict = {
            "events": [{"id": "$pageview"}],
            "properties": [{"key": "$browser", "value": "Mac OS X"}],
            "date_from": "-7d",
            "insight": "TRENDS",
        }

        # create two insights with a -7d date from filter
        self.dashboard_api.create_insight({"filters": filter_dict, "dashboards": [dashboard.pk]})
        self.dashboard_api.create_insight({"filters": filter_dict, "dashboards": [dashboard.pk]})

        query = filter_to_query(filter_dict).model_dump()

        # cache insight results for trends with a -7d date from
        response = self.client.post(f"/api/projects/{self.team.id}/query/", data={"query": query})
        self.assertEqual(response.status_code, 200)
        dashboard_json = self.dashboard_api.get_dashboard(dashboard.pk)
        self.assertEqual(len(dashboard_json["tiles"][0]["insight"]["result"][0]["days"]), 8)

        # set a filter on the dashboard
        _, patch_response_json = self.dashboard_api.update_dashboard(
            dashboard.pk,
            {"filters": {"date_from": "-24h"}},
        )

        self.assertEqual(patch_response_json["tiles"][0]["insight"]["result"], None)
        dashboard.refresh_from_db()
        self.assertEqual(dashboard.filters, {"date_from": "-24h"})

        # cache results
        filter_dict["date_from"] = "-24h"
        response = self.client.post(
            f"/api/projects/{self.team.id}/query/",
            data={"query": filter_to_query(filter_dict).model_dump()},
        )

        self.assertEqual(response.status_code, 200)

        # Expecting this to only have one day as per the dashboard filter
        dashboard_json = self.dashboard_api.get_dashboard(dashboard.pk)
        self.assertEqual(len(dashboard_json["tiles"][0]["insight"]["result"][0]["days"]), 2)

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
        item = Insight.objects.create(
            filters={"events": [{"id": "$pageview"}]},
            team=self.team,
            last_refresh=now(),
        )
        DashboardTile.objects.create(insight=item, dashboard=dashboard)
        response = self.dashboard_api.get_dashboard(dashboard.pk)
        self.assertEqual(
            response["tiles"][0]["insight"]["filters"],
            {
                "events": [{"id": "$pageview"}],
                "insight": "TRENDS",
                "date_from": None,
                "date_to": None,
            },
        )

    def test_retrieve_dashboard_different_team(self):
        team2 = Team.objects.create(organization=Organization.objects.create(name="a"))
        dashboard = Dashboard.objects.create(team=team2, name="dashboard", created_by=self.user)
        self.dashboard_api.get_dashboard(dashboard.pk, team_id=team2.pk, expected_status=status.HTTP_403_FORBIDDEN)

    def test_patch_api_as_form_data(self):
        dashboard = Dashboard.objects.create(team=self.team, name="dashboard", created_by=self.user)
        response = self.client.patch(
            f"/api/projects/{self.team.id}/dashboards/{dashboard.pk}/",
            data="name=replaced",
            content_type="application/x-www-form-urlencoded",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["name"], "replaced")

    def test_dashboard_does_not_load_insight_that_was_deleted(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard"})
        insight_id, _ = self.dashboard_api.create_insight({"dashboards": [dashboard_id]})

        self.dashboard_api.soft_delete(insight_id, "insights")
        dashboard = self.dashboard_api.get_dashboard(dashboard_id)
        self.assertEqual(dashboard["tiles"], [])

    def test_can_soft_delete_insight_after_soft_deleting_dashboard(self) -> None:
        filter_dict = {
            "events": [{"id": "$pageview"}],
            "properties": [{"key": "$browser", "value": "Mac OS X"}],
            "insight": "TRENDS",
        }

        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard"})
        insight_id, _ = self.dashboard_api.create_insight({"filters": filter_dict, "dashboards": [dashboard_id]})

        self.dashboard_api.soft_delete(dashboard_id, "dashboards")

        insight_json = self.dashboard_api.get_insight(insight_id=insight_id)
        self.assertEqual(insight_json["dashboards"], [])

        self.dashboard_api.soft_delete(insight_id, "insights")

    def test_can_soft_delete_dashboard_after_soft_deleting_insight(self) -> None:
        filter_dict = {
            "events": [{"id": "$pageview"}],
            "properties": [{"key": "$browser", "value": "Mac OS X"}],
            "insight": "TRENDS",
        }

        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard"})
        insight_id, _ = self.dashboard_api.create_insight({"filters": filter_dict, "dashboards": [dashboard_id]})

        self.dashboard_api.soft_delete(insight_id, "insights")

        self.dashboard_api.get_insight(insight_id=insight_id, expected_status=status.HTTP_404_NOT_FOUND)

        dashboard_json = self.dashboard_api.get_dashboard(dashboard_id)
        self.assertEqual(len(dashboard_json["tiles"]), 0)

        self.dashboard_api.soft_delete(dashboard_id, "dashboards")

    def test_hard_delete_is_forbidden(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard"})
        api_response = self.client.delete(f"/api/projects/{self.team.id}/dashboards/{dashboard_id}")
        self.assertEqual(api_response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        self.dashboard_api.get_dashboard(dashboard_id, expected_status=status.HTTP_200_OK)

    def test_soft_delete_can_be_reversed_with_patch(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard"})
        self.dashboard_api.create_insight({"dashboards": [dashboard_id]})
        self.dashboard_api.create_text_tile(dashboard_id)

        dashboard_json = self.dashboard_api.get_dashboard(dashboard_id, expected_status=status.HTTP_200_OK)
        self.assertEqual(len(dashboard_json["tiles"]), 2, dashboard_json["tiles"])

        self.dashboard_api.soft_delete(dashboard_id, "dashboards")

        self.dashboard_api.update_dashboard(dashboard_id, {"deleted": False})

        dashboard_json = self.dashboard_api.get_dashboard(dashboard_id, expected_status=status.HTTP_200_OK)
        self.assertEqual(len(dashboard_json["tiles"]), 2, dashboard_json["tiles"])

    def test_soft_delete_does_not_delete_tiles(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "to delete"})
        other_dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "not to delete"})
        insight_one_id, _ = self.dashboard_api.create_insight({"dashboards": [dashboard_id, other_dashboard_id]})
        insight_two_id, _ = self.dashboard_api.create_insight({"dashboards": [dashboard_id]})
        self.dashboard_api.create_text_tile(dashboard_id)

        self.dashboard_api.soft_delete(dashboard_id, "dashboards")

        insight_one_json = self.dashboard_api.get_insight(insight_id=insight_one_id)
        assert [t["dashboard_id"] for t in insight_one_json["dashboard_tiles"]] == [other_dashboard_id]
        assert insight_one_json["dashboards"] == [other_dashboard_id]
        assert insight_one_json["deleted"] is False
        insight_two_json = self.dashboard_api.get_insight(insight_id=insight_two_id)
        assert [t["dashboard_id"] for t in insight_two_json["dashboard_tiles"]] == []
        assert insight_two_json["dashboards"] == []
        assert insight_two_json["deleted"] is False

    def test_can_move_tile_between_dashboards(self) -> None:
        filter_dict = {
            "events": [{"id": "$pageview"}],
            "properties": [{"key": "$browser", "value": "Mac OS X"}],
            "insight": "TRENDS",
        }

        dashboard_one_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard one"})
        dashboard_two_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard two"})
        insight_id, _ = self.dashboard_api.create_insight({"filters": filter_dict, "dashboards": [dashboard_one_id]})

        dashboard_one = self.dashboard_api.get_dashboard(dashboard_one_id)
        assert len(dashboard_one["tiles"]) == 1
        dashboard_two = self.dashboard_api.get_dashboard(dashboard_two_id)
        assert len(dashboard_two["tiles"]) == 0

        patch_response = self.client.patch(
            f"/api/projects/{self.team.id}/dashboards/{dashboard_one_id}/move_tile",
            {"tile": dashboard_one["tiles"][0], "toDashboard": dashboard_two_id},
        )
        assert patch_response.status_code == status.HTTP_200_OK
        assert patch_response.json()["tiles"] == []

        dashboard_two = self.dashboard_api.get_dashboard(dashboard_two_id)
        assert len(dashboard_two["tiles"]) == 1
        assert dashboard_two["tiles"][0]["insight"]["id"] == insight_id

    def test_relations_on_insights_when_dashboards_were_deleted(self) -> None:
        filter_dict = {
            "events": [{"id": "$pageview"}],
            "properties": [{"key": "$browser", "value": "Mac OS X"}],
            "insight": "TRENDS",
        }

        dashboard_one_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard one"})
        dashboard_two_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard two"})
        insight_id, _ = self.dashboard_api.create_insight(
            {"filters": filter_dict, "dashboards": [dashboard_one_id, dashboard_two_id]}
        )

        self.dashboard_api.soft_delete(dashboard_one_id, "dashboards")

        insight_after_dashboard_deletion = self.dashboard_api.get_insight(insight_id)
        assert insight_after_dashboard_deletion["dashboards"] == [dashboard_two_id]

        dashboard_two_json = self.dashboard_api.get_dashboard(dashboard_two_id)
        expected_dashboards_on_insight = dashboard_two_json["tiles"][0]["insight"]["dashboards"]
        assert expected_dashboards_on_insight == [dashboard_two_id]

    @patch("posthog.api.dashboards.dashboard.report_user_action")
    def test_create_from_template_json(self, mock_capture) -> None:
        response = self.client.post(
            f"/api/projects/{self.team.id}/dashboards/create_from_template_json",
            {"template": valid_template, "creation_context": "onboarding"},
            headers={"Referer": "https://posthog.com/my-referer", "X-Posthog-Session-Id": "my-session-id"},
        )
        self.assertEqual(response.status_code, 200, response.content)

        dashboard_id = response.json()["id"]

        dashboard = self.dashboard_api.get_dashboard(dashboard_id)

        self.assertEqual(dashboard["name"], valid_template["template_name"], dashboard)
        self.assertEqual(dashboard["description"], valid_template["dashboard_description"])
        self.assertEqual(
            dashboard["created_by"], dashboard["created_by"] | {"first_name": "", "email": "user1@posthog.com"}
        )

        self.assertEqual(len(dashboard["tiles"]), 1)

        mock_capture.assert_called_once_with(
            self.user,
            "dashboard created",
            {
                "$current_url": "https://posthog.com/my-referer",
                "$session_id": "my-session-id",
                "created_at": mock.ANY,
                "creation_context": "onboarding",
                "dashboard_id": dashboard["id"],
                "duplicated": False,
                "from_template": True,
                "has_description": True,
                "is_shared": False,
                "item_count": 1,
                "pinned": False,
                "tags_count": 0,
                "template_key": valid_template["template_name"],
            },
        )

    def test_create_from_template_json_must_provide_at_least_one_tile(self) -> None:
        template: dict = {**valid_template, "tiles": []}

        response = self.client.post(
            f"/api/projects/{self.team.id}/dashboards/create_from_template_json",
            {"template": template},
        )
        assert response.status_code == 400, response.json()

    def test_create_from_template_json_can_provide_text_tile(self) -> None:
        template: dict = {
            **valid_template,
            "tiles": [{"type": "TEXT", "body": "hello world", "layouts": {}}],
        }

        response = self.client.post(
            f"/api/projects/{self.team.id}/dashboards/create_from_template_json",
            {"template": template},
        )
        assert response.status_code == 200

        assert response.json()["tiles"] == [
            {
                "color": None,
                "filters_overrides": {},
                "id": ANY,
                "insight": None,
                "is_cached": False,
                "last_refresh": None,
                "layouts": {},
                "order": 0,
                "text": {
                    "body": "hello world",
                    "created_by": None,
                    "id": ANY,
                    "last_modified_at": ANY,
                    "last_modified_by": None,
                    "team": self.team.pk,
                },
            },
        ]

    def test_create_from_template_json_can_provide_query_tile(self) -> None:
        template: dict = {
            **valid_template,
            # client provides an incorrect "empty" filter alongside a query
            "tiles": [
                {
                    "type": "INSIGHT",
                    "query": {
                        "kind": "DataTableNode",
                        "columns": ["person", "id", "created_at", "person.$delete"],
                        "source": {
                            "kind": "EventsQuery",
                            "select": ["*"],
                        },
                    },
                    "filters": {"date_from": None},
                    "layouts": {},
                }
            ],
        }

        response = self.client.post(
            f"/api/projects/{self.team.id}/dashboards/create_from_template_json",
            {"template": template},
        )
        assert response.status_code == 200

        self_user_basic_serialized = {
            "id": self.user.id,
            "uuid": str(self.user.uuid),
            "distinct_id": self.user.distinct_id,
            "first_name": self.user.first_name,
            "last_name": self.user.last_name,
            "email": self.user.email,
            "is_email_verified": None,
            "hedgehog_config": None,
            "role_at_organization": None,
        }

        assert response.json()["tiles"] == [
            {
                "color": None,
                "filters_overrides": {},
                "id": ANY,
                "insight": {
                    "columns": None,
                    "created_at": ANY,
                    "created_by": self_user_basic_serialized,
                    "dashboard_tiles": [
                        {
                            "dashboard_id": response.json()["id"],
                            "deleted": None,
                            "id": ANY,
                        }
                    ],
                    "dashboards": [response.json()["id"]],
                    "deleted": False,
                    "derived_name": None,
                    "description": None,
                    "effective_privilege_level": 37,
                    "effective_restriction_level": 21,
                    "favorited": False,
                    "filters": {},
                    "filters_hash": ANY,
                    "hasMore": None,
                    "id": ANY,
                    "is_cached": False,
                    "is_sample": True,
                    "last_modified_at": ANY,
                    "last_modified_by": self_user_basic_serialized,
                    "last_viewed_at": ANY,
                    "last_refresh": None,
                    "name": None,
                    "next_allowed_client_refresh": None,
                    "alerts": [],
                    "cache_target_age": ANY,
                    "order": None,
                    "query": {
                        "kind": "DataTableNode",
                        "columns": ["person", "id", "created_at", "person.$delete"],
                        "source": {
                            "kind": "EventsQuery",
                            "select": ["*"],
                        },
                    },
                    "query_status": None,
                    "result": None,
                    "saved": False,
                    "short_id": ANY,
                    "tags": [],
                    "timezone": None,
                    "updated_at": ANY,
                    "user_access_level": "manager",
                    "hogql": ANY,
                    "types": ANY,
                },
                "is_cached": False,
                "last_refresh": None,
                "layouts": {},
                "order": 0,
                "text": None,
            },
        ]

    def test_invalid_template_receives_400_response(self) -> None:
        invalid_template = {"not a": "template"}

        response = self.client.post(
            f"/api/projects/{self.team.id}/dashboards/create_from_template_json",
            {"template": invalid_template},
        )
        assert response.status_code == 400, response.json()

        response_data = response.json()
        assert response_data["type"] == "validation_error"
        assert response_data["code"] == "invalid_input"
        assert response_data["attr"] is None

        # Check that the error message contains the key validation error information
        detail = response_data["detail"]
        assert "'template_name' is a required property" in detail
        assert "Failed validating 'required' in schema" in detail
        assert "{'not a': 'template'}" in detail

    def test_dashboard_duplication_breakdown_histogram_bin_count_none(self):
        existing_dashboard = Dashboard.objects.create(team=self.team, name="existing dashboard", created_by=self.user)
        insight1 = Insight.objects.create(
            filters={
                "name": "test1",
                "breakdown_histogram_bin_count": None,
                "breakdown_limit": None,
                "breakdown_hide_other_aggregation": None,
            },
            team=self.team,
            last_refresh=now(),
        )
        tile1 = DashboardTile.objects.create(dashboard=existing_dashboard, insight=insight1)
        _, response = self.dashboard_api.create_dashboard({"name": "another", "use_dashboard": existing_dashboard.pk})

        self.assertEqual(response["creation_mode"], "duplicate")
        self.assertEqual(len(response["tiles"]), len(existing_dashboard.insights.all()))

        existing_dashboard_item_id_set = {tile1.pk}
        response_item_id_set = {x.get("id", None) for x in response["tiles"]}
        # check both sets are disjoint to verify that the new items' ids are different than the existing items

        self.assertTrue(existing_dashboard_item_id_set.isdisjoint(response_item_id_set))

        for item in response["tiles"]:
            self.assertNotEqual(item.get("dashboard", None), existing_dashboard.pk)

    def test_dashboard_variables(self):
        variable = InsightVariable.objects.create(
            team=self.team, name="Test 1", code_name="test_1", default_value="some_default_value", type="String"
        )
        dashboard = Dashboard.objects.create(
            team=self.team,
            name="dashboard 1",
            created_by=self.user,
            variables={
                str(variable.id): {
                    "code_name": variable.code_name,
                    "variableId": str(variable.id),
                    "value": "some override value",
                }
            },
        )
        insight = Insight.objects.create(
            filters={},
            query={
                "kind": "DataVisualizationNode",
                "source": {
                    "kind": "HogQLQuery",
                    "query": "select {variables.test_1}",
                    "variables": {
                        str(variable.id): {
                            "code_name": variable.code_name,
                            "variableId": str(variable.id),
                        }
                    },
                },
                "chartSettings": {},
                "tableSettings": {},
            },
            team=self.team,
            last_refresh=now(),
        )
        DashboardTile.objects.create(dashboard=dashboard, insight=insight)

        response_data = self.dashboard_api.get_dashboard(dashboard.pk)

        assert response_data["variables"] is not None
        assert isinstance(response_data["variables"], dict)
        assert len(response_data["variables"].keys()) == 1
        for key, value in response_data["variables"].items():
            assert key == str(variable.id)
            assert value["code_name"] == variable.code_name
            assert value["variableId"] == str(variable.id)
            assert value["value"] == "some override value"

    def test_dashboard_variables_stale(self):
        # if a variable is deleted/updated, the dashboard should not show the stale variable

        variable = InsightVariable.objects.create(
            team=self.team, name="Test 1", code_name="test_1", default_value="some_default_value", type="String"
        )
        dashboard = Dashboard.objects.create(
            team=self.team,
            name="dashboard 1",
            created_by=self.user,
            variables={
                str(variable.id): {
                    "code_name": variable.code_name,
                    "variableId": str(variable.id),
                    "value": "some override value",
                }
            },
        )
        insight = Insight.objects.create(
            filters={},
            query={
                "kind": "DataVisualizationNode",
                "source": {
                    "kind": "HogQLQuery",
                    "query": "select {variables.test_1}",
                    "variables": {
                        str(variable.id): {
                            "code_name": variable.code_name,
                            "variableId": str(variable.id),
                        }
                    },
                },
                "chartSettings": {},
                "tableSettings": {},
            },
            team=self.team,
            last_refresh=now(),
        )
        DashboardTile.objects.create(dashboard=dashboard, insight=insight)

        response_data = self.dashboard_api.get_dashboard(dashboard.pk, query_params={"refresh": "blocking"})

        assert response_data["variables"] is not None
        assert isinstance(response_data["variables"], dict)
        assert len(response_data["variables"].keys()) == 1
        for key, value in response_data["variables"].items():
            assert key == str(variable.id)
            assert value["code_name"] == variable.code_name
            assert value["variableId"] == str(variable.id)
            assert value["value"] == "some override value"

        assert response_data["tiles"][0]["insight"]["query"]["source"]["variables"] is not None
        assert response_data["tiles"][0]["insight"]["query"]["source"]["variables"] == {
            str(variable.id): {
                "code_name": variable.code_name,
                "value": "some override value",
                "variableId": str(variable.id),
            }
        }
        assert response_data["tiles"][0]["insight"]["result"][0][0] == "some override value"

        variable.delete()

        # recreate the variable
        variable2 = InsightVariable.objects.create(
            team=self.team, name="Test 1", code_name="test_1", default_value="some_default_value", type="String"
        )

        response_data = self.dashboard_api.get_dashboard(dashboard.pk, query_params={"refresh": "blocking"})

        assert response_data["variables"] is not None
        assert isinstance(response_data["variables"], dict)
        assert len(response_data["variables"].keys()) == 1
        for key, value in response_data["variables"].items():
            assert key == str(variable2.id)
            assert value["code_name"] == variable2.code_name
            assert value["variableId"] == str(variable2.id)
            assert value["value"] == "some override value"

        assert response_data["tiles"][0]["insight"]["query"]["source"]["variables"] is not None
        assert response_data["tiles"][0]["insight"]["query"]["source"]["variables"] == {
            str(variable2.id): {
                "code_name": variable2.code_name,
                "value": "some override value",
                "variableId": str(variable2.id),
            }
        }
        assert response_data["tiles"][0]["insight"]["result"][0][0] == "some override value"

    def test_dashboard_access_control_filtering(self) -> None:
        """Test that dashboards are properly filtered based on access control."""

        user2 = User.objects.create_and_join(self.organization, "test2@posthog.com", None)

        visible_dashboard = Dashboard.objects.create(
            team=self.team,
            name="Public Dashboard",
            created_by=self.user,
        )
        hidden_dashboard = Dashboard.objects.create(
            team=self.team,
            name="Hidden Dashboard",
            created_by=self.user,
        )
        AccessControl.objects.create(
            resource="dashboard", resource_id=hidden_dashboard.id, team=self.team, access_level="none"
        )

        # Verify we can access visible dashboards
        self.client.force_login(user2)
        response = self.client.get(f"/api/projects/{self.team.pk}/dashboards/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        dashboard_ids = [dashboard["id"] for dashboard in response.json()["results"]]
        self.assertIn(visible_dashboard.id, dashboard_ids)
        self.assertNotIn(hidden_dashboard.id, dashboard_ids)

        # Verify we can access all dashboards as creator
        self.client.force_login(self.user)
        response = self.client.get(f"/api/projects/{self.team.pk}/dashboards/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn(visible_dashboard.id, [dashboard["id"] for dashboard in response.json()["results"]])
        self.assertIn(hidden_dashboard.id, [dashboard["id"] for dashboard in response.json()["results"]])

    def test_dashboard_create_in_folder(self):
        create_response = self.client.post(
            f"/api/projects/{self.team.id}/dashboards/",
            {
                "name": "My Foldered Dashboard",
                "_create_in_folder": "Marketing/Website/Conversion",
            },
            format="json",
        )
        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED, create_response.json())
        created_dashboard_id = create_response.json()["id"]

        dashboard = Dashboard.objects.get(id=created_dashboard_id)
        assert dashboard.name == "My Foldered Dashboard"

        from posthog.models.file_system.file_system import FileSystem

        fs_entry = FileSystem.objects.filter(
            team=self.team,
            type="dashboard",
            ref=str(created_dashboard_id),
        ).first()
        assert fs_entry is not None, "Expected a FileSystem entry for this new Dashboard."
        assert "Marketing/Website/Conversion" in fs_entry.path, "Folder path is missing or incorrect."

    def test_dashboard_variable_overrides(self):
        var1 = InsightVariable.objects.create(
            team=self.team, name="Variable 1", code_name="variable_1", default_value=10, type="Number"
        )
        var2 = InsightVariable.objects.create(
            team=self.team, name="Variable 2", code_name="variable_2", default_value=10, type="Number"
        )
        var3 = InsightVariable.objects.create(
            team=self.team, name="Variable 3", code_name="variable_3", default_value=10, type="Number"
        )
        var4 = InsightVariable.objects.create(
            team=self.team, name="Variable 4", code_name="variable_4", default_value=10, type="Number"
        )

        dashboard = Dashboard.objects.create(
            name="Insight variables",
            team=self.team,
            variables={
                str(var2.id): {
                    "code_name": var2.code_name,
                    "variableId": str(var2.id),
                    "value": 20,  # override
                }
            },
        )

        insight1 = Insight.objects.create(
            team=self.team,
            name="Variable default",
            description="Shows the default value of the variable.",
            query={
                "kind": "DataVisualizationNode",
                "source": {
                    "kind": "HogQLQuery",
                    "query": "SELECT {variables.variable_1}",
                    "variables": {
                        str(var1.id): {
                            "code_name": var1.code_name,
                            "variableId": str(var1.id),
                        }
                    },
                },
                "display": "BoldNumber",
            },
        )
        insight2 = Insight.objects.create(
            team=self.team,
            name="Dashboard override",
            description="Shows a dashboard override of the variable.",
            query={
                "kind": "DataVisualizationNode",
                "source": {
                    "kind": "HogQLQuery",
                    "query": "SELECT {variables.variable_2}",
                    "variables": {
                        str(var2.id): {
                            "code_name": var2.code_name,
                            "variableId": str(var2.id),
                        }
                    },
                },
                "display": "BoldNumber",
            },
        )
        insight3 = Insight.objects.create(
            team=self.team,
            name="Insight override",
            description="Shows an insight override of the variable.",
            query={
                "kind": "DataVisualizationNode",
                "source": {
                    "kind": "HogQLQuery",
                    "query": "SELECT {variables.variable_3}",
                    "variables": {
                        str(var3.id): {
                            "code_name": var3.code_name,
                            "variableId": str(var3.id),
                            "value": 30,  # override
                        }
                    },
                },
                "display": "BoldNumber",
            },
        )
        insight4 = Insight.objects.create(
            team=self.team,
            name="Temporary override",
            description="Shows a temporary variable override through the URL.",
            query={
                "kind": "DataVisualizationNode",
                "source": {
                    "kind": "HogQLQuery",
                    "query": "SELECT {variables.variable_4}",
                    "variables": {
                        str(var4.id): {
                            "code_name": var4.code_name,
                            "variableId": str(var4.id),
                        }
                    },
                },
                "display": "BoldNumber",
            },
        )
        # TODO: adding one erroring insight fails the whole dashboard
        # insight5 = Insight.objects.create(
        #     team=self.team,
        #     name="Missing variable",
        #     description="Shows a validatione error for a missing variable.",
        #     query={
        #         "kind": "DataVisualizationNode",
        #         "source": {
        #             "kind": "HogQLQuery",
        #             "query": "SELECT {variables.var_missing}",
        #             "variables": {
        #                 "missing_variable_id": {
        #                     "code_name": "var_missing",
        #                     "variableId": "missing_variable_id",
        #                 }
        #             },
        #         },
        #         "display": "BoldNumber",
        #     },
        # )

        DashboardTile.objects.create(insight=insight1, dashboard=dashboard)
        DashboardTile.objects.create(insight=insight2, dashboard=dashboard)
        DashboardTile.objects.create(insight=insight3, dashboard=dashboard)
        DashboardTile.objects.create(insight=insight4, dashboard=dashboard)
        # DashboardTile.objects.create(insight=insight5, dashboard=dashboard)
        dashboard.save()

        response_data = self.dashboard_api.get_dashboard(
            dashboard.pk,
            query_params={
                "refresh": "blocking",
                "variables_override": json.dumps(
                    {
                        str(var4.id): {
                            "code_name": var4.code_name,
                            "variableId": str(var4.id),
                            "value": 40,  # temporary override
                        }
                    }
                ),
            },
        )

        # We test five different configurations of insight variables on dashboards:
        # 1. The default value of the variable (should be 10).
        assert response_data["tiles"][0]["insight"]["name"] == "Variable default"
        assert response_data["tiles"][0]["insight"]["result"][0][0] == 10

        # 2. The dashboard overriding the variable value (should be 20).
        assert response_data["tiles"][1]["insight"]["name"] == "Dashboard override"
        assert response_data["tiles"][1]["insight"]["result"][0][0] == 20

        # 3. The insight overriding the variable value (should be 30).
        assert response_data["tiles"][2]["insight"]["name"] == "Insight override"
        assert response_data["tiles"][2]["insight"]["result"][0][0] == 30

        # 4. A temporary variable override, through the URL (should be 40).
        # TODO: Currently the temporary overrides need to have all dashboard overrides,
        # as they replace them entirely. Might want to change this.
        assert response_data["tiles"][3]["insight"]["name"] == "Temporary override"
        assert response_data["tiles"][3]["insight"]["result"][0][0] == 40

        # 5. A missing variable, which should raise a validation error.
        # tbd

    def test_persisted_fields_consistency_between_regular_and_sse_endpoints(self):
        dashboard_filters = {"date_from": "-24h", "properties": [{"key": "test_prop", "value": "test_value"}]}

        variable = InsightVariable.objects.create(
            team=self.team, name="Test Variable", code_name="test_var", default_value="default_value", type="String"
        )
        dashboard_variables = {
            str(variable.id): {
                "code_name": variable.code_name,
                "variableId": str(variable.id),
                "value": "override_value",
            }
        }

        dashboard = Dashboard.objects.create(
            team=self.team,
            name="Test Dashboard",
            created_by=self.user,
            filters=dashboard_filters,
            variables=dashboard_variables,
        )

        insight = Insight.objects.create(
            filters={},
            query={
                "kind": "DataVisualizationNode",
                "source": {
                    "kind": "HogQLQuery",
                    "query": "select {variables.test_var}",
                    "variables": {
                        str(variable.id): {
                            "code_name": variable.code_name,
                            "variableId": str(variable.id),
                        }
                    },
                },
                "chartSettings": {},
                "tableSettings": {},
            },
            team=self.team,
        )
        DashboardTile.objects.create(dashboard=dashboard, insight=insight)
        dashboard_id = dashboard.id

        regular_response = self.dashboard_api.get_dashboard(dashboard_id)

        sse_response = self.client.get(f"/api/projects/{self.team.id}/dashboards/{dashboard_id}/stream_tiles/")
        self.assertEqual(sse_response.status_code, 200)

        sse_content = b"".join(sse_response.streaming_content).decode("utf-8")  # type: ignore

        metadata_line = None
        for line in sse_content.split("\n"):
            if line.startswith("data: ") and '"type":"metadata"' in line:
                metadata_line = line[6:]
                break

        self.assertIsNotNone(metadata_line, f"Could not find metadata in SSE response. Content: {repr(sse_content)}")
        sse_data = json.loads(metadata_line)  # type: ignore
        sse_dashboard = sse_data["dashboard"]

        self.assertEqual(
            regular_response.get("persisted_filters"),
            sse_dashboard.get("persisted_filters"),
            "persisted_filters should be the same in both endpoints",
        )
        self.assertEqual(
            regular_response.get("persisted_variables"),
            sse_dashboard.get("persisted_variables"),
            "persisted_variables should be the same in both endpoints",
        )
        self.assertEqual(
            regular_response.get("team_id"),
            sse_dashboard.get("team_id"),
            "team_id should be the same in both endpoints",
        )

        self.assertEqual(regular_response["persisted_filters"], dashboard_filters)
        self.assertEqual(sse_dashboard["persisted_filters"], dashboard_filters)
        self.assertEqual(regular_response["persisted_variables"], dashboard_variables)
        self.assertEqual(sse_dashboard["persisted_variables"], dashboard_variables)
