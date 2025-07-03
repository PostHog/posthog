import json
from datetime import datetime, timedelta
from typing import Any, Optional
from unittest import mock
from unittest.case import skip
from unittest.mock import ANY, patch
from zoneinfo import ZoneInfo

from django.test import override_settings
from django.utils import timezone
from freezegun import freeze_time
from parameterized import parameterized
from rest_framework import status

from posthog import settings
from posthog.api.test.dashboards import DashboardAPI
from posthog.caching.insight_cache import update_cache
from posthog.caching.insight_caching_state import TargetCacheAge
from posthog.hogql.query import execute_hogql_query
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.models import (
    Cohort,
    Dashboard,
    DashboardTile,
    Filter,
    Insight,
    InsightViewed,
    OrganizationMembership,
    Person,
    SharingConfiguration,
    Team,
    Text,
    User,
)
from ee.models.rbac.access_control import AccessControl
from posthog.models.insight_caching_state import InsightCachingState
from posthog.models.insight_variable import InsightVariable
from posthog.models.project import Project
from posthog.schema import (
    DataTableNode,
    DataVisualizationNode,
    DateRange,
    EventPropertyFilter,
    EventsNode,
    EventsQuery,
    FilterLogicalOperator,
    HogQLFilters,
    HogQLQuery,
    InsightNodeKind,
    InsightVizNode,
    NodeKind,
    PropertyGroupFilter,
    PropertyGroupFilterValue,
    TrendsQuery,
)
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    FuzzyInt,
    QueryMatchingTest,
    _create_event,
    _create_person,
    also_test_with_materialized_columns,
    flush_persons_and_events,
    snapshot_clickhouse_queries,
    snapshot_postgres_queries,
)
from posthog.test.db_context_capturing import capture_db_queries


