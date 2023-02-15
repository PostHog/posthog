import datetime
import json
from typing import Dict, List, Optional
from unittest.mock import patch

from django.core.cache import cache
from django.db import connection
from django.db.utils import OperationalError
from django.test import TransactionTestCase
from django.test.client import RequestFactory
from django.utils import timezone
from freezegun.api import freeze_time
from rest_framework import status

from posthog.api.feature_flag import FeatureFlagSerializer
from posthog.constants import AvailableFeature
from posthog.models import FeatureFlag, GroupTypeMapping, User
from posthog.models.cohort import Cohort
from posthog.models.feature_flag import get_all_feature_flags, get_feature_flags_for_team_in_cache
from posthog.models.group.util import create_group
from posthog.models.organization import Organization
from posthog.models.person import Person
from posthog.models.personal_api_key import PersonalAPIKey, hash_key_value
from posthog.models.team.team import Team
from posthog.models.utils import generate_random_token_personal
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    QueryMatchingTest,
    _create_person,
    snapshot_clickhouse_queries,
    snapshot_postgres_queries_context,
)
from posthog.test.db_context_capturing import capture_db_queries


class TestFeatureFlag(APIBaseTest):
    feature_flag: FeatureFlag = None  # type: ignore

    maxDiff = None

    def setUp(self):
        cache.clear()
        return super().setUp()

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.feature_flag = FeatureFlag.objects.create(team=cls.team, created_by=cls.user, key="red_button")

    def test_cant_create_flag_with_duplicate_key(self):
        count = FeatureFlag.objects.count()
        # Make sure the endpoint works with and without the trailing slash
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags", {"name": "Beta feature", "key": "red_button"}
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            {
                "type": "validation_error",
                "code": "unique",
                "detail": "There is already a feature flag with this key.",
                "attr": "key",
            },
        )
        self.assertEqual(FeatureFlag.objects.count(), count)

    def test_cant_update_flag_with_duplicate_key(self):
        another_feature_flag = FeatureFlag.objects.create(
            team=self.team, rollout_percentage=50, name="some feature", key="some-feature", created_by=self.user
        )
        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{another_feature_flag.pk}",
            {"name": "Beta feature", "key": "red_button"},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            {
                "type": "validation_error",
                "code": "unique",
                "detail": "There is already a feature flag with this key.",
                "attr": "key",
            },
        )
        another_feature_flag.refresh_from_db()
        self.assertEqual(another_feature_flag.key, "some-feature")

        # Try updating the existing one
        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{self.feature_flag.id}/",
            {"name": "Beta feature 3", "key": "red_button"},
        )
        self.assertEqual(response.status_code, 200)
        self.feature_flag.refresh_from_db()
        self.assertEqual(self.feature_flag.name, "Beta feature 3")

    def test_is_simple_flag(self):
        feature_flag = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            data={"name": "Beta feature", "key": "beta-feature", "filters": {"groups": [{"rollout_percentage": 65}]}},
            format="json",
        ).json()
        self.assertTrue(feature_flag["is_simple_flag"])
        self.assertEqual(feature_flag["rollout_percentage"], 65)

    def test_is_not_simple_flag(self):
        feature_flag = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            data={
                "name": "Beta feature",
                "key": "beta-feature",
                "filters": {
                    "groups": [
                        {
                            "rollout_percentage": 65,
                            "properties": [
                                {"key": "email", "type": "person", "value": "@posthog.com", "operator": "icontains"}
                            ],
                        }
                    ]
                },
            },
            format="json",
        ).json()
        self.assertFalse(feature_flag["is_simple_flag"])

    @patch("posthog.api.feature_flag.report_user_action")
    def test_is_simple_flag_groups(self, mock_capture):
        feature_flag = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            data={
                "name": "Beta feature",
                "key": "beta-feature",
                "filters": {"aggregation_group_type_index": 0, "groups": [{"rollout_percentage": 65}]},
            },
            format="json",
        ).json()
        self.assertFalse(feature_flag["is_simple_flag"])
        # Assert analytics are sent
        instance = FeatureFlag.objects.get(id=feature_flag["id"])
        mock_capture.assert_called_once_with(
            self.user,
            "feature flag created",
            {
                "groups_count": 1,
                "has_variants": False,
                "variants_count": 0,
                "has_rollout_percentage": True,
                "has_filters": False,
                "filter_count": 0,
                "created_at": instance.created_at,
                "aggregating_by_groups": True,
                "payload_count": 0,
            },
        )

    @freeze_time("2021-08-25T22:09:14.252Z")
    @patch("posthog.api.feature_flag.report_user_action")
    def test_create_feature_flag(self, mock_capture):

        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {"name": "Alpha feature", "key": "alpha-feature", "filters": {"groups": [{"rollout_percentage": 50}]}},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        flag_id = response.json()["id"]
        instance = FeatureFlag.objects.get(id=flag_id)
        self.assertEqual(instance.key, "alpha-feature")

        # Assert analytics are sent
        mock_capture.assert_called_once_with(
            self.user,
            "feature flag created",
            {
                "groups_count": 1,
                "has_variants": False,
                "variants_count": 0,
                "has_rollout_percentage": True,
                "has_filters": False,
                "filter_count": 0,
                "created_at": instance.created_at,
                "aggregating_by_groups": False,
                "payload_count": 0,
            },
        )

        self.assert_feature_flag_activity(
            flag_id,
            [
                {
                    "user": {"first_name": "", "email": "user1@posthog.com"},
                    "activity": "created",
                    "created_at": "2021-08-25T22:09:14.252000Z",
                    "scope": "FeatureFlag",
                    "item_id": str(flag_id),
                    "detail": {
                        "changes": None,
                        "trigger": None,
                        "name": "alpha-feature",
                        "short_id": None,
                    },
                }
            ],
        )

    @patch("posthog.api.feature_flag.report_user_action")
    def test_create_minimal_feature_flag(self, mock_capture):

        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/", {"key": "omega-feature"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["key"], "omega-feature")
        self.assertEqual(response.json()["name"], "")
        instance = FeatureFlag.objects.get(id=response.json()["id"])
        self.assertEqual(instance.key, "omega-feature")
        self.assertEqual(instance.name, "")

        # Assert analytics are sent
        mock_capture.assert_called_once_with(
            self.user,
            "feature flag created",
            {
                "groups_count": 1,  # 1 is always created by default
                "has_variants": False,
                "variants_count": 0,
                "has_rollout_percentage": False,
                "has_filters": False,
                "filter_count": 0,
                "created_at": instance.created_at,
                "aggregating_by_groups": False,
                "payload_count": 0,
            },
        )

    @patch("posthog.api.feature_flag.report_user_action")
    def test_create_multivariate_feature_flag(self, mock_capture):

        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {
                "name": "Multivariate feature",
                "key": "multivariate-feature",
                "filters": {
                    "groups": [{"properties": [], "rollout_percentage": None}],
                    "multivariate": {
                        "variants": [
                            {"key": "first-variant", "name": "First Variant", "rollout_percentage": 50},
                            {"key": "second-variant", "name": "Second Variant", "rollout_percentage": 25},
                            {"key": "third-variant", "name": "Third Variant", "rollout_percentage": 25},
                        ]
                    },
                },
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        instance = FeatureFlag.objects.get(id=response.json()["id"])
        self.assertEqual(instance.key, "multivariate-feature")

        # Assert analytics are sent
        mock_capture.assert_called_once_with(
            self.user,
            "feature flag created",
            {
                "groups_count": 1,
                "has_variants": True,
                "variants_count": 3,
                "has_filters": False,
                "has_rollout_percentage": False,
                "filter_count": 0,
                "created_at": instance.created_at,
                "aggregating_by_groups": False,
                "payload_count": 0,
            },
        )

    def test_cant_create_multivariate_feature_flag_with_variant_rollout_lt_100(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {
                "name": "Multivariate feature",
                "key": "multivariate-feature",
                "filters": {
                    "groups": [{"properties": [], "rollout_percentage": None}],
                    "multivariate": {
                        "variants": [
                            {"key": "first-variant", "name": "First Variant", "rollout_percentage": 50},
                            {"key": "second-variant", "name": "Second Variant", "rollout_percentage": 25},
                            {"key": "third-variant", "name": "Third Variant", "rollout_percentage": 0},
                        ]
                    },
                },
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json().get("type"), "validation_error")
        self.assertEqual(
            response.json().get("detail"), "Invalid variant definitions: Variant rollout percentages must sum to 100."
        )

    def test_cant_create_multivariate_feature_flag_with_variant_rollout_gt_100(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {
                "name": "Multivariate feature",
                "key": "multivariate-feature",
                "filters": {
                    "groups": [{"properties": [], "rollout_percentage": None}],
                    "multivariate": {
                        "variants": [
                            {"key": "first-variant", "name": "First Variant", "rollout_percentage": 50},
                            {"key": "second-variant", "name": "Second Variant", "rollout_percentage": 25},
                            {"key": "third-variant", "name": "Third Variant", "rollout_percentage": 50},
                        ]
                    },
                },
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json().get("type"), "validation_error")
        self.assertEqual(
            response.json().get("detail"), "Invalid variant definitions: Variant rollout percentages must sum to 100."
        )

    def test_cant_create_feature_flag_without_key(self):
        count = FeatureFlag.objects.count()
        response = self.client.post(f"/api/projects/{self.team.id}/feature_flags/", format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            {"type": "validation_error", "code": "required", "detail": "This field is required.", "attr": "key"},
        )
        self.assertEqual(FeatureFlag.objects.count(), count)

    def test_cant_create_multivariate_feature_flag_with_invalid_variant_overrides(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {
                "name": "Multivariate feature",
                "key": "multivariate-feature",
                "filters": {
                    "groups": [{"properties": [], "rollout_percentage": None, "variant": "unknown-variant"}],
                    "multivariate": {
                        "variants": [
                            {"key": "first-variant", "name": "First Variant", "rollout_percentage": 50},
                            {"key": "second-variant", "name": "Second Variant", "rollout_percentage": 25},
                            {"key": "third-variant", "name": "Third Variant", "rollout_percentage": 25},
                        ]
                    },
                },
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json().get("type"), "validation_error")
        self.assertEqual(response.json().get("detail"), "Filters are not valid (variant override does not exist)")

    def test_cant_update_multivariate_feature_flag_with_invalid_variant_overrides(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {
                "name": "Multivariate feature",
                "key": "multivariate-feature",
                "filters": {
                    "groups": [{"properties": [], "rollout_percentage": None, "variant": "second-variant"}],
                    "multivariate": {
                        "variants": [
                            {"key": "first-variant", "name": "First Variant", "rollout_percentage": 50},
                            {"key": "second-variant", "name": "Second Variant", "rollout_percentage": 25},
                            {"key": "third-variant", "name": "Third Variant", "rollout_percentage": 25},
                        ]
                    },
                },
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        feature_flag_id = response.json()["id"]

        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{feature_flag_id}",
            {
                "filters": {
                    "groups": [{"properties": [], "rollout_percentage": None, "variant": "unknown-variant"}],
                    "multivariate": {
                        "variants": [
                            {"key": "first-variant", "name": "First Variant", "rollout_percentage": 50},
                            {"key": "second-variant", "name": "Second Variant", "rollout_percentage": 25},
                            {"key": "third-variant", "name": "Third Variant", "rollout_percentage": 0},
                        ]
                    },
                },
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json().get("type"), "validation_error")
        self.assertEqual(response.json().get("detail"), "Filters are not valid (variant override does not exist)")

    @patch("posthog.api.feature_flag.report_user_action")
    def test_updating_feature_flag(self, mock_capture):
        with freeze_time("2021-08-25T22:09:14.252Z") as frozen_datetime:
            response = self.client.post(
                f"/api/projects/{self.team.id}/feature_flags/",
                {"name": "original name", "key": "a-feature-flag-that-is-updated"},
                format="json",
            )
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)
            flag_id = response.json()["id"]

            frozen_datetime.tick(delta=datetime.timedelta(minutes=10))

            response = self.client.patch(
                f"/api/projects/{self.team.id}/feature_flags/{flag_id}",
                {
                    "name": "Updated name",
                    "filters": {
                        "groups": [
                            {
                                "rollout_percentage": 65,
                                "properties": [
                                    {"key": "email", "type": "person", "value": "@posthog.com", "operator": "icontains"}
                                ],
                            }
                        ]
                    },
                },
                format="json",
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assertEqual(response.json()["name"], "Updated name")
        self.assertEqual(response.json()["filters"]["groups"][0]["rollout_percentage"], 65)

        # Assert analytics are sent
        mock_capture.assert_called_with(
            self.user,
            "feature flag updated",
            {
                "groups_count": 1,
                "has_variants": False,
                "variants_count": 0,
                "has_rollout_percentage": True,
                "has_filters": True,
                "filter_count": 1,
                "created_at": datetime.datetime.fromisoformat("2021-08-25T22:09:14.252000+00:00"),
                "aggregating_by_groups": False,
                "payload_count": 0,
            },
        )

        self.assert_feature_flag_activity(
            flag_id,
            [
                {
                    "user": {"first_name": self.user.first_name, "email": self.user.email},
                    "activity": "updated",
                    "created_at": "2021-08-25T22:19:14.252000Z",
                    "scope": "FeatureFlag",
                    "item_id": str(flag_id),
                    "detail": {
                        "changes": [
                            {
                                "type": "FeatureFlag",
                                "action": "changed",
                                "field": "name",
                                "before": "original name",
                                "after": "Updated name",
                            },
                            {
                                "type": "FeatureFlag",
                                "action": "changed",
                                "field": "filters",
                                "before": {},
                                "after": {
                                    "groups": [
                                        {
                                            "properties": [
                                                {
                                                    "key": "email",
                                                    "type": "person",
                                                    "value": "@posthog.com",
                                                    "operator": "icontains",
                                                }
                                            ],
                                            "rollout_percentage": 65,
                                        }
                                    ]
                                },
                            },
                        ],
                        "trigger": None,
                        "name": "a-feature-flag-that-is-updated",
                        "short_id": None,
                    },
                },
                {
                    "user": {"first_name": self.user.first_name, "email": self.user.email},
                    "activity": "created",
                    "created_at": "2021-08-25T22:09:14.252000Z",
                    "scope": "FeatureFlag",
                    "item_id": str(flag_id),
                    "detail": {
                        "changes": None,
                        "trigger": None,
                        "name": "a-feature-flag-that-is-updated",
                        "short_id": None,
                    },
                },
            ],
        )

    def test_hard_deleting_feature_flag_is_forbidden(self):
        new_user = User.objects.create_and_join(self.organization, "new_annotations@posthog.com", None)

        instance = FeatureFlag.objects.create(team=self.team, created_by=self.user, key="potato")
        self.client.force_login(new_user)

        response = self.client.delete(f"/api/projects/{self.team.id}/feature_flags/{instance.pk}/")

        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        self.assertTrue(FeatureFlag.objects.filter(pk=instance.pk).exists())

    def test_get_feature_flag_activity(self):
        new_user = User.objects.create_and_join(
            organization=self.organization,
            email="person_acting_and_then_viewing_activity@posthog.com",
            password=None,
            first_name="Potato",
        )
        self.client.force_login(new_user)

        with freeze_time("2021-08-25T22:09:14.252Z") as frozen_datetime:
            create_response = self.client.post(
                f"/api/projects/{self.team.id}/feature_flags/",
                {"name": "feature flag with activity", "key": "feature_with_activity"},
            )

            self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
            flag_id = create_response.json()["id"]

            frozen_datetime.tick(delta=datetime.timedelta(minutes=10))

            update_response = self.client.patch(
                f"/api/projects/{self.team.id}/feature_flags/{flag_id}",
                {
                    "name": "feature flag with activity",
                    "filters": {"groups": [{"properties": [], "rollout_percentage": 74}]},
                },
                format="json",
            )

        self.assertEqual(update_response.status_code, status.HTTP_200_OK)

        self.assert_feature_flag_activity(
            flag_id,
            [
                {
                    "user": {"first_name": new_user.first_name, "email": new_user.email},
                    "activity": "updated",
                    "created_at": "2021-08-25T22:19:14.252000Z",
                    "scope": "FeatureFlag",
                    "item_id": str(flag_id),
                    "detail": {
                        "changes": [
                            {
                                "type": "FeatureFlag",
                                "action": "changed",
                                "field": "filters",
                                "before": {},
                                "after": {"groups": [{"properties": [], "rollout_percentage": 74}]},
                            }
                        ],
                        "trigger": None,
                        "name": "feature_with_activity",
                        "short_id": None,
                    },
                },
                {
                    "user": {"first_name": new_user.first_name, "email": new_user.email},
                    "activity": "created",
                    "created_at": "2021-08-25T22:09:14.252000Z",
                    "scope": "FeatureFlag",
                    "item_id": str(flag_id),
                    "detail": {
                        "changes": None,
                        "trigger": None,
                        "name": "feature_with_activity",
                        "short_id": None,
                    },
                },
            ],
        )

    def test_get_feature_flag_activity_for_all_flags(self):
        new_user = User.objects.create_and_join(
            organization=self.organization,
            email="person_acting_and_then_viewing_activity@posthog.com",
            password=None,
            first_name="Potato",
        )
        self.client.force_login(new_user)

        with freeze_time("2021-08-25T22:09:14.252Z") as frozen_datetime:
            create_response = self.client.post(
                f"/api/projects/{self.team.id}/feature_flags/",
                {"name": "feature flag with activity", "key": "feature_with_activity"},
            )

            self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
            flag_id = create_response.json()["id"]

            frozen_datetime.tick(delta=datetime.timedelta(minutes=10))

            update_response = self.client.patch(
                f"/api/projects/{self.team.id}/feature_flags/{flag_id}",
                {
                    "name": "feature flag with activity",
                    "filters": {"groups": [{"properties": [], "rollout_percentage": 74}]},
                },
                format="json",
            )
            self.assertEqual(update_response.status_code, status.HTTP_200_OK)

            frozen_datetime.tick(delta=datetime.timedelta(minutes=10))

            second_create_response = self.client.post(
                f"/api/projects/{self.team.id}/feature_flags/", {"name": "a second feature flag", "key": "flag-two"}
            )

            self.assertEqual(second_create_response.status_code, status.HTTP_201_CREATED)
            second_flag_id = second_create_response.json()["id"]

        self.assert_feature_flag_activity(
            flag_id=None,
            expected=[
                {
                    "user": {"first_name": new_user.first_name, "email": new_user.email},
                    "activity": "created",
                    "created_at": "2021-08-25T22:29:14.252000Z",
                    "scope": "FeatureFlag",
                    "item_id": str(second_flag_id),
                    "detail": {"changes": None, "trigger": None, "name": "flag-two", "short_id": None},
                },
                {
                    "user": {"first_name": new_user.first_name, "email": new_user.email},
                    "activity": "updated",
                    "created_at": "2021-08-25T22:19:14.252000Z",
                    "scope": "FeatureFlag",
                    "item_id": str(flag_id),
                    "detail": {
                        "changes": [
                            {
                                "type": "FeatureFlag",
                                "action": "changed",
                                "field": "filters",
                                "before": {},
                                "after": {"groups": [{"properties": [], "rollout_percentage": 74}]},
                            }
                        ],
                        "trigger": None,
                        "name": "feature_with_activity",
                        "short_id": None,
                    },
                },
                {
                    "user": {"first_name": new_user.first_name, "email": new_user.email},
                    "activity": "created",
                    "created_at": "2021-08-25T22:09:14.252000Z",
                    "scope": "FeatureFlag",
                    "item_id": str(flag_id),
                    "detail": {
                        "changes": None,
                        "trigger": None,
                        "name": "feature_with_activity",
                        "short_id": None,
                    },
                },
            ],
        )

    def test_length_of_feature_flag_activity_does_not_change_number_of_db_queries(self):
        new_user = User.objects.create_and_join(
            organization=self.organization,
            email="person_acting_and_then_viewing_activity@posthog.com",
            password=None,
            first_name="Potato",
        )
        self.client.force_login(new_user)

        # create the flag
        create_response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {"name": "feature flag with activity", "key": "feature_with_activity"},
        )
        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
        flag_id = create_response.json()["id"]

        # get the activity and capture number of queries made
        with capture_db_queries() as first_read_context:
            self._get_feature_flag_activity(flag_id)

        if isinstance(first_read_context.final_queries, int) and isinstance(first_read_context.initial_queries, int):
            first_activity_read_query_count = first_read_context.final_queries - first_read_context.initial_queries
        else:
            raise AssertionError("must be able to read query numbers from first activity log query")

        # update the flag
        update_response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{flag_id}",
            {
                "name": "feature flag with activity",
                "filters": {"groups": [{"properties": [], "rollout_percentage": 74}]},
            },
            format="json",
        )
        self.assertEqual(update_response.status_code, status.HTTP_200_OK)

        # get the activity and capture number of queries made
        with capture_db_queries() as second_read_context:
            self._get_feature_flag_activity(flag_id)

        if isinstance(second_read_context.final_queries, int) and isinstance(second_read_context.initial_queries, int):
            second_activity_read_query_count = second_read_context.final_queries - second_read_context.initial_queries
        else:
            raise AssertionError("must be able to read query numbers from second activity log query")

        self.assertEqual(first_activity_read_query_count, second_activity_read_query_count)

    def test_get_feature_flag_activity_only_from_own_team(self):
        # two users in two teams
        _, org_one_team, org_one_user = User.objects.bootstrap(
            organization_name="Org 1", email="org1@posthog.com", password=None
        )

        _, org_two_team, org_two_user = User.objects.bootstrap(
            organization_name="Org 2", email="org2@posthog.com", password=None
        )

        # two flags in team 1
        self.client.force_login(org_one_user)
        team_one_flag_one = self._create_flag_with_properties(
            name="team-1-flag-1", team_id=org_one_team.id, properties=[]
        ).json()["id"]
        team_one_flag_two = self._create_flag_with_properties(
            name="team-1-flag-2", team_id=org_one_team.id, properties=[]
        ).json()["id"]

        # two flags in team 2
        self.client.force_login(org_two_user)
        team_two_flag_one = self._create_flag_with_properties(
            name="team-2-flag-1", team_id=org_two_team.id, properties=[]
        ).json()["id"]
        team_two_flag_two = self._create_flag_with_properties(
            name="team-2-flag-2", team_id=org_two_team.id, properties=[]
        ).json()["id"]

        # user in org 1 gets activity
        self.client.force_login(org_one_user)
        self._get_feature_flag_activity(
            flag_id=team_one_flag_one, team_id=org_one_team.id, expected_status=status.HTTP_200_OK
        )
        self._get_feature_flag_activity(
            flag_id=team_one_flag_two, team_id=org_one_team.id, expected_status=status.HTTP_200_OK
        )
        self._get_feature_flag_activity(
            flag_id=team_two_flag_one, team_id=org_one_team.id, expected_status=status.HTTP_404_NOT_FOUND
        )
        self._get_feature_flag_activity(
            flag_id=team_two_flag_two, team_id=org_one_team.id, expected_status=status.HTTP_404_NOT_FOUND
        )

        # user in org 2 gets activity
        self.client.force_login(org_two_user)
        self._get_feature_flag_activity(
            flag_id=team_one_flag_two, team_id=org_two_team.id, expected_status=status.HTTP_404_NOT_FOUND
        )
        self._get_feature_flag_activity(
            flag_id=team_one_flag_two, team_id=org_two_team.id, expected_status=status.HTTP_404_NOT_FOUND
        )
        self._get_feature_flag_activity(
            flag_id=team_two_flag_one, team_id=org_two_team.id, expected_status=status.HTTP_200_OK
        )
        self._get_feature_flag_activity(
            flag_id=team_two_flag_two, team_id=org_two_team.id, expected_status=status.HTTP_200_OK
        )

    def test_paging_all_feature_flag_activity(self):
        for x in range(15):
            create_response = self.client.post(
                f"/api/projects/{self.team.id}/feature_flags/", {"name": f"feature flag {x}", "key": f"{x}"}
            )
            self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)

        # check the first page of data
        url = f"/api/projects/{self.team.id}/feature_flags/activity"
        first_page_response = self.client.get(url)
        self.assertEqual(first_page_response.status_code, status.HTTP_200_OK)
        first_page_json = first_page_response.json()

        self.assertEqual(
            [log_item["detail"]["name"] for log_item in first_page_json["results"]],
            ["14", "13", "12", "11", "10", "9", "8", "7", "6", "5"],
        )
        self.assertEqual(
            first_page_json["next"],
            f"http://testserver/api/projects/{self.team.id}/feature_flags/activity?page=2&limit=10",
        )
        self.assertEqual(first_page_json["previous"], None)

        # check the second page of data
        second_page_response = self.client.get(first_page_json["next"])
        self.assertEqual(second_page_response.status_code, status.HTTP_200_OK)
        second_page_json = second_page_response.json()

        self.assertEqual(
            [log_item["detail"]["name"] for log_item in second_page_json["results"]], ["4", "3", "2", "1", "0"]
        )
        self.assertEqual(second_page_json["next"], None)
        self.assertEqual(
            second_page_json["previous"],
            f"http://testserver/api/projects/{self.team.id}/feature_flags/activity?page=1&limit=10",
        )

    def test_paging_specific_feature_flag_activity(self):
        create_response = self.client.post(f"/api/projects/{self.team.id}/feature_flags/", {"name": "ff", "key": "0"})
        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
        flag_id = create_response.json()["id"]

        for x in range(1, 15):
            update_response = self.client.patch(
                f"/api/projects/{self.team.id}/feature_flags/{flag_id}", {"key": str(x)}, format="json"
            )
            self.assertEqual(update_response.status_code, status.HTTP_200_OK)

        # check the first page of data
        url = f"/api/projects/{self.team.id}/feature_flags/{flag_id}/activity"
        first_page_response = self.client.get(url)
        self.assertEqual(first_page_response.status_code, status.HTTP_200_OK)
        first_page_json = first_page_response.json()

        self.assertEqual(
            # feature flag activity writes the flag key to the detail name
            [log_item["detail"]["name"] for log_item in first_page_json["results"]],
            ["14", "13", "12", "11", "10", "9", "8", "7", "6", "5"],
        )
        self.assertEqual(
            first_page_json["next"],
            f"http://testserver/api/projects/{self.team.id}/feature_flags/{flag_id}/activity?page=2&limit=10",
        )
        self.assertEqual(first_page_json["previous"], None)

        # check the second page of data
        second_page_response = self.client.get(first_page_json["next"])
        self.assertEqual(second_page_response.status_code, status.HTTP_200_OK)
        second_page_json = second_page_response.json()

        self.assertEqual(
            # feature flag activity writes the flag key to the detail name
            [log_item["detail"]["name"] for log_item in second_page_json["results"]],
            ["4", "3", "2", "1", "0"],
        )
        self.assertEqual(second_page_json["next"], None)
        self.assertEqual(
            second_page_json["previous"],
            f"http://testserver/api/projects/{self.team.id}/feature_flags/{flag_id}/activity?page=1&limit=10",
        )

    def test_get_flags_with_specified_token(self):
        _, _, user = User.objects.bootstrap("Test", "team2@posthog.com", None)
        self.client.force_login(user)
        assert user.team is not None
        assert self.team is not None
        self.assertNotEqual(user.team.id, self.team.id)

        response_team_1 = self.client.get(f"/api/projects/@current/feature_flags")
        response_team_1_token = self.client.get(f"/api/projects/@current/feature_flags?token={user.team.api_token}")
        response_team_2 = self.client.get(f"/api/projects/@current/feature_flags?token={self.team.api_token}")

        self.assertEqual(response_team_1.json(), response_team_1_token.json())
        self.assertNotEqual(response_team_1.json(), response_team_2.json())

        response_invalid_token = self.client.get(f"/api/projects/@current/feature_flags?token=invalid")
        self.assertEqual(response_invalid_token.status_code, 401)

    def test_creating_a_feature_flag_with_same_team_and_key_after_deleting(self):
        FeatureFlag.objects.create(team=self.team, created_by=self.user, key="alpha-feature", deleted=True)

        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/", {"name": "Alpha feature", "key": "alpha-feature"}
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        instance = FeatureFlag.objects.get(id=response.json()["id"])
        self.assertEqual(instance.key, "alpha-feature")

    def test_updating_a_feature_flag_with_same_team_and_key_of_a_deleted_one(self):
        FeatureFlag.objects.create(team=self.team, created_by=self.user, key="alpha-feature", deleted=True)

        instance = FeatureFlag.objects.create(team=self.team, created_by=self.user, key="beta-feature")

        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{instance.pk}", {"key": "alpha-feature"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        instance.refresh_from_db()
        self.assertEqual(instance.key, "alpha-feature")

    def test_my_flags_is_not_nplus1(self) -> None:
        self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            data={"name": f"flag", "key": f"flag", "filters": {"groups": [{"rollout_percentage": 5}]}},
            format="json",
        ).json()

        with self.assertNumQueries(7):
            response = self.client.get(f"/api/projects/{self.team.id}/feature_flags/my_flags")
            self.assertEqual(response.status_code, status.HTTP_200_OK)

        for i in range(1, 4):
            self.client.post(
                f"/api/projects/{self.team.id}/feature_flags/",
                data={"name": f"flag", "key": f"flag_{i}", "filters": {"groups": [{"rollout_percentage": 5}]}},
                format="json",
            ).json()

        with self.assertNumQueries(7):
            response = self.client.get(f"/api/projects/{self.team.id}/feature_flags/my_flags")
            self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_getting_flags_is_not_nplus1(self) -> None:
        self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            data={"name": f"flag", "key": f"flag_0", "filters": {"groups": [{"rollout_percentage": 5}]}},
            format="json",
        ).json()

        with self.assertNumQueries(8):
            response = self.client.get(f"/api/projects/{self.team.id}/feature_flags")
            self.assertEqual(response.status_code, status.HTTP_200_OK)

        for i in range(1, 5):
            self.client.post(
                f"/api/projects/{self.team.id}/feature_flags/",
                data={"name": f"flag", "key": f"flag_{i}", "filters": {"groups": [{"rollout_percentage": 5}]}},
                format="json",
            ).json()

        with self.assertNumQueries(8):
            response = self.client.get(f"/api/projects/{self.team.id}/feature_flags")
            self.assertEqual(response.status_code, status.HTTP_200_OK)

    @patch("posthog.api.feature_flag.report_user_action")
    def test_my_flags(self, mock_capture):
        self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {
                "name": "Alpha feature",
                "key": "alpha-feature",
                "filters": {
                    "groups": [{"rollout_percentage": 20}],
                    "multivariate": {
                        "variants": [
                            {"key": "first-variant", "name": "First Variant", "rollout_percentage": 50},
                            {"key": "second-variant", "name": "Second Variant", "rollout_percentage": 25},
                            {"key": "third-variant", "name": "Third Variant", "rollout_percentage": 25},
                        ]
                    },
                },
            },
            format="json",
        )

        # # alpha-feature is set for "distinct_id"
        distinct_id_user = User.objects.create_and_join(self.organization, "distinct_id_user@posthog.com", None)
        distinct_id_user.distinct_id = "distinct_id"
        distinct_id_user.save()
        self.client.force_login(distinct_id_user)
        response = self.client.get(f"/api/projects/{self.team.id}/feature_flags/my_flags")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        self.assertEqual(len(response_data), 2)

        first_flag = response_data[0]
        self.assertEqual(first_flag["feature_flag"]["key"], "alpha-feature")
        self.assertEqual(first_flag["value"], "third-variant")

        second_flag = response_data[1]
        self.assertEqual(second_flag["feature_flag"]["key"], "red_button")
        self.assertEqual(second_flag["value"], True)

        # alpha-feature is not set for "distinct_id_0"
        distinct_id_0_user = User.objects.create_and_join(self.organization, "distinct_id_0_user@posthog.com", None)
        distinct_id_0_user.distinct_id = "distinct_id_0"
        distinct_id_0_user.save()
        self.client.force_login(distinct_id_0_user)
        response = self.client.get(f"/api/projects/{self.team.id}/feature_flags/my_flags")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        self.assertEqual(len(response_data), 2)

        first_flag = response_data[0]
        self.assertEqual(first_flag["feature_flag"]["key"], "alpha-feature")
        self.assertEqual(first_flag["value"], False)

    @patch("posthog.api.feature_flag.report_user_action")
    def test_my_flags_empty_flags(self, mock_capture):
        # Ensure empty feature flag list
        FeatureFlag.objects.all().delete()

        response = self.client.get(f"/api/projects/{self.team.id}/feature_flags/my_flags")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        self.assertEqual(len(response_data), 0)

    @patch("posthoganalytics.capture")
    def test_my_flags_groups(self, mock_capture):
        self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {
                "name": "groups flag",
                "key": "groups-flag",
                "filters": {"aggregation_group_type_index": 0, "groups": [{"rollout_percentage": 100}]},
            },
            format="json",
        )

        GroupTypeMapping.objects.create(team=self.team, group_type="organization", group_type_index=0)

        response = self.client.get(f"/api/projects/{self.team.id}/feature_flags/my_flags")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        groups_flag = response.json()[0]
        self.assertEqual(groups_flag["feature_flag"]["key"], "groups-flag")
        self.assertEqual(groups_flag["value"], False)

        response = self.client.get(
            f"/api/projects/{self.team.id}/feature_flags/my_flags", data={"groups": json.dumps({"organization": "7"})}
        )
        groups_flag = response.json()[0]
        self.assertEqual(groups_flag["feature_flag"]["key"], "groups-flag")
        self.assertEqual(groups_flag["value"], True)

    @patch("posthog.api.feature_flag.report_user_action")
    def test_local_evaluation(self, mock_capture):
        FeatureFlag.objects.all().delete()
        GroupTypeMapping.objects.create(team=self.team, group_type="organization", group_type_index=0)
        GroupTypeMapping.objects.create(team=self.team, group_type="company", group_type_index=1)

        self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {
                "name": "Alpha feature",
                "key": "alpha-feature",
                "filters": {
                    "groups": [{"rollout_percentage": 20}],
                    "multivariate": {
                        "variants": [
                            {"key": "first-variant", "name": "First Variant", "rollout_percentage": 50},
                            {"key": "second-variant", "name": "Second Variant", "rollout_percentage": 25},
                            {"key": "third-variant", "name": "Third Variant", "rollout_percentage": 25},
                        ]
                    },
                },
            },
            format="json",
        )

        self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {
                "name": "Group feature",
                "key": "group-feature",
                "filters": {"aggregation_group_type_index": 0, "groups": [{"rollout_percentage": 21}]},
            },
            format="json",
        )

        # old style feature flags
        FeatureFlag.objects.create(
            name="Beta feature",
            key="beta-feature",
            team=self.team,
            rollout_percentage=51,
            filters={"properties": [{"key": "beta-property", "value": "beta-value"}]},
            created_by=self.user,
        )
        # and inactive flag
        FeatureFlag.objects.create(
            name="Inactive feature",
            key="inactive-flag",
            team=self.team,
            active=False,
            rollout_percentage=100,
            filters={"properties": []},
            created_by=self.user,
        )

        personal_api_key = generate_random_token_personal()
        PersonalAPIKey.objects.create(label="X", user=self.user, secure_value=hash_key_value(personal_api_key))

        self.client.logout()
        # `local_evaluation` is called by logged out clients!

        # missing API key
        response = self.client.get(f"/api/feature_flag/local_evaluation?token={self.team.api_token}")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

        response = self.client.get(f"/api/feature_flag/local_evaluation")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

        response = self.client.get(
            f"/api/feature_flag/local_evaluation?token={self.team.api_token}",
            HTTP_AUTHORIZATION=f"Bearer {personal_api_key}",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        self.assertTrue("flags" in response_data and "group_type_mapping" in response_data)
        self.assertEqual(len(response_data["flags"]), 4)

        sorted_flags = sorted(response_data["flags"], key=lambda x: x["key"])

        self.assertDictContainsSubset(
            {
                "name": "Alpha feature",
                "key": "alpha-feature",
                "filters": {
                    "groups": [{"rollout_percentage": 20}],
                    "multivariate": {
                        "variants": [
                            {"key": "first-variant", "name": "First Variant", "rollout_percentage": 50},
                            {"key": "second-variant", "name": "Second Variant", "rollout_percentage": 25},
                            {"key": "third-variant", "name": "Third Variant", "rollout_percentage": 25},
                        ]
                    },
                },
                "deleted": False,
                "active": True,
                "ensure_experience_continuity": False,
            },
            sorted_flags[0],
        )
        self.assertDictContainsSubset(
            {
                "name": "Beta feature",
                "key": "beta-feature",
                "filters": {
                    "groups": [
                        {"properties": [{"key": "beta-property", "value": "beta-value"}], "rollout_percentage": 51}
                    ]
                },
                "deleted": False,
                "active": True,
                "ensure_experience_continuity": False,
            },
            sorted_flags[1],
        )
        self.assertDictContainsSubset(
            {
                "name": "Group feature",
                "key": "group-feature",
                "filters": {"groups": [{"rollout_percentage": 21}], "aggregation_group_type_index": 0},
                "deleted": False,
                "active": True,
                "ensure_experience_continuity": False,
            },
            sorted_flags[2],
        )
        self.assertDictContainsSubset(
            {
                "name": "Inactive feature",
                "key": "inactive-flag",
                "filters": {"groups": [{"properties": [], "rollout_percentage": 100}]},
                "deleted": False,
                "active": False,
                "ensure_experience_continuity": False,
            },
            sorted_flags[3],
        )

        self.assertEqual(response_data["group_type_mapping"], {"0": "organization", "1": "company"})

    @patch("posthog.api.feature_flag.report_user_action")
    def test_local_evaluation_for_cohorts(self, mock_capture):
        FeatureFlag.objects.all().delete()

        cohort_valid_for_ff = Cohort.objects.create(
            team=self.team,
            filters={
                "properties": {
                    "type": "OR",
                    "values": [
                        {
                            "type": "OR",
                            "values": [
                                {"key": "$some_prop", "value": "nomatchihope", "type": "person"},
                                {"key": "$some_prop2", "value": "nomatchihope2", "type": "person"},
                            ],
                        }
                    ],
                }
            },
            name="cohort1",
        )

        self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {
                "name": "Alpha feature",
                "key": "alpha-feature",
                "filters": {
                    "groups": [
                        {
                            "rollout_percentage": 20,
                            "properties": [{"key": "id", "type": "cohort", "value": cohort_valid_for_ff.pk}],
                        }
                    ],
                    "multivariate": {
                        "variants": [
                            {"key": "first-variant", "name": "First Variant", "rollout_percentage": 50},
                            {"key": "second-variant", "name": "Second Variant", "rollout_percentage": 25},
                            {"key": "third-variant", "name": "Third Variant", "rollout_percentage": 25},
                        ]
                    },
                },
            },
            format="json",
        )

        personal_api_key = generate_random_token_personal()
        PersonalAPIKey.objects.create(label="X", user=self.user, secure_value=hash_key_value(personal_api_key))

        response = self.client.get(
            f"/api/feature_flag/local_evaluation?token={self.team.api_token}",
            HTTP_AUTHORIZATION=f"Bearer {personal_api_key}",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        self.assertTrue("flags" in response_data and "group_type_mapping" in response_data)
        self.assertEqual(len(response_data["flags"]), 1)

        sorted_flags = sorted(response_data["flags"], key=lambda x: x["key"])

        self.assertDictContainsSubset(
            {
                "name": "Alpha feature",
                "key": "alpha-feature",
                "filters": {
                    "groups": [
                        {
                            "properties": [{"key": "$some_prop", "type": "person", "value": "nomatchihope"}],
                            "rollout_percentage": 20,
                        },
                        {
                            "properties": [{"key": "$some_prop2", "type": "person", "value": "nomatchihope2"}],
                            "rollout_percentage": 20,
                        },
                    ],
                    "multivariate": {
                        "variants": [
                            {"key": "first-variant", "name": "First Variant", "rollout_percentage": 50},
                            {"key": "second-variant", "name": "Second Variant", "rollout_percentage": 25},
                            {"key": "third-variant", "name": "Third Variant", "rollout_percentage": 25},
                        ]
                    },
                },
                "deleted": False,
                "active": True,
                "ensure_experience_continuity": False,
            },
            sorted_flags[0],
        )

    @patch("posthog.api.feature_flag.report_user_action")
    def test_evaluation_reasons(self, mock_capture):
        FeatureFlag.objects.all().delete()
        GroupTypeMapping.objects.create(team=self.team, group_type="organization", group_type_index=0)
        GroupTypeMapping.objects.create(team=self.team, group_type="company", group_type_index=1)
        Person.objects.create(
            team_id=self.team.pk,
            distinct_ids=["1", "2"],
            properties={"beta-property": "beta-value"},
        )

        self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {
                "name": "Alpha feature",
                "key": "alpha-feature",
                "filters": {
                    "groups": [{"rollout_percentage": 20}],
                    "multivariate": {
                        "variants": [
                            {"key": "first-variant", "name": "First Variant", "rollout_percentage": 50},
                            {"key": "second-variant", "name": "Second Variant", "rollout_percentage": 25},
                            {"key": "third-variant", "name": "Third Variant", "rollout_percentage": 25},
                        ],
                    },
                },
            },
            format="json",
        )

        # old style feature flags
        FeatureFlag.objects.create(
            name="Beta feature",
            key="beta-feature",
            team=self.team,
            rollout_percentage=81,
            filters={"properties": [{"key": "beta-property", "value": "beta-value"}]},
            created_by=self.user,
        )
        # and inactive flag
        FeatureFlag.objects.create(
            name="Inactive feature",
            key="inactive-flag",
            team=self.team,
            active=False,
            rollout_percentage=100,
            filters={"properties": []},
            created_by=self.user,
        )

        self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {
                "name": "Group feature",
                "key": "group-feature",
                "filters": {
                    "aggregation_group_type_index": 0,
                    "groups": [{"rollout_percentage": 61}],
                },
            },
            format="json",
        )

        # general test
        response = self.client.get(
            f"/api/projects/{self.team.pk}/feature_flags/evaluation_reasons",
            {
                "distinct_id": "test",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        self.assertEqual(len(response_data), 4)

        self.assertEqual(
            response_data,
            {
                "alpha-feature": {
                    "value": False,
                    "evaluation": {
                        "reason": "out_of_rollout_bound",
                        "condition_index": 0,
                    },
                },
                "beta-feature": {
                    "value": False,
                    "evaluation": {
                        "reason": "no_condition_match",
                        "condition_index": 0,
                    },
                },
                "group-feature": {
                    "value": False,
                    "evaluation": {
                        "reason": "no_group_type",
                        "condition_index": None,
                    },
                },
                "inactive-flag": {
                    "value": False,
                    "evaluation": {
                        "reason": "disabled",
                        "condition_index": None,
                    },
                },
            },
        )

        # with person having beta-property for beta-feature
        # also matches alpha-feature as within rollout bounds
        response = self.client.get(
            f"/api/projects/{self.team.pk}/feature_flags/evaluation_reasons",
            {
                "distinct_id": "2",
                # "groups": json.dumps({"organization": "org1", "company": "company1"}),
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        self.assertEqual(len(response_data), 4)

        self.assertEqual(
            response_data,
            {
                "alpha-feature": {
                    "value": "first-variant",
                    "evaluation": {
                        "reason": "condition_match",
                        "condition_index": 0,
                    },
                },
                "beta-feature": {
                    "value": True,
                    "evaluation": {
                        "reason": "condition_match",
                        "condition_index": 0,
                    },
                },
                "group-feature": {
                    "value": False,
                    "evaluation": {
                        "reason": "no_group_type",
                        "condition_index": None,
                    },
                },
                "inactive-flag": {
                    "value": False,
                    "evaluation": {
                        "reason": "disabled",
                        "condition_index": None,
                    },
                },
            },
        )

        # with groups
        response = self.client.get(
            f"/api/projects/{self.team.pk}/feature_flags/evaluation_reasons",
            {
                "distinct_id": "org1234",
                "groups": json.dumps({"organization": "org1234"}),
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        self.assertEqual(len(response_data), 4)

        self.assertEqual(
            response_data,
            {
                "alpha-feature": {
                    "value": False,
                    "evaluation": {
                        "reason": "out_of_rollout_bound",
                        "condition_index": 0,
                    },
                },
                "beta-feature": {
                    "value": False,
                    "evaluation": {
                        "reason": "no_condition_match",
                        "condition_index": 0,
                    },
                },
                "group-feature": {
                    "value": True,
                    "evaluation": {
                        "reason": "condition_match",
                        "condition_index": 0,
                    },
                },
                "inactive-flag": {
                    "value": False,
                    "evaluation": {
                        "reason": "disabled",
                        "condition_index": None,
                    },
                },
            },
        )

    def test_validation_person_properties(self):
        person_request = self._create_flag_with_properties(
            "person-flag", [{"key": "email", "type": "person", "value": "@posthog.com", "operator": "icontains"}]
        )
        self.assertEqual(person_request.status_code, status.HTTP_201_CREATED)

        cohort: Cohort = Cohort.objects.create(team=self.team, name="My Cohort")
        cohort_request = self._create_flag_with_properties(
            "cohort-flag", [{"key": "id", "type": "cohort", "value": cohort.id}]
        )
        self.assertEqual(cohort_request.status_code, status.HTTP_201_CREATED)

        event_request = self._create_flag_with_properties(
            "illegal-event-flag", [{"key": "id", "value": 5}], expected_status=status.HTTP_400_BAD_REQUEST
        )
        self.assertEqual(
            event_request.json(),
            {
                "type": "validation_error",
                "code": "invalid_input",
                "detail": "Filters are not valid (can only use person and cohort properties)",
                "attr": "filters",
            },
        )

        groups_request = self._create_flag_with_properties(
            "illegal-groups-flag",
            [{"key": "industry", "value": "finance", "type": "group", "group_type_index": 0}],
            expected_status=status.HTTP_400_BAD_REQUEST,
        )
        self.assertEqual(
            groups_request.json(),
            {
                "type": "validation_error",
                "code": "invalid_input",
                "detail": "Filters are not valid (can only use person and cohort properties)",
                "attr": "filters",
            },
        )

    def test_creating_feature_flag_with_non_existant_cohort(self):
        cohort_request = self._create_flag_with_properties(
            "cohort-flag", [{"key": "id", "type": "cohort", "value": 5151}], expected_status=status.HTTP_400_BAD_REQUEST
        )

        self.assertDictContainsSubset(
            {
                "type": "validation_error",
                "code": "cohort_does_not_exist",
                "detail": "Cohort with id 5151 does not exist",
                "attr": "filters",
            },
            cohort_request.json(),
        )

    def test_validation_payloads(self):
        self._create_flag_with_properties(
            "person-flag",
            [{"key": "email", "type": "person", "value": "@posthog.com", "operator": "icontains"}],
            payloads={"true": 300},
            expected_status=status.HTTP_201_CREATED,
        )
        self._create_flag_with_properties(
            "person-flag",
            [{"key": "email", "type": "person", "value": "@posthog.com", "operator": "icontains"}],
            payloads={"some-fake-key": 300},
            expected_status=status.HTTP_400_BAD_REQUEST,
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {
                "name": "Multivariate feature",
                "key": "multivariate-feature",
                "filters": {
                    "groups": [{"properties": [], "rollout_percentage": None}],
                    "multivariate": {
                        "variants": [
                            {"key": "first-variant", "name": "First Variant", "rollout_percentage": 50},
                            {"key": "second-variant", "name": "Second Variant", "rollout_percentage": 25},
                            {"key": "third-variant", "name": "Third Variant", "rollout_percentage": 25},
                        ]
                    },
                    "payloads": {"first-variant": {"some": "payload"}},
                },
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {
                "name": "Multivariate feature",
                "key": "multivariate-feature",
                "filters": {
                    "groups": [{"properties": [], "rollout_percentage": None}],
                    "multivariate": {
                        "variants": [
                            {"key": "first-variant", "name": "First Variant", "rollout_percentage": 50},
                            {"key": "second-variant", "name": "Second Variant", "rollout_percentage": 25},
                            {"key": "third-variant", "name": "Third Variant", "rollout_percentage": 25},
                        ]
                    },
                    "payloads": {"first-variant": {"some": "payload"}, "fourth-variant": {"some": "payload"}},
                },
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {
                "name": "Multivariate feature",
                "key": "multivariate-feature",
                "filters": {
                    "groups": [{"properties": [], "rollout_percentage": None}],
                    "multivariate": {
                        "variants": [
                            {"key": "first-variant", "name": "First Variant", "rollout_percentage": 50},
                            {"key": "second-variant", "name": "Second Variant", "rollout_percentage": 25},
                            {"key": "third-variant", "name": "Third Variant", "rollout_percentage": 25},
                        ]
                    },
                    "payloads": {"first-variant": {"some": "payload"}, "true": 2500},
                },
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_creating_feature_flag_with_behavioral_cohort(self):

        cohort_valid_for_ff = Cohort.objects.create(
            team=self.team,
            groups=[{"properties": [{"key": "$some_prop", "value": "nomatchihope", "type": "person"}]}],
            name="cohort1",
        )

        cohort_not_valid_for_ff = Cohort.objects.create(
            team=self.team,
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "key": "$pageview",
                            "event_type": "events",
                            "time_value": 2,
                            "time_interval": "week",
                            "value": "performed_event_first_time",
                            "type": "behavioral",
                        },
                        {"key": "email", "value": "test@posthog.com", "type": "person"},
                    ],
                }
            },
            name="cohort2",
        )

        cohort_request = self._create_flag_with_properties(
            "cohort-flag",
            [{"key": "id", "type": "cohort", "value": cohort_not_valid_for_ff.id}],
            expected_status=status.HTTP_400_BAD_REQUEST,
        )

        self.assertDictContainsSubset(
            {
                "type": "validation_error",
                "code": "behavioral_cohort_found",
                "detail": "Cohort 'cohort2' with behavioral filters cannot be used in feature flags.",
                "attr": "filters",
            },
            cohort_request.json(),
        )

        cohort_request = self._create_flag_with_properties(
            "cohort-flag",
            [{"key": "id", "type": "cohort", "value": cohort_valid_for_ff.id}],
            expected_status=status.HTTP_201_CREATED,
        )
        flag_id = cohort_request.json()["id"]
        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{flag_id}",
            {
                "name": "Updated name",
                "filters": {
                    "groups": [
                        {
                            "rollout_percentage": 65,
                            "properties": [{"key": "id", "type": "cohort", "value": cohort_not_valid_for_ff.id}],
                        }
                    ]
                },
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        self.assertDictContainsSubset(
            {
                "type": "validation_error",
                "code": "behavioral_cohort_found",
                "detail": "Cohort 'cohort2' with behavioral filters cannot be used in feature flags.",
                "attr": "filters",
            },
            response.json(),
        )

    @patch("posthog.tasks.calculate_cohort.calculate_cohort_ch.delay")
    def test_cohort_is_calculated(self, calculate_cohort_ch):
        cohort = Cohort.objects.create(
            team=self.team,
            groups=[{"properties": {"$some_prop": "something", "$another_prop": "something"}}],
            name="cohort1",
        )
        cohort_request = self._create_flag_with_properties(
            "cohort-flag", [{"key": "id", "type": "cohort", "value": cohort.pk}]
        )
        self.assertEqual(cohort_request.status_code, status.HTTP_201_CREATED)
        self.assertEqual(calculate_cohort_ch.call_count, 1)

    def test_validation_group_properties(self):
        groups_request = self._create_flag_with_properties(
            "groups-flag",
            [{"key": "industry", "value": "finance", "type": "group", "group_type_index": 0}],
            aggregation_group_type_index=0,
        )
        self.assertEqual(groups_request.status_code, status.HTTP_201_CREATED)

        illegal_groups_request = self._create_flag_with_properties(
            "illegal-groups-flag",
            [{"key": "industry", "value": "finance", "type": "group", "group_type_index": 0}],
            aggregation_group_type_index=3,
            expected_status=status.HTTP_400_BAD_REQUEST,
        )
        self.assertEqual(
            illegal_groups_request.json(),
            {
                "type": "validation_error",
                "code": "invalid_input",
                "detail": "Filters are not valid (can only use group properties)",
                "attr": "filters",
            },
        )

        person_request = self._create_flag_with_properties(
            "person-flag",
            [{"key": "email", "type": "person", "value": "@posthog.com", "operator": "icontains"}],
            aggregation_group_type_index=0,
            expected_status=status.HTTP_400_BAD_REQUEST,
        )
        self.assertEqual(
            person_request.json(),
            {
                "type": "validation_error",
                "code": "invalid_input",
                "detail": "Filters are not valid (can only use group properties)",
                "attr": "filters",
            },
        )

    def _create_flag_with_properties(
        self,
        name: str,
        properties,
        team_id: Optional[int] = None,
        expected_status: int = status.HTTP_201_CREATED,
        **kwargs,
    ):
        if team_id is None:
            team_id = self.team.id

        create_response = self.client.post(
            f"/api/projects/{team_id}/feature_flags/",
            data={"name": name, "key": name, "filters": {**kwargs, "groups": [{"properties": properties}]}},
            format="json",
        )
        self.assertEqual(create_response.status_code, expected_status)
        return create_response

    def _get_feature_flag_activity(
        self, flag_id: Optional[int] = None, team_id: Optional[int] = None, expected_status: int = status.HTTP_200_OK
    ):
        if team_id is None:
            team_id = self.team.id

        if flag_id:
            url = f"/api/projects/{team_id}/feature_flags/{flag_id}/activity"
        else:
            url = f"/api/projects/{team_id}/feature_flags/activity"

        activity = self.client.get(url)
        self.assertEqual(activity.status_code, expected_status)
        return activity.json()

    def assert_feature_flag_activity(self, flag_id: Optional[int], expected: List[Dict]):
        activity_response = self._get_feature_flag_activity(flag_id)

        activity: List[Dict] = activity_response["results"]
        self.maxDiff = None
        self.assertEqual(activity, expected)

    def test_patch_api_as_form_data(self):
        another_feature_flag = FeatureFlag.objects.create(
            team=self.team,
            name="some feature",
            key="some-feature",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}], "multivariate": None},
            active=True,
        )

        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{another_feature_flag.pk}/",
            data="active=False&name=replaced",
            content_type="application/x-www-form-urlencoded",
        )

        self.assertEqual(response.status_code, 200)
        updated_flag = FeatureFlag.objects.get(pk=another_feature_flag.pk)
        self.assertEqual(updated_flag.active, False)
        self.assertEqual(updated_flag.name, "replaced")
        self.assertEqual(
            updated_flag.filters, {"groups": [{"properties": [], "rollout_percentage": 100}], "multivariate": None}
        )

    def test_feature_flag_threshold(self):
        feature_flag = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            data={
                "name": "Beta feature",
                "key": "beta-feature",
                "filters": {"aggregation_group_type_index": 0, "groups": [{"rollout_percentage": 65}]},
                "rollback_conditions": [
                    {
                        "threshold": 5000,
                        "threshold_metric": {
                            "insight": "trends",
                            "events": [{"order": 0, "id": "$pageview"}],
                            "properties": [
                                {
                                    "key": "$geoip_country_name",
                                    "type": "person",
                                    "value": ["france"],
                                    "operator": "exact",
                                }
                            ],
                        },
                        "operator": "lt",
                        "threshold_type": "insight",
                    }
                ],
                "auto-rollback": True,
            },
            format="json",
        ).json()

        self.assertEqual(len(feature_flag["rollback_conditions"]), 1)

    def test_feature_flag_can_edit(self):
        self.assertEqual((AvailableFeature.ROLE_BASED_ACCESS in self.organization.available_features), False)
        user_a = User.objects.create_and_join(self.organization, "a@potato.com", None)
        FeatureFlag.objects.create(team=self.team, created_by=user_a, key="blue_button")
        res = self.client.get(f"/api/projects/{self.team.id}/feature_flags/")
        self.assertEqual(res.json()["results"][0]["can_edit"], True)
        self.assertEqual(res.json()["results"][1]["can_edit"], True)

    def test_flag_is_cached_on_create_and_update(self):
        # Ensure empty feature flag list
        FeatureFlag.objects.all().delete()

        feature_flag = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            data={
                "name": "Beta feature",
                "key": "beta-feature",
                "filters": {"aggregation_group_type_index": 0, "groups": [{"rollout_percentage": 65}]},
            },
            format="json",
        ).json()

        flags = get_feature_flags_for_team_in_cache(self.team.id)

        assert flags is not None
        self.assertEqual(len(flags), 1)
        self.assertEqual(flags[0].id, feature_flag["id"])
        self.assertEqual(flags[0].key, "beta-feature")
        self.assertEqual(flags[0].name, "Beta feature")

        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{feature_flag['id']}",
            {"name": "XYZ", "key": "red_button"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        flags = get_feature_flags_for_team_in_cache(self.team.id)

        assert flags is not None
        self.assertEqual(len(flags), 1)
        self.assertEqual(flags[0].id, feature_flag["id"])
        self.assertEqual(flags[0].key, "red_button")
        self.assertEqual(flags[0].name, "XYZ")

        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{feature_flag['id']}",
            {"deleted": True},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        flags = get_feature_flags_for_team_in_cache(self.team.id)

        assert flags is not None
        self.assertEqual(len(flags), 0)

    @patch("posthog.api.feature_flag.FeatureFlagThrottle.rate", new="7/minute")
    @patch("posthog.rate_limit.BurstRateThrottle.rate", new="5/minute")
    @patch("posthog.rate_limit.statsd.incr")
    @patch("posthog.rate_limit.is_rate_limit_enabled", return_value=True)
    def test_rate_limits_for_local_evaluation_are_independent(self, rate_limit_enabled_mock, incr_mock):
        personal_api_key = generate_random_token_personal()
        PersonalAPIKey.objects.create(label="X", user=self.user, secure_value=hash_key_value(personal_api_key))

        for _ in range(5):
            response = self.client.get(
                f"/api/projects/{self.team.pk}/feature_flags", HTTP_AUTHORIZATION=f"Bearer {personal_api_key}"
            )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Call to flags gets rate limited
        response = self.client.get(
            f"/api/projects/{self.team.pk}/feature_flags", HTTP_AUTHORIZATION=f"Bearer {personal_api_key}"
        )
        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertEqual(len([1 for name, args, kwargs in incr_mock.mock_calls if args[0] == "rate_limit_exceeded"]), 1)
        incr_mock.assert_any_call(
            "rate_limit_exceeded",
            tags={
                "team_id": self.team.pk,
                "scope": "burst",
                "rate": "5/minute",
                "path": f"/api/projects/TEAM_ID/feature_flags",
            },
        )

        incr_mock.reset_mock()

        # but not call to local evaluation
        for _ in range(7):
            response = self.client.get(
                f"/api/feature_flag/local_evaluation", HTTP_AUTHORIZATION=f"Bearer {personal_api_key}"
            )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len([1 for name, args, kwargs in incr_mock.mock_calls if args[0] == "rate_limit_exceeded"]), 0)


class TestBlastRadius(ClickhouseTestMixin, APIBaseTest):
    @snapshot_clickhouse_queries
    def test_user_blast_radius(self):

        for i in range(10):
            _create_person(team_id=self.team.pk, distinct_ids=[f"person{i}"], properties={"group": f"{i}"})

        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/user_blast_radius",
            {
                "condition": {
                    "properties": [{"key": "group", "type": "person", "value": [0, 1, 2, 3], "operator": "exact"}],
                    "rollout_percentage": 25,
                }
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response_json = response.json()
        self.assertDictContainsSubset({"users_affected": 4, "total_users": 10}, response_json)

    def test_user_blast_radius_with_zero_users(self):

        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/user_blast_radius",
            {
                "condition": {
                    "properties": [{"key": "group", "type": "person", "value": [0, 1, 2, 3], "operator": "exact"}],
                    "rollout_percentage": 25,
                }
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response_json = response.json()
        self.assertDictContainsSubset({"users_affected": 0, "total_users": 0}, response_json)

    def test_user_blast_radius_with_zero_selected_users(self):

        for i in range(5):
            _create_person(team_id=self.team.pk, distinct_ids=[f"person{i}"], properties={"group": f"{i}"})

        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/user_blast_radius",
            {
                "condition": {
                    "properties": [{"key": "group", "type": "person", "value": [8], "operator": "exact"}],
                    "rollout_percentage": 25,
                }
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response_json = response.json()
        self.assertDictContainsSubset({"users_affected": 0, "total_users": 5}, response_json)

    def test_user_blast_radius_with_all_selected_users(self):

        for i in range(5):
            _create_person(team_id=self.team.pk, distinct_ids=[f"person{i}"], properties={"group": f"{i}"})

        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/user_blast_radius",
            {"condition": {"properties": [], "rollout_percentage": 100}},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response_json = response.json()
        self.assertDictContainsSubset({"users_affected": 5, "total_users": 5}, response_json)

    @snapshot_clickhouse_queries
    def test_user_blast_radius_with_single_cohort(self):

        for i in range(10):
            _create_person(team_id=self.team.pk, distinct_ids=[f"person{i}"], properties={"group": f"{i}"})

        cohort1 = Cohort.objects.create(
            team=self.team,
            filters={
                "properties": {
                    "type": "OR",
                    "values": [
                        {
                            "type": "OR",
                            "values": [
                                {"key": "group", "value": "none", "type": "person"},
                                {"key": "group", "value": [1, 2, 3], "type": "person"},
                            ],
                        }
                    ],
                }
            },
            name="cohort1",
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/user_blast_radius",
            {
                "condition": {
                    "properties": [{"key": "id", "type": "cohort", "value": cohort1.pk}],
                    "rollout_percentage": 50,
                }
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response_json = response.json()
        self.assertDictContainsSubset({"users_affected": 3, "total_users": 10}, response_json)

        # test the same with precalculated cohort. Snapshots shouldn't have group property filter
        cohort1.calculate_people_ch(pending_version=0)

        with self.settings(USE_PRECALCULATED_CH_COHORT_PEOPLE=True):
            response = self.client.post(
                f"/api/projects/{self.team.id}/feature_flags/user_blast_radius",
                {
                    "condition": {
                        "properties": [{"key": "id", "type": "cohort", "value": cohort1.pk}],
                        "rollout_percentage": 50,
                    }
                },
            )

            self.assertEqual(response.status_code, status.HTTP_200_OK)

            response_json = response.json()
            self.assertDictContainsSubset({"users_affected": 3, "total_users": 10}, response_json)

    @snapshot_clickhouse_queries
    def test_user_blast_radius_with_multiple_precalculated_cohorts(self):

        for i in range(10):
            _create_person(team_id=self.team.pk, distinct_ids=[f"person{i}"], properties={"group": f"{i}"})

        cohort1 = Cohort.objects.create(
            team=self.team,
            filters={
                "properties": {
                    "type": "OR",
                    "values": [
                        {
                            "type": "OR",
                            "values": [
                                {"key": "group", "value": "none", "type": "person"},
                                {"key": "group", "value": [1, 2, 3], "type": "person"},
                            ],
                        }
                    ],
                }
            },
            name="cohort1",
        )

        cohort2 = Cohort.objects.create(
            team=self.team,
            filters={
                "properties": {
                    "type": "OR",
                    "values": [
                        {
                            "type": "OR",
                            "values": [
                                {"key": "group", "value": [1, 2, 4, 5, 6], "type": "person"},
                            ],
                        }
                    ],
                }
            },
            name="cohort2",
        )

        # converts to precalculated-cohort due to simplify filters
        cohort1.calculate_people_ch(pending_version=0)
        cohort2.calculate_people_ch(pending_version=0)

        with self.settings(USE_PRECALCULATED_CH_COHORT_PEOPLE=True):
            response = self.client.post(
                f"/api/projects/{self.team.id}/feature_flags/user_blast_radius",
                {
                    "condition": {
                        "properties": [
                            {"key": "id", "type": "cohort", "value": cohort1.pk},
                            {"key": "id", "type": "cohort", "value": cohort2.pk},
                        ],
                        "rollout_percentage": 50,
                    }
                },
            )

            self.assertEqual(response.status_code, status.HTTP_200_OK)

            response_json = response.json()
            self.assertDictContainsSubset({"users_affected": 2, "total_users": 10}, response_json)

    @snapshot_clickhouse_queries
    def test_user_blast_radius_with_multiple_static_cohorts(self):

        for i in range(10):
            _create_person(team_id=self.team.pk, distinct_ids=[f"person{i}"], properties={"group": f"{i}"})

        cohort1 = Cohort.objects.create(team=self.team, groups=[], is_static=True, last_calculation=timezone.now())
        cohort1.insert_users_by_list(["person0", "person1", "person2"])

        cohort2 = Cohort.objects.create(
            team=self.team,
            filters={
                "properties": {
                    "type": "OR",
                    "values": [
                        {
                            "type": "OR",
                            "values": [
                                {"key": "group", "value": [1, 2, 4, 5, 6], "type": "person"},
                            ],
                        }
                    ],
                }
            },
            name="cohort2",
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/user_blast_radius",
            {
                "condition": {
                    "properties": [
                        {"key": "id", "type": "cohort", "value": cohort1.pk},
                        {"key": "id", "type": "cohort", "value": cohort2.pk},
                    ],
                    "rollout_percentage": 50,
                }
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response_json = response.json()
        self.assertDictContainsSubset({"users_affected": 2, "total_users": 10}, response_json)

        cohort1.calculate_people_ch(pending_version=0)
        # converts to precalculated-cohort due to simplify filters
        cohort2.calculate_people_ch(pending_version=0)

        with self.settings(USE_PRECALCULATED_CH_COHORT_PEOPLE=True):
            response = self.client.post(
                f"/api/projects/{self.team.id}/feature_flags/user_blast_radius",
                {
                    "condition": {
                        "properties": [
                            {"key": "id", "type": "cohort", "value": cohort1.pk},
                            {"key": "id", "type": "cohort", "value": cohort2.pk},
                        ],
                        "rollout_percentage": 50,
                    }
                },
            )

            self.assertEqual(response.status_code, status.HTTP_200_OK)

            response_json = response.json()
            self.assertDictContainsSubset({"users_affected": 2, "total_users": 10}, response_json)

    @snapshot_clickhouse_queries
    def test_user_blast_radius_with_groups(self):
        GroupTypeMapping.objects.create(team=self.team, group_type="organization", group_type_index=0)

        for i in range(10):
            create_group(
                team_id=self.team.pk, group_type_index=0, group_key=f"org:{i}", properties={"industry": f"{i}"}
            )

        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/user_blast_radius",
            {
                "condition": {
                    "properties": [
                        {
                            "key": "industry",
                            "type": "group",
                            "value": [0, 1, 2, 3],
                            "operator": "exact",
                            "group_type_index": 0,
                        }
                    ],
                    "rollout_percentage": 25,
                },
                "group_type_index": 0,
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response_json = response.json()
        self.assertDictContainsSubset({"users_affected": 4, "total_users": 10}, response_json)

    def test_user_blast_radius_with_groups_zero_selected(self):
        GroupTypeMapping.objects.create(team=self.team, group_type="organization", group_type_index=0)

        for i in range(5):
            create_group(
                team_id=self.team.pk, group_type_index=0, group_key=f"org:{i}", properties={"industry": f"{i}"}
            )

        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/user_blast_radius",
            {
                "condition": {
                    "properties": [
                        {"key": "industry", "type": "group", "value": [8], "operator": "exact", "group_type_index": 0}
                    ],
                    "rollout_percentage": 25,
                },
                "group_type_index": 0,
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response_json = response.json()
        self.assertDictContainsSubset({"users_affected": 0, "total_users": 5}, response_json)

    def test_user_blast_radius_with_groups_all_selected(self):
        GroupTypeMapping.objects.create(team=self.team, group_type="organization", group_type_index=0)
        GroupTypeMapping.objects.create(team=self.team, group_type="company", group_type_index=1)

        for i in range(5):
            create_group(
                team_id=self.team.pk, group_type_index=1, group_key=f"org:{i}", properties={"industry": f"{i}"}
            )

        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/user_blast_radius",
            {
                "condition": {
                    "properties": [],
                    "rollout_percentage": 25,
                },
                "group_type_index": 1,
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response_json = response.json()
        self.assertDictContainsSubset({"users_affected": 5, "total_users": 5}, response_json)

    @snapshot_clickhouse_queries
    def test_user_blast_radius_with_groups_multiple_queries(self):
        GroupTypeMapping.objects.create(team=self.team, group_type="organization", group_type_index=0)
        GroupTypeMapping.objects.create(team=self.team, group_type="company", group_type_index=1)

        for i in range(10):
            create_group(
                team_id=self.team.pk, group_type_index=0, group_key=f"org:{i}", properties={"industry": f"{i}"}
            )

        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/user_blast_radius",
            {
                "condition": {
                    "properties": [
                        {
                            "key": "industry",
                            "type": "group",
                            "value": [0, 1, 2, 3, 4],
                            "operator": "exact",
                            "group_type_index": 0,
                        },
                        {
                            "key": "industry",
                            "type": "group",
                            "value": [2, 3, 4, 5, 6],
                            "operator": "exact",
                            "group_type_index": 0,
                        },
                    ],
                    "rollout_percentage": 25,
                },
                "group_type_index": 0,
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response_json = response.json()
        self.assertDictContainsSubset({"users_affected": 3, "total_users": 10}, response_json)

    def test_user_blast_radius_with_groups_incorrect_group_type(self):
        GroupTypeMapping.objects.create(team=self.team, group_type="organization", group_type_index=0)
        GroupTypeMapping.objects.create(team=self.team, group_type="company", group_type_index=1)

        for i in range(10):
            create_group(
                team_id=self.team.pk, group_type_index=0, group_key=f"org:{i}", properties={"industry": f"{i}"}
            )

        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/user_blast_radius",
            {
                "condition": {
                    "properties": [
                        {
                            "key": "industry",
                            "type": "group",
                            "value": [0, 1, 2, 3, 4],
                            "operator": "exact",
                            "group_type_index": 0,
                        },
                        {
                            "key": "industry",
                            "type": "group",
                            "value": [2, 3, 4, 5, 6],
                            "operator": "exact",
                            "group_type_index": 0,
                        },
                    ],
                    "rollout_percentage": 25,
                },
                "group_type_index": 1,
            },
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        response_json = response.json()
        self.assertDictContainsSubset(
            {
                "type": "validation_error",
                "code": "invalid_input",
                "detail": "Invalid group type index for feature flag condition.",
            },
            response_json,
        )


class QueryTimeoutWrapper:
    def __call__(self, execute, *args, **kwargs):

        raise OperationalError("I am a timeout error")
        # return execute(*args, **kwargs)


def slow_query(execute, sql, *args, **kwargs):
    if "statement_timeout" in sql:
        return execute(sql, *args, **kwargs)
    return execute(f"SELECT pg_sleep(1); {sql}", *args, **kwargs)


class TestResiliency(TransactionTestCase, QueryMatchingTest):
    def test_feature_flags_v3_with_group_properties(self):
        self.organization = Organization.objects.create(name="test")
        self.team = Team.objects.create(organization=self.organization)
        self.user = User.objects.create_and_join(self.organization, "random@test.com", "password", "first_name")

        team_id = self.team.pk
        rf = RequestFactory()
        create_request = rf.post(f"api/projects/{self.team.pk}/feature_flags/", {"name": "xyz"})
        create_request.user = self.user

        GroupTypeMapping.objects.create(team=self.team, group_type="organization", group_type_index=0)

        create_group(team_id=self.team.pk, group_type_index=0, group_key=f"org:1", properties={"industry": f"finance"})

        serialized_data = FeatureFlagSerializer(
            data={
                "name": "Alpha feature",
                "key": "group-flag",
                "filters": {
                    "aggregation_group_type_index": 0,
                    "groups": [
                        {
                            "properties": [
                                {"key": "industry", "value": "finance", "type": "group", "group_type_index": 0}
                            ],
                            "rollout_percentage": None,
                        }
                    ],
                },
            },
            context={"team_id": team_id, "request": create_request},
        )
        self.assertTrue(serialized_data.is_valid())
        serialized_data.save()

        # Should be enabled for everyone, if groups are given
        serialized_data = FeatureFlagSerializer(
            data={
                "name": "Alpha feature",
                "key": "default-flag",
                "filters": {
                    "aggregation_group_type_index": 0,
                    "groups": [{"properties": [], "rollout_percentage": None}],
                },
            },
            context={"team_id": team_id, "request": create_request},
        )
        self.assertTrue(serialized_data.is_valid())
        serialized_data.save()

        with self.assertNumQueries(4):
            # one query to get group type mappings, another to get group properties
            # 2 to set statement timeout
            all_flags, _, _, errors = get_all_feature_flags(team_id, "example_id", groups={"organization": "org:1"})
            self.assertTrue(all_flags["group-flag"])
            self.assertTrue(all_flags["default-flag"])
            self.assertFalse(errors)

        # now db is down
        with snapshot_postgres_queries_context(self), connection.execute_wrapper(QueryTimeoutWrapper()):
            all_flags, _, _, errors = get_all_feature_flags(team_id, "example_id", groups={"organization": "org:1"})

            self.assertTrue("group-flag" not in all_flags)
            # can't be true unless we cache group type mappings as well
            self.assertTrue("default-flag" not in all_flags)
            self.assertTrue(errors)

            # # now db is down, but decide was sent correct group property overrides
            with self.assertNumQueries(1):
                # this query is "None", not executed
                all_flags, _, _, errors = get_all_feature_flags(
                    team_id,
                    "random",
                    groups={"organization": "org:1"},
                    group_property_value_overrides={"organization": {"industry": "finance"}},
                )
                self.assertTrue("group-flag" not in all_flags)
                # can't be true unless we cache group type mappings as well
                self.assertTrue("default-flag" not in all_flags)
                self.assertTrue(errors)

            # # now db is down, but decide was sent different group property overrides
            with self.assertNumQueries(1):
                # this query is "None", not executed
                all_flags, _, _, errors = get_all_feature_flags(
                    team_id,
                    "exam",
                    groups={"organization": "org:1"},
                    group_property_value_overrides={"organization": {"industry": "finna"}},
                )
                self.assertTrue("group-flag" not in all_flags)
                # can't be true unless we cache group type mappings as well
                self.assertTrue("default-flag" not in all_flags)
                self.assertTrue(errors)

    def test_feature_flags_v3_with_person_properties(self):
        self.organization = Organization.objects.create(name="test")
        self.team = Team.objects.create(organization=self.organization)
        self.user = User.objects.create_and_join(self.organization, "random@test.com", "password", "first_name")

        team_id = self.team.pk
        rf = RequestFactory()
        create_request = rf.post(f"api/projects/{self.team.pk}/feature_flags/", {"name": "xyz"})
        create_request.user = self.user

        Person.objects.create(team=self.team, distinct_ids=["example_id"], properties={"email": "tim@posthog.com"})

        serialized_data = FeatureFlagSerializer(
            data={
                "name": "Alpha feature",
                "key": "property-flag",
                "filters": {
                    "groups": [
                        {
                            "properties": [
                                {"key": "email", "value": "tim@posthog.com", "type": "person", "operator": "exact"}
                            ],
                            "rollout_percentage": None,
                        }
                    ]
                },
            },
            context={"team_id": team_id, "request": create_request},
        )
        self.assertTrue(serialized_data.is_valid())
        serialized_data.save()

        # Should be enabled for everyone
        serialized_data = FeatureFlagSerializer(
            data={
                "name": "Alpha feature",
                "key": "default-flag",
                "filters": {"groups": [{"properties": [], "rollout_percentage": None}]},
            },
            context={"team_id": team_id, "request": create_request},
        )
        self.assertTrue(serialized_data.is_valid())
        serialized_data.save()

        with self.assertNumQueries(2):
            # 1 query to get person properties
            # 1 to set statement timeout
            all_flags, _, _, errors = get_all_feature_flags(team_id, "example_id")

            self.assertTrue(all_flags["property-flag"])
            self.assertTrue(all_flags["default-flag"])
            self.assertFalse(errors)

        # now db is down
        with snapshot_postgres_queries_context(self), connection.execute_wrapper(QueryTimeoutWrapper()):
            all_flags, _, _, errors = get_all_feature_flags(team_id, "example_id")

            self.assertTrue("property-flag" not in all_flags)
            self.assertTrue(all_flags["default-flag"])
            self.assertTrue(errors)

            # # now db is down, but decide was sent email parameter with correct email
            with self.assertNumQueries(0):
                all_flags, _, _, errors = get_all_feature_flags(
                    team_id, "random", property_value_overrides={"email": "tim@posthog.com"}
                )
                self.assertTrue(all_flags["property-flag"])
                self.assertTrue(all_flags["default-flag"])
                self.assertFalse(errors)

            # # now db is down, but decide was sent email parameter with different email
            with self.assertNumQueries(0):
                all_flags, _, _, errors = get_all_feature_flags(
                    team_id, "example_id", property_value_overrides={"email": "tom@posthog.com"}
                )
                self.assertFalse(all_flags["property-flag"])
                self.assertTrue(all_flags["default-flag"])
                self.assertFalse(errors)

    def test_feature_flags_v3_with_a_working_slow_db(self):
        self.organization = Organization.objects.create(name="test")
        self.team = Team.objects.create(organization=self.organization)
        self.user = User.objects.create_and_join(self.organization, "random@test.com", "password", "first_name")

        team_id = self.team.pk
        rf = RequestFactory()
        create_request = rf.post(f"api/projects/{self.team.pk}/feature_flags/", {"name": "xyz"})
        create_request.user = self.user

        Person.objects.create(team=self.team, distinct_ids=["example_id"], properties={"email": "tim@posthog.com"})

        serialized_data = FeatureFlagSerializer(
            data={
                "name": "Alpha feature",
                "key": "property-flag",
                "filters": {
                    "groups": [
                        {
                            "properties": [
                                {"key": "email", "value": "tim@posthog.com", "type": "person", "operator": "exact"}
                            ],
                            "rollout_percentage": None,
                        }
                    ]
                },
            },
            context={"team_id": team_id, "request": create_request},
        )
        self.assertTrue(serialized_data.is_valid())
        serialized_data.save()

        # Should be enabled for everyone
        serialized_data = FeatureFlagSerializer(
            data={
                "name": "Alpha feature",
                "key": "default-flag",
                "filters": {"groups": [{"properties": [], "rollout_percentage": None}]},
            },
            context={"team_id": team_id, "request": create_request},
        )
        self.assertTrue(serialized_data.is_valid())
        serialized_data.save()

        with self.assertNumQueries(2):
            # 1 query to get person properties
            # 1 query to set statement timeout
            all_flags, _, _, errors = get_all_feature_flags(team_id, "example_id")

            self.assertTrue(all_flags["property-flag"])
            self.assertTrue(all_flags["default-flag"])
            self.assertFalse(errors)

        # now db is slow and times out
        with snapshot_postgres_queries_context(self), connection.execute_wrapper(slow_query), patch(
            "posthog.models.feature_flag.flag_matching.FLAG_MATCHING_QUERY_TIMEOUT_MS", 500
        ):
            all_flags, _, _, errors = get_all_feature_flags(team_id, "example_id")

            self.assertTrue("property-flag" not in all_flags)
            self.assertTrue(all_flags["default-flag"])
            self.assertTrue(errors)

            # # now db is down, but decide was sent email parameter with correct email
            with self.assertNumQueries(0):
                all_flags, _, _, errors = get_all_feature_flags(
                    team_id, "random", property_value_overrides={"email": "tim@posthog.com"}
                )
                self.assertTrue(all_flags["property-flag"])
                self.assertTrue(all_flags["default-flag"])
                self.assertFalse(errors)

            # # now db is down, but decide was sent email parameter with different email
            with self.assertNumQueries(0):
                all_flags, _, _, errors = get_all_feature_flags(
                    team_id, "example_id", property_value_overrides={"email": "tom@posthog.com"}
                )
                self.assertFalse(all_flags["property-flag"])
                self.assertTrue(all_flags["default-flag"])
                self.assertFalse(errors)

    def test_feature_flags_v3_with_group_properties_and_slow_db(self):
        self.organization = Organization.objects.create(name="test")
        self.team = Team.objects.create(organization=self.organization)
        self.user = User.objects.create_and_join(self.organization, "randomXYZ@test.com", "password", "first_name")

        team_id = self.team.pk
        rf = RequestFactory()
        create_request = rf.post(f"api/projects/{self.team.pk}/feature_flags/", {"name": "xyz"})
        create_request.user = self.user

        GroupTypeMapping.objects.create(team=self.team, group_type="organization", group_type_index=0)

        create_group(team_id=self.team.pk, group_type_index=0, group_key=f"org:1", properties={"industry": f"finance"})

        serialized_data = FeatureFlagSerializer(
            data={
                "name": "Alpha feature",
                "key": "group-flag",
                "filters": {
                    "aggregation_group_type_index": 0,
                    "groups": [
                        {
                            "properties": [
                                {"key": "industry", "value": "finance", "type": "group", "group_type_index": 0}
                            ],
                            "rollout_percentage": None,
                        }
                    ],
                },
            },
            context={"team_id": team_id, "request": create_request},
        )
        self.assertTrue(serialized_data.is_valid())
        serialized_data.save()

        # Should be enabled for everyone, if groups are given
        serialized_data = FeatureFlagSerializer(
            data={
                "name": "Alpha feature",
                "key": "default-flag",
                "filters": {
                    "aggregation_group_type_index": 0,
                    "groups": [{"properties": [], "rollout_percentage": None}],
                },
            },
            context={"team_id": team_id, "request": create_request},
        )
        self.assertTrue(serialized_data.is_valid())
        serialized_data.save()

        with self.assertNumQueries(4):
            # one query to get group type mappings, another to get group properties
            # 2 queries to set statement timeout
            all_flags, _, _, errors = get_all_feature_flags(team_id, "example_id", groups={"organization": "org:1"})
            self.assertTrue(all_flags["group-flag"])
            self.assertTrue(all_flags["default-flag"])
            self.assertFalse(errors)

        # now db is slow
        with snapshot_postgres_queries_context(self), connection.execute_wrapper(slow_query), patch(
            "posthog.models.feature_flag.flag_matching.FLAG_MATCHING_QUERY_TIMEOUT_MS", 500
        ):
            all_flags, _, _, errors = get_all_feature_flags(team_id, "example_id", groups={"organization": "org:1"})

            self.assertTrue("group-flag" not in all_flags)
            # can't be true unless we cache group type mappings as well
            self.assertTrue("default-flag" not in all_flags)
            self.assertTrue(errors)

            # # now db is slow, but decide was sent correct group property overrides
            with self.assertNumQueries(2):
                all_flags, _, _, errors = get_all_feature_flags(
                    team_id,
                    "random",
                    groups={"organization": "org:1"},
                    group_property_value_overrides={"organization": {"industry": "finance"}},
                )
                self.assertTrue("group-flag" not in all_flags)
                # can't be true unless we cache group type mappings as well
                self.assertTrue("default-flag" not in all_flags)
                self.assertTrue(errors)

            # # now db is down, but decide was sent different group property overrides
            with self.assertNumQueries(2):
                all_flags, _, _, errors = get_all_feature_flags(
                    team_id,
                    "exam",
                    groups={"organization": "org:1"},
                    group_property_value_overrides={"organization": {"industry": "finna"}},
                )
                self.assertTrue("group-flag" not in all_flags)
                # can't be true unless we cache group type mappings as well
                self.assertTrue("default-flag" not in all_flags)
                self.assertTrue(errors)

    def test_feature_flags_v3_with_experience_continuity_working_slow_db(self):
        self.organization = Organization.objects.create(name="test")
        self.team = Team.objects.create(organization=self.organization)
        self.user = User.objects.create_and_join(self.organization, "random12@test.com", "password", "first_name")

        team_id = self.team.pk
        rf = RequestFactory()
        create_request = rf.post(f"api/projects/{self.team.pk}/feature_flags/", {"name": "xyz"})
        create_request.user = self.user

        Person.objects.create(
            team=self.team, distinct_ids=["example_id", "random"], properties={"email": "tim@posthog.com"}
        )

        serialized_data = FeatureFlagSerializer(
            data={
                "name": "Alpha feature",
                "key": "property-flag",
                "filters": {
                    "groups": [
                        {
                            "properties": [
                                {"key": "email", "value": "tim@posthog.com", "type": "person", "operator": "exact"}
                            ],
                            "rollout_percentage": 91,
                        }
                    ],
                },
                "ensure_experience_continuity": True,
            },
            context={"team_id": team_id, "request": create_request},
        )
        self.assertTrue(serialized_data.is_valid())
        serialized_data.save()

        # Should be enabled for everyone
        serialized_data = FeatureFlagSerializer(
            data={
                "name": "Alpha feature",
                "key": "default-flag",
                "filters": {"groups": [{"properties": [], "rollout_percentage": None}]},
            },
            context={"team_id": team_id, "request": create_request},
        )
        self.assertTrue(serialized_data.is_valid())
        serialized_data.save()

        with snapshot_postgres_queries_context(self), self.assertNumQueries(10):
            all_flags, _, _, errors = get_all_feature_flags(team_id, "example_id", hash_key_override="random")

            self.assertTrue(all_flags["property-flag"])
            self.assertTrue(all_flags["default-flag"])
            self.assertFalse(errors)

        # db is slow and times out
        with snapshot_postgres_queries_context(self), connection.execute_wrapper(slow_query), patch(
            "posthog.models.feature_flag.flag_matching.FLAG_MATCHING_QUERY_TIMEOUT_MS", 500
        ):
            all_flags, _, _, errors = get_all_feature_flags(team_id, "example_id", hash_key_override="random")

            self.assertTrue("property-flag" not in all_flags)
            self.assertTrue(all_flags["default-flag"])
            self.assertTrue(errors)

            # # now db is slow, but decide was sent email parameter with correct email
            # still need to get hash key override from db, so should time out
            with self.assertNumQueries(2):
                all_flags, _, _, errors = get_all_feature_flags(
                    team_id, "random", property_value_overrides={"email": "tim@posthog.com"}
                )
                self.assertTrue("property-flag" not in all_flags)
                self.assertTrue(all_flags["default-flag"])
                self.assertTrue(errors)
