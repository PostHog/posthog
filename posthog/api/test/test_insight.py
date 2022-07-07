import json
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from unittest.case import skip
from unittest.mock import patch

import pytz
from django.utils import timezone
from freezegun import freeze_time
from rest_framework import status

from ee.api.test.base import LicensedTestMixin
from ee.models import DashboardPrivilege
from ee.models.explicit_team_membership import ExplicitTeamMembership
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
from posthog.tasks.update_cache import update_insight_cache
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, QueryMatchingTest, _create_event, _create_person
from posthog.test.db_context_capturing import capture_db_queries
from posthog.test.test_journeys import journeys_for


class TestInsight(ClickhouseTestMixin, LicensedTestMixin, APIBaseTest, QueryMatchingTest):
    maxDiff = None

    CLASS_DATA_LEVEL_SETUP = False

    def test_get_insight_items(self):
        filter_dict = {
            "events": [{"id": "$pageview"}],
            "properties": [{"key": "$browser", "value": "Mac OS X"}],
        }

        Insight.objects.create(filters=Filter(data=filter_dict).to_dict(), team=self.team, created_by=self.user)

        # create without user
        Insight.objects.create(filters=Filter(data=filter_dict).to_dict(), team=self.team)

        response = self.client.get(f"/api/projects/{self.team.id}/insights/", data={"user": "true"}).json()

        self.assertEqual(len(response["results"]), 1)

    def test_created_updated_and_last_modified(self):
        alt_user = User.objects.create_and_join(self.organization, "team2@posthog.com", None)
        self_user_basic_serialized = {
            "id": self.user.id,
            "uuid": str(self.user.uuid),
            "distinct_id": self.user.distinct_id,
            "first_name": self.user.first_name,
            "email": self.user.email,
        }
        alt_user_basic_serialized = {
            "id": alt_user.id,
            "uuid": str(alt_user.uuid),
            "distinct_id": alt_user.distinct_id,
            "first_name": alt_user.first_name,
            "email": alt_user.email,
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
            response_2 = self.client.patch(f"/api/projects/{self.team.id}/insights/{insight_id}", {"favorited": True})
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
                f"/api/projects/{self.team.id}/insights/{insight_id}", {"filters": {"events": []}}
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
                f"/api/projects/{self.team.id}/insights/{insight_id}", {"description": "Lorem ipsum."}
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

    def test_get_saved_insight_items(self):
        filter_dict = {
            "events": [{"id": "$pageview"}],
            "properties": [{"key": "$browser", "value": "Mac OS X"}],
        }

        Insight.objects.create(
            filters=Filter(data=filter_dict).to_dict(), saved=True, team=self.team, created_by=self.user,
        )

        # create without saved
        Insight.objects.create(
            filters=Filter(data=filter_dict).to_dict(), team=self.team, created_by=self.user,
        )

        # create without user
        Insight.objects.create(filters=Filter(data=filter_dict).to_dict(), team=self.team)

        response = self.client.get(f"/api/projects/{self.team.id}/insights/", data={"saved": "true", "user": "true"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assertEqual(len(response.json()["results"]), 1)
        self.assertEqual(len(response.json()["results"][0]["short_id"]), 8)

    def test_get_favorited_insight_items(self):
        filter_dict = {
            "events": [{"id": "$pageview"}],
            "properties": [{"key": "$browser", "value": "Mac OS X"}],
        }

        Insight.objects.create(
            filters=Filter(data=filter_dict).to_dict(), favorited=True, team=self.team, created_by=self.user,
        )

        # create without favorited
        Insight.objects.create(
            filters=Filter(data=filter_dict).to_dict(), team=self.team, created_by=self.user,
        )

        # create without user
        Insight.objects.create(filters=Filter(data=filter_dict).to_dict(), team=self.team)

        response = self.client.get(f"/api/projects/{self.team.id}/insights/?favorited=true&user=true")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assertEqual(len(response.json()["results"]), 1)
        self.assertEqual((response.json()["results"][0]["favorited"]), True)

    def test_get_insight_in_dashboard_context(self):
        filter_dict = {
            "events": [{"id": "$pageview"}],
            "properties": [{"key": "$browser", "value": "Mac OS X"}],
        }

        dashboard_id, _ = self._create_dashboard({"name": "the dashboard"})

        blue_insight_id, _ = self._create_insight(
            {"filters": filter_dict, "name": "blue insight", "dashboards": [dashboard_id]}
        )

        response = self.client.patch(
            f"/api/projects/{self.team.id}/dashboards/{dashboard_id}",
            {"colors": [{"id": blue_insight_id, "color": "blue"}]},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        blue_insight_in_isolation = self._get_insight(blue_insight_id)
        self.assertEqual(blue_insight_in_isolation["name"], "blue insight")
        self.assertEqual(blue_insight_in_isolation.get("color", None), None)

        blue_insight_on_dashboard = self._get_insight(blue_insight_id, query_params={"from_dashboard": dashboard_id})
        self.assertEqual(blue_insight_on_dashboard["name"], "blue insight")
        self.assertEqual(blue_insight_on_dashboard.get("color", None), "blue")

    def test_get_insight_by_short_id(self):
        filter_dict = {
            "events": [{"id": "$pageview"}],
        }

        Insight.objects.create(
            filters=Filter(data=filter_dict).to_dict(), team=self.team, short_id="12345678",
        )

        # Red herring: Should be ignored because it's not on the current team (even though the user has access)
        new_team = Team.objects.create(organization=self.organization)
        Insight.objects.create(
            filters=Filter(data=filter_dict).to_dict(), team=new_team, short_id="12345678",
        )

        response = self.client.get(f"/api/projects/{self.team.id}/insights/?short_id=12345678")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assertEqual(len(response.json()["results"]), 1)
        self.assertEqual(response.json()["results"][0]["short_id"], "12345678")
        self.assertEqual(response.json()["results"][0]["filters"]["events"][0]["id"], "$pageview")

    def test_basic_results(self):
        """
        The `skip_results` query parameter can be passed so that only a list of objects is returned, without
        the actual query data. This can speed things up if it's not needed.
        """
        filter_dict = {
            "events": [{"id": "$pageview"}],
        }

        Insight.objects.create(
            filters=Filter(data=filter_dict).to_dict(), team=self.team, short_id="12345678",
        )
        Insight.objects.create(
            filters=Filter(data=filter_dict).to_dict(), team=self.team, saved=True,
        )

        response = self.client.get(f"/api/projects/{self.team.id}/insights/?basic=true")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assertEqual(len(response.json()["results"]), 2)
        self.assertEqual(
            set(response.json()["results"][0].keys()),
            {
                "id",
                "short_id",
                "name",
                "filters",
                "dashboards",
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

    def test_listing_insights_does_not_nplus1(self):
        query_counts: List[int] = []
        queries = []

        for i in range(20):
            user = User.objects.create(email=f"testuser{i}@posthog.com")
            OrganizationMembership.objects.create(user=user, organization=self.organization)
            dashboard = Dashboard.objects.create(name=f"Dashboard {i}", team=self.team)

            self._create_insight(
                data={
                    "short_id": f"insight{i}",
                    "dashboards": [dashboard.pk],
                    "filters": {"events": [{"id": "$pageview"}]},
                }
            )

            self.assertEqual(Insight.objects.count(), i + 1)

            with capture_db_queries() as capture_query_context:
                response = self.client.get(f"/api/projects/{self.team.id}/insights")
                self.assertEqual(response.status_code, status.HTTP_200_OK)
                self.assertEqual(len(response.json()["results"]), i + 1)

            query_count_for_create_and_read = len(capture_query_context.captured_queries)
            queries.append(capture_query_context.captured_queries)
            query_counts.append(query_count_for_create_and_read)

        # adding more insights doesn't change the query count
        self.assertTrue(
            all(x == query_counts[0] for x in query_counts),
            f"received query counts\n\n{query_counts}\n\nwith queries:\n\n{queries}",
        )

    @freeze_time("2012-01-14T03:21:34.000Z")
    def test_create_insight_items(self):
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
                    "user": {"first_name": "", "email": "user1@posthog.com",},
                    "activity": "created",
                    "created_at": "2012-01-14T03:21:34Z",
                    "scope": "Insight",
                    "item_id": str(response_data["id"]),
                    "detail": {
                        "changes": None,
                        "merge": None,
                        "name": "a created dashboard",
                        "short_id": response_data["short_id"],
                    },
                }
            ],
        )

    @freeze_time("2012-01-14T03:21:34.000Z")
    def test_create_insight_with_no_names_logs_no_activity(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/insights",
            data={
                "filters": {
                    "events": [{"id": "$pageview"}],
                    "properties": [{"key": "$browser", "value": "Mac OS X"}],
                    "date_from": "-90d",
                },
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        response_data = response.json()
        self.assertEqual(response_data["name"], None)
        self.assertEqual(response_data["derived_name"], None)

        self.assert_insight_activity(
            response_data["id"], [],
        )

    def test_create_insight_items_on_a_dashboard(self):
        dashboard_id, _ = self._create_dashboard({})

        insight_id, _ = self._create_insight(
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
        self.assertIsNotNone(tile.filters_hash)

    @freeze_time("2012-01-14T03:21:34.000Z")
    def test_create_insight_logs_derived_name_if_there_is_no_name(self):
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
                    "user": {"first_name": "", "email": "user1@posthog.com",},
                    "activity": "created",
                    "created_at": "2012-01-14T03:21:34Z",
                    "scope": "Insight",
                    "item_id": str(response_data["id"]),
                    "detail": {
                        "changes": None,
                        "merge": None,
                        "name": "pageview unique users",
                        "short_id": response_data["short_id"],
                    },
                }
            ],
        )

    def test_update_insight(self):
        with freeze_time("2012-01-14T03:21:34.000Z") as frozen_time:
            insight_id, insight = self._create_insight({"name": "insight name"})
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
                response_data["effective_restriction_level"], Dashboard.RestrictionLevel.EVERYONE_IN_PROJECT_CAN_EDIT
            )
            self.assertEqual(response_data["effective_privilege_level"], Dashboard.PrivilegeLevel.CAN_EDIT)

            response = self.client.get(f"/api/projects/{self.team.id}/insights/{insight_id}",)

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
                            "merge": None,
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
                        "detail": {"changes": None, "merge": None, "name": "insight name", "short_id": short_id},
                        "created_at": "2012-01-14T03:21:34Z",
                    },
                ],
            )

    def test_cannot_set_filters_hash_via_api(self):
        insight_id, insight = self._create_insight({"name": "should not update the filters_hash"})
        original_filters_hash = insight["filters_hash"]
        self.assertIsNotNone(original_filters_hash)

        response = self.client.patch(
            f"/api/projects/{self.team.id}/insights/{insight_id}", {"filters_hash": "should not update the value"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["filters_hash"], original_filters_hash)

    @freeze_time("2012-01-14T03:21:34.000Z")
    def test_can_add_and_remove_tags(self):
        insight_id, response_data = self._create_insight(
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

        remove_tags_response = self.client.patch(
            f"/api/projects/{self.team.id}/insights/{insight_id}", {"tags": ["3"]},
        )

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
                        "merge": None,
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
                        "merge": None,
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
                        "merge": None,
                        "name": "a created dashboard",
                        "short_id": insight_short_id,
                    },
                    "created_at": "2012-01-14T03:21:34Z",
                },
            ],
        )

    @skip("Compatibility issue caused by test account filters")
    def test_update_insight_filters(self):
        insight = Insight.objects.create(
            team=self.team,
            name="insight with custom filters",
            created_by=self.user,
            filters={"events": [{"id": "$pageview"}]},
        )

        for custom_name, expected_name in zip(
            ["Custom filter", 100, "", "  ", None], ["Custom filter", "100", None, None, None]
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

    def test_save_new_funnel(self):
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

    @patch("posthog.api.insight.update_insight_cache", wraps=update_insight_cache)
    def test_insight_refreshing(self, spy_update_insight_cache):
        dashboard_id, _ = self._create_dashboard({"filters": {"date_from": "-14d",}})

        with freeze_time("2012-01-14T03:21:34.000Z"):
            _create_event(team=self.team, event="$pageview", distinct_id="1", properties={"prop": "val"})
            _create_event(team=self.team, event="$pageview", distinct_id="2", properties={"prop": "another_val"})
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
                        "properties": [{"key": "another", "value": "never_return_this", "operator": "is_not"}],
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
                [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 2.0, 1.0, 0.0],
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
        dashboard.filters = {"properties": [{"key": "prop", "value": "val"}], "date_from": "-14d"}
        dashboard.save()
        with freeze_time("2012-01-16T05:01:34.000Z"):
            response = self.client.get(
                f"/api/projects/{self.team.id}/insights/{response['id']}/?refresh=true&from_dashboard={dashboard_id}"
            ).json()
            self.assertEqual(spy_update_insight_cache.call_count, 4)
            self.assertEqual(
                response["result"][0]["data"],
                [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0],
            )

    # BASIC TESTING OF ENDPOINTS. /queries as in depth testing for each insight

    def test_insight_trends_basic(self):
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

    def test_nonexistent_cohort_is_handled(self):
        response_nonexistent_property = self.client.get(
            f"/api/projects/{self.team.id}/insights/trend/?events={json.dumps([{'id': '$pageview'}])}&properties={json.dumps([{'type':'event','key':'foo','value':'barabarab'}])}"
        )
        response_nonexistent_cohort = self.client.get(
            f"/api/projects/{self.team.id}/insights/trend/?events={json.dumps([{'id': '$pageview'}])}&properties={json.dumps([{'type':'cohort','key':'id','value':2137}])}"
        )  # This should not throw an error, just act like there's no event matches

        response_nonexistent_property_data = response_nonexistent_property.json()
        response_nonexistent_cohort_data = response_nonexistent_cohort.json()
        response_nonexistent_property_data.pop("last_refresh")
        response_nonexistent_cohort_data.pop("last_refresh")
        self.assertEntityResponseEqual(
            response_nonexistent_property_data["result"], response_nonexistent_cohort_data["result"]
        )  # Both cases just empty

    def test_cohort_without_match_group_works(self):
        whatever_cohort_without_match_groups = Cohort.objects.create(team=self.team)

        response_nonexistent_property = self.client.get(
            f"/api/projects/{self.team.id}/insights/trend/?events={json.dumps([{'id': '$pageview'}])}&properties={json.dumps([{'type':'event','key':'foo','value':'barabarab'}])}"
        )
        response_cohort_without_match_groups = self.client.get(
            f"/api/projects/{self.team.id}/insights/trend/?events={json.dumps([{'id':'$pageview'}])}&properties={json.dumps([{'type':'cohort','key':'id','value':whatever_cohort_without_match_groups.pk}])}"
        )  # This should not throw an error, just act like there's no event matches

        self.assertEqual(response_nonexistent_property.status_code, 200)
        response_nonexistent_property_data = response_nonexistent_property.json()
        response_cohort_without_match_groups_data = response_cohort_without_match_groups.json()
        response_nonexistent_property_data.pop("last_refresh")
        response_cohort_without_match_groups_data.pop("last_refresh")
        self.assertEntityResponseEqual(
            response_nonexistent_property_data["result"], response_cohort_without_match_groups_data["result"]
        )  # Both cases just empty

    def test_precalculated_cohort_works(self):
        _create_person(team=self.team, distinct_ids=["person_1"], properties={"foo": "bar"})

        whatever_cohort: Cohort = Cohort.objects.create(
            id=113,
            team=self.team,
            groups=[{"properties": [{"type": "person", "key": "foo", "value": "bar", "operator": "exact"}]}],
            last_calculation=timezone.now(),
        )

        whatever_cohort.calculate_people_ch(pending_version=0)

        with self.settings(USE_PRECALCULATED_CH_COHORT_PEOPLE=True):  # Normally this is False in tests
            response_user_property = self.client.get(
                f"/api/projects/{self.team.id}/insights/trend/?events={json.dumps([{'id': '$pageview'}])}&properties={json.dumps([{'type':'person','key':'foo','value':'bar'}])}"
            )
            response_precalculated_cohort = self.client.get(
                f"/api/projects/{self.team.id}/insights/trend/?events={json.dumps([{'id':'$pageview'}])}&properties={json.dumps([{'type':'cohort','key':'id','value':113}])}"
            )

        self.assertEqual(response_precalculated_cohort.status_code, 200)
        response_user_property_data = response_user_property.json()
        response_precalculated_cohort_data = response_precalculated_cohort.json()
        response_user_property_data.pop("last_refresh")
        response_precalculated_cohort_data.pop("last_refresh")

        self.assertEntityResponseEqual(
            response_user_property_data["result"], response_precalculated_cohort_data["result"]
        )

    def test_insight_trends_compare(self):
        with freeze_time("2012-01-14T03:21:34.000Z"):
            for i in range(25):
                _create_event(
                    team=self.team, event="$pageview", distinct_id="1", properties={"$some_property": f"value{i}"},
                )

        with freeze_time("2012-01-15T04:01:34.000Z"):
            response = self.client.get(
                f"/api/projects/{self.team.id}/insights/trend/",
                data={"events": json.dumps([{"id": "$pageview"}]), "compare": "true",},
            )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        result = response.json()
        self.assertEqual(len(result["result"]), 2)
        self.assertEqual(result["result"][0]["compare_label"], "current")
        self.assertEqual(result["result"][1]["compare_label"], "previous")

    def test_insight_trends_breakdown_pagination(self):
        with freeze_time("2012-01-14T03:21:34.000Z"):
            for i in range(25):

                _create_event(
                    team=self.team, event="$pageview", distinct_id="1", properties={"$some_property": f"value{i}"},
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

    def test_insight_trends_breakdown_persons_with_histogram(self):
        people = journeys_for(
            {
                "1": [
                    {"event": "$pageview", "properties": {"$session_id": "one"}, "timestamp": "2012-01-14 00:16:00"},
                    {
                        "event": "$pageview",
                        "properties": {"$session_id": "one"},
                        "timestamp": "2012-01-14 00:16:10",
                    },  # 10s session
                    {"event": "$pageview", "properties": {"$session_id": "two"}, "timestamp": "2012-01-15 00:16:00"},
                    {
                        "event": "$pageview",
                        "properties": {"$session_id": "two"},
                        "timestamp": "2012-01-15 00:16:50",
                    },  # 50s session, day 2
                ],
                "2": [
                    {"event": "$pageview", "properties": {"$session_id": "three"}, "timestamp": "2012-01-14 00:16:00"},
                    {
                        "event": "$pageview",
                        "properties": {"$session_id": "three"},
                        "timestamp": "2012-01-14 00:16:30",
                    },  # 30s session
                    {"event": "$pageview", "properties": {"$session_id": "four"}, "timestamp": "2012-01-15 00:16:00"},
                    {
                        "event": "$pageview",
                        "properties": {"$session_id": "four"},
                        "timestamp": "2012-01-15 00:16:20",
                    },  # 20s session, day 2
                ],
                "3": [
                    {"event": "$pageview", "properties": {"$session_id": "five"}, "timestamp": "2012-01-15 00:16:00"},
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

            self.assertEqual([resp["breakdown_value"] for resp in result], ["[10.0,30.0]", "[30.0,50.01]"])
            self.assertEqual(result[0]["labels"], ["13-Jan-2012", "14-Jan-2012", "15-Jan-2012", "16-Jan-2012"])
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

    def test_insight_paths_basic(self):
        _create_person(team=self.team, distinct_ids=["person_1"])
        _create_event(
            properties={"$current_url": "/", "test": "val"}, distinct_id="person_1", event="$pageview", team=self.team,
        )
        _create_event(
            properties={"$current_url": "/about", "test": "val"},
            distinct_id="person_1",
            event="$pageview",
            team=self.team,
        )

        _create_person(team=self.team, distinct_ids=["dontcount"])
        _create_event(
            properties={"$current_url": "/", "test": "val"}, distinct_id="dontcount", event="$pageview", team=self.team,
        )
        _create_event(
            properties={"$current_url": "/about", "test": "val"},
            distinct_id="dontcount",
            event="$pageview",
            team=self.team,
        )

        get_response = self.client.get(
            f"/api/projects/{self.team.id}/insights/path",
            data={"properties": json.dumps([{"key": "test", "value": "val"}]),},
        ).json()
        post_response = self.client.post(
            f"/api/projects/{self.team.id}/insights/path", {"properties": [{"key": "test", "value": "val"}],}
        ).json()
        self.assertEqual(len(get_response["result"]), 1)
        self.assertEqual(len(post_response["result"]), 1)

    def test_insight_funnels_basic_post(self):
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
    def test_insight_funnels_basic_get(self):
        _create_event(team=self.team, event="user signed up", distinct_id="1")
        _create_event(team=self.team, event="user did things", distinct_id="1")
        response = self.client.get(
            f"/api/projects/{self.team.id}/insights/funnel/?funnel_window_days=14&events={json.dumps([{'id': 'user signed up', 'type': 'events', 'order': 0},{'id': 'user did things', 'type': 'events', 'order': 1},])}"
        ).json()

        # clickhouse funnels don't have a loading system
        self.assertEqual(len(response["result"]), 2)
        self.assertEqual(response["result"][0]["name"], "user signed up")
        self.assertEqual(response["result"][1]["name"], "user did things")
        self.assertEqual(response["timezone"], "UTC")

    def test_insight_retention_basic(self):
        _create_person(team=self.team, distinct_ids=["person1"], properties={"email": "person1@test.com"})
        _create_event(
            team=self.team, event="$pageview", distinct_id="person1", timestamp=timezone.now() - timedelta(days=11),
        )

        _create_event(
            team=self.team, event="$pageview", distinct_id="person1", timestamp=timezone.now() - timedelta(days=10),
        )
        response = self.client.get(f"/api/projects/{self.team.id}/insights/retention/",).json()

        self.assertEqual(len(response["result"]), 11)

    def test_insight_with_specified_token(self):
        _, _, user2 = User.objects.bootstrap("Test", "team2@posthog.com", None)
        assert user2.team is not None
        assert self.team is not None
        assert self.user.team is not None

        self.assertNotEqual(user2.team.id, self.team.id)
        self.client.force_login(self.user)

        _create_person(team=self.team, distinct_ids=["person1"], properties={"email": "person1@test.com"})

        _create_event(
            team=self.team, event="$pageview", distinct_id="person1", timestamp=timezone.now() - timedelta(days=6),
        )

        _create_event(
            team=self.team, event="$pageview", distinct_id="person1", timestamp=timezone.now() - timedelta(days=5),
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

    def test_insight_trends_csv(self):
        with freeze_time("2012-01-14T03:21:34.000Z"):
            _create_event(team=self.team, event="$pageview", distinct_id="1")
            _create_event(team=self.team, event="$pageview", distinct_id="2")

        with freeze_time("2012-01-15T04:01:34.000Z"):
            _create_event(team=self.team, event="$pageview", distinct_id="2")
            response = self.client.get(
                f"/api/projects/{self.team.id}/insights/trend.csv/?events={json.dumps([{'id': '$pageview', 'custom_name': 'test custom'}])}&export_name=Pageview count&export_insight_id=test123",
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
    def test_insight_trends_allowed_if_project_open_and_org_member(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        self.team.access_control = False
        self.team.save()
        response = self.client.get(
            f"/api/projects/{self.team.id}/insights/trend/?events={json.dumps([{'id': '$pageview'}])}"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_insight_trends_forbidden_if_project_private_and_org_member(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        self.team.access_control = True
        self.team.save()
        response = self.client.get(
            f"/api/projects/{self.team.id}/insights/trend/?events={json.dumps([{'id': '$pageview'}])}"
        )
        self.assertDictEqual(self.permission_denied_response("You don't have access to the project."), response.json())
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_insight_trends_allowed_if_project_private_and_org_member_and_project_member(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        self.team.access_control = True
        self.team.save()
        ExplicitTeamMembership.objects.create(
            team=self.team, parent_membership=self.organization_membership, level=ExplicitTeamMembership.Level.MEMBER
        )
        response = self.client.get(
            f"/api/projects/{self.team.id}/insights/trend/?events={json.dumps([{'id': '$pageview'}])}"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    @patch("posthog.api.insight.capture_exception")
    def test_serializer(self, patch_capture_exception):
        """
        Various regression tests for the serializer
        """
        # Display
        response = self.client.get(
            f"/api/projects/{self.team.id}/insights/trend/?events={json.dumps([{'id': '$pageview'}])}&properties=%5B%5D&display=ActionsLineGraph"
        )

        self.assertEqual(patch_capture_exception.call_count, 0, patch_capture_exception.call_args_list)

        # Properties with an array
        events = [{"id": "$pageview", "properties": [{"key": "something", "value": ["something"]}]}]
        response = self.client.get(
            f"/api/projects/{self.team.id}/insights/trend/?events={json.dumps(events)}&properties=%5B%5D&display=ActionsLineGraph"
        )
        self.assertEqual(patch_capture_exception.call_count, 0, patch_capture_exception.call_args_list)

        # Breakdown with ints in funnels
        cohort_one_id = self._create_one_person_cohort([{"key": "prop", "value": 5, "type": "person"}])
        cohort_two_id = self._create_one_person_cohort([{"key": "prop", "value": 6, "type": "person"}])

        events = [
            {"id": "$pageview", "properties": [{"key": "something", "value": ["something"]}]},
            {"id": "$pageview"},
        ]
        response = self.client.post(
            f"/api/projects/{self.team.id}/insights/funnel/",
            {"events": events, "breakdown": [cohort_one_id, cohort_two_id], "breakdown_type": "cohort"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(patch_capture_exception.call_count, 0, patch_capture_exception.call_args_list)

    def _create_one_person_cohort(self, properties: List[Dict[str, Any]]) -> int:
        Person.objects.create(team=self.team, properties=properties)
        cohort_one_id = self.client.post(
            f"/api/projects/{self.team.id}/cohorts", data={"name": "whatever", "groups": [{"properties": properties}]},
        ).json()["id"]
        return cohort_one_id

    @freeze_time("2022-03-22T00:00:00.000Z")
    def test_create_insight_viewed(self):
        filter_dict = {
            "events": [{"id": "$pageview"}],
        }

        insight = Insight.objects.create(
            filters=Filter(data=filter_dict).to_dict(), team=self.team, short_id="12345678",
        )

        response = self.client.post(f"/api/projects/{self.team.id}/insights/{insight.id}/viewed")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        created_insight_viewed = InsightViewed.objects.all()[0]
        self.assertEqual(created_insight_viewed.insight, insight)
        self.assertEqual(created_insight_viewed.team, self.team)
        self.assertEqual(created_insight_viewed.user, self.user)
        self.assertEqual(created_insight_viewed.last_viewed_at, datetime(2022, 3, 22, 0, 0, tzinfo=pytz.UTC))

    def test_update_insight_viewed(self):
        filter_dict = {
            "events": [{"id": "$pageview"}],
        }
        insight = Insight.objects.create(
            filters=Filter(data=filter_dict).to_dict(), team=self.team, short_id="12345678",
        )
        with freeze_time("2022-03-22T00:00:00.000Z"):

            response = self.client.post(f"/api/projects/{self.team.id}/insights/{insight.id}/viewed")
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        with freeze_time("2022-03-23T00:00:00.000Z"):
            response = self.client.post(f"/api/projects/{self.team.id}/insights/{insight.id}/viewed")
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)
            self.assertEqual(InsightViewed.objects.count(), 1)

            updated_insight_viewed = InsightViewed.objects.all()[0]
            self.assertEqual(updated_insight_viewed.last_viewed_at, datetime(2022, 3, 23, 0, 0, tzinfo=pytz.UTC))

    def test_cant_create_insight_viewed_for_another_team(self):
        other_team = Team.objects.create(organization=self.organization, name="other team")
        filter_dict = {
            "events": [{"id": "$pageview"}],
        }
        insight = Insight.objects.create(
            filters=Filter(data=filter_dict).to_dict(), team=self.team, short_id="12345678",
        )

        response = self.client.post(f"/api/projects/{other_team.id}/insights/{insight.id}/viewed")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(InsightViewed.objects.count(), 0)

    def test_cant_create_insight_viewed_for_insight_in_another_team(self):
        other_team = Team.objects.create(organization=self.organization, name="other team")
        filter_dict = {
            "events": [{"id": "$pageview"}],
        }
        insight = Insight.objects.create(
            filters=Filter(data=filter_dict).to_dict(), team=other_team, short_id="12345678",
        )

        response = self.client.post(f"/api/projects/{self.team.id}/insights/{insight.id}/viewed")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(InsightViewed.objects.count(), 0)

    def test_get_recently_viewed_insights(self):
        filter_dict = {
            "events": [{"id": "$pageview"}],
        }

        insight = Insight.objects.create(
            filters=Filter(data=filter_dict).to_dict(), team=self.team, short_id="12345678",
        )

        self.client.post(f"/api/projects/{self.team.id}/insights/{insight.id}/viewed")

        response = self.client.get(
            f"/api/projects/{self.team.id}/insights/?my_last_viewed=true&order=-my_last_viewed_at"
        )
        response_data = response.json()

        # No results if no insights have been viewed
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response_data["results"]), 1)
        self.assertEqual(response_data["results"][0]["id"], insight.id)

    def test_get_recently_viewed_insights_when_no_insights_viewed(self):
        filter_dict = {
            "events": [{"id": "$pageview"}],
        }

        Insight.objects.create(
            filters=Filter(data=filter_dict).to_dict(), team=self.team, short_id="12345678",
        )

        response = self.client.get(
            f"/api/projects/{self.team.id}/insights/?my_last_viewed=true&order=-my_last_viewed_at"
        )
        response_data = response.json()
        # No results if no insights have been viewed
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response_data["results"]), 0)

    def test_recently_viewed_insights_ordered_by_view_date(self):
        filter_dict = {
            "events": [{"id": "$pageview"}],
        }

        insight_1 = Insight.objects.create(
            filters=Filter(data=filter_dict).to_dict(), team=self.team, short_id="12345678",
        )
        insight_2 = Insight.objects.create(
            filters=Filter(data=filter_dict).to_dict(), team=self.team, short_id="98765432",
        )

        self.client.post(f"/api/projects/{self.team.id}/insights/{insight_1.id}/viewed")
        self.client.post(f"/api/projects/{self.team.id}/insights/{insight_2.id}/viewed")

        response = self.client.get(
            f"/api/projects/{self.team.id}/insights/?my_last_viewed=true&order=-my_last_viewed_at"
        )
        response_data = response.json()

        # Insights are ordered by most recently viewed
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response_data["results"]), 2)
        self.assertEqual(response_data["results"][0]["id"], insight_2.id)
        self.assertEqual(response_data["results"][1]["id"], insight_1.id)

        self.client.post(f"/api/projects/{self.team.id}/insights/{insight_1.id}/viewed")

        response = self.client.get(
            f"/api/projects/{self.team.id}/insights/?my_last_viewed=true&order=-my_last_viewed_at"
        )
        response_data = response.json()

        # Order updates when an insight is viewed again
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response_data["results"]), 2)
        self.assertEqual(response_data["results"][0]["id"], insight_1.id)
        self.assertEqual(response_data["results"][1]["id"], insight_2.id)

    def test_another_user_viewing_an_insight_does_not_impact_the_list(self):
        filter_dict = {
            "events": [{"id": "$pageview"}],
        }

        insight = Insight.objects.create(
            filters=Filter(data=filter_dict).to_dict(), team=self.team, short_id="12345678",
        )
        another_user = User.objects.create_and_join(self.organization, "team2@posthog.com", None)
        InsightViewed.objects.create(team=self.team, user=another_user, insight=insight, last_viewed_at=timezone.now())

        response = self.client.get(
            f"/api/projects/{self.team.id}/insights/?my_last_viewed=true&order=-my_last_viewed_at"
        )
        response_data = response.json()

        # Insights are ordered by most recently viewed
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response_data["results"]), 0)

    def test_cannot_create_insight_with_dashboards_relation_from_another_team(self):
        dashboard_own_team: Dashboard = Dashboard.objects.create(team=self.team)
        another_team = Team.objects.create(organization=self.organization)
        dashboard_other_team: Dashboard = Dashboard.objects.create(team=another_team)

        self._create_insight(
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

    def test_cannot_update_insight_with_dashboard_from_another_team(self):
        another_team = Team.objects.create(organization=self.organization)
        dashboard_other_team: Dashboard = Dashboard.objects.create(team=another_team)
        dashboard_own_team: Dashboard = Dashboard.objects.create(team=self.team)

        insight_id, _ = self._create_insight(
            data={
                "filters": {
                    "events": [{"id": "$pageview"}],
                    "properties": [{"key": "$browser", "value": "Mac OS X"}],
                    "date_from": "-90d",
                },
                "dashboards": [dashboard_own_team.pk],
            },
        )

        response = self.client.patch(
            f"/api/projects/{self.team.id}/insights/{insight_id}",
            {"dashboards": [dashboard_own_team.pk, dashboard_other_team.pk],},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_an_insight_on_no_dashboard_has_no_restrictions(self):
        _, response_data = self._create_insight(data={"name": "not on a dashboard"})
        self.assertEqual(
            response_data["effective_restriction_level"], Dashboard.RestrictionLevel.EVERYONE_IN_PROJECT_CAN_EDIT
        )
        self.assertEqual(response_data["effective_privilege_level"], Dashboard.PrivilegeLevel.CAN_EDIT)

    def test_an_insight_on_unrestricted_dashboard_has_no_restrictions(self):
        dashboard: Dashboard = Dashboard.objects.create(team=self.team)
        _, response_data = self._create_insight(
            data={"name": "on an unrestricted dashboard", "dashboards": [dashboard.pk]}
        )
        self.assertEqual(
            response_data["effective_restriction_level"], Dashboard.RestrictionLevel.EVERYONE_IN_PROJECT_CAN_EDIT
        )
        self.assertEqual(response_data["effective_privilege_level"], Dashboard.PrivilegeLevel.CAN_EDIT)

    def test_an_insight_on_restricted_dashboard_has_restrictions_cannot_edit_without_explicit_privilege(self):
        dashboard: Dashboard = Dashboard.objects.create(
            team=self.team, restriction_level=Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT
        )
        _, response_data = self._create_insight(
            data={"name": "on a restricted dashboard", "dashboards": [dashboard.pk]}
        )
        self.assertEqual(
            response_data["effective_restriction_level"], Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT
        )
        self.assertEqual(response_data["effective_privilege_level"], Dashboard.PrivilegeLevel.CAN_VIEW)

    def test_an_insight_on_both_restricted_and_unrestricted_dashboard_has_no_restrictions(self):
        dashboard_restricted: Dashboard = Dashboard.objects.create(
            team=self.team, restriction_level=Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT
        )
        dashboard_unrestricted: Dashboard = Dashboard.objects.create(
            team=self.team, restriction_level=Dashboard.RestrictionLevel.EVERYONE_IN_PROJECT_CAN_EDIT
        )
        _, response_data = self._create_insight(
            data={
                "name": "on a restricted and unrestricted dashboard",
                "dashboards": [dashboard_restricted.pk, dashboard_unrestricted.pk],
            }
        )
        self.assertEqual(
            response_data["effective_restriction_level"], Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT
        )
        self.assertEqual(response_data["effective_privilege_level"], Dashboard.PrivilegeLevel.CAN_EDIT)

    def test_an_insight_on_restricted_dashboard_does_not_restrict_admin(self):
        dashboard_restricted: Dashboard = Dashboard.objects.create(
            team=self.team, restriction_level=Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT
        )

        admin = User.objects.create_and_join(
            organization=self.organization, email="y@x.com", password=None, level=OrganizationMembership.Level.ADMIN
        )
        self.client.force_login(admin)
        _, response_data = self._create_insight(
            data={"name": "on a restricted and unrestricted dashboard", "dashboards": [dashboard_restricted.pk],}
        )
        self.assertEqual(
            response_data["effective_restriction_level"], Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT
        )
        self.assertEqual(response_data["effective_privilege_level"], Dashboard.PrivilegeLevel.CAN_EDIT)

    def test_an_insight_on_both_restricted_dashboard_does_not_restrict_with_explicit_privilege(self):
        dashboard_restricted: Dashboard = Dashboard.objects.create(
            team=self.team, restriction_level=Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT
        )

        DashboardPrivilege.objects.create(
            dashboard=dashboard_restricted, user=self.user, level=Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT
        )

        _, response_data = self._create_insight(
            data={"name": "on a restricted and unrestricted dashboard", "dashboards": [dashboard_restricted.pk],}
        )
        self.assertEqual(
            response_data["effective_restriction_level"], Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT
        )
        self.assertEqual(response_data["effective_privilege_level"], Dashboard.PrivilegeLevel.CAN_EDIT)

    def test_cannot_update_an_insight_if_on_restricted_dashboard(self):
        dashboard_restricted: Dashboard = Dashboard.objects.create(
            team=self.team, restriction_level=Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT
        )

        insight_id, response_data = self._create_insight(
            data={"name": "on a restricted and unrestricted dashboard", "dashboards": [dashboard_restricted.pk],}
        )

        response = self.client.patch(
            f"/api/projects/{self.team.id}/insights/{insight_id}", {"name": "changing when restricted"},
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_saving_an_insight_with_new_filters_updates_the_dashboard_tile(self):
        dashboard_id, _ = self._create_dashboard({})
        insight_id, _ = self._create_insight(
            {"filters": {"events": [{"id": "$pageview"}], "properties": [{"key": "$browser", "value": "Mac OS X"}],},},
        )
        self._add_insight_to_dashboard([dashboard_id], insight_id)

        before_save = DashboardTile.objects.get(dashboard__id=dashboard_id, insight__id=insight_id).filters_hash

        response = self.client.patch(
            f"/api/projects/{self.team.id}/insights/{insight_id}",
            {"filters": {"events": [{"id": "$pageview"}], "properties": [{"key": "$browser", "value": "Chrome"}],},},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        after_save = DashboardTile.objects.get(dashboard__id=dashboard_id, insight__id=insight_id).filters_hash

        self.assertIsNotNone(before_save)
        self.assertIsNotNone(after_save)
        self.assertNotEqual(before_save, after_save)

    def test_saving_an_insight_with_unchanged_filters_does_not_update_the_dashboard_tile(self):
        dashboard_id, _ = self._create_dashboard({})
        insight_id, _ = self._create_insight(
            {"filters": {"events": [{"id": "$pageview"}], "properties": [{"key": "$browser", "value": "Mac OS X"}],},},
        )
        self._add_insight_to_dashboard([dashboard_id], insight_id)

        before_save = DashboardTile.objects.get(dashboard__id=dashboard_id, insight__id=insight_id).filters_hash

        response = self.client.patch(
            f"/api/projects/{self.team.id}/insights/{insight_id}", {"name": "a non-filter change"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        after_save = DashboardTile.objects.get(dashboard__id=dashboard_id, insight__id=insight_id).filters_hash

        self.assertIsNotNone(before_save)
        self.assertIsNotNone(after_save)
        self.assertEqual(before_save, after_save)

    def test_saving_a_dashboard_with_new_filters_updates_the_dashboard_tile(self):
        dashboard_id, _ = self._create_dashboard({})
        insight_id, _ = self._create_insight(
            {"filters": {"events": [{"id": "$pageview"}], "properties": [{"key": "$browser", "value": "Mac OS X"}],},},
        )
        self._add_insight_to_dashboard([dashboard_id], insight_id)

        before_save = DashboardTile.objects.get(dashboard__id=dashboard_id, insight__id=insight_id).filters_hash

        response = self.client.patch(
            f"/api/projects/{self.team.id}/dashboards/{dashboard_id}", {"filters": {"date_from": "-14d"},},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        after_save = DashboardTile.objects.get(dashboard__id=dashboard_id, insight__id=insight_id).filters_hash

        self.assertIsNotNone(before_save)
        self.assertIsNotNone(after_save)
        self.assertNotEqual(before_save, after_save)

    def test_saving_a_dashboard_with_unchanged_filters_does_not_update_the_dashboard_tile(self):
        dashboard_id, _ = self._create_dashboard({"name": "the dashboard's name"})
        insight_id, _ = self._create_insight(
            {"filters": {"events": [{"id": "$pageview"}], "properties": [{"key": "$browser", "value": "Mac OS X"}],},},
        )
        self._add_insight_to_dashboard([dashboard_id], insight_id)

        before_save = DashboardTile.objects.get(dashboard__id=dashboard_id, insight__id=insight_id).filters_hash

        response = self.client.patch(
            f"/api/projects/{self.team.id}/dashboards/{dashboard_id}", {"name": "the dashboard's name"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        after_save = DashboardTile.objects.get(dashboard__id=dashboard_id, insight__id=insight_id).filters_hash

        self.assertIsNotNone(before_save)
        self.assertIsNotNone(after_save)
        self.assertEqual(before_save, after_save)

    def test_hard_delete_is_forbidden(self) -> None:
        insight_id, _ = self._create_insight({"name": "to be deleted"})
        api_response = self.client.delete(f"/api/projects/{self.team.id}/insights/{insight_id}")
        self.assertEqual(api_response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        self.assertEqual(
            self.client.get(f"/api/projects/{self.team.id}/insights/{insight_id}").status_code, status.HTTP_200_OK,
        )

    def test_soft_delete_causes_404(self) -> None:
        insight_id, _ = self._create_insight({"name": "to be deleted"})
        self._get_insight(insight_id=insight_id, expected_status=status.HTTP_200_OK)

        update_response = self.client.patch(f"/api/projects/{self.team.id}/insights/{insight_id}", {"deleted": True})
        self.assertEqual(update_response.status_code, status.HTTP_200_OK)

        self._get_insight(insight_id=insight_id, expected_status=status.HTTP_404_NOT_FOUND)

    def test_soft_delete_can_be_reversed_by_patch(self) -> None:
        insight_id, _ = self._create_insight({"name": "an insight"})

        self.client.patch(f"/api/projects/{self.team.id}/insights/{insight_id}", {"deleted": True})

        self.assertEqual(
            self.client.get(f"/api/projects/{self.team.id}/insights/{insight_id}").status_code,
            status.HTTP_404_NOT_FOUND,
        )

        update_response = self.client.patch(f"/api/projects/{self.team.id}/insights/{insight_id}", {"deleted": False})
        self.assertEqual(update_response.status_code, status.HTTP_200_OK)

        self.assertEqual(
            self.client.get(f"/api/projects/{self.team.id}/insights/{insight_id}").status_code, status.HTTP_200_OK
        )

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

    def _create_dashboard(self, data: Dict[str, Any], team_id: Optional[int] = None) -> Tuple[int, Dict[str, Any]]:
        if team_id is None:
            team_id = self.team.id
        response = self.client.post(f"/api/projects/{team_id}/dashboards/", data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        response_json = response.json()
        return response_json["id"], response_json

    def _add_insight_to_dashboard(
        self, dashboard_ids: List[int], insight_id: int, expected_status: int = status.HTTP_200_OK
    ):
        response = self.client.patch(
            f"/api/projects/{self.team.id}/insights/{insight_id}", {"dashboards": dashboard_ids,},
        )
        self.assertEqual(response.status_code, expected_status)

    def _get_insight(
        self,
        insight_id: int,
        team_id: Optional[int] = None,
        expected_status: int = status.HTTP_200_OK,
        query_params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if team_id is None:
            team_id = self.team.id

        if query_params is None:
            query_params = {}

        response = self.client.get(f"/api/projects/{team_id}/insights/{insight_id}", query_params)
        self.assertEqual(response.status_code, expected_status)

        response_json = response.json()
        return response_json

    def _get_insight_activity(
        self, insight_id: Optional[int] = None, team_id: Optional[int] = None, expected_status: int = status.HTTP_200_OK
    ):
        if team_id is None:
            team_id = self.team.id

        if insight_id is None:
            url = f"/api/projects/{team_id}/insights/activity"
        else:
            url = f"/api/projects/{team_id}/insights/{insight_id}/activity"

        activity = self.client.get(url)
        self.assertEqual(activity.status_code, expected_status)
        return activity.json()

    def assert_insight_activity(self, insight_id: Optional[int], expected: List[Dict]):
        activity_response = self._get_insight_activity(insight_id)

        activity: List[Dict] = activity_response["results"]

        self.maxDiff = None
        self.assertEqual(
            activity, expected,
        )