class TestInsight(ClickhouseTestMixin, APIBaseTest, QueryMatchingTest):
    maxDiff = None

    def setUp(self) -> None:
        super().setUp()
        self.dashboard_api = DashboardAPI(self.client, self.team, self.assertEqual)

    def test_get_insight_items(self) -> None:
        filter_dict = {
            "events": [{"id": "$pageview"}],
            "properties": [{"key": "$browser", "value": "Mac OS X"}],
        }

        Insight.objects.create(
            filters=Filter(data=filter_dict).to_dict(),
            team=self.team,
            created_by=self.user,
        )

        # create without user
        Insight.objects.create(filters=Filter(data=filter_dict).to_dict(), team=self.team)

        response = self.client.get(f"/api/projects/{self.team.id}/insights/", data={"user": "true"}).json()

        self.assertEqual(len(response["results"]), 1)

    def test_get_insight_items_all_environments_included(self) -> None:
        filter_dict = {
            "events": [{"id": "$pageview"}],
            "properties": [{"key": "$browser", "value": "Mac OS X"}],
        }

        other_team_in_project = Team.objects.create(organization=self.organization, project=self.project)
        _, team_in_other_project = Project.objects.create_with_team(
            organization=self.organization, initiating_user=self.user
        )

        insight_a = Insight.objects.create(
            filters=Filter(data=filter_dict).to_dict(),
            team=self.team,
            created_by=self.user,
        )
        insight_b = Insight.objects.create(
            filters=Filter(data=filter_dict).to_dict(),
            team=other_team_in_project,
            created_by=self.user,
        )
        Insight.objects.create(
            filters=Filter(data=filter_dict).to_dict(),
            team=team_in_other_project,
            created_by=self.user,
        )

        # All of these three ways should return the same set of insights,
        # i.e. all insights in the test project regardless of environment
        response_project = self.client.get(f"/api/projects/{self.project.id}/insights/").json()
        response_env_current = self.client.get(f"/api/environments/{self.team.id}/insights/").json()
        response_env_other = self.client.get(f"/api/environments/{other_team_in_project.id}/insights/").json()

        self.assertEqual({insight["id"] for insight in response_project["results"]}, {insight_a.id, insight_b.id})
        self.assertEqual({insight["id"] for insight in response_env_current["results"]}, {insight_a.id, insight_b.id})
        self.assertEqual({insight["id"] for insight in response_env_other["results"]}, {insight_a.id, insight_b.id})

    @patch("posthoganalytics.capture")
    def test_created_updated_and_last_modified(self, mock_capture: mock.Mock) -> None:
        alt_user = User.objects.create_and_join(self.organization, "team2@posthog.com", None)
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
        alt_user_basic_serialized = {
            "id": alt_user.id,
            "uuid": str(alt_user.uuid),
            "distinct_id": alt_user.distinct_id,
            "first_name": alt_user.first_name,
            "last_name": alt_user.last_name,
            "email": alt_user.email,
            "is_email_verified": None,
            "hedgehog_config": None,
            "role_at_organization": None,
        }

        # Newly created insight should have created_at being the current time, and same last_modified_at
        # Fields created_by and last_modified_by should be set to the current user
        with freeze_time("2021-08-23T12:00:00Z"):
            response_1 = self.client.post(
                f"/api/projects/{self.team.id}/insights/",
                {"name": "test"},
                headers={"Referer": "https://posthog.com/my-referer", "X-Posthog-Session-Id": "my-session-id"},
            )
            self.assertEqual(response_1.status_code, status.HTTP_201_CREATED)
            self.assertDictContainsSubset(
                {
                    "created_at": "2021-08-23T12:00:00Z",
                    "created_by": self_user_basic_serialized,
                    "updated_at": "2021-08-23T12:00:00Z",
                    "last_modified_at": "2021-08-23T12:00:00Z",
                    "last_modified_by": self_user_basic_serialized,
                },
                response_1.json(),
            )
            mock_capture.assert_called_once_with(
                "insight created",
                distinct_id=self.user.distinct_id,
                properties={
                    "insight_id": response_1.json()["short_id"],
                    "$current_url": "https://posthog.com/my-referer",
                    "$session_id": "my-session-id",
                },
                groups=ANY,
            )
            mock_capture.reset_mock()

        insight_id = response_1.json()["id"]

        # Updating fields that don't change the substance of the insight should affect updated_at
        # BUT NOT last_modified_at or last_modified_by
        with freeze_time("2021-09-20T12:00:00Z"):
            response_2 = self.client.patch(
                f"/api/projects/{self.team.id}/insights/{insight_id}",
                {"favorited": True},
                headers={"Referer": "https://posthog.com/my-referer", "X-Posthog-Session-Id": "my-session-id"},
            )
            self.assertEqual(response_2.status_code, status.HTTP_200_OK)
            self.assertDictContainsSubset(
                {
                    "created_at": "2021-08-23T12:00:00Z",
                    "created_by": self_user_basic_serialized,
                    "updated_at": "2021-09-20T12:00:00Z",
                    "last_modified_at": "2021-08-23T12:00:00Z",
                    "last_modified_by": self_user_basic_serialized,
                },
                response_2.json(),
            )
            insight_short_id = response_2.json()["short_id"]
            mock_capture.assert_called_once_with(
                "insight updated",
                distinct_id=self.user.distinct_id,
                properties={
                    "insight_id": insight_short_id,
                    "$current_url": "https://posthog.com/my-referer",
                    "$session_id": "my-session-id",
                },
                groups=ANY,
            )
            mock_capture.reset_mock()

        # Updating fields that DO change the substance of the insight should affect updated_at
        # AND last_modified_at plus last_modified_by
        with freeze_time("2021-10-21T12:00:00Z"):
            response_3 = self.client.patch(
                f"/api/projects/{self.team.id}/insights/{insight_id}",
                {"filters": {"events": []}},
            )
            self.assertEqual(response_3.status_code, status.HTTP_200_OK)
            self.assertDictContainsSubset(
                {
                    "created_at": "2021-08-23T12:00:00Z",
                    "created_by": self_user_basic_serialized,
                    "updated_at": "2021-10-21T12:00:00Z",
                    "last_modified_at": "2021-10-21T12:00:00Z",
                    "last_modified_by": self_user_basic_serialized,
                },
                response_3.json(),
            )
        with freeze_time("2021-12-23T12:00:00Z"):
            response_4 = self.client.patch(f"/api/projects/{self.team.id}/insights/{insight_id}", {"name": "XYZ"})
            self.assertEqual(response_4.status_code, status.HTTP_200_OK)
            self.assertDictContainsSubset(
                {
                    "created_at": "2021-08-23T12:00:00Z",
                    "created_by": self_user_basic_serialized,
                    "updated_at": "2021-12-23T12:00:00Z",
                    "last_modified_at": "2021-12-23T12:00:00Z",
                    "last_modified_by": self_user_basic_serialized,
                },
                response_4.json(),
            )

        # Field last_modified_by is updated when another user makes a material change
        self.client.force_login(alt_user)
        with freeze_time("2022-01-01T12:00:00Z"):
            response_5 = self.client.patch(
                f"/api/projects/{self.team.id}/insights/{insight_id}",
                {"description": "Lorem ipsum."},
            )
            self.assertEqual(response_5.status_code, status.HTTP_200_OK)
            self.assertDictContainsSubset(
                {
                    "created_at": "2021-08-23T12:00:00Z",
                    "created_by": self_user_basic_serialized,
                    "updated_at": "2022-01-01T12:00:00Z",
                    "last_modified_at": "2022-01-01T12:00:00Z",
                    "last_modified_by": alt_user_basic_serialized,
                },
                response_5.json(),
            )

    def test_get_saved_insight_items(self) -> None:
        filter_dict = {
            "events": [{"id": "$pageview"}],
            "properties": [{"key": "$browser", "value": "Mac OS X"}],
        }

        Insight.objects.create(
            filters=Filter(data=filter_dict).to_dict(),
            saved=True,
            team=self.team,
            created_by=self.user,
        )

        # create without saved
        Insight.objects.create(
            filters=Filter(data=filter_dict).to_dict(),
            team=self.team,
            created_by=self.user,
        )

        # create without user
        Insight.objects.create(filters=Filter(data=filter_dict).to_dict(), team=self.team)

        response = self.client.get(
            f"/api/projects/{self.team.id}/insights/",
            data={"saved": "true", "user": "true"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assertEqual(len(response.json()["results"]), 1)
        self.assertEqual(len(response.json()["results"][0]["short_id"]), 8)

    def test_get_favorited_insight_items(self) -> None:
        filter_dict = {
            "events": [{"id": "$pageview"}],
            "properties": [{"key": "$browser", "value": "Mac OS X"}],
        }

        Insight.objects.create(
            filters=Filter(data=filter_dict).to_dict(),
            favorited=True,
            team=self.team,
            created_by=self.user,
        )

        # create without favorited
        Insight.objects.create(
            filters=Filter(data=filter_dict).to_dict(),
            team=self.team,
            created_by=self.user,
        )

        # create without user
        Insight.objects.create(filters=Filter(data=filter_dict).to_dict(), team=self.team)

        response = self.client.get(f"/api/projects/{self.team.id}/insights/?favorited=true&user=true")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assertEqual(len(response.json()["results"]), 1)
        self.assertEqual((response.json()["results"][0]["favorited"]), True)

    def test_get_insight_in_dashboard_context(self) -> None:
        filter_dict = {
            "events": [{"id": "$pageview"}],
            "properties": [{"key": "$browser", "value": "Mac OS X"}],
        }

        dashboard_id, _ = self.dashboard_api.create_dashboard(
            {"name": "the dashboard", "filters": {"date_from": "-180d"}}
        )

        insight_id, _ = self.dashboard_api.create_insight(
            {"filters": filter_dict, "name": "insight", "dashboards": [dashboard_id]}
        )

        insight_in_isolation = self.dashboard_api.get_insight(insight_id)
        self.assertIsNotNone(insight_in_isolation.get("filters_hash", None))

        insight_on_dashboard = self.dashboard_api.get_insight(insight_id, query_params={"from_dashboard": dashboard_id})
        self.assertIsNotNone(insight_on_dashboard.get("filters_hash", None))

        self.assertNotEqual(insight_in_isolation["filters_hash"], insight_on_dashboard["filters_hash"])

    def test_get_insight_in_shared_context(self) -> None:
        filter_dict = {
            "events": [{"id": "$pageview"}],
            "properties": [{"key": "$browser", "value": "Mac OS X"}],
        }

        dashboard_id, _ = self.dashboard_api.create_dashboard(
            {"name": "the dashboard", "filters": {"date_from": "-180d"}}
        )

        insight_id, _ = self.dashboard_api.create_insight(
            {"filters": filter_dict, "name": "insight", "dashboards": [dashboard_id]}
        )
        sharing_config = SharingConfiguration.objects.create(team=self.team, insight_id=insight_id, enabled=True)

        valid_url = f"{settings.SITE_URL}/shared/{sharing_config.access_token}"

        with patch(
            "posthog.caching.calculate_results.calculate_for_query_based_insight"
        ) as calculate_for_query_based_insight:
            self.client.get(valid_url)
            calculate_for_query_based_insight.assert_called_once_with(
                mock.ANY,
                dashboard=mock.ANY,
                execution_mode=ExecutionMode.EXTENDED_CACHE_CALCULATE_ASYNC_IF_STALE,
                team=self.team,
                user=mock.ANY,
                filters_override=None,
                variables_override=None,
            )

        with patch(
            "posthog.caching.calculate_results.calculate_for_query_based_insight"
        ) as calculate_for_query_based_insight:
            self.client.get(valid_url, data={"refresh": True})
            calculate_for_query_based_insight.assert_called_once_with(
                mock.ANY,
                dashboard=mock.ANY,
                execution_mode=ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE,
                team=self.team,
                user=mock.ANY,
                filters_override=None,
                variables_override=None,
            )

    def test_get_insight_by_short_id(self) -> None:
        filter_dict = {"events": [{"id": "$pageview"}]}

        Insight.objects.create(
            filters=Filter(data=filter_dict).to_dict(),
            team=self.team,
            short_id="12345678",
        )

        # We need at least one more insight to make sure we're not just getting the first one
        Insight.objects.create(
            filters=Filter(data=filter_dict).to_dict(),
            team=self.team,
            short_id="not-that-one",
        )

        # Red herring: Should be ignored because it's not on the current team (even though the user has access)
        new_team = Team.objects.create(organization=self.organization)
        Insight.objects.create(
            filters=Filter(data=filter_dict).to_dict(),
            team=new_team,
            short_id="12345678",
        )

        response = self.client.get(f"/api/projects/{self.team.id}/insights/?short_id=12345678")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assertEqual(len(response.json()["results"]), 1)
        self.assertEqual(response.json()["results"][0]["short_id"], "12345678")
        self.assertEqual(response.json()["results"][0]["filters"]["events"][0]["id"], "$pageview")

    def test_basic_results(self) -> None:
        """
        The `skip_results` query parameter can be passed so that only a list of objects is returned, without
        the actual query data. This can speed things up if it's not needed.
        """
        filter_dict = {"events": [{"id": "$pageview"}]}

        Insight.objects.create(
            filters=Filter(data=filter_dict).to_dict(),
            team=self.team,
            short_id="12345678",
        )
        Insight.objects.create(filters=Filter(data=filter_dict).to_dict(), team=self.team, saved=True)

        response = self.client.get(f"/api/projects/{self.team.id}/insights/?basic=true")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assertEqual(len(response.json()["results"]), 2)
        self.assertEqual(
            set(response.json()["results"][0].keys()),
            {
                "id",
                "short_id",
                "name",
                "derived_name",
                "favorited",
                "filters",
                "query",
                "dashboards",
                "dashboard_tiles",
                "description",
                "last_refresh",
                "refreshing",
                "saved",
                "updated_at",
                "created_by",
                "created_at",
                "last_modified_at",
                "tags",
                "user_access_level",
            },
        )

    # :KLUDGE: avoid making extra queries that are explicitly not cached in tests. Avoids false N+1-s.
    @override_settings(PERSON_ON_EVENTS_OVERRIDE=False, PERSON_ON_EVENTS_V2_OVERRIDE=False)
    @snapshot_postgres_queries
    def test_listing_insights_does_not_nplus1(self) -> None:
        query_counts: list[int] = []
        queries = []

        for i in range(5):
            user = User.objects.create(email=f"testuser{i}@posthog.com")
            OrganizationMembership.objects.create(user=user, organization=self.organization)
            dashboard = Dashboard.objects.create(name=f"Dashboard {i}", team=self.team)

            self.dashboard_api.create_insight(
                data={
                    "short_id": f"insight{i}",
                    "dashboards": [dashboard.pk],
                    "filters": {"events": [{"id": "$pageview"}]},
                }
            )

            self.assertEqual(Insight.objects.count(), i + 1)

            with capture_db_queries() as capture_query_context:
                response = self.client.get(f"/api/projects/{self.team.id}/insights?basic=true")
                self.assertEqual(response.status_code, status.HTTP_200_OK)
                self.assertEqual(len(response.json()["results"]), i + 1)

            query_count_for_create_and_read = len(capture_query_context.captured_queries)
            queries.append(capture_query_context.captured_queries)
            query_counts.append(query_count_for_create_and_read)

        # adding more insights doesn't change the query count
        self.assertEqual(
            [
                FuzzyInt(12, 13),
                FuzzyInt(12, 13),
                FuzzyInt(12, 13),
                FuzzyInt(12, 13),
                FuzzyInt(12, 13),
            ],
            query_counts,
            f"received query counts\n\n{query_counts}",
        )

    def test_listing_insights_shows_legacy_and_hogql_ones(self) -> None:
        self.dashboard_api.create_insight(
            data={
                "short_id": f"insight",
                "query": {
                    "kind": "DataVisualizationNode",
                    "source": {
                        "kind": "HogQLQuery",
                        "query": "select * from events",
                    },
                },
            }
        )

        self.dashboard_api.create_insight(
            data={
                "short_id": f"insight",
                "filters": {"insight": "TRENDS", "events": [{"id": "$pageview"}]},
            }
        )
        self.dashboard_api.create_insight(
            data={
                "short_id": f"insight",
                "query": InsightVizNode(source=TrendsQuery(series=[EventsNode(event="$pageview")])).model_dump(),
            }
        )

        response = self.client.get(f"/api/environments/{self.team.pk}/insights/?insight=TRENDS")

        self.assertEqual(len(response.json()["results"]), 2)

    def test_can_list_insights_by_which_dashboards_they_are_in(self) -> None:
        insight_one_id, _ = self.dashboard_api.create_insight(
            {"name": "insight 1", "filters": {"events": [{"id": "$pageview"}]}}
        )
        insight_two_id, _ = self.dashboard_api.create_insight(
            {"name": "insight 2", "filters": {"events": [{"id": "$pageview"}]}}
        )
        insight_three_id, _ = self.dashboard_api.create_insight(
            {"name": "insight 3", "filters": {"events": [{"id": "$pageview"}]}}
        )

        dashboard_one_id, _ = self.dashboard_api.create_dashboard(
            {"name": "dashboard 1", "filters": {"date_from": "-180d"}}
        )
        dashboard_two_id, _ = self.dashboard_api.create_dashboard(
            {"name": "dashboard 1", "filters": {"date_from": "-180d"}}
        )
        self.dashboard_api.add_insight_to_dashboard([dashboard_one_id], insight_one_id)
        self.dashboard_api.add_insight_to_dashboard([dashboard_one_id, dashboard_two_id], insight_two_id)

        any_on_dashboard_one = self.client.get(
            f"/api/projects/{self.team.id}/insights/?dashboards=[{dashboard_one_id}]"
        )
        self.assertEqual(any_on_dashboard_one.status_code, status.HTTP_200_OK)
        matched_insights = [insight["id"] for insight in any_on_dashboard_one.json()["results"]]
        assert sorted(matched_insights) == [insight_one_id, insight_two_id]

        # match is AND, not OR
        any_on_dashboard_one_and_two = self.client.get(
            f"/api/projects/{self.team.id}/insights/?dashboards=[{dashboard_one_id}, {dashboard_two_id}]"
        )
        self.assertEqual(any_on_dashboard_one_and_two.status_code, status.HTTP_200_OK)
        matched_insights = [insight["id"] for insight in any_on_dashboard_one_and_two.json()["results"]]
        assert matched_insights == [insight_two_id]

        # respects deleted tiles
        self.dashboard_api.update_insight(insight_two_id, {"dashboards": []})  # remove from all dashboards

        any_on_dashboard_one = self.client.get(
            f"/api/projects/{self.team.id}/insights/?dashboards=[{dashboard_one_id}]"
        )
        self.assertEqual(any_on_dashboard_one.status_code, status.HTTP_200_OK)
        matched_insights = [insight["id"] for insight in any_on_dashboard_one.json()["results"]]
        assert sorted(matched_insights) == [insight_one_id]

    @freeze_time("2012-01-14T03:21:34.000Z")
    def test_create_insight_items(self) -> None:
        response = self.client.post(
            f"/api/projects/{self.team.id}/insights",
            data={
                "name": "a created dashboard",
                "filters": {
                    "events": [{"id": "$pageview"}],
                    "properties": [{"key": "$browser", "value": "Mac OS X"}],
                    "date_from": "-90d",
                },
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        response_data = response.json()
        self.assertEqual(response_data["description"], None)
        self.assertEqual(response_data["tags"], [])

        objects = Insight.objects.all()
        self.assertEqual(objects.count(), 1)
        self.assertEqual(objects[0].filters["events"][0]["id"], "$pageview")
        self.assertEqual(objects[0].filters["date_from"], "-90d")
        self.assertEqual(len(objects[0].short_id), 8)

        self.assert_insight_activity(
            response_data["id"],
            [
                {
                    "user": {"first_name": "", "email": "user1@posthog.com"},
                    "activity": "created",
                    "created_at": "2012-01-14T03:21:34Z",
                    "scope": "Insight",
                    "item_id": str(response_data["id"]),
                    "detail": {
                        "changes": None,
                        "trigger": None,
                        "type": None,
                        "name": "a created dashboard",
                        "short_id": response_data["short_id"],
                    },
                }
            ],
        )

    @freeze_time("2012-01-14T03:21:34.000Z")
    def test_create_insight_with_no_names_logs_no_activity(self) -> None:
        response = self.client.post(
            f"/api/projects/{self.team.id}/insights",
            data={
                "filters": {
                    "events": [{"id": "$pageview"}],
                    "properties": [{"key": "$browser", "value": "Mac OS X"}],
                    "date_from": "-90d",
                }
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        response_data = response.json()
        self.assertEqual(response_data["name"], None)
        self.assertEqual(response_data["derived_name"], None)

        self.assert_insight_activity(response_data["id"], [])

    def test_create_insight_items_on_a_dashboard(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({})

        insight_id, _ = self.dashboard_api.create_insight(
            {
                "filters": {
                    "events": [{"id": "$pageview"}],
                    "properties": [{"key": "$browser", "value": "Mac OS X"}],
                    "date_from": "-90d",
                },
                "dashboards": [dashboard_id],
            }
        )

        tile: DashboardTile = DashboardTile.objects.get(dashboard__id=dashboard_id, insight__id=insight_id)
        self.assertIsNotNone(tile)

    def test_insight_items_on_a_dashboard_ignore_deleted_dashboards(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({})
        deleted_dashboard_id, _ = self.dashboard_api.create_dashboard({})

        insight_id, _ = self.dashboard_api.create_insight(
            {
                "filters": {
                    "events": [{"id": "$pageview"}],
                    "properties": [{"key": "$browser", "value": "Mac OS X"}],
                    "date_from": "-90d",
                },
                "dashboards": [dashboard_id, deleted_dashboard_id],
            }
        )

        self.dashboard_api.update_dashboard(deleted_dashboard_id, {"deleted": True})

        insight_json = self.dashboard_api.get_insight(insight_id)
        assert insight_json["dashboards"] == [dashboard_id]
        assert insight_json["dashboard_tiles"] == [{"id": mock.ANY, "deleted": None, "dashboard_id": dashboard_id}]

        new_dashboard_id, _ = self.dashboard_api.create_dashboard({})
        # accidentally include a deleted dashboard
        _, update_response = self.dashboard_api.update_insight(
            insight_id,
            {"dashboards": [dashboard_id, deleted_dashboard_id, new_dashboard_id]},
            expected_status=status.HTTP_400_BAD_REQUEST,
        )

        insight_json = self.dashboard_api.get_insight(insight_id)
        assert insight_json["dashboards"] == [dashboard_id]
        assert insight_json["dashboard_tiles"] == [{"id": mock.ANY, "deleted": None, "dashboard_id": dashboard_id}]

    def test_insight_items_on_a_dashboard_ignore_deleted_dashboard_tiles(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({})

        insight_id, insight_json = self.dashboard_api.create_insight(
            {
                "filters": {
                    "events": [{"id": "$pageview"}],
                    "properties": [{"key": "$browser", "value": "Mac OS X"}],
                    "date_from": "-90d",
                },
                "dashboards": [dashboard_id],
            }
        )

        tile: DashboardTile = DashboardTile.objects.get(insight_id=insight_id, dashboard_id=dashboard_id)
        tile.deleted = True
        tile.save()

        insight_json = self.dashboard_api.get_insight(insight_id)
        assert insight_json["dashboards"] == []
        assert insight_json["dashboard_tiles"] == []

        insight_by_short_id = self.client.get(
            f"/api/projects/{self.team.pk}/insights?short_id={insight_json['short_id']}"
        )
        assert insight_by_short_id.json()["results"][0]["dashboards"] == []
        assert insight_by_short_id.json()["results"][0]["dashboard_tiles"] == []

        self.dashboard_api.add_insight_to_dashboard([dashboard_id], insight_id)

        insight_json = self.dashboard_api.get_insight(insight_id)
        assert insight_json["dashboards"] == [dashboard_id]
        assert insight_json["dashboard_tiles"] == [{"id": mock.ANY, "deleted": False, "dashboard_id": dashboard_id}]

    def test_can_update_insight_with_inconsistent_dashboards(self) -> None:
        """
        Regression test because there are some DashboardTiles in production that should not exist.
        Which were created before Tiles were deleted when dashboards are soft deleted
        """
        dashboard_id, _ = self.dashboard_api.create_dashboard({})
        deleted_dashboard_id, _ = self.dashboard_api.create_dashboard({})

        insight_id, _ = self.dashboard_api.create_insight(
            {
                "name": "the insight",
                "dashboards": [dashboard_id, deleted_dashboard_id],
            }
        )

        # update outside of API so that DashboardTile still exists
        dashboard_in_db = Dashboard.objects.get(id=deleted_dashboard_id)
        dashboard_in_db.deleted = True
        dashboard_in_db.save(update_fields=["deleted"])

        assert not DashboardTile.objects.filter(dashboard_id=deleted_dashboard_id).exists()
        assert DashboardTile.objects_including_soft_deleted.filter(dashboard_id=deleted_dashboard_id).exists()

        insight_json = self.dashboard_api.get_insight(insight_id)
        assert insight_json["dashboards"] == [dashboard_id]
        assert insight_json["dashboard_tiles"] == [{"id": mock.ANY, "deleted": None, "dashboard_id": dashboard_id}]

        # accidentally include a deleted dashboard
        _, update_response = self.dashboard_api.update_insight(
            insight_id,
            {"dashboards": [deleted_dashboard_id]},
            expected_status=status.HTTP_400_BAD_REQUEST,
        )

        # confirm no updates happened
        insight_json = self.dashboard_api.get_insight(insight_id)
        assert insight_json["dashboards"] == [dashboard_id]
        assert insight_json["dashboard_tiles"] == [{"id": mock.ANY, "deleted": None, "dashboard_id": dashboard_id}]

    def test_dashboards_relation_is_tile_soft_deletion_aware(self) -> None:
        dashboard_one_id, _ = self.dashboard_api.create_dashboard({"name": "dash 1"})
        dashboard_two_id, _ = self.dashboard_api.create_dashboard({"name": "dash 2"})

        insight_id, insight_json = self.dashboard_api.create_insight(
            {
                "name": "start with two dashboards",
                "dashboards": [dashboard_one_id, dashboard_two_id],
            }
        )

        # then remove from one of them
        _, on_update_insight_json = self.dashboard_api.update_insight(
            insight_id,
            {
                "dashboards": [dashboard_one_id],
            },
        )
        assert on_update_insight_json["dashboards"] == [dashboard_one_id]
        assert on_update_insight_json["dashboard_tiles"] == [
            {"id": mock.ANY, "deleted": None, "dashboard_id": dashboard_one_id}
        ]

        insight_json = self.dashboard_api.get_insight(insight_id)
        assert insight_json["dashboards"] == [dashboard_one_id]
        assert insight_json["dashboard_tiles"] == [{"id": mock.ANY, "deleted": None, "dashboard_id": dashboard_one_id}]

        insights_list = self.dashboard_api.list_insights()
        assert insights_list["count"] == 1
        assert [i["dashboards"] for i in insights_list["results"]] == [[dashboard_one_id]]
        assert [i["dashboard_tiles"] for i in insights_list["results"]] == [
            [
                {
                    "dashboard_id": dashboard_one_id,
                    "deleted": None,
                    "id": mock.ANY,
                }
            ]
        ]

    def test_adding_insight_to_dashboard_updates_activity_log(self) -> None:
        dashboard_one_id, _ = self.dashboard_api.create_dashboard({"name": "dash 1"})
        dashboard_two_id, _ = self.dashboard_api.create_dashboard({"name": "dash 2"})

        insight_id, insight_json = self.dashboard_api.create_insight(
            {
                "name": "have to have a name to hit the activity log",
                "dashboards": [dashboard_one_id, dashboard_two_id],
            }
        )

        # then remove from one of them
        self.dashboard_api.update_insight(
            insight_id,
            {
                "dashboards": [dashboard_one_id],
            },
        )

        # then add one
        self.dashboard_api.update_insight(
            insight_id,
            {
                "dashboards": [dashboard_one_id, dashboard_two_id],
            },
        )

        self.assert_insight_activity(
            # expected activity is
            # * added dash 2
            # * removed dash 2
            # * created insight
            insight_id,
            [
                {
                    "activity": "updated",
                    "created_at": mock.ANY,
                    "detail": {
                        "changes": [
                            {
                                "action": "changed",
                                "before": [{"id": dashboard_one_id, "name": "dash 1"}],
                                "after": [
                                    {"id": dashboard_one_id, "name": "dash 1"},
                                    {"id": dashboard_two_id, "name": "dash 2"},
                                ],
                                "field": "dashboards",
                                "type": "Insight",
                            }
                        ],
                        "name": "have to have a name to hit the activity log",
                        "short_id": insight_json["short_id"],
                        "trigger": None,
                        "type": None,
                    },
                    "item_id": str(insight_id),
                    "scope": "Insight",
                    "user": {"email": "user1@posthog.com", "first_name": ""},
                },
                {
                    "activity": "updated",
                    "created_at": mock.ANY,
                    "detail": {
                        "changes": [
                            {
                                "action": "changed",
                                "before": [
                                    {"id": dashboard_one_id, "name": "dash 1"},
                                    {"id": dashboard_two_id, "name": "dash 2"},
                                ],
                                "after": [{"id": dashboard_one_id, "name": "dash 1"}],
                                "field": "dashboards",
                                "type": "Insight",
                            }
                        ],
                        "name": "have to have a name to hit the activity log",
                        "short_id": insight_json["short_id"],
                        "trigger": None,
                        "type": None,
                    },
                    "item_id": str(insight_id),
                    "scope": "Insight",
                    "user": {"email": "user1@posthog.com", "first_name": ""},
                },
                {
                    "activity": "created",
                    "created_at": mock.ANY,
                    "detail": {
                        "changes": None,
                        "name": "have to have a name to hit the activity log",
                        "short_id": insight_json["short_id"],
                        "trigger": None,
                        "type": None,
                    },
                    "item_id": str(insight_id),
                    "scope": "Insight",
                    "user": {"email": "user1@posthog.com", "first_name": ""},
                },
            ],
        )

    def test_can_update_insight_dashboards_without_deleting_tiles(self) -> None:
        dashboard_one_id, _ = self.dashboard_api.create_dashboard({})
        dashboard_two_id, _ = self.dashboard_api.create_dashboard({})

        insight_id, _ = self.dashboard_api.create_insight(
            {
                "dashboards": [dashboard_one_id, dashboard_two_id],
            }
        )

        self.dashboard_api.set_tile_layout(dashboard_one_id, 1)

        dashboard_one_json = self.dashboard_api.get_dashboard(dashboard_one_id)
        original_tiles = dashboard_one_json["tiles"]

        # update the insight without changing anything
        self.dashboard_api.update_insight(
            insight_id,
            {
                "dashboards": [dashboard_one_id, dashboard_two_id],
            },
        )

        dashboard_one_json = self.dashboard_api.get_dashboard(dashboard_one_id)
        after_update_tiles = dashboard_one_json["tiles"]

        assert [t["id"] for t in original_tiles] == [t["id"] for t in after_update_tiles]
        assert after_update_tiles[0]["layouts"] is not None

        # update the insight, removing a tile
        self.dashboard_api.update_insight(
            insight_id,
            {
                "dashboards": [dashboard_one_id],
            },
        )

        dashboard_one_json = self.dashboard_api.get_dashboard(dashboard_one_id)
        after_update_tiles = dashboard_one_json["tiles"]

        assert len(after_update_tiles) == 1
        assert original_tiles[0]["id"] == after_update_tiles[0]["id"]  # tile has not been recreated in DB
        assert after_update_tiles[0]["layouts"] is not None  # tile has not been recreated in DB
        assert original_tiles[0]["insight"]["id"] == after_update_tiles[0]["insight"]["id"]
        assert sorted(original_tiles[0]["insight"]["dashboards"]) == sorted([dashboard_one_id, dashboard_two_id])
        assert sorted(t["dashboard_id"] for t in original_tiles[0]["insight"]["dashboard_tiles"]) == sorted(
            [dashboard_one_id, dashboard_two_id]
        )
        assert [t["dashboard_id"] for t in after_update_tiles[0]["insight"]["dashboard_tiles"]] == [
            dashboard_one_id
        ]  # removed dashboard is removed

    @freeze_time("2012-01-14T03:21:34.000Z")
    def test_create_insight_logs_derived_name_if_there_is_no_name(self) -> None:
        response = self.client.post(
            f"/api/projects/{self.team.id}/insights",
            data={
                "derived_name": "pageview unique users",
                "filters": {
                    "events": [{"id": "$pageview"}],
                    "properties": [{"key": "$browser", "value": "Mac OS X"}],
                    "date_from": "-90d",
                },
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        response_data = response.json()
        self.assertEqual(response_data["derived_name"], "pageview unique users")

        self.assert_insight_activity(
            response_data["id"],
            [
                {
                    "user": {"first_name": "", "email": "user1@posthog.com"},
                    "activity": "created",
                    "created_at": "2012-01-14T03:21:34Z",
                    "scope": "Insight",
                    "item_id": str(response_data["id"]),
                    "detail": {
                        "changes": None,
                        "trigger": None,
                        "type": None,
                        "name": "pageview unique users",
                        "short_id": response_data["short_id"],
                    },
                }
            ],
        )

    def test_update_insight(self) -> None:
        with freeze_time("2012-01-14T03:21:34.000Z") as frozen_time:
            insight_id, insight = self.dashboard_api.create_insight({"name": "insight name"})
            short_id = insight["short_id"]

            frozen_time.tick(delta=timedelta(minutes=10))

            response = self.client.patch(
                f"/api/projects/{self.team.id}/insights/{insight_id}",
                {"name": "insight new name", "tags": ["add", "these", "tags"]},
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)

            response_data = response.json()
            self.assertEqual(response_data["name"], "insight new name")
            # tags are a paid feature and safely ignored when not licensed
            self.assertEqual(sorted(response_data["tags"]), [])
            self.assertEqual(response_data["created_by"]["distinct_id"], self.user.distinct_id)
            self.assertEqual(
                response_data["effective_restriction_level"],
                Dashboard.RestrictionLevel.EVERYONE_IN_PROJECT_CAN_EDIT,
            )
            self.assertEqual(
                response_data["effective_privilege_level"],
                Dashboard.PrivilegeLevel.CAN_EDIT,
            )

            response = self.client.get(f"/api/projects/{self.team.id}/insights/{insight_id}")

            self.assertEqual(response.json()["name"], "insight new name")

            self.assert_insight_activity(
                insight_id,
                [
                    {
                        "user": {"first_name": "", "email": "user1@posthog.com"},
                        "activity": "updated",
                        "scope": "Insight",
                        "item_id": str(insight_id),
                        "detail": {
                            "changes": [
                                {
                                    "type": "Insight",
                                    "action": "changed",
                                    "field": "name",
                                    "before": "insight name",
                                    "after": "insight new name",
                                },
                            ],
                            "trigger": None,
                            "type": None,
                            "name": "insight new name",
                            "short_id": short_id,
                        },
                        "created_at": "2012-01-14T03:31:34Z",
                    },
                    {
                        "user": {"first_name": "", "email": "user1@posthog.com"},
                        "activity": "created",
                        "scope": "Insight",
                        "item_id": str(insight_id),
                        "detail": {
                            "changes": None,
                            "trigger": None,
                            "type": None,
                            "name": "insight name",
                            "short_id": short_id,
                        },
                        "created_at": "2012-01-14T03:21:34Z",
                    },
                ],
            )

    def test_cannot_set_filters_hash_via_api(self) -> None:
        insight_id, insight = self.dashboard_api.create_insight({"name": "should not update the filters_hash"})
        original_filters_hash = insight["filters_hash"]
        self.assertIsNotNone(original_filters_hash)

        response = self.client.patch(
            f"/api/projects/{self.team.id}/insights/{insight_id}",
            {"filters_hash": "should not update the value"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["filters_hash"], original_filters_hash)

    @skip("Compatibility issue caused by test account filters")
    def test_update_insight_filters(self) -> None:
        insight = Insight.objects.create(
            team=self.team,
            name="insight with custom filters",
            created_by=self.user,
            filters={"events": [{"id": "$pageview"}]},
        )

        for custom_name, expected_name in zip(
            ["Custom filter", 100, "", "  ", None],
            ["Custom filter", "100", None, None, None],
        ):
            response = self.client.patch(
                f"/api/projects/{self.team.id}/insights/{insight.id}",
                {"filters": {"events": [{"id": "$pageview", "custom_name": custom_name}]}},
            )

            self.assertEqual(response.status_code, status.HTTP_200_OK)

            response_data = response.json()
            self.assertEqual(response_data["filters"]["events"][0]["custom_name"], expected_name)
            insight.refresh_from_db()
            self.assertEqual(insight.filters["events"][0]["custom_name"], expected_name)

    def test_save_new_funnel(self) -> None:
        dashboard = Dashboard.objects.create(name="My Dashboard", team=self.team)

        response = self.client.post(
            f"/api/projects/{self.team.id}/insights",
            data={
                "filters": {
                    "insight": "FUNNELS",
                    "events": [
                        {
                            "id": "$pageview",
                            "math": None,
                            "name": "$pageview",
                            "type": "events",
                            "order": 0,
                            "properties": [],
                            "math_hogql": None,
                            "math_property": None,
                        },
                        {
                            "id": "$rageclick",
                            "math": None,
                            "name": "$rageclick",
                            "type": "events",
                            "order": 2,
                            "properties": [],
                            "math_hogql": None,
                            "math_property": None,
                        },
                    ],
                    "display": "FunnelViz",
                    "interval": "day",
                    "date_from": "-30d",
                    "actions": [],
                    "new_entity": [],
                    "layout": "horizontal",
                },
                "name": "My Funnel One",
                "dashboard": dashboard.pk,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        objects = Insight.objects.all()
        self.assertEqual(objects.count(), 1)
        self.assertEqual(objects[0].filters["events"][1]["id"], "$rageclick")
        self.assertEqual(objects[0].filters["display"], "FunnelViz")
        self.assertEqual(objects[0].filters["interval"], "day")
        self.assertEqual(objects[0].filters["date_from"], "-30d")
        self.assertEqual(objects[0].filters["layout"], "horizontal")
        self.assertEqual(len(objects[0].short_id), 8)

    def test_insight_refreshing_legacy_conversion(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"filters": {"date_from": "-14d"}})

        with freeze_time("2012-01-14T03:21:34.000Z"):
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="1",
                properties={"prop": "val"},
            )
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="2",
                properties={"prop": "another_val"},
            )
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="2",
                properties={"prop": "val", "another": "never_return_this"},
            )

        with freeze_time("2012-01-15T04:01:34.000Z"):
            response = self.client.post(
                f"/api/projects/{self.team.id}/insights",
                data={
                    "filters": {
                        "events": [{"id": "$pageview"}],
                        "properties": [
                            {
                                "key": "another",
                                "value": "never_return_this",
                                "operator": "is_not",
                            }
                        ],
                    },
                    "dashboards": [dashboard_id],
                },
            ).json()
            self.assertEqual(response["last_refresh"], None)

            response = self.client.get(f"/api/projects/{self.team.id}/insights/{response['id']}/?refresh=true").json()
            self.assertEqual(response["result"][0]["data"], [0, 0, 0, 0, 0, 0, 2, 0])
            self.assertEqual(response["last_refresh"], "2012-01-15T04:01:34Z")
            self.assertEqual(response["last_modified_at"], "2012-01-15T04:01:34Z")

        with freeze_time("2012-01-15T05:01:34.000Z"):
            _create_event(team=self.team, event="$pageview", distinct_id="1")
            response = self.client.get(f"/api/projects/{self.team.id}/insights/{response['id']}/?refresh=true").json()
            self.assertEqual(response["result"][0]["data"], [0, 0, 0, 0, 0, 0, 2, 1])
            self.assertEqual(response["last_refresh"], "2012-01-15T05:01:34Z")
            self.assertEqual(response["last_modified_at"], "2012-01-15T04:01:34Z")  # did not change

        with freeze_time("2012-01-16T05:01:34.000Z"):
            # load it in the context of the dashboard, so has last 14 days as filter
            response = self.client.get(
                f"/api/projects/{self.team.id}/insights/{response['id']}/?refresh=true&from_dashboard={dashboard_id}"
            ).json()
            self.assertEqual(
                response["result"][0]["data"],
                [
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    2.0,
                    1.0,
                    0.0,
                ],
            )
            self.assertEqual(response["last_refresh"], "2012-01-16T05:01:34Z")
            self.assertEqual(response["last_modified_at"], "2012-01-15T04:01:34Z")  # did not change

        with freeze_time("2012-01-25T05:01:34.000Z"):
            response = self.client.get(f"/api/projects/{self.team.id}/insights/{response['id']}/").json()
            self.assertEqual(response["last_refresh"], None)
            self.assertEqual(response["last_modified_at"], "2012-01-15T04:01:34Z")  # did not change

        #  Test property filter

        dashboard = Dashboard.objects.get(pk=dashboard_id)
        dashboard.filters = {
            "properties": [{"key": "prop", "value": "val"}],
            "date_from": "-14d",
        }
        dashboard.save()
        with freeze_time("2012-01-16T05:01:34.000Z"):
            response = self.client.get(
                f"/api/projects/{self.team.id}/insights/{response['id']}/?refresh=true&from_dashboard={dashboard_id}"
            ).json()
            self.assertEqual(
                response["result"][0]["data"],
                [
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    1.0,
                    0.0,
                    0.0,
                ],
            )

    @parameterized.expand(
        [
            [  # Property group filter, which is what's actually used these days
                PropertyGroupFilter(
                    type=FilterLogicalOperator.AND_,
                    values=[
                        PropertyGroupFilterValue(
                            type=FilterLogicalOperator.OR_,
                            values=[EventPropertyFilter(key="another", value="never_return_this", operator="is_not")],
                        )
                    ],
                )
            ],
            [  # Classic list of filters
                [EventPropertyFilter(key="another", value="never_return_this", operator="is_not")]
            ],
        ]
    )
    @patch("posthog.hogql_queries.insights.trends.trends_query_runner.execute_hogql_query", wraps=execute_hogql_query)
    def test_insight_refreshing_query(self, properties_filter, spy_execute_hogql_query) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"filters": {"date_from": "-14d"}})

        with freeze_time("2012-01-14T03:21:34.000Z"):
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="1",
                properties={"prop": "val"},
            )
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="2",
                properties={"prop": "another_val"},
            )
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="2",
                properties={"prop": "val", "another": "never_return_this"},
            )

        query_dict = TrendsQuery(
            series=[
                EventsNode(
                    event="$pageview",
                )
            ],
            properties=properties_filter,
        ).model_dump()

        with freeze_time("2012-01-15T04:01:34.000Z"):
            response = self.client.post(
                f"/api/projects/{self.team.id}/insights",
                data={
                    "query": query_dict,
                    "dashboards": [dashboard_id],
                },
            ).json()
            self.assertNotIn("code", response)  # Watching out for an error code
            self.assertEqual(response["last_refresh"], None)
            insight_id = response["id"]

            response = self.client.get(f"/api/projects/{self.team.id}/insights/{insight_id}/?refresh=true").json()
            self.assertNotIn("code", response)
            self.assertEqual(spy_execute_hogql_query.call_count, 1)
            self.assertEqual(response["result"][0]["data"], [0, 0, 0, 0, 0, 0, 2, 0])
            self.assertEqual(response["last_refresh"], "2012-01-15T04:01:34Z")
            self.assertEqual(response["last_modified_at"], "2012-01-15T04:01:34Z")
            self.assertFalse(response["is_cached"])

        with freeze_time("2012-01-15T05:01:34.000Z"):
            _create_event(team=self.team, event="$pageview", distinct_id="1")
            response = self.client.get(f"/api/projects/{self.team.id}/insights/{insight_id}/?refresh=true").json()
            self.assertNotIn("code", response)
            self.assertEqual(spy_execute_hogql_query.call_count, 2)
            self.assertEqual(response["result"][0]["data"], [0, 0, 0, 0, 0, 0, 2, 1])
            self.assertEqual(response["last_refresh"], "2012-01-15T05:01:34Z")
            self.assertEqual(response["last_modified_at"], "2012-01-15T04:01:34Z")  # did not change
            self.assertFalse(response["is_cached"])

        with freeze_time("2012-01-15T05:17:34.000Z"):
            response = self.client.get(f"/api/projects/{self.team.id}/insights/{insight_id}/").json()
            self.assertNotIn("code", response)
            self.assertEqual(spy_execute_hogql_query.call_count, 2)
            self.assertEqual(response["result"][0]["data"], [0, 0, 0, 0, 0, 0, 2, 1])
            self.assertEqual(response["last_refresh"], "2012-01-15T05:01:34Z")  # Using cached result
            self.assertEqual(response["last_modified_at"], "2012-01-15T04:01:34Z")  # did not change
            self.assertTrue(response["is_cached"])

        with freeze_time("2012-01-15T05:17:39.000Z"):
            # Make sure the /query/ endpoint reuses the same cached result
            response = self.client.post(f"/api/projects/{self.team.id}/query/", {"query": query_dict}).json()
            self.assertNotIn("code", response)
            self.assertEqual(spy_execute_hogql_query.call_count, 2)
            self.assertEqual(response["results"][0]["data"], [0, 0, 0, 0, 0, 0, 2, 1])
            self.assertEqual(response["last_refresh"], "2012-01-15T05:01:34Z")  # Using cached result
            self.assertTrue(response["is_cached"])

        with freeze_time("2012-01-16T05:01:34.000Z"):
            # load it in the context of the dashboard, so has last 14 days as filter
            response = self.client.get(
                f"/api/projects/{self.team.id}/insights/{insight_id}/?refresh=true&from_dashboard={dashboard_id}"
            ).json()
            self.assertNotIn("code", response)
            self.assertEqual(spy_execute_hogql_query.call_count, 3)
            self.assertEqual(
                response["result"][0]["data"],
                [
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    2.0,
                    1.0,
                    0.0,
                ],
            )
            self.assertEqual(response["last_refresh"], "2012-01-16T05:01:34Z")
            self.assertEqual(response["last_modified_at"], "2012-01-15T04:01:34Z")  # did not change
            self.assertFalse(response["is_cached"])

        #  Test property filter

        Dashboard.objects.update(
            id=dashboard_id,
            filters={
                "properties": [{"key": "prop", "value": "val"}],
                "date_from": "-14d",
            },
        )
        with freeze_time("2012-01-16T05:01:34.000Z"):
            response = self.client.get(
                f"/api/projects/{self.team.id}/insights/{insight_id}/?refresh=true&from_dashboard={dashboard_id}"
            ).json()
            self.assertNotIn("code", response)
            self.assertEqual(spy_execute_hogql_query.call_count, 4)
            self.assertEqual(
                response["result"][0]["data"],
                [
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    1.0,
                    0.0,
                    0.0,
                ],
            )

    @patch(
        "posthog.caching.insight_caching_state.calculate_target_age_insight",
        # The tested insight normally wouldn't satisfy the criteria for being refreshed in the background,
        # this patch means it will be treated as if it did satisfy them
        return_value=TargetCacheAge.MID_PRIORITY,
    )
    def test_insight_refreshing_legacy_with_background_update(self, spy_calculate_target_age_insight) -> None:
        with freeze_time("2012-01-14T03:21:34.000Z"):
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="1",
                properties={"prop": "val"},
            )
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="2",
                properties={"prop": "another_val"},
            )
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="2",
                properties={"prop": "val", "another": "never_return_this"},
            )
            flush_persons_and_events()

        with freeze_time("2012-01-15T04:01:34.000Z"):
            response = self.client.post(
                f"/api/projects/{self.team.id}/insights",
                data={
                    "filters": {
                        "events": [{"id": "$pageview"}],
                        "properties": [
                            {
                                "key": "another",
                                "value": "never_return_this",
                                "operator": "is_not",
                            }
                        ],
                    },
                },
            ).json()
            self.assertNotIn("code", response)  # Watching out for an error code
            self.assertEqual(response["last_refresh"], None)
            insight_id = response["id"]

            response = self.client.get(f"/api/projects/{self.team.id}/insights/{insight_id}/?refresh=true").json()
            self.assertNotIn("code", response)
            self.assertEqual(response["result"][0]["data"], [0, 0, 0, 0, 0, 0, 2, 0])
            self.assertEqual(response["last_refresh"], "2012-01-15T04:01:34Z")
            self.assertEqual(response["last_modified_at"], "2012-01-15T04:01:34Z")
            self.assertFalse(response["is_cached"])

        with freeze_time("2012-01-17T05:01:34.000Z"):
            update_cache(InsightCachingState.objects.get(insight_id=insight_id).id)

        with freeze_time("2012-01-17T06:01:34.000Z"):
            response = self.client.get(f"/api/projects/{self.team.id}/insights/{insight_id}/?refresh=false").json()
            self.assertNotIn("code", response)
            self.assertEqual(response["result"][0]["data"], [0, 0, 0, 0, 2, 0, 0, 0])
            self.assertEqual(response["last_refresh"], "2012-01-17T05:01:34Z")  # Got refreshed with `update_cache`!
            self.assertEqual(response["last_modified_at"], "2012-01-15T04:01:34Z")
            self.assertTrue(response["is_cached"])

    @parameterized.expand(
        [
            [  # Property group filter, which is what's actually used these days
                PropertyGroupFilter(
                    type=FilterLogicalOperator.AND_,
                    values=[
                        PropertyGroupFilterValue(
                            type=FilterLogicalOperator.OR_,
                            values=[EventPropertyFilter(key="another", value="never_return_this", operator="is_not")],
                        )
                    ],
                )
            ],
            [  # Classic list of filters
                [EventPropertyFilter(key="another", value="never_return_this", operator="is_not")]
            ],
        ]
    )
    @patch("posthog.hogql_queries.insights.trends.trends_query_runner.execute_hogql_query", wraps=execute_hogql_query)
    @patch(
        "posthog.caching.insight_caching_state.calculate_target_age_insight",
        # The tested insight normally wouldn't satisfy the criteria for being refreshed in the background,
        # this patch means it will be treated as if it did satisfy them
        return_value=TargetCacheAge.MID_PRIORITY,
    )
    def test_insight_refreshing_query_with_background_update(
        self, properties_filter, spy_execute_hogql_query, spy_calculate_target_age_insight
    ) -> None:
        with freeze_time("2012-01-14T03:21:34.000Z"):
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="1",
                properties={"prop": "val"},
            )
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="2",
                properties={"prop": "another_val"},
            )
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="2",
                properties={"prop": "val", "another": "never_return_this"},
            )
            flush_persons_and_events()

        query_dict = TrendsQuery(
            series=[
                EventsNode(
                    event="$pageview",
                )
            ],
            properties=properties_filter,
        ).model_dump()

        with freeze_time("2012-01-15T04:01:34.000Z"):
            response = self.client.post(f"/api/projects/{self.team.id}/insights", data={"query": query_dict}).json()
            self.assertNotIn("code", response)  # Watching out for an error code
            self.assertEqual(response["last_refresh"], None)
            insight_id = response["id"]

            response = self.client.get(f"/api/projects/{self.team.id}/insights/{insight_id}/?refresh=true").json()
            self.assertNotIn("code", response)
            self.assertEqual(spy_execute_hogql_query.call_count, 1)
            self.assertEqual(response["result"][0]["data"], [0, 0, 0, 0, 0, 0, 2, 0])
            self.assertEqual(response["last_refresh"], "2012-01-15T04:01:34Z")
            self.assertEqual(response["last_modified_at"], "2012-01-15T04:01:34Z")
            self.assertFalse(response["is_cached"])

        with freeze_time("2012-01-17T05:01:34.000Z"):
            update_cache(InsightCachingState.objects.get(insight_id=insight_id).id)

        with freeze_time("2012-01-17T06:01:34.000Z"):
            response = self.client.get(f"/api/projects/{self.team.id}/insights/{insight_id}/?refresh=false").json()
            self.assertNotIn("code", response)
            self.assertEqual(spy_execute_hogql_query.call_count, 1)
            self.assertEqual(response["result"][0]["data"], [0, 0, 0, 0, 2, 0, 0, 0])
            self.assertEqual(response["last_refresh"], "2012-01-17T05:01:34Z")  # Got refreshed with `update_cache`!
            self.assertEqual(response["last_modified_at"], "2012-01-15T04:01:34Z")
            self.assertTrue(response["is_cached"])

    @parameterized.expand(
        [
            [  # Property group filter, which is what's actually used these days
                PropertyGroupFilter(
                    type=FilterLogicalOperator.AND_,
                    values=[
                        PropertyGroupFilterValue(
                            type=FilterLogicalOperator.OR_,
                            values=[EventPropertyFilter(key="another", value="never_return_this", operator="is_not")],
                        )
                    ],
                )
            ],
            [  # Classic list of filters
                [EventPropertyFilter(key="another", value="never_return_this", operator="is_not")]
            ],
        ]
    )
    @patch("posthog.hogql_queries.insights.trends.trends_query_runner.execute_hogql_query", wraps=execute_hogql_query)
    def test_insight_refreshing_query_async(self, properties_filter, spy_execute_hogql_query) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"filters": {"date_from": "-14d"}})

        with freeze_time("2012-01-14T03:21:34.000Z"):
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="1",
                properties={"prop": "val"},
            )
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="2",
                properties={"prop": "another_val"},
            )
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="2",
                properties={"prop": "val", "another": "never_return_this"},
            )

        query_dict = TrendsQuery(
            series=[
                EventsNode(
                    event="$pageview",
                )
            ],
            properties=properties_filter,
        ).model_dump()

        with freeze_time("2012-01-15T04:01:34.000Z"):
            response = self.client.post(
                f"/api/projects/{self.team.id}/insights",
                data={
                    "query": query_dict,
                    "dashboards": [dashboard_id],
                },
            ).json()
            self.assertNotIn("code", response)  # Watching out for an error code
            self.assertEqual(response["last_refresh"], None)
            insight_id = response["id"]

            response = self.client.get(f"/api/projects/{self.team.id}/insights/{insight_id}/?refresh=blocking").json()
            self.assertNotIn("code", response)
            self.assertEqual(spy_execute_hogql_query.call_count, 1)
            self.assertEqual(response["result"][0]["data"], [0, 0, 0, 0, 0, 0, 2, 0])
            self.assertEqual(response["last_refresh"], "2012-01-15T04:01:34Z")
            self.assertEqual(response["last_modified_at"], "2012-01-15T04:01:34Z")
            self.assertFalse(response["is_cached"])

        with freeze_time("2012-01-15T05:17:39.000Z"):
            # Make sure the /query/ endpoint reuses the same cached result - ASYNC EXECUTION HERE!
            response = self.client.post(
                f"/api/projects/{self.team.id}/query/", {"query": query_dict, "refresh": "async"}
            ).json()
            self.assertNotIn("code", response)
            self.assertIsNone(response.get("query_status"))
            self.assertEqual(spy_execute_hogql_query.call_count, 1)
            self.assertEqual(response["results"][0]["data"], [0, 0, 0, 0, 0, 0, 2, 0])
            self.assertEqual(response["last_refresh"], "2012-01-15T04:01:34Z")  # Using cached result
            self.assertTrue(response["is_cached"])

        with freeze_time("2012-01-15T05:17:39.000Z"):
            # Now with force async requested - cache should be ignored
            response = self.client.post(
                f"/api/projects/{self.team.id}/query/", {"query": query_dict, "refresh": "force_async"}
            ).json()
            self.assertNotIn("code", response)
            self.assertIs(response.get("query_status", {}).get("query_async"), True)
            self.assertIs(
                response.get("query_status", {}).get("complete"), False
            )  # Just checking that recalculation was initiated

        # make new insight to test cache miss
        query_dict = TrendsQuery(
            series=[
                EventsNode(
                    event="$pageview",
                ),
                EventsNode(
                    event="$something",
                ),
            ],
            properties=properties_filter,
        ).model_dump()

        response = self.client.post(
            f"/api/projects/{self.team.id}/insights",
            data={
                "query": query_dict,
                "dashboards": [dashboard_id],
            },
        ).json()
        insight_id = response["id"]

        # Check that cache miss contains query status
        response = self.client.get(f"/api/projects/{self.team.id}/insights/{insight_id}/?refresh=async").json()
        self.assertNotIn("code", response)
        self.assertEqual(response["result"], None)
        self.assertEqual(response["query_status"]["query_async"], True)

    def test_dashboard_filters_applied_to_sql_data_table_node(self):
        dashboard_id, _ = self.dashboard_api.create_dashboard(
            {"name": "the dashboard", "filters": {"date_from": "-180d"}}
        )
        query = DataTableNode(
            source=HogQLQuery(
                query="SELECT count(1) FROM events", filters=HogQLFilters(dateRange=DateRange(date_from="-3d"))
            ),
        ).model_dump()
        insight_id, _ = self.dashboard_api.create_insight(
            {"query": query, "name": "insight", "dashboards": [dashboard_id]}
        )

        response = self.client.get(f"/api/projects/{self.team.id}/insights/{insight_id}/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["query"], query)

        response = self.client.get(
            f"/api/projects/{self.team.id}/insights/{insight_id}/?refresh=true&from_dashboard={dashboard_id}"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["query"]["source"]["filters"]["dateRange"]["date_from"], "-180d")

    def test_dashboard_filters_applied_to_data_visualization_node(self):
        dashboard_id, _ = self.dashboard_api.create_dashboard(
            {"name": "the dashboard", "filters": {"date_from": "-180d"}}
        )
        query = DataVisualizationNode(
            source=HogQLQuery(
                query="SELECT count(1) FROM events", filters=HogQLFilters(dateRange=DateRange(date_from="-3d"))
            ),
        ).model_dump()
        insight_id, _ = self.dashboard_api.create_insight(
            {"query": query, "name": "insight", "dashboards": [dashboard_id]}
        )

        response = self.client.get(f"/api/projects/{self.team.id}/insights/{insight_id}/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["query"], query)

        response = self.client.get(
            f"/api/projects/{self.team.id}/insights/{insight_id}/?refresh=true&from_dashboard={dashboard_id}"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["query"]["source"]["filters"]["dateRange"]["date_from"], "-180d")

    def test_dashboard_filters_applied_to_events_query_data_table_node(self):
        dashboard_id, _ = self.dashboard_api.create_dashboard(
            {"name": "the dashboard", "filters": {"date_from": "-180d"}}
        )
        query = DataTableNode(
            source=EventsQuery(select=["uuid", "event", "timestamp"], after="-3d").model_dump(),
        ).model_dump()
        insight_id, _ = self.dashboard_api.create_insight(
            {"query": query, "name": "insight", "dashboards": [dashboard_id]}
        )

        response = self.client.get(f"/api/projects/{self.team.id}/insights/{insight_id}/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["query"], query)

        response = self.client.get(
            f"/api/projects/{self.team.id}/insights/{insight_id}/?refresh=true&from_dashboard={dashboard_id}"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["query"]["source"]["after"], "-180d")

    # BASIC TESTING OF ENDPOINTS. /queries as in depth testing for each insight

    def test_insight_trends_basic(self) -> None:
        with freeze_time("2012-01-14T03:21:34.000Z"):
            _create_event(team=self.team, event="$pageview", distinct_id="1")
            _create_event(team=self.team, event="$pageview", distinct_id="2")

        with freeze_time("2012-01-15T04:01:34.000Z"):
            response = self.client.get(
                f"/api/projects/{self.team.id}/insights/trend/?events={json.dumps([{'id': '$pageview'}])}"
            ).json()

        self.assertEqual(response["result"][0]["count"], 2)
        self.assertEqual(response["result"][0]["action"]["name"], "$pageview")
        self.assertEqual(response["timezone"], "UTC")

    def test_nonexistent_cohort_is_handled(self) -> None:
        response = self.client.get(
            f"/api/projects/{self.team.id}/insights/trend/?events={json.dumps([{'id': '$pageview'}])}&properties={json.dumps([{'type': 'cohort', 'key': 'id', 'value': 2137}])}"
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.json())

    def test_cohort_without_match_group_works(self) -> None:
        whatever_cohort_without_match_groups = Cohort.objects.create(team=self.team)

        response_nonexistent_property = self.client.get(
            f"/api/projects/{self.team.id}/insights/trend/?events={json.dumps([{'id': '$pageview'}])}&properties={json.dumps([{'type': 'event', 'key': 'foo', 'value': 'barabarab'}])}"
        )
        response_cohort_without_match_groups = self.client.get(
            f"/api/projects/{self.team.id}/insights/trend/?events={json.dumps([{'id': '$pageview'}])}&properties={json.dumps([{'type': 'cohort', 'key': 'id', 'value': whatever_cohort_without_match_groups.pk}])}"
        )  # This should not throw an error, just act like there's no event matches

        self.assertEqual(response_nonexistent_property.status_code, 200)
        response_nonexistent_property_data = response_nonexistent_property.json()
        response_cohort_without_match_groups_data = response_cohort_without_match_groups.json()
        response_nonexistent_property_data.pop("last_refresh")
        response_cohort_without_match_groups_data.pop("last_refresh")
        self.assertEntityResponseEqual(
            response_nonexistent_property_data["result"],
            response_cohort_without_match_groups_data["result"],
        )  # Both cases just empty

    def test_precalculated_cohort_works(self) -> None:
        _create_person(team=self.team, distinct_ids=["person_1"], properties={"foo": "bar"})

        whatever_cohort: Cohort = Cohort.objects.create(
            id=113,
            team=self.team,
            groups=[
                {
                    "properties": [
                        {
                            "type": "person",
                            "key": "foo",
                            "value": "bar",
                            "operator": "exact",
                        }
                    ]
                }
            ],
            last_calculation=timezone.now(),
        )

        whatever_cohort.calculate_people_ch(pending_version=0)

        with self.settings(USE_PRECALCULATED_CH_COHORT_PEOPLE=True):  # Normally this is False in tests
            response_user_property = self.client.get(
                f"/api/projects/{self.team.id}/insights/trend/?events={json.dumps([{'id': '$pageview'}])}&properties={json.dumps([{'type': 'person', 'key': 'foo', 'value': 'bar'}])}"
            )
            response_precalculated_cohort = self.client.get(
                f"/api/projects/{self.team.id}/insights/trend/?events={json.dumps([{'id': '$pageview'}])}&properties={json.dumps([{'type': 'cohort', 'key': 'id', 'value': 113}])}"
            )

        self.assertEqual(response_precalculated_cohort.status_code, 200)
        response_user_property_data = response_user_property.json()
        response_precalculated_cohort_data = response_precalculated_cohort.json()
        response_user_property_data.pop("last_refresh")
        response_precalculated_cohort_data.pop("last_refresh")

        self.assertEntityResponseEqual(
            response_user_property_data["result"],
            response_precalculated_cohort_data["result"],
        )

    def test_insight_trends_compare(self) -> None:
        with freeze_time("2012-01-14T03:21:34.000Z"):
            for i in range(25):
                _create_event(
                    team=self.team,
                    event="$pageview",
                    distinct_id="1",
                    properties={"$some_property": f"value{i}"},
                )

        with freeze_time("2012-01-15T04:01:34.000Z"):
            response = self.client.get(
                f"/api/projects/{self.team.id}/insights/trend/",
                data={"events": json.dumps([{"id": "$pageview"}]), "compare": "true"},
            )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        result = response.json()
        self.assertEqual(len(result["result"]), 2)
        self.assertEqual(result["result"][0]["compare_label"], "current")
        self.assertEqual(result["result"][1]["compare_label"], "previous")

    def test_insight_trends_breakdown_pagination(self) -> None:
        with freeze_time("2012-01-14T03:21:34.000Z"):
            for i in range(25):
                _create_event(
                    team=self.team,
                    event="$pageview",
                    distinct_id="1",
                    properties={"$some_property": f"value{i}"},
                )

        with freeze_time("2012-01-15T04:01:34.000Z"):
            response = self.client.get(
                f"/api/projects/{self.team.id}/insights/trend/",
                data={
                    "events": json.dumps([{"id": "$pageview"}]),
                    "breakdown": "$some_property",
                    "breakdown_type": "event",
                },
            )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        self.assertIn("offset=25", response.json()["next"])

    def test_insight_funnels_basic_post(self) -> None:
        _create_person(team=self.team, distinct_ids=["1"])
        _create_event(team=self.team, event="user signed up", distinct_id="1")
        _create_event(team=self.team, event="user did things", distinct_id="1")
        response = self.client.post(
            f"/api/projects/{self.team.id}/insights/funnel/",
            {
                "events": [
                    {"id": "user signed up", "type": "events", "order": 0},
                    {"id": "user did things", "type": "events", "order": 1},
                ],
                "funnel_window_days": 14,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response_json = response.json()
        # clickhouse funnels don't have a loading system
        self.assertEqual(len(response_json["result"]), 2)
        self.assertEqual(response_json["result"][0]["name"], "user signed up")
        self.assertEqual(response_json["result"][0]["count"], 1)
        self.assertEqual(response_json["result"][1]["name"], "user did things")
        self.assertEqual(response_json["result"][1]["count"], 1)

    # Tests backwards-compatibility when we changed GET to POST | GET
    def test_insight_funnels_basic_get(self) -> None:
        _create_event(team=self.team, event="user signed up", distinct_id="1")
        _create_event(team=self.team, event="user did things", distinct_id="1")
        response = self.client.get(
            f"/api/projects/{self.team.id}/insights/funnel/?funnel_window_days=14&events={json.dumps([{'id': 'user signed up', 'type': 'events', 'order': 0}, {'id': 'user did things', 'type': 'events', 'order': 1}])}"
        ).json()

        # clickhouse funnels don't have a loading system
        self.assertEqual(len(response["result"]), 2)
        self.assertEqual(response["result"][0]["name"], "user signed up")
        self.assertEqual(response["result"][1]["name"], "user did things")
        self.assertEqual(response["timezone"], "UTC")

    def test_logged_out_user_cannot_retrieve_insight(self) -> None:
        self.client.logout()
        insight = Insight.objects.create(
            filters=Filter(data={"events": [{"id": "$pageview"}]}).to_dict(),
            team=self.team,
            short_id="12345678",
        )

        response = self.client.get(
            f"/api/projects/{self.team.id}/insights/{insight.id}/",
        )

        self.assertEqual(response.status_code, 403, response.json())
        self.assertEqual(
            response.json(),
            self.unauthenticated_response(),
        )

    def test_logged_out_user_can_retrieve_insight_with_correct_insight_sharing_access_token(self) -> None:
        self.client.logout()
        _create_person(
            team=self.team,
            distinct_ids=["person1"],
            properties={"email": "person1@test.com"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="person1",
            timestamp=timezone.now() - timedelta(days=5),
        )
        flush_persons_and_events()
        insight = Insight.objects.create(
            name="Foobar",
            filters=Filter(data={"events": [{"id": "$pageview"}]}).to_dict(),
            team=self.team,
            short_id="12345678",
        )
        Insight.objects.create(  # This one isn't shared
            name="Foobar",
            filters=Filter(data={"events": [{"id": "$pageview"}]}).to_dict(),
            team=self.team,
            short_id="abcdfghi",
        )
        sharing_configuration = SharingConfiguration.objects.create(
            team=self.team, insight=insight, enabled=True, access_token="xyz"
        )
        other_sharing_configuration = SharingConfiguration.objects.create(
            team=self.team, enabled=True, access_token="klm"
        )

        response_invalid_token_retrieve = self.client.get(
            f"/api/projects/{self.team.id}/insights/{insight.id}/?sharing_access_token=abc",
        )
        response_incorrect_token_retrieve = self.client.get(
            f"/api/projects/{self.team.id}/insights/{insight.id}/?sharing_access_token={other_sharing_configuration.access_token}",
        )
        response_correct_token_retrieve = self.client.get(
            f"/api/projects/{self.team.id}/insights/{insight.id}/?sharing_access_token={sharing_configuration.access_token}",
        )
        response_correct_token_list = self.client.get(
            f"/api/projects/{self.team.id}/insights/?sharing_access_token={sharing_configuration.access_token}",
        )

        self.assertEqual(
            response_invalid_token_retrieve.status_code,
            403,
            response_invalid_token_retrieve.json(),
        )
        self.assertEqual(
            response_invalid_token_retrieve.json(),
            self.unauthenticated_response("Sharing access token is invalid.", "authentication_failed"),
        )
        self.assertEqual(
            response_incorrect_token_retrieve.status_code,
            404,
            response_incorrect_token_retrieve.json(),
        )
        self.assertEqual(
            response_incorrect_token_retrieve.json(),
            self.not_found_response(),
        )
        self.assertEqual(
            response_correct_token_retrieve.status_code,
            200,
            response_correct_token_retrieve.json(),
        )
        self.assertDictContainsSubset(
            {
                "name": "Foobar",
            },
            response_correct_token_retrieve.json(),
        )
        self.assertEqual(
            response_correct_token_list.status_code,
            200,
            response_correct_token_list.json(),
        )
        # abcdfghi not returned as it's not related to this sharing configuration
        self.assertEqual(response_correct_token_list.json()["count"], 1)
        self.assertDictContainsSubset(
            {
                "id": insight.id,
                "name": "Foobar",
                "short_id": "12345678",
            },
            response_correct_token_list.json()["results"][0],
        )

    def test_logged_out_user_cannot_retrieve_deleted_insight_with_correct_insight_sharing_access_token(self) -> None:
        self.client.logout()
        deleted_insight = Insight.objects.create(
            name="Foobar",
            filters=Filter(data={"events": [{"id": "$pageview"}]}).to_dict(),
            team=self.team,
            short_id="12345678",
            deleted=True,
        )
        sharing_configuration = SharingConfiguration.objects.create(
            team=self.team, insight=deleted_insight, enabled=True, access_token="ghi"
        )

        response_retrieve = self.client.get(
            f"/api/projects/{self.team.id}/insights/{deleted_insight.id}/?sharing_access_token={sharing_configuration.access_token}",
        )

        self.assertEqual(response_retrieve.status_code, 404, response_retrieve.json())
        self.assertEqual(
            response_retrieve.json(),
            self.not_found_response(),
        )

    def test_logged_out_user_cannot_update_insight_with_correct_insight_sharing_access_token(self) -> None:
        self.client.logout()
        insight = Insight.objects.create(
            name="Foobar",
            filters=Filter(data={"events": [{"id": "$pageview"}]}).to_dict(),
            team=self.team,
            short_id="12345678",
        )
        sharing_configuration = SharingConfiguration.objects.create(
            team=self.team, insight=insight, enabled=True, access_token="ghi"
        )

        response_retrieve = self.client.patch(
            f"/api/projects/{self.team.id}/insights/{insight.id}/?sharing_access_token={sharing_configuration.access_token}",
            {"name": "Barfoo"},
        )

        self.assertEqual(response_retrieve.status_code, 403, response_retrieve.json())
        self.assertEqual(
            response_retrieve.json(),
            self.unauthenticated_response(
                "Sharing access token can only be used for GET requests.",
                "authentication_failed",
            ),
        )

    def test_logged_out_user_cannot_retrieve_insight_with_disabled_insight_sharing_access_token(self) -> None:
        self.client.logout()
        insight = Insight.objects.create(
            filters=Filter(data={"events": [{"id": "$pageview"}]}).to_dict(),
            team=self.team,
            short_id="12345678",
        )
        sharing_configuration = SharingConfiguration.objects.create(
            team=self.team,
            insight=insight,
            enabled=False,
            access_token="xyz",  # DISABLED!
        )

        response_retrieve = self.client.get(
            f"/api/projects/{self.team.id}/insights/{insight.id}/?sharing_access_token={sharing_configuration.access_token}",
        )
        response_list = self.client.get(
            f"/api/projects/{self.team.id}/insights/?short_id={insight.short_id}&sharing_access_token={sharing_configuration.access_token}",
        )

        self.assertEqual(response_retrieve.status_code, 403, response_retrieve.json())
        self.assertEqual(
            response_retrieve.json(),
            self.unauthenticated_response("Sharing access token is invalid.", "authentication_failed"),
        )
        self.assertEqual(response_list.status_code, 403, response_retrieve.json())
        self.assertEqual(
            response_list.json(),
            self.unauthenticated_response("Sharing access token is invalid.", "authentication_failed"),
        )

    def test_logged_out_user_can_retrieve_insight_with_correct_dashboard_sharing_access_token(self) -> None:
        self.client.logout()
        _create_person(
            team=self.team,
            distinct_ids=["person1"],
            properties={"email": "person1@test.com"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="person1",
            timestamp=timezone.now() - timedelta(days=5),
        )
        flush_persons_and_events()
        insight = Insight.objects.create(
            name="Foobar",
            filters=Filter(data={"events": [{"id": "$pageview"}]}).to_dict(),
            team=self.team,
            short_id="12345678",
        )
        deleted_insight = Insight.objects.create(
            name="Barfoo",
            filters=Filter(data={"events": [{"id": "$pageview"}]}).to_dict(),
            team=self.team,
            short_id="87654321",
            deleted=True,
        )
        deleted_tile_insight = Insight.objects.create(
            name="Foobaz",
            filters=Filter(data={"events": [{"id": "$pageview"}]}).to_dict(),
            team=self.team,
            short_id="abcdabcd",
        )
        random_text = Text.objects.create(team=self.team)
        dashboard = Dashboard.objects.create(team=self.team, name="Test dashboard")
        DashboardTile.objects.create(dashboard=dashboard, insight=insight)
        DashboardTile.objects.create(dashboard=dashboard, insight=deleted_insight)
        DashboardTile.objects.create(dashboard=dashboard, insight=deleted_tile_insight, deleted=True)
        DashboardTile.objects.create(dashboard=dashboard, text=random_text)
        sharing_configuration = SharingConfiguration.objects.create(
            team=self.team, dashboard=dashboard, enabled=True, access_token="xyz"
        )

        response_incorrect_token_retrieve = self.client.get(
            f"/api/projects/{self.team.id}/insights/{insight.id}/?sharing_access_token=abc",
        )
        response_correct_token_retrieve = self.client.get(
            f"/api/projects/{self.team.id}/insights/{insight.id}/?sharing_access_token={sharing_configuration.access_token}",
        )
        response_correct_token_list = self.client.get(
            f"/api/projects/{self.team.id}/insights/?sharing_access_token={sharing_configuration.access_token}",
        )

        self.assertEqual(
            response_incorrect_token_retrieve.status_code,
            403,
            response_incorrect_token_retrieve.json(),
        )
        self.assertEqual(
            response_incorrect_token_retrieve.json(),
            self.unauthenticated_response("Sharing access token is invalid.", "authentication_failed"),
        )
        self.assertEqual(
            response_correct_token_retrieve.status_code,
            200,
            response_correct_token_retrieve.json(),
        )
        self.assertDictContainsSubset({"name": "Foobar"}, response_correct_token_retrieve.json())
        # Below checks that the deleted insight and non-deleted insight whose tile is deleted are not be retrievable
        # Also, the text tile should not affect things
        self.assertEqual(
            response_correct_token_list.status_code,
            200,
            response_correct_token_list.json(),
        )
        self.assertEqual(response_correct_token_list.json()["count"], 1)

    def test_logged_out_user_cannot_retrieve_insight_with_correct_deleted_dashboard_sharing_access_token(self) -> None:
        self.client.logout()
        insight = Insight.objects.create(
            name="Foobar",
            filters=Filter(data={"events": [{"id": "$pageview"}]}).to_dict(),
            team=self.team,
            short_id="12345678",
        )
        dashboard = Dashboard.objects.create(team=self.team, name="Test dashboard", deleted=True)
        DashboardTile.objects.create(dashboard=dashboard, insight=insight)
        sharing_configuration = SharingConfiguration.objects.create(
            team=self.team, dashboard=dashboard, enabled=True, access_token="xyz"
        )

        response_correct_token_list = self.client.get(
            f"/api/projects/{self.team.id}/insights/?sharing_access_token={sharing_configuration.access_token}",
        )

        self.assertEqual(
            response_correct_token_list.status_code,
            200,
            response_correct_token_list.json(),
        )
        self.assertEqual(response_correct_token_list.json()["count"], 0)

    def test_insight_trends_csv(self) -> None:
        with freeze_time("2012-01-14T03:21:34.000Z"):
            _create_event(team=self.team, event="$pageview", distinct_id="1")
            _create_event(team=self.team, event="$pageview", distinct_id="2")

        with freeze_time("2012-01-15T04:01:34.000Z"):
            _create_event(team=self.team, event="$pageview", distinct_id="2")
            response = self.client.get(
                f"/api/projects/{self.team.id}/insights/trend.csv/?events={json.dumps([{'id': '$pageview', 'custom_name': 'test custom'}])}&export_name=Pageview count&export_insight_id=test123"
            )

        lines = response.content.splitlines()

        self.assertEqual(lines[0], b"http://localhost:8010/insights/test123/", lines[0])
        self.assertEqual(
            lines[1],
            b"series,8-Jan-2012,9-Jan-2012,10-Jan-2012,11-Jan-2012,12-Jan-2012,13-Jan-2012,14-Jan-2012,15-Jan-2012",
            lines[0],
        )
        self.assertEqual(lines[2], b"test custom,0,0,0,0,0,0,2,1")
        self.assertEqual(len(lines), 3, response.content)

    def test_insight_trends_formula_and_fractional_numbers_csv(self) -> None:
        with freeze_time("2012-01-14T03:21:34.000Z"):
            _create_event(team=self.team, event="$pageview", distinct_id="1")
            _create_event(team=self.team, event="$pageview", distinct_id="2")

        with freeze_time("2012-01-15T04:01:34.000Z"):
            _create_event(team=self.team, event="$pageview", distinct_id="2")
            response = self.client.get(
                f"/api/projects/{self.team.id}/insights/trend.csv/?events={json.dumps([{'id': '$pageview', 'custom_name': 'test custom'}])}&export_name=Pageview count&export_insight_id=test123&formula=A*0.5"
            )

        lines = response.content.splitlines()

        self.assertEqual(lines[0], b"http://localhost:8010/insights/test123/", lines[0])
        self.assertEqual(
            lines[1],
            b"series,8-Jan-2012,9-Jan-2012,10-Jan-2012,11-Jan-2012,12-Jan-2012,13-Jan-2012,14-Jan-2012,15-Jan-2012",
            lines[0],
        )
        self.assertEqual(lines[2], b"Formula (A*0.5),0.0,0.0,0.0,0.0,0.0,0.0,1.0,0.5")
        self.assertEqual(len(lines), 3, response.content)

    # Extra permissioning tests here
    def test_insight_trends_allowed_if_project_open_and_org_member(self) -> None:
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        self.team.access_control = False
        self.team.save()
        response = self.client.get(
            f"/api/projects/{self.team.id}/insights/trend/?events={json.dumps([{'id': '$pageview'}])}"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def _create_one_person_cohort(self, properties: list[dict[str, Any]]) -> int:
        Person.objects.create(team=self.team, properties=properties)
        cohort_one_id = self.client.post(
            f"/api/projects/{self.team.id}/cohorts",
            data={"name": "whatever", "groups": [{"properties": properties}]},
        ).json()["id"]
        return cohort_one_id

    @freeze_time("2022-03-22T00:00:00.000Z")
    def test_create_insight_viewed(self) -> None:
        filter_dict = {"events": [{"id": "$pageview"}]}

        insight = Insight.objects.create(
            filters=Filter(data=filter_dict).to_dict(),
            team=self.team,
            short_id="12345678",
        )

        response = self.client.post(f"/api/projects/{self.team.id}/insights/{insight.id}/viewed")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        created_insight_viewed = InsightViewed.objects.all()[0]
        self.assertEqual(created_insight_viewed.insight, insight)
        self.assertEqual(created_insight_viewed.team, self.team)
        self.assertEqual(created_insight_viewed.user, self.user)
        self.assertEqual(
            created_insight_viewed.last_viewed_at,
            datetime(2022, 3, 22, 0, 0, tzinfo=ZoneInfo("UTC")),
        )

    def test_update_insight_viewed(self) -> None:
        filter_dict = {"events": [{"id": "$pageview"}]}
        insight = Insight.objects.create(
            filters=Filter(data=filter_dict).to_dict(),
            team=self.team,
            short_id="12345678",
        )
        with freeze_time("2022-03-22T00:00:00.000Z"):
            response = self.client.post(f"/api/projects/{self.team.id}/insights/{insight.id}/viewed")
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        with freeze_time("2022-03-23T00:00:00.000Z"):
            response = self.client.post(f"/api/projects/{self.team.id}/insights/{insight.id}/viewed")
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)
            self.assertEqual(InsightViewed.objects.count(), 1)

            updated_insight_viewed = InsightViewed.objects.all()[0]
            self.assertEqual(
                updated_insight_viewed.last_viewed_at,
                datetime(2022, 3, 23, 0, 0, tzinfo=ZoneInfo("UTC")),
            )

    def test_cant_view_insight_viewed_for_insight_in_another_team(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="other team")
        filter_dict = {"events": [{"id": "$pageview"}]}
        insight = Insight.objects.create(
            filters=Filter(data=filter_dict).to_dict(),
            team=other_team,
            short_id="12345678",
        )

        response = self.client.post(f"/api/projects/{self.team.id}/insights/{insight.id}/viewed")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(InsightViewed.objects.count(), 0)

    def test_get_recently_viewed_insights(self) -> None:
        insight_1_id, _ = self.dashboard_api.create_insight({"short_id": "12345678"})

        self.client.post(f"/api/projects/{self.team.id}/insights/{insight_1_id}/viewed")

        response = self.client.get(f"/api/projects/{self.team.id}/insights/my_last_viewed")
        response_data = response.json()

        # No results if no insights have been viewed
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        assert [r["id"] for r in response_data] == [insight_1_id]

    def test_get_recently_viewed_insights_include_query_based_insights(self) -> None:
        insight_1_id, _ = self.dashboard_api.create_insight({"short_id": "12345678"})
        insight_2_id, _ = self.dashboard_api.create_insight(
            {
                "short_id": "3456",
                "query": {
                    "kind": "DataTableNode",
                    "source": {
                        "kind": "EventsQuery",
                        "select": [
                            "*",
                            "event",
                            "person",
                            "coalesce(properties.$current_url, properties.$screen_name)",
                            "properties.$lib",
                            "timestamp",
                        ],
                        "properties": [
                            {
                                "type": "event",
                                "key": "$browser",
                                "operator": "exact",
                                "value": "Chrome",
                            }
                        ],
                        "limit": 100,
                    },
                },
            }
        )

        self.client.post(f"/api/projects/{self.team.id}/insights/{insight_1_id}/viewed")
        self.client.post(f"/api/projects/{self.team.id}/insights/{insight_2_id}/viewed")

        response = self.client.get(f"/api/projects/{self.team.id}/insights/my_last_viewed")
        response_data = response.json()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        assert [r["id"] for r in response_data] == [insight_2_id, insight_1_id]

    def test_get_recently_viewed_insights_when_no_insights_viewed(self) -> None:
        insight_1_id, _ = self.dashboard_api.create_insight({"short_id": "12345678"})

        response = self.client.get(f"/api/projects/{self.team.id}/insights/my_last_viewed")
        response_data = response.json()
        # No results if no insights have been viewed
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response_data), 0)

    def test_recently_viewed_insights_ordered_by_view_date(self) -> None:
        insight_1_id, _ = self.dashboard_api.create_insight({"short_id": "12345678"})
        insight_2_id, _ = self.dashboard_api.create_insight({"short_id": "98765432"})
        insight_3_id, _ = self.dashboard_api.create_insight({"short_id": "43219876"})

        # multiple views of a single don't drown out other views
        self.client.post(f"/api/projects/{self.team.id}/insights/{insight_1_id}/viewed")
        self.client.post(f"/api/projects/{self.team.id}/insights/{insight_1_id}/viewed")
        self.client.post(f"/api/projects/{self.team.id}/insights/{insight_1_id}/viewed")

        # soft-deleted insights aren't shown
        self.client.post(f"/api/projects/{self.team.id}/insights/{insight_3_id}/viewed")
        self.dashboard_api.soft_delete(insight_3_id, "insights")

        self.client.post(f"/api/projects/{self.team.id}/insights/{insight_2_id}/viewed")

        response = self.client.get(f"/api/projects/{self.team.id}/insights/my_last_viewed")
        response_data = response.json()

        # Insights are ordered by most recently viewed
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        assert [r["id"] for r in response_data] == [insight_2_id, insight_1_id]

        self.client.post(f"/api/projects/{self.team.id}/insights/{insight_1_id}/viewed")

        response = self.client.get(f"/api/projects/{self.team.id}/insights/my_last_viewed")
        response_data = response.json()

        # Order updates when an insight is viewed again
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        assert [r["id"] for r in response_data] == [insight_1_id, insight_2_id]

    def test_another_user_viewing_an_insight_does_not_impact_the_list(self) -> None:
        insight_1_id, _ = self.dashboard_api.create_insight({"short_id": "12345678"})

        another_user = User.objects.create_and_join(self.organization, "team2@posthog.com", None)
        InsightViewed.objects.create(
            team=self.team,
            user=another_user,
            insight_id=insight_1_id,
            last_viewed_at=timezone.now(),
        )

        response = self.client.get(f"/api/projects/{self.team.id}/insights/my_last_viewed")
        response_data = response.json()

        # Insights are ordered by most recently viewed
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response_data), 0)

    def test_get_recent_insights_with_feature_flag(self) -> None:
        filter_dict = {
            "events": [{"id": "$pageview"}],
            "breakdown": "$feature/insight-with-flag-used",
        }
        filter_dict2 = {
            "events": [{"id": "$pageview"}],
            "properties": [{"key": "$active_feature_flag", "value": "insight-with-flag-used"}],
        }
        filter_dict3 = {"events": [{"id": "$pageview"}], "breakdown": "email"}

        insight = Insight.objects.create(
            filters=Filter(data=filter_dict).to_dict(),
            team=self.team,
            short_id="11223344",
        )
        insight2 = Insight.objects.create(
            filters=Filter(data=filter_dict2).to_dict(),
            team=self.team,
            short_id="44332211",
        )
        Insight.objects.create(
            filters=Filter(data=filter_dict3).to_dict(),
            team=self.team,
            short_id="00992281",
        )

        response = self.client.get(f"/api/projects/{self.team.id}/insights/?feature_flag=insight-with-flag-used")
        response_data = response.json()

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        ids_in_response = [r["id"] for r in response_data["results"]]
        # insight 3 is not included in response
        self.assertCountEqual(ids_in_response, [insight.id, insight2.id])

    def test_cannot_create_insight_with_dashboards_relation_from_another_team(
        self,
    ) -> None:
        dashboard_own_team: Dashboard = Dashboard.objects.create(team=self.team)
        another_team = Team.objects.create(organization=self.organization)
        dashboard_other_team: Dashboard = Dashboard.objects.create(team=another_team)

        self.dashboard_api.create_insight(
            data={
                "filters": {
                    "events": [{"id": "$pageview"}],
                    "properties": [{"key": "$browser", "value": "Mac OS X"}],
                    "date_from": "-90d",
                },
                "dashboards": [dashboard_own_team.pk, dashboard_other_team.pk],
            },
            expected_status=status.HTTP_400_BAD_REQUEST,
        )

    @skip("is this not how things work?")
    def test_cannot_create_insight_in_another_team(
        self,
    ) -> None:
        another_team = Team.objects.create(organization=self.organization)

        # logged in to self.team and trying to create an insight in another_team
        self.dashboard_api.create_insight(
            team_id=another_team.pk,
            data={
                "filters": {
                    "events": [{"id": "$pageview"}],
                    "properties": [{"key": "$browser", "value": "Mac OS X"}],
                    "date_from": "-90d",
                },
            },
            expected_status=status.HTTP_400_BAD_REQUEST,
        )

    def test_cannot_update_insight_with_dashboard_from_another_team(self) -> None:
        another_team = Team.objects.create(organization=self.organization)
        dashboard_other_team: Dashboard = Dashboard.objects.create(team=another_team)
        dashboard_own_team: Dashboard = Dashboard.objects.create(team=self.team)

        insight_id, _ = self.dashboard_api.create_insight(
            data={
                "filters": {
                    "events": [{"id": "$pageview"}],
                    "properties": [{"key": "$browser", "value": "Mac OS X"}],
                    "date_from": "-90d",
                },
                "dashboards": [dashboard_own_team.pk],
            }
        )

        response = self.client.patch(
            f"/api/projects/{self.team.id}/insights/{insight_id}",
            {"dashboards": [dashboard_own_team.pk, dashboard_other_team.pk]},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_hard_delete_is_forbidden(self) -> None:
        insight_id, _ = self.dashboard_api.create_insight({"name": "to be deleted"})
        api_response = self.client.delete(f"/api/projects/{self.team.id}/insights/{insight_id}")
        self.assertEqual(api_response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        self.assertEqual(
            self.client.get(f"/api/projects/{self.team.id}/insights/{insight_id}").status_code,
            status.HTTP_200_OK,
        )

    def test_soft_delete_causes_404(self) -> None:
        insight_id, _ = self.dashboard_api.create_insight({"name": "to be deleted"})
        self.dashboard_api.get_insight(insight_id=insight_id, expected_status=status.HTTP_200_OK)

        update_response = self.client.patch(f"/api/projects/{self.team.id}/insights/{insight_id}", {"deleted": True})
        self.assertEqual(update_response.status_code, status.HTTP_200_OK)

        self.dashboard_api.get_insight(insight_id=insight_id, expected_status=status.HTTP_404_NOT_FOUND)

    def test_soft_delete_can_be_reversed_by_patch(self) -> None:
        insight_id, _ = self.dashboard_api.create_insight({"name": "an insight"})

        self.client.patch(
            f"/api/projects/{self.team.id}/insights/{insight_id}",
            {
                "deleted": True,
                "name": "an insight",
            },  # This request should work also if other fields are provided
        )

        self.assertEqual(
            self.client.get(f"/api/projects/{self.team.id}/insights/{insight_id}").status_code,
            status.HTTP_404_NOT_FOUND,
        )

        update_response = self.client.patch(
            f"/api/projects/{self.team.id}/insights/{insight_id}",
            {
                "deleted": False,
                "name": "an insight",
            },  # This request should work also if other fields are provided
        )
        self.assertEqual(update_response.status_code, status.HTTP_200_OK)

        self.assertEqual(
            self.client.get(f"/api/projects/{self.team.id}/insights/{insight_id}").status_code,
            status.HTTP_200_OK,
        )

        # assert that undeletes end up in the activity log
        activity_response = self.dashboard_api.get_insight_activity(insight_id)

        activity: list[dict] = activity_response["results"]
        # we will have three logged activities (in reverse order) undelete, delete, create
        assert [a["activity"] for a in activity] == ["updated", "updated", "created"]
        undelete_change_log = activity[0]["detail"]["changes"][0]
        assert undelete_change_log == {
            "action": "changed",
            "after": False,
            "before": True,
            "field": "deleted",
            "type": "Insight",
        }

    def test_soft_delete_cannot_be_reversed_for_another_team(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="other team")
        other_insight = Insight.objects.create(
            filters=Filter(data={"events": [{"id": "$pageview"}]}).to_dict(),
            team=other_team,
            short_id="abcabc",
            deleted=True,
        )

        other_update_response = self.client.patch(
            f"/api/projects/{self.team.id}/insights/{other_insight.id}",
            {"deleted": False},
        )
        self.assertEqual(other_update_response.status_code, status.HTTP_404_NOT_FOUND)

    def test_cancel_running_query(self) -> None:
        # There is no good way of writing a test that tests this without it being very slow
        #  Just verify it doesn't throw an error
        response = self.client.post(
            f"/api/projects/{self.team.id}/insights/cancel",
            {"client_query_id": f"testid"},
        )
        self.assertEqual(response.status_code, 201, response.content)

    @patch("posthog.decorators.get_safe_cache")
    def test_including_query_id_does_not_affect_cache_key(self, patched_get_safe_cache) -> None:
        """
        regression test, by introducing a query_id we were changing the cache key
        so, if you made the same query twice, the second one would not be cached, only because the query id had changed
        """
        self._get_insight_with_client_query_id("b3ef3987-b8e7-4339-b9b8-fa2b65606692")
        self._get_insight_with_client_query_id("00000000-b8e7-4339-b9b8-fa2b65606692")

        assert patched_get_safe_cache.call_count == 2
        assert patched_get_safe_cache.call_args_list[0] == patched_get_safe_cache.call_args_list[1]

    def _get_insight_with_client_query_id(self, client_query_id: str) -> None:
        query_params = f"?events={json.dumps([{'id': '$pageview'}])}&client_query_id={client_query_id}"
        self.client.get(f"/api/projects/{self.team.id}/insights/trend/{query_params}").json()

    def assert_insight_activity(self, insight_id: Optional[int], expected: list[dict]):
        activity_response = self.dashboard_api.get_insight_activity(insight_id)

        activity: list[dict] = activity_response["results"]

        self.maxDiff = None
        assert activity == expected

    @also_test_with_materialized_columns(event_properties=["int_value"], person_properties=["fish"])
    @snapshot_clickhouse_queries
    def test_insight_trend_hogql_global_filters(self) -> None:
        _create_person(team=self.team, distinct_ids=["1"], properties={"fish": "there is no fish"})
        with freeze_time("2012-01-14T03:21:34.000Z"):
            for i in range(25):
                _create_event(
                    team=self.team,
                    event="$pageview",
                    distinct_id="1",
                    properties={"int_value": i},
                )
        with freeze_time("2012-01-15T04:01:34.000Z"):
            # 25 events total
            response = self.client.get(
                f"/api/projects/{self.team.id}/insights/trend/",
                data={"events": json.dumps([{"id": "$pageview"}])},
            )
            found_data_points = response.json()["result"][0]["count"]
            self.assertEqual(found_data_points, 25)

            # test trends global property filter
            response = self.client.get(
                f"/api/projects/{self.team.id}/insights/trend/",
                data={
                    "events": json.dumps([{"id": "$pageview"}]),
                    "properties": json.dumps(
                        [
                            {
                                "key": "toInt(properties.int_value) > 10 and 'bla' != 'a%sd'",
                                "type": "hogql",
                            },
                            {
                                "key": "like(person.properties.fish, '%fish%')",
                                "type": "hogql",
                            },
                        ]
                    ),
                },
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
            found_data_points = response.json()["result"][0]["count"]
            self.assertEqual(found_data_points, 14)

            # test trends global property filter with a disallowed placeholder
            response_placeholder = self.client.get(
                f"/api/projects/{self.team.id}/insights/trend/",
                data={
                    "events": json.dumps([{"id": "$pageview"}]),
                    "properties": json.dumps(
                        [
                            {"key": "{team_id} * 5", "type": "hogql"},
                        ]
                    ),
                },
            )
            self.assertEqual(
                response_placeholder.status_code,
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                response_placeholder.json(),
            )
            # With the new HogQL query runner this legacy endpoint now returns 500 instead of a proper 400.
            # We don't really care, since this endpoint should eventually be removed alltogether.
            # self.assertEqual(
            #     response_placeholder.json(),
            #     self.validation_error_response("Unresolved placeholder: {team_id}"),
            # )

    @also_test_with_materialized_columns(event_properties=["int_value"], person_properties=["fish"])
    @snapshot_clickhouse_queries
    def test_insight_trend_hogql_local_filters(self) -> None:
        _create_person(team=self.team, distinct_ids=["1"], properties={"fish": "there is no fish"})
        with freeze_time("2012-01-14T03:21:34.000Z"):
            for i in range(25):
                _create_event(
                    team=self.team,
                    event="$pageview",
                    distinct_id="1",
                    properties={"int_value": i},
                )
        with freeze_time("2012-01-15T04:01:34.000Z"):
            # test trends local property filter
            response = self.client.get(
                f"/api/projects/{self.team.id}/insights/trend/",
                data={
                    "events": json.dumps(
                        [
                            {
                                "id": "$pageview",
                                "properties": json.dumps(
                                    [
                                        {
                                            "key": "toInt(properties.int_value) < 10 and 'bla' != 'a%sd'",
                                            "type": "hogql",
                                        },
                                        {
                                            "key": "like(person.properties.fish, '%fish%')",
                                            "type": "hogql",
                                        },
                                    ]
                                ),
                            }
                        ]
                    )
                },
            )
            found_data_points = response.json()["result"][0]["count"]
            self.assertEqual(found_data_points, 10)

    @also_test_with_materialized_columns(event_properties=["int_value"], person_properties=["fish"])
    @snapshot_clickhouse_queries
    def test_insight_trend_hogql_breakdown(self) -> None:
        _create_person(team=self.team, distinct_ids=["1"], properties={"fish": "there is no fish"})
        with freeze_time("2012-01-14T03:21:34.000Z"):
            for i in range(25):
                _create_event(
                    team=self.team,
                    event="$pageview",
                    distinct_id="1",
                    properties={"int_value": i},
                )
        with freeze_time("2012-01-15T04:01:34.000Z"):
            # test trends breakdown
            response = self.client.get(
                f"/api/projects/{self.team.id}/insights/trend/",
                data={
                    "events": json.dumps([{"id": "$pageview"}]),
                    "breakdown_type": "hogql",
                    "breakdown": "if(toInt(properties.int_value) < 10, 'le%ss', 'more')",
                },
            )
            result = response.json()["result"]
            self.assertEqual(result[0]["count"], 15)
            self.assertEqual(result[0]["breakdown_value"], "more")
            self.assertEqual(result[1]["count"], 10)
            self.assertEqual(result[1]["breakdown_value"], "le%ss")

    @snapshot_clickhouse_queries
    @also_test_with_materialized_columns(event_properties=["int_value"], person_properties=["fish"])
    def test_insight_funnels_hogql_global_filters(self) -> None:
        with freeze_time("2012-01-15T04:01:34.000Z"):
            _create_person(
                team=self.team,
                distinct_ids=["1"],
                properties={"fish": "there is no fish"},
            )
            _create_event(
                team=self.team,
                event="user signed up",
                distinct_id="1",
                properties={"int_value": 1},
            )
            _create_event(
                team=self.team,
                event="user did things",
                distinct_id="1",
                properties={"int_value": 20},
            )
            response = self.client.post(
                f"/api/projects/{self.team.id}/insights/funnel/",
                {
                    "events": [
                        {"id": "user signed up", "type": "events", "order": 0},
                        {"id": "user did things", "type": "events", "order": 1},
                    ],
                    "properties": json.dumps(
                        [
                            {
                                "key": "toInt(properties.int_value) < 10 and 'bla' != 'a%sd'",
                                "type": "hogql",
                            },
                            {
                                "key": "like(person.properties.fish, '%fish%')",
                                "type": "hogql",
                            },
                        ]
                    ),
                    "funnel_window_days": 14,
                },
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            response_json = response.json()
            self.assertEqual(len(response_json["result"]), 2)
            self.assertEqual(response_json["result"][0]["name"], "user signed up")
            self.assertEqual(response_json["result"][0]["count"], 1)
            self.assertEqual(response_json["result"][1]["name"], "user did things")
            self.assertEqual(response_json["result"][1]["count"], 0)
            self.assertEqual(response_json["timezone"], "UTC")

    @snapshot_clickhouse_queries
    @also_test_with_materialized_columns(event_properties=["int_value"], person_properties=["fish"])
    def test_insight_funnels_hogql_local_filters(self) -> None:
        with freeze_time("2012-01-15T04:01:34.000Z"):
            _create_person(
                team=self.team,
                distinct_ids=["1"],
                properties={"fish": "there is no fish"},
            )
            _create_event(
                team=self.team,
                event="user signed up",
                distinct_id="1",
                properties={"int_value": 1},
            )
            _create_event(
                team=self.team,
                event="user did things",
                distinct_id="1",
                properties={"int_value": 20},
            )
            response = self.client.post(
                f"/api/projects/{self.team.id}/insights/funnel/",
                {
                    "events": [
                        {
                            "id": "user signed up",
                            "type": "events",
                            "order": 0,
                            "properties": json.dumps(
                                [
                                    {
                                        "key": "toInt(properties.int_value) < 10 and 'bla' != 'a%sd'",
                                        "type": "hogql",
                                    },
                                    {
                                        "key": "like(person.properties.fish, '%fish%')",
                                        "type": "hogql",
                                    },
                                ]
                            ),
                        },
                        {
                            "id": "user did things",
                            "type": "events",
                            "order": 1,
                            "properties": json.dumps(
                                [
                                    {
                                        "key": "toInt(properties.int_value) < 10 and 'bla' != 'a%sd'",
                                        "type": "hogql",
                                    },
                                    {
                                        "key": "like(person.properties.fish, '%fish%')",
                                        "type": "hogql",
                                    },
                                ]
                            ),
                        },
                    ],
                    "funnel_window_days": 14,
                },
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            response_json = response.json()
            self.assertEqual(len(response_json["result"]), 2)
            self.assertEqual(response_json["result"][0]["name"], "user signed up")
            self.assertEqual(response_json["result"][0]["count"], 1)
            self.assertEqual(response_json["result"][1]["name"], "user did things")
            self.assertEqual(response_json["result"][1]["count"], 0)
            self.assertEqual(response_json["timezone"], "UTC")

    @snapshot_clickhouse_queries
    @also_test_with_materialized_columns(event_properties=["int_value"], person_properties=["fish"])
    def test_insight_funnels_hogql_breakdown(self) -> None:
        with freeze_time("2012-01-15T04:01:34.000Z"):
            _create_person(
                team=self.team,
                distinct_ids=["1"],
                properties={"fish": "there is no fish"},
            )
            _create_event(
                team=self.team,
                event="user signed up",
                distinct_id="1",
                properties={"int_value": 1},
            )
            _create_event(
                team=self.team,
                event="user did things",
                distinct_id="1",
                properties={"int_value": 20},
            )
            response = self.client.post(
                f"/api/projects/{self.team.id}/insights/funnel/",
                {
                    "breakdown_type": "hogql",
                    "breakdowns": [{"property": "person.properties.fish", "type": "hogql"}],
                    "events": [
                        {"id": "user signed up", "type": "events", "order": 0},
                        {"id": "user did things", "type": "events", "order": 1},
                    ],
                    "properties": json.dumps(
                        [
                            {
                                "key": "toInt(properties.int_value) < 10 and 'bla' != 'a%sd'",
                                "type": "hogql",
                            },
                        ]
                    ),
                    "funnel_window_days": 14,
                },
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
            response_json = response.json()
            self.assertEqual(len(response_json["result"]), 1)
            self.assertEqual(len(response_json["result"][0]), 2)
            self.assertEqual(response_json["result"][0][0]["name"], "user signed up")
            self.assertEqual(response_json["result"][0][0]["count"], 1)
            self.assertEqual(response_json["result"][0][0]["breakdown"], ["there is no fish"])
            self.assertEqual(response_json["result"][0][0]["breakdown_value"], ["there is no fish"])
            self.assertEqual(response_json["result"][0][1]["name"], "user did things")
            self.assertEqual(response_json["result"][0][1]["count"], 0)
            self.assertEqual(response_json["result"][0][1]["breakdown"], ["there is no fish"])
            self.assertEqual(response_json["result"][0][1]["breakdown_value"], ["there is no fish"])
            self.assertEqual(response_json["timezone"], "UTC")

    # @snapshot_clickhouse_queries
    @also_test_with_materialized_columns(event_properties=["int_value"], person_properties=["fish"])
    def test_insight_funnels_hogql_breakdown_single(self) -> None:
        with freeze_time("2012-01-15T04:01:34.000Z"):
            _create_person(
                team=self.team,
                distinct_ids=["1"],
                properties={"fish": "there is no fish"},
            )
            _create_event(
                team=self.team,
                event="user signed up",
                distinct_id="1",
                properties={"int_value": 1},
            )
            _create_event(
                team=self.team,
                event="user did things",
                distinct_id="1",
                properties={"int_value": 20},
            )
            response = self.client.post(
                f"/api/projects/{self.team.id}/insights/funnel/",
                {
                    "breakdown_type": "hogql",
                    "breakdown": "person.properties.fish",
                    "events": [
                        {"id": "user signed up", "type": "events", "order": 0},
                        {"id": "user did things", "type": "events", "order": 1},
                    ],
                    "properties": json.dumps(
                        [
                            {
                                "key": "toInt(properties.int_value) < 10 and 'bla' != 'a%sd'",
                                "type": "hogql",
                            },
                        ]
                    ),
                    "funnel_window_days": 14,
                },
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
            response_json = response.json()
            self.assertEqual(len(response_json["result"]), 1)
            self.assertEqual(len(response_json["result"][0]), 2)
            self.assertEqual(response_json["result"][0][0]["name"], "user signed up")
            self.assertEqual(response_json["result"][0][0]["count"], 1)
            self.assertEqual(response_json["result"][0][0]["breakdown"], ["there is no fish"])
            self.assertEqual(response_json["result"][0][0]["breakdown_value"], ["there is no fish"])
            self.assertEqual(response_json["result"][0][1]["name"], "user did things")
            self.assertEqual(response_json["result"][0][1]["count"], 0)
            self.assertEqual(response_json["result"][0][1]["breakdown"], ["there is no fish"])
            self.assertEqual(response_json["result"][0][1]["breakdown_value"], ["there is no fish"])
            self.assertEqual(response_json["timezone"], "UTC")

    def test_insight_funnels_hogql_aggregating_steps(self) -> None:
        with freeze_time("2012-01-15T04:01:34.000Z"):
            _create_person(team=self.team, distinct_ids=["1"], properties={"int_value": 1})
            _create_event(
                team=self.team,
                event="user signed up",
                distinct_id="1",
                properties={"$browser": "Chrome"},
            )
            _create_event(
                team=self.team,
                event="user signed up",
                distinct_id="1",
                properties={"$browser": "Firefox"},
            )
            _create_event(
                team=self.team,
                event="user did things",
                distinct_id="1",
                properties={"$browser": "Chrome"},
            )
            response = self.client.post(
                f"/api/projects/{self.team.id}/insights/funnel/",
                {
                    "insight": "FUNNELS",
                    "entity_type": "events",
                    "events": [
                        {
                            "id": "user signed up",
                            "type": "events",
                            "order": 0,
                            "math": "total",
                        },
                        {
                            "id": "user did things",
                            "type": "events",
                            "order": 1,
                            "math": "total",
                        },
                    ],
                    "properties": json.dumps(
                        [
                            {
                                "key": "toInt(person.properties.int_value) < 10 and 'bla' != 'a%sd'",
                                "type": "hogql",
                            },
                        ]
                    ),
                    "funnel_aggregate_by_hogql": "properties.$browser",
                    "funnel_viz_type": "steps",
                },
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            response_json = response.json()
            self.assertEqual(len(response_json["result"]), 2)
            self.assertEqual(response_json["result"][0]["name"], "user signed up")
            self.assertEqual(response_json["result"][0]["count"], 2)
            self.assertEqual(response_json["result"][1]["name"], "user did things")
            self.assertEqual(response_json["result"][1]["count"], 1)
            self.assertEqual(response_json["timezone"], "UTC")

    @skip("Compatibility issue CH 23.12 (see #21318)")
    def test_insight_funnels_hogql_aggregating_time_to_convert(self) -> None:
        with freeze_time("2012-01-15T04:01:34.000Z"):
            _create_person(team=self.team, distinct_ids=["1"], properties={"int_value": 1})
            _create_event(
                team=self.team,
                event="user signed up",
                distinct_id="1",
                properties={"$browser": "Chrome"},
            )
        with freeze_time("2012-01-15T04:01:36.500Z"):
            _create_event(
                team=self.team,
                event="user signed up",
                distinct_id="1",
                properties={"$browser": "Firefox"},
            )
        with freeze_time("2012-01-15T04:01:38.200Z"):
            _create_event(
                team=self.team,
                event="user did things",
                distinct_id="1",
                properties={"$browser": "Chrome"},
            )
        with freeze_time("2012-01-16T04:01:38.200Z"):
            response = self.client.post(
                f"/api/projects/{self.team.id}/insights/funnel/",
                {
                    "insight": "FUNNELS",
                    "entity_type": "events",
                    "events": [
                        {
                            "id": "user signed up",
                            "type": "events",
                            "order": 0,
                            "math": "total",
                        },
                        {
                            "id": "user did things",
                            "type": "events",
                            "order": 1,
                            "math": "total",
                        },
                    ],
                    "properties": json.dumps(
                        [
                            {
                                "key": "toInt(person.properties.int_value) < 10 and 'bla' != 'a%sd'",
                                "type": "hogql",
                            },
                        ]
                    ),
                    "funnel_aggregate_by_hogql": "properties.$browser",
                    "funnel_viz_type": "time_to_convert",
                    "date_from": "-14d",
                    "date_to": None,
                },
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            response_json = response.json()
            self.assertEqual(response_json["result"]["bins"], [[4.0, 1], [64.0, 0]])
            self.assertEqual(response_json["result"]["average_conversion_time"], 4.0)
            self.assertEqual(response_json["timezone"], "UTC")

    def test_insight_funnels_hogql_aggregating_trends(self) -> None:
        with freeze_time("2012-01-15T04:01:34.000Z"):
            _create_person(team=self.team, distinct_ids=["1"], properties={"int_value": 1})
            _create_event(
                team=self.team,
                event="user signed up",
                distinct_id="1",
                properties={"$browser": "Chrome"},
            )
        with freeze_time("2012-01-15T04:01:36.500Z"):
            _create_event(
                team=self.team,
                event="user signed up",
                distinct_id="1",
                properties={"$browser": "Firefox"},
            )
        with freeze_time("2012-01-15T04:01:38.200Z"):
            _create_event(
                team=self.team,
                event="user did things",
                distinct_id="1",
                properties={"$browser": "Chrome"},
            )
        with freeze_time("2012-01-16T04:01:38.200Z"):
            response = self.client.post(
                f"/api/projects/{self.team.id}/insights/funnel/",
                {
                    "insight": "FUNNELS",
                    "entity_type": "events",
                    "events": [
                        {"id": "user signed up", "type": "events", "order": 0},
                        {"id": "user did things", "type": "events", "order": 1},
                    ],
                    "properties": json.dumps(
                        [
                            {
                                "key": "toInt(person.properties.int_value) < 10 and 'bla' != 'a%sd'",
                                "type": "hogql",
                            },
                        ]
                    ),
                    "funnel_aggregate_by_hogql": "properties.$browser",
                    "funnel_viz_type": "trends",
                },
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            response_json = response.json()
            self.assertEqual(len(response_json["result"]), 1)
            self.assertEqual(
                response_json["result"][0]["data"],
                [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 50.0, 0.0],
            )
            self.assertEqual(
                response_json["result"][0]["days"],
                [
                    "2012-01-09",
                    "2012-01-10",
                    "2012-01-11",
                    "2012-01-12",
                    "2012-01-13",
                    "2012-01-14",
                    "2012-01-15",
                    "2012-01-16",
                ],
            )
            self.assertEqual(
                response_json["result"][0]["labels"],
                [
                    "9-Jan-2012",
                    "10-Jan-2012",
                    "11-Jan-2012",
                    "12-Jan-2012",
                    "13-Jan-2012",
                    "14-Jan-2012",
                    "15-Jan-2012",
                    "16-Jan-2012",
                ],
            )
            self.assertEqual(response_json["timezone"], "UTC")

    def test_insight_with_filters_via_hogql(self) -> None:
        filter_dict = {"insight": "LIFECYCLE", "events": [{"id": "$pageview"}]}

        insight = Insight.objects.create(
            filters=Filter(data=filter_dict).to_dict(),
            team=self.team,
            short_id="xyz123",
        )

        # fresh response
        response = self.client.get(f"/api/projects/{self.team.id}/insights/{insight.id}/?refresh=true")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["result"][0]["data"], [0, 0, 0, 0, 0, 0, 0, 0])
        self.assertFalse(response.json()["is_cached"])

        # cached response
        response = self.client.get(f"/api/projects/{self.team.id}/insights/{insight.id}/?refresh=false&use_cache=true")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["result"][0]["data"], [0, 0, 0, 0, 0, 0, 0, 0])
        self.assertTrue(response.json()["is_cached"])

    def test_insight_returns_cached_hogql(self) -> None:
        insight = Insight.objects.create(
            query={
                "kind": NodeKind.INSIGHT_VIZ_NODE.value,
                "source": {
                    "filterTestAccounts": False,
                    "kind": InsightNodeKind.TRENDS_QUERY.value,
                    "series": [
                        {
                            "kind": NodeKind.EVENTS_NODE.value,
                            "event": "$pageview",
                            "name": "$pageview",
                            "math": "total",
                        }
                    ],
                    "interval": "day",
                },
            },
            team=self.team,
            created_by=self.user,
        )

        response = self.client.get(
            f"/api/projects/{self.team.id}/insights",
            data={
                "short_id": insight.short_id,
            },
        ).json()

        self.assertNotIn("code", response)  # Watching out for an error code
        self.assertEqual(response["results"][0]["last_refresh"], None)
        self.assertIsNone(response["results"][0]["hogql"])

        response = self.client.get(
            f"/api/projects/{self.team.id}/insights",
            data={"short_id": insight.short_id, "refresh": True},
        ).json()

        self.assertNotIn("code", response)
        self.assertIsNotNone(response["results"][0]["hogql"])

    def test_insight_returns_cached_types(self) -> None:
        insight = Insight.objects.create(
            query={
                "kind": NodeKind.HOG_QL_QUERY,
                "query": """
                        select toDate(timestamp) as timestamp, count()
                        from events
                        where {filters} and timestamp <= now()
                        group by timestamp
                        order by timestamp asc
                        limit 100
                    """,
            },
            team=self.team,
            created_by=self.user,
        )

        response = self.client.get(
            f"/api/projects/{self.team.id}/insights",
            data={
                "short_id": insight.short_id,
            },
        ).json()

        self.assertNotIn("code", response)
        self.assertEqual(response["results"][0]["last_refresh"], None)
        self.assertIsNone(response["results"][0]["types"])

        response = self.client.get(
            f"/api/projects/{self.team.id}/insights",
            data={"short_id": insight.short_id, "refresh": True},
        ).json()

        self.assertNotIn("code", response)
        self.assertIsNotNone(response["results"][0]["types"])

    def test_insight_variables_overrides(self):
        dashboard = Dashboard.objects.create(
            team=self.team,
            name="dashboard 1",
            created_by=self.user,
        )
        variable = InsightVariable.objects.create(
            team=self.team, name="Test 1", code_name="test_1", default_value="some_default_value", type="String"
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
        )
        DashboardTile.objects.create(dashboard=dashboard, insight=insight)

        response = self.client.get(
            f"/api/projects/{self.team.id}/insights/{insight.pk}",
            data={
                "from_dashboard": dashboard.pk,
                "variables_override": json.dumps(
                    {
                        str(variable.id): {
                            "code_name": variable.code_name,
                            "variableId": str(variable.id),
                            "value": "override value!",
                        }
                    }
                ),
            },
        ).json()

        assert isinstance(response["query"], dict)
        assert isinstance(response["query"]["source"], dict)
        assert isinstance(response["query"]["source"]["variables"], dict)

        assert len(response["query"]["source"]["variables"].keys()) == 1
        for key, value in response["query"]["source"]["variables"].items():
            assert key == str(variable.id)
            assert value["code_name"] == variable.code_name
            assert value["variableId"] == str(variable.id)
            assert value["value"] == "override value!"

    def test_insight_access_control_filtering(self) -> None:
        """Test that insights are properly filtered based on access control."""

        user2 = self._create_user("test2@posthog.com")

        visible_insight = Insight.objects.create(
            team=self.team,
            name="Public Insight",
            created_by=self.user,
            filters={"events": [{"id": "$pageview"}]},
        )
        hidden_insight = Insight.objects.create(
            team=self.team,
            name="Hidden Insight",
            created_by=self.user,
            filters={"events": [{"id": "$pageview"}]},
        )
        AccessControl.objects.create(
            resource="insight", resource_id=hidden_insight.id, team=self.team, access_level="none"
        )

        # Verify we can access visible insights
        self.client.force_login(user2)
        response = self.client.get(f"/api/projects/{self.team.pk}/insights/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        insight_ids = [insight["id"] for insight in response.json()["results"]]
        self.assertIn(visible_insight.id, insight_ids)
        self.assertNotIn(hidden_insight.id, insight_ids)

        # Verify we can access all insights as creator
        self.client.force_login(self.user)
        response = self.client.get(f"/api/projects/{self.team.pk}/insights/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn(visible_insight.id, [insight["id"] for insight in response.json()["results"]])
        self.assertIn(hidden_insight.id, [insight["id"] for insight in response.json()["results"]])

    def test_create_insight_in_specific_folder(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/insights/",
            {
                "name": "My test insight in folder",
                "filters": {"events": [{"id": "$pageview"}]},
                "_create_in_folder": "Special Folder/Subfolder",
                "saved": True,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.json())
        insight_id = response.json()["short_id"]

        assert insight_id is not None

        from posthog.models.file_system.file_system import FileSystem

        fs_entry = FileSystem.objects.filter(team=self.team, ref=str(insight_id), type="insight").first()
        assert fs_entry is not None
        assert "Special Folder/Subfolder" in fs_entry.path

    def test_insight_with_variables_match_existing_variables(self):
        """Test that variables on insights are always referencing existing variables"""

        # Create an insight with a DataVisualizationNode query that references a fake variable
        insight = Insight.objects.create(
            team=self.team,
            query={
                "kind": "DataVisualizationNode",
                "source": {
                    "kind": "HogQLQuery",
                    "query": "SELECT {variables.test_var}",
                    "variables": {
                        "123e4567-e89b-12d3-a456-426614174000": {
                            "code_name": "test_var",
                            "variableId": "123e4567-e89b-12d3-a456-426614174000",
                        }
                    },
                },
                "display": "ActionsTable",
                "chartSettings": {"seriesBreakdownColumn": None},
                "tableSettings": {"conditionalFormatting": []},
            },
        )

        response = self.client.get(f"/api/projects/{self.team.id}/insights/{insight.id}")
        self.assertEqual(response.status_code, 200)

        response_data = response.json()
        self.assertIn("query", response_data)
        self.assertIn("source", response_data["query"])
        self.assertIn("variables", response_data["query"]["source"])

        # only one variable should be included
        self.assertEqual(len(response_data["query"]["source"]["variables"]), 0)

        variable = InsightVariable.objects.create(team=self.team, code_name="test_var", name="Test Variable")

        # # Get the insight via the API
        response = self.client.get(f"/api/projects/{self.team.id}/insights/{insight.id}")
        self.assertEqual(response.status_code, 200)

        # # Verify both variables are properly included in the response
        response_data = response.json()
        self.assertIn("query", response_data)
        self.assertIn("source", response_data["query"])
        self.assertIn("variables", response_data["query"]["source"])

        # # Check that the variable properties are included
        variable_id = str(variable.id)
        self.assertIn(variable_id, response_data["query"]["source"]["variables"])
        variable_data = response_data["query"]["source"]["variables"][variable_id]
        self.assertEqual(variable_data["code_name"], "test_var")
        self.assertEqual(variable_data["variableId"], variable_id)
