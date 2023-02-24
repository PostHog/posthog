import json
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from unittest import mock
from unittest.case import skip
from unittest.mock import patch

import pytz
from django.test import override_settings
from django.utils import timezone
from freezegun import freeze_time
from rest_framework import status

from ee.api.test.base import LicensedTestMixin
from ee.models import DashboardPrivilege
from ee.models.explicit_team_membership import ExplicitTeamMembership
from posthog.api.test.dashboards import DashboardAPI
from posthog.caching.fetch_from_cache import synchronously_update_cache
from posthog.models import (
    Cohort,
    Dashboard,
    DashboardTile,
    Filter,
    Insight,
    InsightViewed,
    Person,
    Team,
    User,
)
from posthog.models.organization import OrganizationMembership
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    QueryMatchingTest,
    _create_event,
    _create_person,
    also_test_with_materialized_columns,
    snapshot_clickhouse_queries,
    snapshot_postgres_queries,
)
from posthog.test.db_context_capturing import capture_db_queries
from posthog.test.test_journeys import journeys_for


class TestInsight(ClickhouseTestMixin, LicensedTestMixin, APIBaseTest, QueryMatchingTest):
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

    def test_created_updated_and_last_modified(self) -> None:
        alt_user = User.objects.create_and_join(self.organization, "team2@posthog.com", None)
        self_user_basic_serialized = {
            "id": self.user.id,
            "uuid": str(self.user.uuid),
            "distinct_id": self.user.distinct_id,
            "first_name": self.user.first_name,
            "email": self.user.email,
            "is_email_verified": None,
        }
        alt_user_basic_serialized = {
            "id": alt_user.id,
            "uuid": str(alt_user.uuid),
            "distinct_id": alt_user.distinct_id,
            "first_name": alt_user.first_name,
            "email": alt_user.email,
            "is_email_verified": None,
        }

        # Newly created insight should have created_at being the current time, and same last_modified_at
        # Fields created_by and last_modified_by should be set to the current user
        with freeze_time("2021-08-23T12:00:00Z"):
            response_1 = self.client.post(f"/api/projects/{self.team.id}/insights/")
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

        insight_id = response_1.json()["id"]

        # Updating fields that don't change the substance of the insight should affect updated_at
        # BUT NOT last_modified_at or last_modified_by
        with freeze_time("2021-09-20T12:00:00Z"):
            response_2 = self.client.patch(
                f"/api/projects/{self.team.id}/insights/{insight_id}",
                {"favorited": True},
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

    def test_get_insight_by_short_id(self) -> None:
        filter_dict = {"events": [{"id": "$pageview"}]}

        Insight.objects.create(
            filters=Filter(data=filter_dict).to_dict(),
            team=self.team,
            short_id="12345678",
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
            },
        )

    # :KLUDGE: avoid making extra queries that are explicitly not cached in tests. Avoids false N+1-s.
    @override_settings(PERSON_ON_EVENTS_OVERRIDE=False)
    @snapshot_postgres_queries
    def test_listing_insights_does_not_nplus1(self) -> None:
        query_counts: List[int] = []
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
            [11, 11, 11, 11, 11],
            query_counts,
            f"received query counts\n\n{query_counts}",
        )

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

    def test_searching_insights_includes_tags_and_description(self) -> None:
        insight_one_id, _ = self.dashboard_api.create_insight(
            {
                "name": "needle in a haystack",
                "filters": {"events": [{"id": "$pageview"}]},
            }
        )
        insight_two_id, _ = self.dashboard_api.create_insight(
            {"name": "not matching", "filters": {"events": [{"id": "$pageview"}]}}
        )

        insight_three_id, _ = self.dashboard_api.create_insight(
            {
                "name": "not matching name",
                "filters": {"events": [{"id": "$pageview"}]},
                "tags": ["needle"],
            }
        )

        insight_four_id, _ = self.dashboard_api.create_insight(
            {
                "name": "not matching name",
                "description": "another needle",
                "filters": {"events": [{"id": "$pageview"}]},
                "tags": ["not matching"],
            }
        )

        matching = self.client.get(f"/api/projects/{self.team.id}/insights/?search=needle")
        self.assertEqual(matching.status_code, status.HTTP_200_OK)
        matched_insights = [insight["id"] for insight in matching.json()["results"]]
        assert sorted(matched_insights) == [
            insight_one_id,
            insight_three_id,
            insight_four_id,
        ]

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
            f'/api/projects/{self.team.pk}/insights?short_id={insight_json["short_id"]}'
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
            insight_id, {"dashboards": [deleted_dashboard_id]}, expected_status=status.HTTP_400_BAD_REQUEST
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
            self.assertEqual(sorted(response_data["tags"]), sorted(["add", "these", "tags"]))
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
                                    "field": "tags",
                                    "before": [],
                                    "after": ["add", "tags", "these"],
                                },
                                {
                                    "type": "Insight",
                                    "action": "changed",
                                    "field": "name",
                                    "before": "insight name",
                                    "after": "insight new name",
                                },
                            ],
                            "trigger": None,
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

    @freeze_time("2012-01-14T03:21:34.000Z")
    def test_can_add_and_remove_tags(self) -> None:
        insight_id, response_data = self.dashboard_api.create_insight(
            {
                "name": "a created dashboard",
                "filters": {
                    "events": [{"id": "$pageview"}],
                    "properties": [{"key": "$browser", "value": "Mac OS X"}],
                    "date_from": "-90d",
                },
            }
        )
        insight_short_id = response_data["short_id"]
        self.assertEqual(response_data["tags"], [])

        add_tags_response = self.client.patch(
            # tags are displayed in order of insertion
            f"/api/projects/{self.team.id}/insights/{insight_id}",
            {"tags": ["2", "1", "3"]},
        )

        self.assertEqual(sorted(add_tags_response.json()["tags"]), ["1", "2", "3"])

        remove_tags_response = self.client.patch(f"/api/projects/{self.team.id}/insights/{insight_id}", {"tags": ["3"]})

        self.assertEqual(remove_tags_response.json()["tags"], ["3"])

        self.assert_insight_activity(
            insight_id=insight_id,
            expected=[
                {
                    "user": {"first_name": "", "email": "user1@posthog.com"},
                    "activity": "created",
                    "scope": "Insight",
                    "item_id": str(insight_id),
                    "detail": {
                        "changes": None,
                        "trigger": None,
                        "name": "a created dashboard",
                        "short_id": insight_short_id,
                    },
                    "created_at": "2012-01-14T03:21:34Z",
                },
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
                                "field": "tags",
                                "before": [],
                                "after": ["1", "2", "3"],
                            }
                        ],
                        "trigger": None,
                        "name": "a created dashboard",
                        "short_id": insight_short_id,
                    },
                    "created_at": "2012-01-14T03:21:34Z",
                },
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
                                "field": "tags",
                                "before": ["1", "2", "3"],
                                "after": ["3"],
                            }
                        ],
                        "trigger": None,
                        "name": "a created dashboard",
                        "short_id": insight_short_id,
                    },
                    "created_at": "2012-01-14T03:21:34Z",
                },
            ],
        )

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
                            "math_property": None,
                        },
                        {
                            "id": "$rageclick",
                            "math": None,
                            "name": "$rageclick",
                            "type": "events",
                            "order": 2,
                            "properties": [],
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

    @patch(
        "posthog.api.insight.synchronously_update_cache",
        wraps=synchronously_update_cache,
    )
    def test_insight_refreshing(self, spy_update_insight_cache) -> None:
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
            self.assertEqual(spy_update_insight_cache.call_count, 1)
            self.assertEqual(response["result"][0]["data"], [0, 0, 0, 0, 0, 0, 2, 0])
            self.assertEqual(response["last_refresh"], "2012-01-15T04:01:34Z")
            self.assertEqual(response["last_modified_at"], "2012-01-15T04:01:34Z")

        with freeze_time("2012-01-15T05:01:34.000Z"):
            _create_event(team=self.team, event="$pageview", distinct_id="1")
            response = self.client.get(f"/api/projects/{self.team.id}/insights/{response['id']}/?refresh=true").json()
            self.assertEqual(spy_update_insight_cache.call_count, 2)
            self.assertEqual(response["result"][0]["data"], [0, 0, 0, 0, 0, 0, 2, 1])
            self.assertEqual(response["last_refresh"], "2012-01-15T05:01:34Z")
            self.assertEqual(response["last_modified_at"], "2012-01-15T04:01:34Z")  # did not change

        with freeze_time("2012-01-16T05:01:34.000Z"):
            # load it in the context of the dashboard, so has last 14 days as filter
            response = self.client.get(
                f"/api/projects/{self.team.id}/insights/{response['id']}/?refresh=true&from_dashboard={dashboard_id}"
            ).json()
            self.assertEqual(spy_update_insight_cache.call_count, 3)
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
            self.assertEqual(spy_update_insight_cache.call_count, 3)
            self.assertEqual(response["last_refresh"], None)
            self.assertEqual(response["last_modified_at"], "2012-01-15T04:01:34Z")  # did not change

        #  Test property filter

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
            self.assertEqual(spy_update_insight_cache.call_count, 4)
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
        response_nonexistent_property = self.client.get(
            f"/api/projects/{self.team.id}/insights/trend/?events={json.dumps([{'id': '$pageview'}])}&properties={json.dumps([{'type': 'event', 'key': 'foo', 'value': 'barabarab'}])}"
        )
        response_nonexistent_cohort = self.client.get(
            f"/api/projects/{self.team.id}/insights/trend/?events={json.dumps([{'id': '$pageview'}])}&properties={json.dumps([{'type': 'cohort', 'key': 'id', 'value': 2137}])}"
        )  # This should not throw an error, just act like there's no event matches

        response_nonexistent_property_data = response_nonexistent_property.json()
        response_nonexistent_cohort_data = response_nonexistent_cohort.json()
        response_nonexistent_property_data.pop("last_refresh")
        response_nonexistent_cohort_data.pop("last_refresh")
        self.assertEntityResponseEqual(
            response_nonexistent_property_data["result"],
            response_nonexistent_cohort_data["result"],
        )  # Both cases just empty

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
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("offset=25", response.json()["next"])

    def test_insight_trends_breakdown_persons_with_histogram(self) -> None:
        people = journeys_for(
            {
                "1": [
                    {
                        "event": "$pageview",
                        "properties": {"$session_id": "one"},
                        "timestamp": "2012-01-14 00:16:00",
                    },
                    {
                        "event": "$pageview",
                        "properties": {"$session_id": "one"},
                        "timestamp": "2012-01-14 00:16:10",
                    },  # 10s session
                    {
                        "event": "$pageview",
                        "properties": {"$session_id": "two"},
                        "timestamp": "2012-01-15 00:16:00",
                    },
                    {
                        "event": "$pageview",
                        "properties": {"$session_id": "two"},
                        "timestamp": "2012-01-15 00:16:50",
                    },  # 50s session, day 2
                ],
                "2": [
                    {
                        "event": "$pageview",
                        "properties": {"$session_id": "three"},
                        "timestamp": "2012-01-14 00:16:00",
                    },
                    {
                        "event": "$pageview",
                        "properties": {"$session_id": "three"},
                        "timestamp": "2012-01-14 00:16:30",
                    },  # 30s session
                    {
                        "event": "$pageview",
                        "properties": {"$session_id": "four"},
                        "timestamp": "2012-01-15 00:16:00",
                    },
                    {
                        "event": "$pageview",
                        "properties": {"$session_id": "four"},
                        "timestamp": "2012-01-15 00:16:20",
                    },  # 20s session, day 2
                ],
                "3": [
                    {
                        "event": "$pageview",
                        "properties": {"$session_id": "five"},
                        "timestamp": "2012-01-15 00:16:00",
                    },
                    {
                        "event": "$pageview",
                        "properties": {"$session_id": "five"},
                        "timestamp": "2012-01-15 00:16:35",
                    },  # 35s session, day 2
                ],
            },
            self.team,
        )

        with freeze_time("2012-01-16T04:01:34.000Z"):
            response = self.client.post(
                f"/api/projects/{self.team.id}/insights/trend/",
                {
                    "events": json.dumps([{"id": "$pageview"}]),
                    "breakdown": "$session_duration",
                    "breakdown_type": "session",
                    "breakdown_histogram_bin_count": 2,
                    "date_from": "-3d",
                },
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            result = response.json()["result"]

            self.assertEqual(
                [resp["breakdown_value"] for resp in result],
                ["[10.0,30.0]", "[30.0,50.01]"],
            )
            self.assertEqual(
                result[0]["labels"],
                ["13-Jan-2012", "14-Jan-2012", "15-Jan-2012", "16-Jan-2012"],
            )
            self.assertEqual(result[0]["data"], [0, 2, 2, 0])
            self.assertEqual(result[1]["data"], [0, 2, 4, 0])

            first_breakdown_persons = self.client.get("/" + result[0]["persons_urls"][1]["url"])
            self.assertCountEqual(
                [person["id"] for person in first_breakdown_persons.json()["results"][0]["people"]],
                [str(people["1"].uuid)],
            )

            first_breakdown_persons_day_two = self.client.get("/" + result[0]["persons_urls"][2]["url"])
            self.assertCountEqual(
                [person["id"] for person in first_breakdown_persons_day_two.json()["results"][0]["people"]],
                [str(people["2"].uuid)],
            )

            second_breakdown_persons = self.client.get("/" + result[1]["persons_urls"][1]["url"])
            self.assertCountEqual(
                [person["id"] for person in second_breakdown_persons.json()["results"][0]["people"]],
                [str(people["2"].uuid)],
            )

            second_breakdown_persons_day_two = self.client.get("/" + result[1]["persons_urls"][2]["url"])
            self.assertCountEqual(
                [person["id"] for person in second_breakdown_persons_day_two.json()["results"][0]["people"]],
                [str(people["1"].uuid), str(people["3"].uuid)],
            )

    def test_insight_paths_basic(self) -> None:
        _create_person(team=self.team, distinct_ids=["person_1"], properties={"$os": "Mac"})
        _create_event(
            properties={"$current_url": "/", "test": "val"},
            distinct_id="person_1",
            event="$pageview",
            team=self.team,
        )
        _create_event(
            properties={"$current_url": "/about", "test": "val"},
            distinct_id="person_1",
            event="$pageview",
            team=self.team,
        )

        _create_person(team=self.team, distinct_ids=["dontcount"])
        _create_event(
            properties={"$current_url": "/", "test": "val"},
            distinct_id="dontcount",
            event="$pageview",
            team=self.team,
        )
        _create_event(
            properties={"$current_url": "/about", "test": "val"},
            distinct_id="dontcount",
            event="$pageview",
            team=self.team,
        )

        get_response = self.client.get(
            f"/api/projects/{self.team.id}/insights/path",
            data={"properties": json.dumps([{"key": "test", "value": "val"}])},
        ).json()
        self.assertEqual(len(get_response["result"]), 1)

        post_response = self.client.post(
            f"/api/projects/{self.team.id}/insights/path",
            {"properties": [{"key": "test", "value": "val"}]},
        ).json()
        self.assertEqual(len(post_response["result"]), 1)

        hogql_response = self.client.get(
            f"/api/projects/{self.team.id}/insights/path",
            data={
                "properties": json.dumps(
                    [{"key": "properties.test == 'val' and person.properties.$os == 'Mac'", "type": "hogql"}]
                )
            },
        ).json()
        self.assertEqual(len(hogql_response["result"]), 1)

        hogql_non_response = self.client.get(
            f"/api/projects/{self.team.id}/insights/path",
            data={
                "properties": json.dumps(
                    [{"key": "properties.test == 'val' and person.properties.$os == 'Windows'", "type": "hogql"}]
                )
            },
        ).json()
        self.assertEqual(len(hogql_non_response["result"]), 0)

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
            f"/api/projects/{self.team.id}/insights/funnel/?funnel_window_days=14&events={json.dumps([{'id': 'user signed up', 'type': 'events', 'order': 0}, {'id': 'user did things', 'type': 'events', 'order': 1}, ])}"
        ).json()

        # clickhouse funnels don't have a loading system
        self.assertEqual(len(response["result"]), 2)
        self.assertEqual(response["result"][0]["name"], "user signed up")
        self.assertEqual(response["result"][1]["name"], "user did things")
        self.assertEqual(response["timezone"], "UTC")

    def test_insight_retention_basic(self) -> None:
        _create_person(
            team=self.team,
            distinct_ids=["person1"],
            properties={"email": "person1@test.com"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="person1",
            timestamp=timezone.now() - timedelta(days=11),
        )

        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="person1",
            timestamp=timezone.now() - timedelta(days=10),
        )
        response = self.client.get(f"/api/projects/{self.team.id}/insights/retention/").json()

        self.assertEqual(len(response["result"]), 11)

    def test_insight_with_specified_token(self) -> None:
        _, _, user2 = User.objects.bootstrap("Test", "team2@posthog.com", None)
        assert user2.team is not None
        assert self.team is not None
        assert self.user.team is not None

        self.assertNotEqual(user2.team.id, self.team.id)
        self.client.force_login(self.user)

        _create_person(
            team=self.team,
            distinct_ids=["person1"],
            properties={"email": "person1@test.com"},
        )

        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="person1",
            timestamp=timezone.now() - timedelta(days=6),
        )

        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="person1",
            timestamp=timezone.now() - timedelta(days=5),
        )

        events_filter = json.dumps([{"id": "$pageview"}])

        response_team1 = self.client.get(f"/api/projects/{self.team.id}/insights/trend/?events={events_filter}")
        response_team1_token = self.client.get(
            f"/api/projects/{self.team.id}/insights/trend/?events={events_filter}&token={self.user.team.api_token}"
        )

        self.client.force_login(user2)
        response_team2 = self.client.get(
            f"/api/projects/{self.team.id}/insights/trend/?events={events_filter}",
            data={"token": user2.team.api_token},
        )

        self.assertEqual(response_team1.status_code, 200)
        self.assertEqual(response_team2.status_code, 200)
        self.assertEqual(response_team1.json()["result"], response_team1_token.json()["result"])
        self.assertNotEqual(len(response_team1.json()["result"]), len(response_team2.json()["result"]))

        response_invalid_token = self.client.get(f"/api/projects/{self.team.id}/insights/trend?token=invalid")
        self.assertEqual(response_invalid_token.status_code, 401)

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

        self.assertEqual(lines[0], b"http://localhost:8000/insights/test123/", lines[0])
        self.assertEqual(
            lines[1],
            b"series,8-Jan-2012,9-Jan-2012,10-Jan-2012,11-Jan-2012,12-Jan-2012,13-Jan-2012,14-Jan-2012,15-Jan-2012",
            lines[0],
        )
        self.assertEqual(lines[2], b"test custom,0.0,0.0,0.0,0.0,0.0,0.0,2.0,1.0")
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

    def test_insight_trends_forbidden_if_project_private_and_org_member(self) -> None:
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        self.team.access_control = True
        self.team.save()
        response = self.client.get(
            f"/api/projects/{self.team.id}/insights/trend/?events={json.dumps([{'id': '$pageview'}])}"
        )
        self.assertDictEqual(
            self.permission_denied_response("You don't have access to the project."),
            response.json(),
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_insight_trends_allowed_if_project_private_and_org_member_and_project_member(
        self,
    ) -> None:
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        self.team.access_control = True
        self.team.save()
        ExplicitTeamMembership.objects.create(
            team=self.team,
            parent_membership=self.organization_membership,
            level=ExplicitTeamMembership.Level.MEMBER,
        )
        response = self.client.get(
            f"/api/projects/{self.team.id}/insights/trend/?events={json.dumps([{'id': '$pageview'}])}"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    @patch("posthog.api.insight.capture_exception")
    def test_serializer(self, patch_capture_exception) -> None:
        """
        Various regression tests for the serializer
        """
        # Display
        self.client.get(
            f"/api/projects/{self.team.id}/insights/trend/?events={json.dumps([{'id': '$pageview'}])}&properties=%5B%5D&display=ActionsLineGraph"
        )

        self.assertEqual(
            patch_capture_exception.call_count,
            0,
            patch_capture_exception.call_args_list,
        )

        # Properties with an array
        events = [
            {
                "id": "$pageview",
                "properties": [{"key": "something", "value": ["something"]}],
            }
        ]
        self.client.get(
            f"/api/projects/{self.team.id}/insights/trend/?events={json.dumps(events)}&properties=%5B%5D&display=ActionsLineGraph"
        )
        self.assertEqual(
            patch_capture_exception.call_count,
            0,
            patch_capture_exception.call_args_list,
        )

        # Breakdown with ints in funnels
        cohort_one_id = self._create_one_person_cohort([{"key": "prop", "value": 5, "type": "person"}])
        cohort_two_id = self._create_one_person_cohort([{"key": "prop", "value": 6, "type": "person"}])

        events = [
            {
                "id": "$pageview",
                "properties": [{"key": "something", "value": ["something"]}],
            },
            {"id": "$pageview"},
        ]
        response = self.client.post(
            f"/api/projects/{self.team.id}/insights/funnel/",
            {
                "events": events,
                "breakdown": [cohort_one_id, cohort_two_id],
                "breakdown_type": "cohort",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            patch_capture_exception.call_count,
            0,
            patch_capture_exception.call_args_list,
        )

    def _create_one_person_cohort(self, properties: List[Dict[str, Any]]) -> int:
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
            datetime(2022, 3, 22, 0, 0, tzinfo=pytz.UTC),
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
                datetime(2022, 3, 23, 0, 0, tzinfo=pytz.UTC),
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

    def test_an_insight_on_no_dashboard_has_no_restrictions(self) -> None:
        _, response_data = self.dashboard_api.create_insight(data={"name": "not on a dashboard"})
        self.assertEqual(
            response_data["effective_restriction_level"],
            Dashboard.RestrictionLevel.EVERYONE_IN_PROJECT_CAN_EDIT,
        )
        self.assertEqual(
            response_data["effective_privilege_level"],
            Dashboard.PrivilegeLevel.CAN_EDIT,
        )

    def test_an_insight_on_unrestricted_dashboard_has_no_restrictions(self) -> None:
        dashboard: Dashboard = Dashboard.objects.create(team=self.team)
        _, response_data = self.dashboard_api.create_insight(
            data={"name": "on an unrestricted dashboard", "dashboards": [dashboard.pk]}
        )
        self.assertEqual(
            response_data["effective_restriction_level"],
            Dashboard.RestrictionLevel.EVERYONE_IN_PROJECT_CAN_EDIT,
        )
        self.assertEqual(
            response_data["effective_privilege_level"],
            Dashboard.PrivilegeLevel.CAN_EDIT,
        )

    def test_an_insight_on_restricted_dashboard_has_restrictions_cannot_edit_without_explicit_privilege(
        self,
    ) -> None:
        dashboard: Dashboard = Dashboard.objects.create(
            team=self.team,
            restriction_level=Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT,
        )
        _, response_data = self.dashboard_api.create_insight(
            data={"name": "on a restricted dashboard", "dashboards": [dashboard.pk]}
        )
        self.assertEqual(
            response_data["effective_restriction_level"],
            Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT,
        )
        self.assertEqual(
            response_data["effective_privilege_level"],
            Dashboard.PrivilegeLevel.CAN_VIEW,
        )

    def test_an_insight_on_both_restricted_and_unrestricted_dashboard_has_no_restrictions(
        self,
    ) -> None:
        dashboard_restricted: Dashboard = Dashboard.objects.create(
            team=self.team,
            restriction_level=Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT,
        )
        dashboard_unrestricted: Dashboard = Dashboard.objects.create(
            team=self.team,
            restriction_level=Dashboard.RestrictionLevel.EVERYONE_IN_PROJECT_CAN_EDIT,
        )
        _, response_data = self.dashboard_api.create_insight(
            data={
                "name": "on a restricted and unrestricted dashboard",
                "dashboards": [dashboard_restricted.pk, dashboard_unrestricted.pk],
            }
        )
        self.assertEqual(
            response_data["effective_restriction_level"],
            Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT,
        )
        self.assertEqual(
            response_data["effective_privilege_level"],
            Dashboard.PrivilegeLevel.CAN_EDIT,
        )

    def test_an_insight_on_restricted_dashboard_does_not_restrict_admin(self) -> None:
        dashboard_restricted: Dashboard = Dashboard.objects.create(
            team=self.team,
            restriction_level=Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT,
        )

        admin = User.objects.create_and_join(
            organization=self.organization,
            email="y@x.com",
            password=None,
            level=OrganizationMembership.Level.ADMIN,
        )
        self.client.force_login(admin)
        _, response_data = self.dashboard_api.create_insight(
            data={
                "name": "on a restricted and unrestricted dashboard",
                "dashboards": [dashboard_restricted.pk],
            }
        )
        self.assertEqual(
            response_data["effective_restriction_level"],
            Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT,
        )
        self.assertEqual(
            response_data["effective_privilege_level"],
            Dashboard.PrivilegeLevel.CAN_EDIT,
        )

    def test_an_insight_on_both_restricted_dashboard_does_not_restrict_with_explicit_privilege(
        self,
    ) -> None:
        dashboard_restricted: Dashboard = Dashboard.objects.create(
            team=self.team,
            restriction_level=Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT,
        )

        DashboardPrivilege.objects.create(
            dashboard=dashboard_restricted,
            user=self.user,
            level=Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT,
        )

        _, response_data = self.dashboard_api.create_insight(
            data={
                "name": "on a restricted and unrestricted dashboard",
                "dashboards": [dashboard_restricted.pk],
            }
        )
        self.assertEqual(
            response_data["effective_restriction_level"],
            Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT,
        )
        self.assertEqual(
            response_data["effective_privilege_level"],
            Dashboard.PrivilegeLevel.CAN_EDIT,
        )

    def test_cannot_update_an_insight_if_on_restricted_dashboard(self) -> None:
        dashboard_restricted: Dashboard = Dashboard.objects.create(
            team=self.team,
            restriction_level=Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT,
        )

        insight_id, response_data = self.dashboard_api.create_insight(
            data={
                "name": "on a restricted and unrestricted dashboard",
                "dashboards": [dashboard_restricted.pk],
            }
        )
        assert [t["dashboard_id"] for t in response_data["dashboard_tiles"]] == [dashboard_restricted.pk]

        response = self.client.patch(
            f"/api/projects/{self.team.id}/insights/{insight_id}",
            {"name": "changing when restricted"},
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_non_admin_user_cannot_add_an_insight_to_a_restricted_dashboard(
        self,
    ) -> None:
        # create insight and dashboard separately with default user
        dashboard_restricted_id, _ = self.dashboard_api.create_dashboard(
            {"restriction_level": Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT}
        )

        insight_id, response_data = self.dashboard_api.create_insight(data={"name": "starts un-restricted dashboard"})

        # user with no permissions on the dashboard cannot add insight to it
        user_without_permissions = User.objects.create_and_join(
            organization=self.organization,
            email="no_access_user@posthog.com",
            password=None,
        )
        self.client.force_login(user_without_permissions)

        response = self.client.patch(
            f"/api/projects/{self.team.id}/insights/{insight_id}",
            {"dashboards": [dashboard_restricted_id]},
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

        self.client.force_login(self.user)

        response = self.client.patch(
            f"/api/projects/{self.team.id}/insights/{insight_id}",
            {"dashboards": [dashboard_restricted_id]},
        )
        assert response.status_code == status.HTTP_200_OK

    def test_non_admin_user_with_privilege_can_add_an_insight_to_a_restricted_dashboard(
        self,
    ) -> None:
        # create insight and dashboard separately with default user
        dashboard_restricted: Dashboard = Dashboard.objects.create(
            team=self.team,
            restriction_level=Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT,
        )

        insight_id, response_data = self.dashboard_api.create_insight(data={"name": "starts un-restricted dashboard"})

        user_with_permissions = User.objects.create_and_join(
            organization=self.organization,
            email="with_access_user@posthog.com",
            password=None,
        )

        DashboardPrivilege.objects.create(
            dashboard=dashboard_restricted,
            user=user_with_permissions,
            level=Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT,
        )

        self.client.force_login(user_with_permissions)

        response = self.client.patch(
            f"/api/projects/{self.team.id}/insights/{insight_id}",
            {"dashboards": [dashboard_restricted.id]},
        )
        assert response.status_code == status.HTTP_200_OK

    def test_admin_user_can_add_an_insight_to_a_restricted_dashboard(self) -> None:
        # create insight and dashboard separately with default user
        dashboard_restricted: Dashboard = Dashboard.objects.create(
            team=self.team,
            restriction_level=Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT,
        )

        insight_id, response_data = self.dashboard_api.create_insight(data={"name": "starts un-restricted dashboard"})

        # an admin user has implicit permissions on the dashboard and can add the insight to it
        admin = User.objects.create_and_join(
            organization=self.organization,
            email="team2@posthog.com",
            password=None,
            level=OrganizationMembership.Level.ADMIN,
        )
        self.client.force_login(admin)

        response = self.client.patch(
            f"/api/projects/{self.team.id}/insights/{insight_id}",
            {"dashboards": [dashboard_restricted.id]},
        )
        assert response.status_code == status.HTTP_200_OK

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

        self.client.patch(f"/api/projects/{self.team.id}/insights/{insight_id}", {"deleted": True})

        self.assertEqual(
            self.client.get(f"/api/projects/{self.team.id}/insights/{insight_id}").status_code,
            status.HTTP_404_NOT_FOUND,
        )

        update_response = self.client.patch(f"/api/projects/{self.team.id}/insights/{insight_id}", {"deleted": False})
        self.assertEqual(update_response.status_code, status.HTTP_200_OK)

        self.assertEqual(
            self.client.get(f"/api/projects/{self.team.id}/insights/{insight_id}").status_code,
            status.HTTP_200_OK,
        )

    def test_cancel_running_query(self) -> None:
        # There is no good way of writing a test that tests this without it being very slow
        #  Just verify it doesn't throw an error
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
        query_params = f"?events={json.dumps([{'id': '$pageview', }])}&client_query_id={client_query_id}"
        self.client.get(f"/api/projects/{self.team.id}/insights/trend/{query_params}").json()

    def assert_insight_activity(self, insight_id: Optional[int], expected: List[Dict]):
        activity_response = self.dashboard_api.get_insight_activity(insight_id)

        activity: List[Dict] = activity_response["results"]

        self.maxDiff = None
        assert activity == expected

    @also_test_with_materialized_columns(event_properties=["int_value"], person_properties=["fish"])
    @snapshot_clickhouse_queries
    def test_insight_trend_hogql_global_filters(self) -> None:
        _create_person(team=self.team, distinct_ids=["1"], properties={"fish": "there is no fish"})
        with freeze_time("2012-01-14T03:21:34.000Z"):
            for i in range(25):
                _create_event(team=self.team, event="$pageview", distinct_id="1", properties={"int_value": i})
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
                            {"key": "toInt(properties.int_value) > 10 and 'bla' != 'a%sd'", "type": "hogql"},
                            {"key": "like(person.properties.fish, '%fish%')", "type": "hogql"},
                        ]
                    ),
                },
            )
            found_data_points = response.json()["result"][0]["count"]
            self.assertEqual(found_data_points, 14)

    @also_test_with_materialized_columns(event_properties=["int_value"], person_properties=["fish"])
    @snapshot_clickhouse_queries
    def test_insight_trend_hogql_local_filters(self) -> None:
        _create_person(team=self.team, distinct_ids=["1"], properties={"fish": "there is no fish"})
        with freeze_time("2012-01-14T03:21:34.000Z"):
            for i in range(25):
                _create_event(team=self.team, event="$pageview", distinct_id="1", properties={"int_value": i})
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
                                        {"key": "like(person.properties.fish, '%fish%')", "type": "hogql"},
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
                _create_event(team=self.team, event="$pageview", distinct_id="1", properties={"int_value": i})
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
            _create_person(team=self.team, distinct_ids=["1"], properties={"fish": "there is no fish"})
            _create_event(team=self.team, event="user signed up", distinct_id="1", properties={"int_value": 1})
            _create_event(team=self.team, event="user did things", distinct_id="1", properties={"int_value": 20})
            response = self.client.post(
                f"/api/projects/{self.team.id}/insights/funnel/",
                {
                    "events": [
                        {"id": "user signed up", "type": "events", "order": 0},
                        {"id": "user did things", "type": "events", "order": 1},
                    ],
                    "properties": json.dumps(
                        [
                            {"key": "toInt(properties.int_value) < 10 and 'bla' != 'a%sd'", "type": "hogql"},
                            {"key": "like(person.properties.fish, '%fish%')", "type": "hogql"},
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
            _create_person(team=self.team, distinct_ids=["1"], properties={"fish": "there is no fish"})
            _create_event(team=self.team, event="user signed up", distinct_id="1", properties={"int_value": 1})
            _create_event(team=self.team, event="user did things", distinct_id="1", properties={"int_value": 20})
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
                                    {"key": "toInt(properties.int_value) < 10 and 'bla' != 'a%sd'", "type": "hogql"},
                                    {"key": "like(person.properties.fish, '%fish%')", "type": "hogql"},
                                ]
                            ),
                        },
                        {
                            "id": "user did things",
                            "type": "events",
                            "order": 1,
                            "properties": json.dumps(
                                [
                                    {"key": "toInt(properties.int_value) < 10 and 'bla' != 'a%sd'", "type": "hogql"},
                                    {"key": "like(person.properties.fish, '%fish%')", "type": "hogql"},
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

    def test_insight_retention_hogql(self) -> None:
        with freeze_time("2012-01-15T04:01:34.000Z"):
            _create_person(
                team=self.team,
                distinct_ids=["person1"],
                properties={"email": "person1@test.com"},
            )
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="person1",
                timestamp=timezone.now() - timedelta(days=11),
                properties={"int_value": 1},
            )

            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="person1",
                timestamp=timezone.now() - timedelta(days=10),
                properties={"int_value": 20},
            )
            response = self.client.get(f"/api/projects/{self.team.id}/insights/retention/").json()

            self.assertEqual(len(response["result"]), 11)
            self.assertEqual(response["result"][0]["values"][0]["count"], 1)

            response = self.client.get(
                f"/api/projects/{self.team.id}/insights/retention/",
                data={
                    "properties": json.dumps(
                        [
                            {"key": "toInt(properties.int_value) > 100 and 'bla' != 'a%sd'", "type": "hogql"},
                            {"key": "like(person.properties.email, '%test.com%')", "type": "hogql"},
                        ]
                    ),
                },
            ).json()
            self.assertEqual(len(response["result"]), 11)
            self.assertEqual(response["result"][0]["values"][0]["count"], 0)

            response = self.client.get(
                f"/api/projects/{self.team.id}/insights/retention/",
                data={
                    "properties": json.dumps(
                        [
                            {"key": "toInt(properties.int_value) > 0 and 'bla' != 'a%sd'", "type": "hogql"},
                            {"key": "like(person.properties.email, '%test.com%')", "type": "hogql"},
                        ]
                    ),
                },
            ).json()
            self.assertEqual(len(response["result"]), 11)
            self.assertEqual(response["result"][0]["values"][0]["count"], 1)
