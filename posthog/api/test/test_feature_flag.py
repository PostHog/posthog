import datetime
import json
from typing import Optional
from unittest.mock import call, patch

from django.core.cache import cache
from django.db import connection
from django.db.utils import OperationalError
from django.test import TransactionTestCase
from django.test.client import RequestFactory
from django.utils import timezone
from freezegun.api import freeze_time
from rest_framework import status

from posthog import redis
from posthog.api.cohort import get_cohort_actors_for_feature_flag
from posthog.api.feature_flag import FeatureFlagSerializer
from posthog.constants import AvailableFeature
from posthog.models import FeatureFlag, GroupTypeMapping, User
from posthog.models.cohort import Cohort
from posthog.models.dashboard import Dashboard
from posthog.models.early_access_feature import EarlyAccessFeature
from posthog.models.feature_flag import (
    FeatureFlagDashboards,
    get_all_feature_flags,
    get_feature_flags_for_team_in_cache,
)
from posthog.models.feature_flag.feature_flag import FeatureFlagHashKeyOverride
from posthog.models.group.util import create_group
from posthog.models.organization import Organization
from posthog.models.person import Person
from posthog.models.personal_api_key import PersonalAPIKey, hash_key_value
from posthog.models.team.team import Team
from posthog.models.utils import generate_random_token_personal
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    FuzzyInt,
    QueryMatchingTest,
    _create_person,
    flush_persons_and_events,
    snapshot_clickhouse_queries,
    snapshot_postgres_queries_context,
)
from posthog.test.db_context_capturing import capture_db_queries


class TestFeatureFlag(APIBaseTest, ClickhouseTestMixin):
    feature_flag: FeatureFlag = None  # type: ignore

    maxDiff = None

    def setUp(self):
        cache.clear()

        # delete all keys in redis
        r = redis.get_client()
        for key in r.scan_iter("*"):
            r.delete(key)
        return super().setUp()

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.feature_flag = FeatureFlag.objects.create(team=cls.team, created_by=cls.user, key="red_button")

    def test_cant_create_flag_with_more_than_max_values(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags",
            {
                "name": "Beta feature",
                "key": "beta-x",
                "filters": {
                    "groups": [
                        {
                            "rollout_percentage": 65,
                            "properties": [
                                {
                                    "key": "email",
                                    "type": "person",
                                    "value": [
                                        "1@gmail.com",
                                        "2@gmail.com",
                                        "3@gmail.com",
                                        "4@gmail.com",
                                        "5@gmail.com",
                                        "6@gmail.com",
                                        "7@gmail.com",
                                        "8@gmail.com",
                                        "9@gmail.com",
                                        "10@gmail.com",
                                        "11@gmail.com",
                                        "12@gmail.com",
                                    ],
                                    "operator": "exact",
                                }
                            ],
                        }
                    ]
                },
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            {
                "type": "validation_error",
                "code": "invalid_input",
                "detail": "Property group expressions of type email cannot contain more than 10 values.",
                "attr": "filters",
            },
        )

    def test_cant_create_flag_with_duplicate_key(self):
        count = FeatureFlag.objects.count()
        # Make sure the endpoint works with and without the trailing slash
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags",
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
        self.assertEqual(FeatureFlag.objects.count(), count)

    def test_cant_create_flag_with_invalid_filters(self):
        count = FeatureFlag.objects.count()

        invalid_operators = ["icontains", "regex", "not_icontains", "not_regex", "lt", "gt", "lte", "gte"]

        for operator in invalid_operators:
            response = self.client.post(
                f"/api/projects/{self.team.id}/feature_flags",
                {
                    "name": "Beta feature",
                    "key": "beta-x",
                    "filters": {
                        "groups": [
                            {
                                "rollout_percentage": 65,
                                "properties": [
                                    {
                                        "key": "email",
                                        "type": "person",
                                        "value": ["@posthog.com"],
                                        "operator": operator,
                                    }
                                ],
                            }
                        ]
                    },
                },
            )
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertEqual(
                response.json(),
                {
                    "type": "validation_error",
                    "code": "invalid_value",
                    "detail": f"Invalid value for operator {operator}: ['@posthog.com']",
                    "attr": "filters",
                },
            )

        self.assertEqual(FeatureFlag.objects.count(), count)

        # Test that a string value is still acceptable
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags",
            {
                "name": "Beta feature",
                "key": "beta-x",
                "filters": {
                    "groups": [
                        {
                            "rollout_percentage": 65,
                            "properties": [
                                {
                                    "key": "email",
                                    "type": "person",
                                    "value": '["@posthog.com"]',  # fine as long as a string
                                    "operator": "not_regex",
                                }
                            ],
                        }
                    ]
                },
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_cant_update_flag_with_duplicate_key(self):
        another_feature_flag = FeatureFlag.objects.create(
            team=self.team,
            rollout_percentage=50,
            name="some feature",
            key="some-feature",
            created_by=self.user,
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
            data={
                "name": "Beta feature",
                "key": "beta-feature",
                "filters": {"groups": [{"rollout_percentage": 65}]},
            },
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
                                {
                                    "key": "email",
                                    "type": "person",
                                    "value": "@posthog.com",
                                    "operator": "icontains",
                                }
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
                "filters": {
                    "aggregation_group_type_index": 0,
                    "groups": [{"rollout_percentage": 65}],
                },
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
            {
                "name": "Alpha feature",
                "key": "alpha-feature",
                "filters": {"groups": [{"rollout_percentage": 50}]},
            },
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
                        "type": None,
                        "name": "alpha-feature",
                        "short_id": None,
                    },
                }
            ],
        )

    @patch("posthog.api.feature_flag.report_user_action")
    def test_create_minimal_feature_flag(self, mock_capture):
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {"key": "omega-feature"},
            format="json",
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
                            {
                                "key": "first-variant",
                                "name": "First Variant",
                                "rollout_percentage": 50,
                            },
                            {
                                "key": "second-variant",
                                "name": "Second Variant",
                                "rollout_percentage": 25,
                            },
                            {
                                "key": "third-variant",
                                "name": "Third Variant",
                                "rollout_percentage": 25,
                            },
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
                            {
                                "key": "first-variant",
                                "name": "First Variant",
                                "rollout_percentage": 50,
                            },
                            {
                                "key": "second-variant",
                                "name": "Second Variant",
                                "rollout_percentage": 25,
                            },
                            {
                                "key": "third-variant",
                                "name": "Third Variant",
                                "rollout_percentage": 0,
                            },
                        ]
                    },
                },
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json().get("type"), "validation_error")
        self.assertEqual(
            response.json().get("detail"),
            "Invalid variant definitions: Variant rollout percentages must sum to 100.",
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
                            {
                                "key": "first-variant",
                                "name": "First Variant",
                                "rollout_percentage": 50,
                            },
                            {
                                "key": "second-variant",
                                "name": "Second Variant",
                                "rollout_percentage": 25,
                            },
                            {
                                "key": "third-variant",
                                "name": "Third Variant",
                                "rollout_percentage": 50,
                            },
                        ]
                    },
                },
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json().get("type"), "validation_error")
        self.assertEqual(
            response.json().get("detail"),
            "Invalid variant definitions: Variant rollout percentages must sum to 100.",
        )

    def test_cant_create_feature_flag_without_key(self):
        count = FeatureFlag.objects.count()
        response = self.client.post(f"/api/projects/{self.team.id}/feature_flags/", format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            {
                "type": "validation_error",
                "code": "required",
                "detail": "This field is required.",
                "attr": "key",
            },
        )
        self.assertEqual(FeatureFlag.objects.count(), count)

    def test_cant_create_multivariate_feature_flag_with_invalid_variant_overrides(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {
                "name": "Multivariate feature",
                "key": "multivariate-feature",
                "filters": {
                    "groups": [
                        {
                            "properties": [],
                            "rollout_percentage": None,
                            "variant": "unknown-variant",
                        }
                    ],
                    "multivariate": {
                        "variants": [
                            {
                                "key": "first-variant",
                                "name": "First Variant",
                                "rollout_percentage": 50,
                            },
                            {
                                "key": "second-variant",
                                "name": "Second Variant",
                                "rollout_percentage": 25,
                            },
                            {
                                "key": "third-variant",
                                "name": "Third Variant",
                                "rollout_percentage": 25,
                            },
                        ]
                    },
                },
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json().get("type"), "validation_error")
        self.assertEqual(
            response.json().get("detail"),
            "Filters are not valid (variant override does not exist)",
        )

    def test_cant_update_multivariate_feature_flag_with_invalid_variant_overrides(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {
                "name": "Multivariate feature",
                "key": "multivariate-feature",
                "filters": {
                    "groups": [
                        {
                            "properties": [],
                            "rollout_percentage": None,
                            "variant": "second-variant",
                        }
                    ],
                    "multivariate": {
                        "variants": [
                            {
                                "key": "first-variant",
                                "name": "First Variant",
                                "rollout_percentage": 50,
                            },
                            {
                                "key": "second-variant",
                                "name": "Second Variant",
                                "rollout_percentage": 25,
                            },
                            {
                                "key": "third-variant",
                                "name": "Third Variant",
                                "rollout_percentage": 25,
                            },
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
                    "groups": [
                        {
                            "properties": [],
                            "rollout_percentage": None,
                            "variant": "unknown-variant",
                        }
                    ],
                    "multivariate": {
                        "variants": [
                            {
                                "key": "first-variant",
                                "name": "First Variant",
                                "rollout_percentage": 50,
                            },
                            {
                                "key": "second-variant",
                                "name": "Second Variant",
                                "rollout_percentage": 25,
                            },
                            {
                                "key": "third-variant",
                                "name": "Third Variant",
                                "rollout_percentage": 0,
                            },
                        ]
                    },
                },
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json().get("type"), "validation_error")
        self.assertEqual(
            response.json().get("detail"),
            "Filters are not valid (variant override does not exist)",
        )

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
                                    {
                                        "key": "email",
                                        "type": "person",
                                        "value": "@posthog.com",
                                        "operator": "icontains",
                                    }
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
                    "user": {
                        "first_name": self.user.first_name,
                        "email": self.user.email,
                    },
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
                        "type": None,
                        "name": "a-feature-flag-that-is-updated",
                        "short_id": None,
                    },
                },
                {
                    "user": {
                        "first_name": self.user.first_name,
                        "email": self.user.email,
                    },
                    "activity": "created",
                    "created_at": "2021-08-25T22:09:14.252000Z",
                    "scope": "FeatureFlag",
                    "item_id": str(flag_id),
                    "detail": {
                        "changes": None,
                        "trigger": None,
                        "type": None,
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
                    "user": {
                        "first_name": new_user.first_name,
                        "email": new_user.email,
                    },
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
                        "type": None,
                        "name": "feature_with_activity",
                        "short_id": None,
                    },
                },
                {
                    "user": {
                        "first_name": new_user.first_name,
                        "email": new_user.email,
                    },
                    "activity": "created",
                    "created_at": "2021-08-25T22:09:14.252000Z",
                    "scope": "FeatureFlag",
                    "item_id": str(flag_id),
                    "detail": {
                        "changes": None,
                        "trigger": None,
                        "type": None,
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
                f"/api/projects/{self.team.id}/feature_flags/",
                {"name": "a second feature flag", "key": "flag-two"},
            )

            self.assertEqual(second_create_response.status_code, status.HTTP_201_CREATED)
            second_flag_id = second_create_response.json()["id"]

        self.assert_feature_flag_activity(
            flag_id=None,
            expected=[
                {
                    "user": {
                        "first_name": new_user.first_name,
                        "email": new_user.email,
                    },
                    "activity": "created",
                    "created_at": "2021-08-25T22:29:14.252000Z",
                    "scope": "FeatureFlag",
                    "item_id": str(second_flag_id),
                    "detail": {
                        "changes": None,
                        "trigger": None,
                        "type": None,
                        "name": "flag-two",
                        "short_id": None,
                    },
                },
                {
                    "user": {
                        "first_name": new_user.first_name,
                        "email": new_user.email,
                    },
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
                        "type": None,
                        "name": "feature_with_activity",
                        "short_id": None,
                    },
                },
                {
                    "user": {
                        "first_name": new_user.first_name,
                        "email": new_user.email,
                    },
                    "activity": "created",
                    "created_at": "2021-08-25T22:09:14.252000Z",
                    "scope": "FeatureFlag",
                    "item_id": str(flag_id),
                    "detail": {
                        "changes": None,
                        "trigger": None,
                        "type": None,
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
            flag_id=team_one_flag_one,
            team_id=org_one_team.id,
            expected_status=status.HTTP_200_OK,
        )
        self._get_feature_flag_activity(
            flag_id=team_one_flag_two,
            team_id=org_one_team.id,
            expected_status=status.HTTP_200_OK,
        )
        self._get_feature_flag_activity(
            flag_id=team_two_flag_one,
            team_id=org_one_team.id,
            expected_status=status.HTTP_404_NOT_FOUND,
        )
        self._get_feature_flag_activity(
            flag_id=team_two_flag_two,
            team_id=org_one_team.id,
            expected_status=status.HTTP_404_NOT_FOUND,
        )

        # user in org 2 gets activity
        self.client.force_login(org_two_user)
        self._get_feature_flag_activity(
            flag_id=team_one_flag_two,
            team_id=org_two_team.id,
            expected_status=status.HTTP_404_NOT_FOUND,
        )
        self._get_feature_flag_activity(
            flag_id=team_one_flag_two,
            team_id=org_two_team.id,
            expected_status=status.HTTP_404_NOT_FOUND,
        )
        self._get_feature_flag_activity(
            flag_id=team_two_flag_one,
            team_id=org_two_team.id,
            expected_status=status.HTTP_200_OK,
        )
        self._get_feature_flag_activity(
            flag_id=team_two_flag_two,
            team_id=org_two_team.id,
            expected_status=status.HTTP_200_OK,
        )

    def test_paging_all_feature_flag_activity(self):
        for x in range(15):
            create_response = self.client.post(
                f"/api/projects/{self.team.id}/feature_flags/",
                {"name": f"feature flag {x}", "key": f"{x}"},
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
            [log_item["detail"]["name"] for log_item in second_page_json["results"]],
            ["4", "3", "2", "1", "0"],
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
                f"/api/projects/{self.team.id}/feature_flags/{flag_id}",
                {"key": str(x)},
                format="json",
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
            f"/api/projects/{self.team.id}/feature_flags/",
            {"name": "Alpha feature", "key": "alpha-feature"},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        instance = FeatureFlag.objects.get(id=response.json()["id"])
        self.assertEqual(instance.key, "alpha-feature")

    def test_updating_a_feature_flag_with_same_team_and_key_of_a_deleted_one(self):
        FeatureFlag.objects.create(team=self.team, created_by=self.user, key="alpha-feature", deleted=True)

        instance = FeatureFlag.objects.create(team=self.team, created_by=self.user, key="beta-feature")

        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{instance.pk}",
            {"key": "alpha-feature"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        instance.refresh_from_db()
        self.assertEqual(instance.key, "alpha-feature")

    def test_my_flags_is_not_nplus1(self) -> None:
        self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            data={
                "name": f"flag",
                "key": f"flag",
                "filters": {"groups": [{"rollout_percentage": 5}]},
            },
            format="json",
        ).json()

        with self.assertNumQueries(FuzzyInt(7, 8)):
            response = self.client.get(f"/api/projects/{self.team.id}/feature_flags/my_flags")
            self.assertEqual(response.status_code, status.HTTP_200_OK)

        for i in range(1, 4):
            self.client.post(
                f"/api/projects/{self.team.id}/feature_flags/",
                data={
                    "name": f"flag",
                    "key": f"flag_{i}",
                    "filters": {"groups": [{"rollout_percentage": 5}]},
                },
                format="json",
            ).json()

        with self.assertNumQueries(FuzzyInt(7, 8)):
            response = self.client.get(f"/api/projects/{self.team.id}/feature_flags/my_flags")
            self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_getting_flags_is_not_nplus1(self) -> None:
        self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            data={
                "name": f"flag",
                "key": f"flag_0",
                "filters": {"groups": [{"rollout_percentage": 5}]},
            },
            format="json",
        ).json()

        with self.assertNumQueries(FuzzyInt(13, 14)):
            response = self.client.get(f"/api/projects/{self.team.id}/feature_flags")
            self.assertEqual(response.status_code, status.HTTP_200_OK)

        for i in range(1, 5):
            self.client.post(
                f"/api/projects/{self.team.id}/feature_flags/",
                data={
                    "name": f"flag",
                    "key": f"flag_{i}",
                    "filters": {"groups": [{"rollout_percentage": 5}]},
                },
                format="json",
            ).json()

        with self.assertNumQueries(FuzzyInt(13, 14)):
            response = self.client.get(f"/api/projects/{self.team.id}/feature_flags")
            self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_getting_flags_with_no_creator(self) -> None:
        FeatureFlag.objects.all().delete()

        self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            data={
                "name": f"flag",
                "key": f"flag_0",
                "filters": {"groups": [{"rollout_percentage": 5}]},
            },
            format="json",
        ).json()

        FeatureFlag.objects.create(
            created_by=None,
            team=self.team,
            key="flag_role_access",
            name="Flag role access",
        )

        with self.assertNumQueries(FuzzyInt(13, 14)):
            response = self.client.get(f"/api/projects/{self.team.id}/feature_flags")
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(len(response.json()["results"]), 2)
            sorted_results = sorted(response.json()["results"], key=lambda x: x["key"])
            self.assertEqual(sorted_results[1]["created_by"], None)
            self.assertEqual(sorted_results[1]["key"], "flag_role_access")

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
                            {
                                "key": "first-variant",
                                "name": "First Variant",
                                "rollout_percentage": 50,
                            },
                            {
                                "key": "second-variant",
                                "name": "Second Variant",
                                "rollout_percentage": 25,
                            },
                            {
                                "key": "third-variant",
                                "name": "Third Variant",
                                "rollout_percentage": 25,
                            },
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
                "filters": {
                    "aggregation_group_type_index": 0,
                    "groups": [{"rollout_percentage": 100}],
                },
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
            f"/api/projects/{self.team.id}/feature_flags/my_flags",
            data={"groups": json.dumps({"organization": "7"})},
        )
        groups_flag = response.json()[0]
        self.assertEqual(groups_flag["feature_flag"]["key"], "groups-flag")
        self.assertEqual(groups_flag["value"], True)

    @freeze_time("2021-08-25T22:09:14.252Z")
    @patch("posthog.api.feature_flag.report_user_action")
    def test_create_feature_flag_usage_dashboard(self, mock_capture):
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {
                "name": "Alpha feature",
                "key": "alpha-feature",
                "filters": {"groups": [{"rollout_percentage": 50}]},
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        flag_id = response.json()["id"]
        instance = FeatureFlag.objects.get(id=flag_id)
        self.assertEqual(instance.key, "alpha-feature")

        dashboard = instance.usage_dashboard
        tiles = sorted(dashboard.tiles.all(), key=lambda x: x.insight.name)

        self.assertEqual(dashboard.name, "Generated Dashboard: alpha-feature Usage")
        self.assertEqual(
            dashboard.description,
            "This dashboard was generated by the feature flag with key (alpha-feature)",
        )
        self.assertEqual(dashboard.filters, {"date_from": "-30d"})
        self.assertEqual(len(tiles), 2)
        self.assertEqual(tiles[0].insight.name, "Feature Flag Called Total Volume")
        self.assertEqual(
            tiles[0].insight.filters,
            {
                "events": [
                    {
                        "id": "$feature_flag_called",
                        "name": "$feature_flag_called",
                        "type": "events",
                    }
                ],
                "display": "ActionsLineGraph",
                "insight": "TRENDS",
                "interval": "day",
                "breakdown": "$feature_flag_response",
                "date_from": "-30d",
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "AND",
                            "values": [
                                {
                                    "key": "$feature_flag",
                                    "type": "event",
                                    "value": "alpha-feature",
                                }
                            ],
                        }
                    ],
                },
                "breakdown_type": "event",
                "filter_test_accounts": False,
            },
        )
        self.assertEqual(tiles[1].insight.name, "Feature Flag calls made by unique users per variant")
        self.assertEqual(
            tiles[1].insight.filters,
            {
                "events": [
                    {
                        "id": "$feature_flag_called",
                        "math": "dau",
                        "name": "$feature_flag_called",
                        "type": "events",
                    }
                ],
                "display": "ActionsTable",
                "insight": "TRENDS",
                "interval": "day",
                "breakdown": "$feature_flag_response",
                "date_from": "-30d",
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "AND",
                            "values": [
                                {
                                    "key": "$feature_flag",
                                    "type": "event",
                                    "value": "alpha-feature",
                                }
                            ],
                        }
                    ],
                },
                "breakdown_type": "event",
                "filter_test_accounts": False,
            },
        )

        # now enable enriched analytics
        instance.has_enriched_analytics = True
        instance.save()

        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/{flag_id}/enrich_usage_dashboard",
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        instance.refresh_from_db()

        dashboard = instance.usage_dashboard
        tiles = sorted(dashboard.tiles.all(), key=lambda x: x.insight.name)

        self.assertEqual(dashboard.name, "Generated Dashboard: alpha-feature Usage")
        self.assertEqual(
            dashboard.description,
            "This dashboard was generated by the feature flag with key (alpha-feature)",
        )
        self.assertEqual(dashboard.filters, {"date_from": "-30d"})
        self.assertEqual(len(tiles), 4)
        self.assertEqual(tiles[0].insight.name, "Feature Flag Called Total Volume")
        self.assertEqual(
            tiles[0].insight.filters,
            {
                "events": [
                    {
                        "id": "$feature_flag_called",
                        "name": "$feature_flag_called",
                        "type": "events",
                    }
                ],
                "display": "ActionsLineGraph",
                "insight": "TRENDS",
                "interval": "day",
                "breakdown": "$feature_flag_response",
                "date_from": "-30d",
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "AND",
                            "values": [
                                {
                                    "key": "$feature_flag",
                                    "type": "event",
                                    "value": "alpha-feature",
                                }
                            ],
                        }
                    ],
                },
                "breakdown_type": "event",
                "filter_test_accounts": False,
            },
        )
        self.assertEqual(tiles[1].insight.name, "Feature Flag calls made by unique users per variant")
        self.assertEqual(
            tiles[1].insight.filters,
            {
                "events": [
                    {
                        "id": "$feature_flag_called",
                        "math": "dau",
                        "name": "$feature_flag_called",
                        "type": "events",
                    }
                ],
                "display": "ActionsTable",
                "insight": "TRENDS",
                "interval": "day",
                "breakdown": "$feature_flag_response",
                "date_from": "-30d",
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "AND",
                            "values": [
                                {
                                    "key": "$feature_flag",
                                    "type": "event",
                                    "value": "alpha-feature",
                                }
                            ],
                        }
                    ],
                },
                "breakdown_type": "event",
                "filter_test_accounts": False,
            },
        )

        # enriched insights
        self.assertEqual(tiles[2].insight.name, "Feature Interaction Total Volume")
        self.assertEqual(
            tiles[2].insight.filters,
            {
                "events": [
                    {
                        "id": "$feature_interaction",
                        "name": "Feature Interaction - Total",
                        "type": "events",
                    },
                    {
                        "id": "$feature_interaction",
                        "math": "dau",
                        "name": "Feature Interaction - Unique users",
                        "type": "events",
                    },
                ],
                "display": "ActionsLineGraph",
                "insight": "TRENDS",
                "interval": "day",
                "date_from": "-30d",
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "AND",
                            "values": [
                                {
                                    "key": "feature_flag",
                                    "type": "event",
                                    "value": "alpha-feature",
                                }
                            ],
                        }
                    ],
                },
                "filter_test_accounts": False,
            },
        )
        self.assertEqual(tiles[3].insight.name, "Feature Viewed Total Volume")
        self.assertEqual(
            tiles[3].insight.filters,
            {
                "events": [
                    {
                        "id": "$feature_view",
                        "name": "Feature View - Total",
                        "type": "events",
                    },
                    {
                        "id": "$feature_view",
                        "math": "dau",
                        "name": "Feature View - Unique users",
                        "type": "events",
                    },
                ],
                "display": "ActionsLineGraph",
                "insight": "TRENDS",
                "interval": "day",
                "date_from": "-30d",
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "AND",
                            "values": [
                                {
                                    "key": "feature_flag",
                                    "type": "event",
                                    "value": "alpha-feature",
                                }
                            ],
                        }
                    ],
                },
                "filter_test_accounts": False,
            },
        )

    @freeze_time("2021-08-25T22:09:14.252Z")
    @patch("posthog.api.feature_flag.report_user_action")
    def test_dashboard_enrichment_fails_if_already_enriched(self, mock_capture):
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {
                "name": "Alpha feature",
                "key": "alpha-feature",
                "filters": {"groups": [{"rollout_percentage": 50}]},
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        flag_id = response.json()["id"]
        instance = FeatureFlag.objects.get(id=flag_id)
        self.assertEqual(instance.key, "alpha-feature")

        # now enable enriched analytics
        instance.has_enriched_analytics = True
        instance.save()

        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/{flag_id}/enrich_usage_dashboard",
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # now try enriching again
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/{flag_id}/enrich_usage_dashboard",
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            {"error": "Usage dashboard already has enriched data", "success": False},
        )

    @patch("posthog.api.feature_flag.report_user_action")
    def test_dashboard_enrichment_fails_if_no_enriched_data(self, mock_capture):
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {
                "name": "Alpha feature",
                "key": "alpha-feature",
                "filters": {"groups": [{"rollout_percentage": 50}]},
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        flag_id = response.json()["id"]
        instance = FeatureFlag.objects.get(id=flag_id)
        self.assertEqual(instance.key, "alpha-feature")

        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/{flag_id}/enrich_usage_dashboard",
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            {
                "error": "No enriched analytics available for this feature flag",
                "success": False,
            },
        )

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
                            {
                                "key": "first-variant",
                                "name": "First Variant",
                                "rollout_percentage": 50,
                            },
                            {
                                "key": "second-variant",
                                "name": "Second Variant",
                                "rollout_percentage": 25,
                            },
                            {
                                "key": "third-variant",
                                "name": "Third Variant",
                                "rollout_percentage": 25,
                            },
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
                "filters": {
                    "aggregation_group_type_index": 0,
                    "groups": [{"rollout_percentage": 21}],
                },
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
        self.assertEqual(len(response_data["flags"]), 3)  # inactive flags not sent

        sorted_flags = sorted(response_data["flags"], key=lambda x: x["key"])

        self.assertDictContainsSubset(
            {
                "name": "Alpha feature",
                "key": "alpha-feature",
                "filters": {
                    "groups": [{"rollout_percentage": 20}],
                    "multivariate": {
                        "variants": [
                            {
                                "key": "first-variant",
                                "name": "First Variant",
                                "rollout_percentage": 50,
                            },
                            {
                                "key": "second-variant",
                                "name": "Second Variant",
                                "rollout_percentage": 25,
                            },
                            {
                                "key": "third-variant",
                                "name": "Third Variant",
                                "rollout_percentage": 25,
                            },
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
                        {
                            "properties": [{"key": "beta-property", "value": "beta-value"}],
                            "rollout_percentage": 51,
                        }
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
                "filters": {
                    "groups": [{"rollout_percentage": 21}],
                    "aggregation_group_type_index": 0,
                },
                "deleted": False,
                "active": True,
                "ensure_experience_continuity": False,
            },
            sorted_flags[2],
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
                                {
                                    "key": "$some_prop",
                                    "value": "nomatchihope",
                                    "type": "person",
                                },
                                {
                                    "key": "$some_prop2",
                                    "value": "nomatchihope2",
                                    "type": "person",
                                },
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
                            "properties": [
                                {
                                    "key": "id",
                                    "type": "cohort",
                                    "value": cohort_valid_for_ff.pk,
                                }
                            ],
                        }
                    ],
                    "multivariate": {
                        "variants": [
                            {
                                "key": "first-variant",
                                "name": "First Variant",
                                "rollout_percentage": 50,
                            },
                            {
                                "key": "second-variant",
                                "name": "Second Variant",
                                "rollout_percentage": 25,
                            },
                            {
                                "key": "third-variant",
                                "name": "Third Variant",
                                "rollout_percentage": 25,
                            },
                        ]
                    },
                },
            },
            format="json",
        )

        personal_api_key = generate_random_token_personal()
        PersonalAPIKey.objects.create(label="X", user=self.user, secure_value=hash_key_value(personal_api_key))

        self.client.logout()

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
                            "properties": [
                                {
                                    "key": "$some_prop",
                                    "type": "person",
                                    "value": "nomatchihope",
                                }
                            ],
                            "rollout_percentage": 20,
                        },
                        {
                            "properties": [
                                {
                                    "key": "$some_prop2",
                                    "type": "person",
                                    "value": "nomatchihope2",
                                }
                            ],
                            "rollout_percentage": 20,
                        },
                    ],
                    "multivariate": {
                        "variants": [
                            {
                                "key": "first-variant",
                                "name": "First Variant",
                                "rollout_percentage": 50,
                            },
                            {
                                "key": "second-variant",
                                "name": "Second Variant",
                                "rollout_percentage": 25,
                            },
                            {
                                "key": "third-variant",
                                "name": "Third Variant",
                                "rollout_percentage": 25,
                            },
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
    def test_local_evaluation_for_invalid_cohorts(self, mock_capture):
        FeatureFlag.objects.all().delete()

        self.team.app_urls = ["https://example.com"]
        self.team.save()

        other_team = Team.objects.create(
            organization=self.organization,
            api_token="bazinga_new",
            name="New Team",
        )

        personal_api_key = generate_random_token_personal()
        PersonalAPIKey.objects.create(label="X", user=self.user, secure_value=hash_key_value(personal_api_key))

        deleted_cohort = Cohort.objects.create(
            team=self.team,
            groups=[
                {
                    "properties": [
                        {
                            "key": "$some_prop_1",
                            "value": "something_1",
                            "type": "person",
                        }
                    ]
                },
            ],
            name="cohort1",
            deleted=True,
        )

        cohort_from_other_team = Cohort.objects.create(
            team=other_team,
            groups=[
                {
                    "properties": [
                        {
                            "key": "$some_prop_1",
                            "value": "something_1",
                            "type": "person",
                        }
                    ]
                },
            ],
            name="cohort1",
        )

        cohort_with_nested_invalid = Cohort.objects.create(
            team=self.team,
            groups=[
                {
                    "properties": [
                        {
                            "key": "$some_prop_1",
                            "value": "something_1",
                            "type": "person",
                        },
                        {
                            "key": "id",
                            "value": 99999,
                            "type": "cohort",
                        },
                        {
                            "key": "id",
                            "value": deleted_cohort.pk,
                            "type": "cohort",
                        },
                        {
                            "key": "id",
                            "value": cohort_from_other_team.pk,
                            "type": "cohort",
                        },
                    ]
                },
            ],
            name="cohort1",
        )

        cohort_valid = Cohort.objects.create(
            team=self.team,
            groups=[
                {
                    "properties": [
                        {
                            "key": "$some_prop_1",
                            "value": "something_1",
                            "type": "person",
                        },
                    ]
                },
            ],
            name="cohort1",
        )

        FeatureFlag.objects.create(
            team=self.team,
            filters={"groups": [{"properties": [{"key": "id", "value": 99999, "type": "cohort"}]}]},
            name="This is a cohort-based flag",
            key="cohort-flag",
            created_by=self.user,
        )
        FeatureFlag.objects.create(
            team=self.team,
            filters={
                "groups": [{"properties": [{"key": "id", "value": cohort_with_nested_invalid.pk, "type": "cohort"}]}]
            },
            name="This is a cohort-based flag",
            key="cohort-flag-2",
            created_by=self.user,
        )
        FeatureFlag.objects.create(
            team=self.team,
            filters={"groups": [{"properties": [{"key": "id", "value": cohort_from_other_team.pk, "type": "cohort"}]}]},
            name="This is a cohort-based flag",
            key="cohort-flag-3",
            created_by=self.user,
        )
        FeatureFlag.objects.create(
            team=self.team,
            filters={
                "groups": [
                    {"properties": [{"key": "id", "value": cohort_valid.pk, "type": "cohort"}]},
                    {"properties": [{"key": "id", "value": cohort_with_nested_invalid.pk, "type": "cohort"}]},
                    {"properties": [{"key": "id", "value": 99999, "type": "cohort"}]},
                    {"properties": [{"key": "id", "value": deleted_cohort.pk, "type": "cohort"}]},
                ]
            },
            name="This is a cohort-based flag",
            key="cohort-flag-4",
            created_by=self.user,
        )
        self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {
                "name": "Alpha feature",
                "key": "alpha-feature",
                "filters": {
                    "groups": [
                        {
                            "rollout_percentage": 100,
                            "properties": [],
                        }
                    ],
                },
            },
            format="json",
        )

        self.client.logout()

        with self.assertNumQueries(14):
            # E  1. SAVEPOINT
            # E  2. SELECT "posthog_personalapikey"."id"
            # E  3. RELEASE SAVEPOINT
            # E  4. UPDATE "posthog_personalapikey" SET "last_used_at" = '2024-01-31T13:01:37.394080+00:00'
            # E  5. SELECT "posthog_team"."id", "posthog_team"."uuid"
            # E  6. SELECT "posthog_organizationmembership"."id"
            # E  7. SELECT "ee_accesscontrol"."id"
            # E  8. SELECT "posthog_organizationmembership"."id", "posthog_organizationmembership"."organization_id"
            # E  9. SELECT "posthog_cohort"."id"  -- all cohorts
            # E  10. SELECT "posthog_featureflag"."id", "posthog_featureflag"."key", -- all flags
            # E  11. SELECT "posthog_cohort". id = 99999
            # E  12. SELECT "posthog_cohort". id = deleted cohort
            # E  13. SELECT "posthog_cohort". id = cohort from other team
            # E  14. SELECT "posthog_grouptypemapping"."id", -- group type mapping

            response = self.client.get(
                f"/api/feature_flag/local_evaluation?token={self.team.api_token}&send_cohorts",
                HTTP_AUTHORIZATION=f"Bearer {personal_api_key}",
            )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        self.assertTrue("flags" in response_data and "group_type_mapping" in response_data)
        self.assertEqual(len(response_data["flags"]), 5)
        self.assertEqual(len(response_data["cohorts"]), 2)
        assert str(cohort_valid.pk) in response_data["cohorts"]
        assert str(cohort_with_nested_invalid.pk) in response_data["cohorts"]

    @patch("posthog.api.feature_flag.report_user_action")
    def test_local_evaluation_for_cohorts_with_variant_overrides(self, mock_capture):
        FeatureFlag.objects.all().delete()

        cohort_valid_for_ff = Cohort.objects.create(
            team=self.team,
            filters={
                "properties": {
                    "type": "OR",
                    "values": [
                        {
                            "type": "AND",
                            "values": [
                                {
                                    "key": "$some_prop",
                                    "value": "nomatchihope",
                                    "type": "person",
                                },
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
                            "variant": "test",
                            "properties": [
                                {
                                    "key": "id",
                                    "type": "cohort",
                                    "value": cohort_valid_for_ff.pk,
                                }
                            ],
                            "rollout_percentage": 100,
                        },
                        {
                            "variant": "test",
                            "properties": [
                                {
                                    "key": "email",
                                    "type": "person",
                                    "value": "@posthog.com",
                                    "operator": "icontains",
                                }
                            ],
                            "rollout_percentage": 100,
                        },
                    ],
                    "multivariate": {
                        "variants": [
                            {"key": "control", "name": "", "rollout_percentage": 100},
                            {"key": "test", "name": "", "rollout_percentage": 0},
                        ]
                    },
                },
            },
            format="json",
        )

        personal_api_key = generate_random_token_personal()
        PersonalAPIKey.objects.create(label="X", user=self.user, secure_value=hash_key_value(personal_api_key))

        self.client.logout()

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
                            "variant": "test",
                            "properties": [
                                {
                                    "key": "id",
                                    "type": "cohort",
                                    "value": cohort_valid_for_ff.pk,
                                }
                            ],
                            "rollout_percentage": 100,
                        },
                        {
                            "variant": "test",
                            "properties": [
                                {
                                    "key": "email",
                                    "type": "person",
                                    "value": "@posthog.com",
                                    "operator": "icontains",
                                }
                            ],
                            "rollout_percentage": 100,
                        },
                    ],
                    "multivariate": {
                        "variants": [
                            {"key": "control", "name": "", "rollout_percentage": 100},
                            {"key": "test", "name": "", "rollout_percentage": 0},
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
    def test_local_evaluation_for_static_cohorts(self, mock_capture):
        FeatureFlag.objects.all().delete()

        cohort_valid_for_ff = Cohort.objects.create(
            team=self.team,
            is_static=True,
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
                            "properties": [
                                {
                                    "key": "id",
                                    "type": "cohort",
                                    "value": cohort_valid_for_ff.pk,
                                }
                            ],
                        }
                    ],
                    "multivariate": {
                        "variants": [
                            {
                                "key": "first-variant",
                                "name": "First Variant",
                                "rollout_percentage": 50,
                            },
                            {
                                "key": "second-variant",
                                "name": "Second Variant",
                                "rollout_percentage": 25,
                            },
                            {
                                "key": "third-variant",
                                "name": "Third Variant",
                                "rollout_percentage": 25,
                            },
                        ]
                    },
                },
            },
            format="json",
        )

        personal_api_key = generate_random_token_personal()
        PersonalAPIKey.objects.create(label="X", user=self.user, secure_value=hash_key_value(personal_api_key))

        response = self.client.get(
            f"/api/feature_flag/local_evaluation?token={self.team.api_token}&send_cohorts",
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
                            "rollout_percentage": 20,
                            "properties": [
                                {
                                    "key": "id",
                                    "type": "cohort",
                                    "value": cohort_valid_for_ff.pk,
                                }
                            ],
                        }
                    ],
                    "multivariate": {
                        "variants": [
                            {
                                "key": "first-variant",
                                "name": "First Variant",
                                "rollout_percentage": 50,
                            },
                            {
                                "key": "second-variant",
                                "name": "Second Variant",
                                "rollout_percentage": 25,
                            },
                            {
                                "key": "third-variant",
                                "name": "Third Variant",
                                "rollout_percentage": 25,
                            },
                        ]
                    },
                },
                "deleted": False,
                "active": True,
                "ensure_experience_continuity": False,
            },
            sorted_flags[0],
        )

        self.assertEqual(
            response_data["cohorts"],
            {},
        )

    @patch("posthog.api.feature_flag.report_user_action")
    def test_local_evaluation_for_arbitrary_cohorts(self, mock_capture):
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
                                {
                                    "key": "$some_prop",
                                    "value": "nomatchihope",
                                    "type": "person",
                                },
                                {
                                    "key": "$some_prop2",
                                    "value": "nomatchihope2",
                                    "type": "person",
                                },
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
                                {
                                    "key": "$some_prop",
                                    "value": "nomatchihope",
                                    "type": "person",
                                },
                                {
                                    "key": "$some_prop2",
                                    "value": "nomatchihope2",
                                    "type": "person",
                                },
                                {
                                    "key": "id",
                                    "value": cohort_valid_for_ff.pk,
                                    "type": "cohort",
                                    "negation": True,
                                },
                            ],
                        }
                    ],
                }
            },
            name="cohort2",
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
                            "properties": [{"key": "id", "type": "cohort", "value": cohort2.pk}],
                        }
                    ],
                    "multivariate": {
                        "variants": [
                            {
                                "key": "first-variant",
                                "name": "First Variant",
                                "rollout_percentage": 50,
                            },
                            {
                                "key": "second-variant",
                                "name": "Second Variant",
                                "rollout_percentage": 25,
                            },
                            {
                                "key": "third-variant",
                                "name": "Third Variant",
                                "rollout_percentage": 25,
                            },
                        ]
                    },
                },
            },
            format="json",
        )

        self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {
                "name": "Alpha feature",
                "key": "alpha-feature-2",
                "filters": {
                    "groups": [
                        {
                            "rollout_percentage": 20,
                            "properties": [
                                {
                                    "key": "id",
                                    "type": "cohort",
                                    "value": cohort_valid_for_ff.pk,
                                }
                            ],
                        }
                    ],
                },
            },
            format="json",
        )

        personal_api_key = generate_random_token_personal()
        PersonalAPIKey.objects.create(label="X", user=self.user, secure_value=hash_key_value(personal_api_key))

        response = self.client.get(
            f"/api/feature_flag/local_evaluation?token={self.team.api_token}&send_cohorts",
            HTTP_AUTHORIZATION=f"Bearer {personal_api_key}",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        self.assertTrue(
            "flags" in response_data and "group_type_mapping" in response_data and "cohorts" in response_data
        )
        self.assertEqual(len(response_data["flags"]), 2)

        sorted_flags = sorted(response_data["flags"], key=lambda x: x["key"])

        self.assertEqual(
            response_data["cohorts"],
            {
                str(cohort_valid_for_ff.pk): {
                    "type": "OR",
                    "values": [
                        {
                            "type": "OR",
                            "values": [
                                {
                                    "key": "$some_prop",
                                    "type": "person",
                                    "value": "nomatchihope",
                                },
                                {
                                    "key": "$some_prop2",
                                    "type": "person",
                                    "value": "nomatchihope2",
                                },
                            ],
                        }
                    ],
                },
                str(cohort2.pk): {
                    "type": "OR",
                    "values": [
                        {
                            "type": "OR",
                            "values": [
                                {
                                    "key": "$some_prop",
                                    "type": "person",
                                    "value": "nomatchihope",
                                },
                                {
                                    "key": "$some_prop2",
                                    "type": "person",
                                    "value": "nomatchihope2",
                                },
                                {
                                    "key": "id",
                                    "type": "cohort",
                                    "value": cohort_valid_for_ff.pk,
                                    "negation": True,
                                },
                            ],
                        }
                    ],
                },
            },
        )

        self.assertDictContainsSubset(
            {
                "name": "Alpha feature",
                "key": "alpha-feature",
                "filters": {
                    "groups": [
                        {
                            "rollout_percentage": 20,
                            "properties": [{"key": "id", "type": "cohort", "value": cohort2.pk}],
                        }
                    ],
                    "multivariate": {
                        "variants": [
                            {
                                "key": "first-variant",
                                "name": "First Variant",
                                "rollout_percentage": 50,
                            },
                            {
                                "key": "second-variant",
                                "name": "Second Variant",
                                "rollout_percentage": 25,
                            },
                            {
                                "key": "third-variant",
                                "name": "Third Variant",
                                "rollout_percentage": 25,
                            },
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
                "name": "Alpha feature",
                "key": "alpha-feature-2",
                "filters": {
                    "groups": [
                        {
                            "properties": [
                                {
                                    "key": "id",
                                    "type": "cohort",
                                    "value": cohort_valid_for_ff.pk,
                                }
                            ],
                            "rollout_percentage": 20,
                        },
                    ],
                },
                "deleted": False,
                "active": True,
                "ensure_experience_continuity": False,
            },
            sorted_flags[1],
        )

    @patch("posthog.models.feature_flag.flag_analytics.CACHE_BUCKET_SIZE", 10)
    def test_local_evaluation_billing_analytics(self):
        FeatureFlag.objects.all().delete()

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

        client = redis.get_client()

        personal_api_key = generate_random_token_personal()
        PersonalAPIKey.objects.create(label="X", user=self.user, secure_value=hash_key_value(personal_api_key))

        self.client.logout()
        # `local_evaluation` is called by logged out clients!

        with freeze_time("2022-05-07 12:23:07"):
            # missing API key
            response = self.client.get(f"/api/feature_flag/local_evaluation?token={self.team.api_token}")
            self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
            self.assertEqual(client.hgetall(f"posthog:local_evaluation_requests:{self.team.pk}"), {})

            response = self.client.get(f"/api/feature_flag/local_evaluation")
            self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
            self.assertEqual(client.hgetall(f"posthog:local_evaluation_requests:{self.team.pk}"), {})

            response = self.client.get(
                f"/api/feature_flag/local_evaluation?token={self.team.api_token}",
                HTTP_AUTHORIZATION=f"Bearer {personal_api_key}",
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(
                client.hgetall(f"posthog:local_evaluation_requests:{self.team.pk}"),
                {b"165192618": b"1"},
            )

            for _ in range(5):
                response = self.client.get(
                    f"/api/feature_flag/local_evaluation?token={self.team.api_token}",
                    HTTP_AUTHORIZATION=f"Bearer {personal_api_key}",
                )
                self.assertEqual(response.status_code, status.HTTP_200_OK)

            self.assertEqual(
                client.hgetall(f"posthog:local_evaluation_requests:{self.team.pk}"),
                {b"165192618": b"6"},
            )

    @patch("posthog.models.feature_flag.flag_analytics.CACHE_BUCKET_SIZE", 10)
    def test_local_evaluation_billing_analytics_for_regular_feature_flag_list(self):
        FeatureFlag.objects.all().delete()

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

        client = redis.get_client()

        personal_api_key = generate_random_token_personal()
        PersonalAPIKey.objects.create(label="X", user=self.user, secure_value=hash_key_value(personal_api_key))

        # request made while logged in, via client cookie auth
        response = self.client.get(f"/api/feature_flag?token={self.team.api_token}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 2)

        # shouldn't add to local eval requests
        self.assertEqual(client.hgetall(f"posthog:local_evaluation_requests:{self.team.pk}"), {})

        self.client.logout()
        # `local_evaluation` is called by logged out clients!

        with freeze_time("2022-05-07 12:23:07"):
            # missing API key
            response = self.client.get(f"/api/feature_flag?token={self.team.api_token}")
            self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
            self.assertEqual(client.hgetall(f"posthog:local_evaluation_requests:{self.team.pk}"), {})

            response = self.client.get(f"/api/feature_flag/")
            self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
            self.assertEqual(client.hgetall(f"posthog:local_evaluation_requests:{self.team.pk}"), {})

            response = self.client.get(
                f"/api/feature_flag/?token={self.team.api_token}",
                HTTP_AUTHORIZATION=f"Bearer {personal_api_key}",
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(
                client.hgetall(f"posthog:local_evaluation_requests:{self.team.pk}"),
                {b"165192618": b"1"},
            )

            for _ in range(4):
                response = self.client.get(
                    f"/api/feature_flag/?token={self.team.api_token}",
                    HTTP_AUTHORIZATION=f"Bearer {personal_api_key}",
                )
                self.assertEqual(response.status_code, status.HTTP_200_OK)

            # local evaluation still works
            response = self.client.get(
                f"/api/feature_flag/local_evaluation?token={self.team.api_token}",
                HTTP_AUTHORIZATION=f"Bearer {personal_api_key}",
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)

            self.assertEqual(
                client.hgetall(f"posthog:local_evaluation_requests:{self.team.pk}"),
                {b"165192618": b"6"},
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
                            {
                                "key": "first-variant",
                                "name": "First Variant",
                                "rollout_percentage": 50,
                            },
                            {
                                "key": "second-variant",
                                "name": "Second Variant",
                                "rollout_percentage": 25,
                            },
                            {
                                "key": "third-variant",
                                "name": "Third Variant",
                                "rollout_percentage": 25,
                            },
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
            "person-flag",
            [
                {
                    "key": "email",
                    "type": "person",
                    "value": "@posthog.com",
                    "operator": "icontains",
                }
            ],
        )
        self.assertEqual(person_request.status_code, status.HTTP_201_CREATED)

        cohort: Cohort = Cohort.objects.create(team=self.team, name="My Cohort")
        cohort_request = self._create_flag_with_properties(
            "cohort-flag", [{"key": "id", "type": "cohort", "value": cohort.id}]
        )
        self.assertEqual(cohort_request.status_code, status.HTTP_201_CREATED)

        event_request = self._create_flag_with_properties(
            "illegal-event-flag",
            [{"key": "id", "value": 5}],
            expected_status=status.HTTP_400_BAD_REQUEST,
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
            [
                {
                    "key": "industry",
                    "value": "finance",
                    "type": "group",
                    "group_type_index": 0,
                }
            ],
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

    def test_create_flag_with_invalid_date(self):
        resp = self._create_flag_with_properties(
            "date-flag",
            [
                {
                    "key": "created_for",
                    "type": "person",
                    "value": "6hed",
                    "operator": "is_date_before",
                }
            ],
            expected_status=status.HTTP_400_BAD_REQUEST,
        )

        self.assertDictContainsSubset(
            {
                "type": "validation_error",
                "code": "invalid_date",
                "detail": "Invalid date value: 6hed",
                "attr": "filters",
            },
            resp.json(),
        )

        resp = self._create_flag_with_properties(
            "date-flag",
            [
                {
                    "key": "created_for",
                    "type": "person",
                    "value": "1234-02-993284",
                    "operator": "is_date_after",
                }
            ],
            expected_status=status.HTTP_400_BAD_REQUEST,
        )

        self.assertDictContainsSubset(
            {
                "type": "validation_error",
                "code": "invalid_date",
                "detail": "Invalid date value: 1234-02-993284",
                "attr": "filters",
            },
            resp.json(),
        )

    def test_creating_feature_flag_with_non_existant_cohort(self):
        cohort_request = self._create_flag_with_properties(
            "cohort-flag",
            [{"key": "id", "type": "cohort", "value": 5151}],
            expected_status=status.HTTP_400_BAD_REQUEST,
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
            [
                {
                    "key": "email",
                    "type": "person",
                    "value": "@posthog.com",
                    "operator": "icontains",
                }
            ],
            payloads={"true": 300},
            expected_status=status.HTTP_201_CREATED,
        )
        self._create_flag_with_properties(
            "person-flag",
            [
                {
                    "key": "email",
                    "type": "person",
                    "value": "@posthog.com",
                    "operator": "icontains",
                }
            ],
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
                            {
                                "key": "first-variant",
                                "name": "First Variant",
                                "rollout_percentage": 50,
                            },
                            {
                                "key": "second-variant",
                                "name": "Second Variant",
                                "rollout_percentage": 25,
                            },
                            {
                                "key": "third-variant",
                                "name": "Third Variant",
                                "rollout_percentage": 25,
                            },
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
                            {
                                "key": "first-variant",
                                "name": "First Variant",
                                "rollout_percentage": 50,
                            },
                            {
                                "key": "second-variant",
                                "name": "Second Variant",
                                "rollout_percentage": 25,
                            },
                            {
                                "key": "third-variant",
                                "name": "Third Variant",
                                "rollout_percentage": 25,
                            },
                        ]
                    },
                    "payloads": {
                        "first-variant": {"some": "payload"},
                        "fourth-variant": {"some": "payload"},
                    },
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
                            {
                                "key": "first-variant",
                                "name": "First Variant",
                                "rollout_percentage": 50,
                            },
                            {
                                "key": "second-variant",
                                "name": "Second Variant",
                                "rollout_percentage": 25,
                            },
                            {
                                "key": "third-variant",
                                "name": "Third Variant",
                                "rollout_percentage": 25,
                            },
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
                "detail": "Cohort 'cohort2' with filters on events cannot be used in feature flags.",
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
                            "properties": [
                                {
                                    "key": "id",
                                    "type": "cohort",
                                    "value": cohort_not_valid_for_ff.id,
                                }
                            ],
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
                "detail": "Cohort 'cohort2' with filters on events cannot be used in feature flags.",
                "attr": "filters",
            },
            response.json(),
        )

    def test_creating_feature_flag_with_nested_behavioral_cohort(self):
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
            name="cohort-behavioural",
        )

        nested_cohort_not_valid_for_ff = Cohort.objects.create(
            team=self.team,
            groups=[
                {
                    "properties": [
                        {
                            "key": "id",
                            "value": cohort_not_valid_for_ff.pk,
                            "type": "cohort",
                        }
                    ]
                }
            ],
            name="cohort-not-behavioural",
        )

        cohort_request = self._create_flag_with_properties(
            "cohort-flag",
            [
                {
                    "key": "id",
                    "type": "cohort",
                    "value": nested_cohort_not_valid_for_ff.id,
                }
            ],
            expected_status=status.HTTP_400_BAD_REQUEST,
        )

        self.assertDictContainsSubset(
            {
                "type": "validation_error",
                "code": "behavioral_cohort_found",
                "detail": "Cohort 'cohort-behavioural' with filters on events cannot be used in feature flags.",
                "attr": "filters",
            },
            cohort_request.json(),
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
                "detail": "Cohort 'cohort-behavioural' with filters on events cannot be used in feature flags.",
                "attr": "filters",
            },
            cohort_request.json(),
        )

    def test_validation_group_properties(self):
        groups_request = self._create_flag_with_properties(
            "groups-flag",
            [
                {
                    "key": "industry",
                    "value": "finance",
                    "type": "group",
                    "group_type_index": 0,
                }
            ],
            aggregation_group_type_index=0,
        )
        self.assertEqual(groups_request.status_code, status.HTTP_201_CREATED)

        illegal_groups_request = self._create_flag_with_properties(
            "illegal-groups-flag",
            [
                {
                    "key": "industry",
                    "value": "finance",
                    "type": "group",
                    "group_type_index": 0,
                }
            ],
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
            [
                {
                    "key": "email",
                    "type": "person",
                    "value": "@posthog.com",
                    "operator": "icontains",
                }
            ],
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
            data={
                "name": name,
                "key": name,
                "filters": {**kwargs, "groups": [{"properties": properties}]},
            },
            format="json",
        )
        self.assertEqual(create_response.status_code, expected_status)
        return create_response

    def _get_feature_flag_activity(
        self,
        flag_id: Optional[int] = None,
        team_id: Optional[int] = None,
        expected_status: int = status.HTTP_200_OK,
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

    def assert_feature_flag_activity(self, flag_id: Optional[int], expected: list[dict]):
        activity_response = self._get_feature_flag_activity(flag_id)

        activity: list[dict] = activity_response["results"]
        self.maxDiff = None
        assert activity == expected

    def test_patch_api_as_form_data(self):
        another_feature_flag = FeatureFlag.objects.create(
            team=self.team,
            name="some feature",
            key="some-feature",
            created_by=self.user,
            filters={
                "groups": [{"properties": [], "rollout_percentage": 100}],
                "multivariate": None,
            },
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
            updated_flag.filters,
            {
                "groups": [{"properties": [], "rollout_percentage": 100}],
                "multivariate": None,
            },
        )

    def test_feature_flag_threshold(self):
        feature_flag = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            data={
                "name": "Beta feature",
                "key": "beta-feature",
                "filters": {
                    "aggregation_group_type_index": 0,
                    "groups": [{"rollout_percentage": 65}],
                },
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
        self.assertEqual(
            (
                AvailableFeature.ROLE_BASED_ACCESS
                in [feature["key"] for feature in self.organization.available_product_features or []]
            ),
            False,
        )
        user_a = User.objects.create_and_join(self.organization, "a@potato.com", None)
        FeatureFlag.objects.create(team=self.team, created_by=user_a, key="blue_button")
        res = self.client.get(f"/api/projects/{self.team.id}/feature_flags/")
        self.assertEqual(res.json()["results"][0]["can_edit"], True)
        self.assertEqual(res.json()["results"][1]["can_edit"], True)

    def test_get_flags_dont_return_survey_targeting_flags(self):
        survey = self.client.post(
            f"/api/projects/{self.team.id}/surveys/",
            data={
                "name": "Notebooks power users survey",
                "type": "popover",
                "questions": [
                    {
                        "type": "open",
                        "question": "What would you want to improve from notebooks?",
                    }
                ],
                "targeting_flag_filters": {
                    "groups": [
                        {
                            "variant": None,
                            "rollout_percentage": None,
                            "properties": [
                                {
                                    "key": "billing_plan",
                                    "value": ["cloud"],
                                    "operator": "exact",
                                    "type": "person",
                                }
                            ],
                        }
                    ]
                },
                "conditions": {"url": "https://app.posthog.com/notebooks"},
            },
            format="json",
        )
        assert FeatureFlag.objects.filter(id=survey.json()["targeting_flag"]["id"]).exists()

        flags_list = self.client.get(f"/api/projects/@current/feature_flags")
        response = flags_list.json()
        assert len(response["results"]) == 1
        assert response["results"][0]["id"] is not survey.json()["targeting_flag"]["id"]

    def test_flag_is_cached_on_create_and_update(self):
        # Ensure empty feature flag list
        FeatureFlag.objects.all().delete()

        feature_flag = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            data={
                "name": "Beta feature",
                "key": "beta-feature",
                "filters": {
                    "aggregation_group_type_index": 0,
                    "groups": [{"rollout_percentage": 65}],
                },
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
                f"/api/projects/{self.team.pk}/feature_flags",
                HTTP_AUTHORIZATION=f"Bearer {personal_api_key}",
            )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Call to flags gets rate limited
        response = self.client.get(
            f"/api/projects/{self.team.pk}/feature_flags",
            HTTP_AUTHORIZATION=f"Bearer {personal_api_key}",
        )
        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertEqual(
            len([1 for name, args, kwargs in incr_mock.mock_calls if args[0] == "rate_limit_exceeded"]),
            1,
        )
        incr_mock.assert_any_call(
            "rate_limit_exceeded",
            tags={
                "team_id": self.team.pk,
                "scope": "burst",
                "rate": "5/minute",
                "path": f"/api/projects/TEAM_ID/feature_flags",
                "hashed_personal_api_key": hash_key_value(personal_api_key),
            },
        )

        incr_mock.reset_mock()

        # but not call to local evaluation
        for _ in range(7):
            response = self.client.get(
                f"/api/feature_flag/local_evaluation",
                HTTP_AUTHORIZATION=f"Bearer {personal_api_key}",
            )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            len([1 for name, args, kwargs in incr_mock.mock_calls if args[0] == "rate_limit_exceeded"]),
            0,
        )

    def test_feature_flag_dashboard(self):
        another_feature_flag = FeatureFlag.objects.create(
            team=self.team,
            rollout_percentage=50,
            name="some feature",
            key="some-feature",
            created_by=self.user,
        )
        dashboard = Dashboard.objects.create(team=self.team, name="private dashboard", created_by=self.user)
        relationship = FeatureFlagDashboards.objects.create(
            feature_flag=another_feature_flag, dashboard_id=dashboard.pk
        )

        response = self.client.get(f"/api/projects/{self.team.id}/feature_flags/" + str(another_feature_flag.pk))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_json = response.json()

        self.assertEqual(len(response_json["analytics_dashboards"]), 1)

        # check deleting the dashboard doesn't delete flag, but deletes the relationship
        dashboard.delete()
        another_feature_flag.refresh_from_db()

        with self.assertRaises(FeatureFlagDashboards.DoesNotExist):
            relationship.refresh_from_db()

    def test_feature_flag_dashboard_patch(self):
        another_feature_flag = FeatureFlag.objects.create(
            team=self.team,
            rollout_percentage=50,
            name="some feature",
            key="some-feature",
            created_by=self.user,
        )
        dashboard = Dashboard.objects.create(team=self.team, name="private dashboard", created_by=self.user)
        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/" + str(another_feature_flag.pk),
            {"analytics_dashboards": [dashboard.pk]},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response = self.client.get(f"/api/projects/{self.team.id}/feature_flags/" + str(another_feature_flag.pk))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_json = response.json()

        self.assertEqual(len(response_json["analytics_dashboards"]), 1)

    def test_feature_flag_dashboard_already_exists(self):
        another_feature_flag = FeatureFlag.objects.create(
            team=self.team,
            rollout_percentage=50,
            name="some feature",
            key="some-feature",
            created_by=self.user,
        )
        dashboard = Dashboard.objects.create(team=self.team, name="private dashboard", created_by=self.user)
        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/" + str(another_feature_flag.pk),
            {"analytics_dashboards": [dashboard.pk]},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/" + str(another_feature_flag.pk),
            {"analytics_dashboards": [dashboard.pk]},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_json = response.json()

        self.assertEqual(len(response_json["analytics_dashboards"]), 1)

    @freeze_time("2021-01-01")
    @snapshot_clickhouse_queries
    def test_creating_static_cohort(self):
        flag = FeatureFlag.objects.create(
            team=self.team,
            rollout_percentage=100,
            filters={
                "groups": [{"properties": [{"key": "key", "value": "value", "type": "person"}]}],
                "multivariate": None,
            },
            name="some feature",
            key="some-feature",
            created_by=self.user,
        )

        _create_person(
            team=self.team,
            distinct_ids=[f"person1"],
            properties={"key": "value"},
        )
        _create_person(
            team=self.team,
            distinct_ids=[f"person2"],
            properties={"key": "value2"},
        )
        _create_person(
            team=self.team,
            distinct_ids=[f"person3"],
            properties={"key2": "value3"},
        )
        flush_persons_and_events()

        with (
            snapshot_postgres_queries_context(self),
            self.settings(
                CELERY_TASK_ALWAYS_EAGER=True, PERSON_ON_EVENTS_OVERRIDE=False, PERSON_ON_EVENTS_V2_OVERRIDE=False
            ),
        ):
            response = self.client.post(
                f"/api/projects/{self.team.id}/feature_flags/{flag.id}/create_static_cohort_for_flag",
                {},
                format="json",
            )
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # fires an async task for computation, but celery runs sync in tests
        cohort_id = response.json()["cohort"]["id"]
        cohort = Cohort.objects.get(id=cohort_id)
        self.assertEqual(cohort.name, "Users with feature flag some-feature enabled at 2021-01-01 00:00:00")
        self.assertEqual(cohort.count, 1)

        response = self.client.get(f"/api/cohort/{cohort.pk}/persons")
        self.assertEqual(len(response.json()["results"]), 1, response)

    def test_cant_update_early_access_flag_with_group(self):
        feature_flag = FeatureFlag.objects.create(
            team=self.team,
            rollout_percentage=100,
            filters={
                "aggregation_group_type_index": None,
                "groups": [{"properties": [], "rollout_percentage": None}],
            },
            name="some feature",
            key="some-feature",
            created_by=self.user,
        )

        EarlyAccessFeature.objects.create(
            team=self.team,
            name="earlyAccessFeature",
            description="early access feature",
            stage="alpha",
            feature_flag=feature_flag,
        )

        update_data = {
            "filters": {
                "aggregation_group_type_index": 2,
                "groups": [{"properties": [], "rollout_percentage": 100}],
            }
        }
        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{feature_flag.id}/", update_data, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertDictContainsSubset(
            {
                "type": "validation_error",
                "code": "invalid_input",
                "detail": "Cannot change this flag to a group-based when linked to an Early Access Feature.",
            },
            response.json(),
        )

    def test_cant_create_flag_with_data_that_fails_to_query(self):
        Person.objects.create(
            distinct_ids=["123"],
            team=self.team,
            properties={"email": "x y z"},
        )
        Person.objects.create(
            distinct_ids=["456"],
            team=self.team,
            properties={"email": "2.3.999"},
        )

        # Only snapshot flag evaluation queries
        with snapshot_postgres_queries_context(self, custom_query_matcher=lambda query: "posthog_person" in query):
            response = self.client.post(
                f"/api/projects/{self.team.id}/feature_flags",
                {
                    "name": "Beta feature",
                    "key": "beta-x",
                    "filters": {
                        "groups": [
                            {
                                "rollout_percentage": 65,
                                "properties": [
                                    {
                                        "key": "email",
                                        "type": "person",
                                        "value": "2.3.9{0-9}{1}",
                                        "operator": "regex",
                                    }
                                ],
                            }
                        ]
                    },
                },
            )
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertEqual(
                response.json(),
                {
                    "type": "validation_error",
                    "code": "invalid_input",
                    "detail": "Can't evaluate flag - please check release conditions",
                    "attr": None,
                },
            )

    def test_cant_create_flag_with_group_data_that_fails_to_query(self):
        GroupTypeMapping.objects.create(team=self.team, group_type="organization", group_type_index=0)
        GroupTypeMapping.objects.create(team=self.team, group_type="xyz", group_type_index=1)

        for i in range(5):
            create_group(
                team_id=self.team.pk,
                group_type_index=1,
                group_key=f"xyz:{i}",
                properties={"industry": f"{i}", "email": "2.3.4445"},
            )

        # Only snapshot flag evaluation queries
        with snapshot_postgres_queries_context(self, custom_query_matcher=lambda query: "posthog_group" in query):
            # Test group flag with invalid regex
            response = self.client.post(
                f"/api/projects/{self.team.id}/feature_flags",
                {
                    "name": "Beta feature",
                    "key": "beta-x",
                    "filters": {
                        "aggregation_group_type_index": 1,
                        "groups": [
                            {
                                "rollout_percentage": 65,
                                "properties": [
                                    {
                                        "key": "email",
                                        "type": "group",
                                        "group_type_index": 1,
                                        "value": "2.3.9{0-9}{1 ef}",
                                        "operator": "regex",
                                    }
                                ],
                            }
                        ],
                    },
                },
            )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            {
                "type": "validation_error",
                "code": "invalid_input",
                "detail": "Can't evaluate flag - please check release conditions",
                "attr": None,
            },
        )


class TestCohortGenerationForFeatureFlag(APIBaseTest, ClickhouseTestMixin):
    def test_creating_static_cohort_with_deleted_flag(self):
        FeatureFlag.objects.create(
            team=self.team,
            rollout_percentage=100,
            filters={
                "groups": [{"properties": [{"key": "key", "value": "value", "type": "person"}]}],
                "multivariate": None,
            },
            name="some feature",
            key="some-feature",
            created_by=self.user,
            deleted=True,
        )

        _create_person(
            team=self.team,
            distinct_ids=[f"person1"],
            properties={"key": "value"},
        )
        flush_persons_and_events()

        cohort = Cohort.objects.create(
            team=self.team,
            is_static=True,
            name="some cohort",
        )

        with self.assertNumQueries(1):
            get_cohort_actors_for_feature_flag(cohort.pk, "some-feature", self.team.pk)

        cohort.refresh_from_db()
        self.assertEqual(cohort.name, "some cohort")
        # don't even try inserting anything, because invalid flag, so None instead of 0
        self.assertEqual(cohort.count, None)

        response = self.client.get(f"/api/cohort/{cohort.pk}/persons")
        self.assertEqual(len(response.json()["results"]), 0, response)

    def test_creating_static_cohort_with_inactive_flag(self):
        FeatureFlag.objects.create(
            team=self.team,
            rollout_percentage=100,
            filters={
                "groups": [{"properties": [{"key": "key", "value": "value", "type": "person"}]}],
                "multivariate": None,
            },
            name="some feature",
            key="some-feature2",
            created_by=self.user,
            active=False,
        )

        _create_person(
            team=self.team,
            distinct_ids=[f"person1"],
            properties={"key": "value"},
        )
        flush_persons_and_events()

        cohort = Cohort.objects.create(
            team=self.team,
            is_static=True,
            name="some cohort",
        )

        with self.assertNumQueries(1):
            get_cohort_actors_for_feature_flag(cohort.pk, "some-feature2", self.team.pk)

        cohort.refresh_from_db()
        self.assertEqual(cohort.name, "some cohort")
        # don't even try inserting anything, because invalid flag, so None instead of 0
        self.assertEqual(cohort.count, None)

        response = self.client.get(f"/api/cohort/{cohort.pk}/persons")
        self.assertEqual(len(response.json()["results"]), 0, response)

    @freeze_time("2021-01-01")
    def test_creating_static_cohort_with_group_flag(self):
        FeatureFlag.objects.create(
            team=self.team,
            rollout_percentage=100,
            filters={
                "groups": [{"properties": [{"key": "key", "value": "value", "type": "group", "group_type_index": 1}]}],
                "multivariate": None,
                "aggregation_group_type_index": 1,
            },
            name="some feature",
            key="some-feature3",
            created_by=self.user,
        )

        _create_person(
            team=self.team,
            distinct_ids=[f"person1"],
            properties={"key": "value"},
        )
        flush_persons_and_events()

        cohort = Cohort.objects.create(
            team=self.team,
            is_static=True,
            name="some cohort",
        )

        with self.assertNumQueries(1):
            get_cohort_actors_for_feature_flag(cohort.pk, "some-feature3", self.team.pk)

        cohort.refresh_from_db()
        self.assertEqual(cohort.name, "some cohort")
        # don't even try inserting anything, because invalid flag, so None instead of 0
        self.assertEqual(cohort.count, None)

        response = self.client.get(f"/api/cohort/{cohort.pk}/persons")
        self.assertEqual(len(response.json()["results"]), 0, response)

    def test_creating_static_cohort_with_no_person_distinct_ids(self):
        FeatureFlag.objects.create(
            team=self.team,
            rollout_percentage=100,
            filters={
                "groups": [{"properties": [], "rollout_percentage": 100}],
                "multivariate": None,
            },
            name="some feature",
            key="some-feature2",
            created_by=self.user,
        )

        Person.objects.create(team=self.team)

        cohort = Cohort.objects.create(
            team=self.team,
            is_static=True,
            name="some cohort",
        )

        with self.assertNumQueries(5):
            get_cohort_actors_for_feature_flag(cohort.pk, "some-feature2", self.team.pk)

        cohort.refresh_from_db()
        self.assertEqual(cohort.name, "some cohort")
        # don't even try inserting anything, because invalid flag, so None instead of 0
        self.assertEqual(cohort.count, None)

        response = self.client.get(f"/api/cohort/{cohort.pk}/persons")
        self.assertEqual(len(response.json()["results"]), 0, response)

    def test_creating_static_cohort_with_non_existing_flag(self):
        cohort = Cohort.objects.create(
            team=self.team,
            is_static=True,
            name="some cohort",
        )

        with self.assertNumQueries(1):
            get_cohort_actors_for_feature_flag(cohort.pk, "some-feature2", self.team.pk)

        cohort.refresh_from_db()
        self.assertEqual(cohort.name, "some cohort")
        # don't even try inserting anything, because invalid flag, so None instead of 0
        self.assertEqual(cohort.count, None)

        response = self.client.get(f"/api/cohort/{cohort.pk}/persons")
        self.assertEqual(len(response.json()["results"]), 0, response)

    def test_creating_static_cohort_with_experience_continuity_flag(self):
        FeatureFlag.objects.create(
            team=self.team,
            filters={
                "groups": [
                    {"properties": [{"key": "key", "value": "value", "type": "person"}], "rollout_percentage": 50}
                ],
                "multivariate": None,
            },
            name="some feature",
            key="some-feature2",
            created_by=self.user,
            ensure_experience_continuity=True,
        )

        p1 = _create_person(team=self.team, distinct_ids=[f"person1"], properties={"key": "value"}, immediate=True)
        _create_person(
            team=self.team,
            distinct_ids=[f"person2"],
            properties={"key": "value"},
        )
        _create_person(
            team=self.team,
            distinct_ids=[f"person3"],
            properties={"key": "value"},
        )
        flush_persons_and_events()

        FeatureFlagHashKeyOverride.objects.create(
            feature_flag_key="some-feature2",
            person=p1,
            team=self.team,
            hash_key="123",
        )

        cohort = Cohort.objects.create(
            team=self.team,
            is_static=True,
            name="some cohort",
        )

        # TODO: Ensure server-side cursors are disabled, since in production we use this with pgbouncer
        with snapshot_postgres_queries_context(self), self.assertNumQueries(12):
            get_cohort_actors_for_feature_flag(cohort.pk, "some-feature2", self.team.pk)

        cohort.refresh_from_db()
        self.assertEqual(cohort.name, "some cohort")
        self.assertEqual(cohort.count, 1)

        response = self.client.get(f"/api/cohort/{cohort.pk}/persons")
        self.assertEqual(len(response.json()["results"]), 1, response)

    def test_creating_static_cohort_iterator(self):
        FeatureFlag.objects.create(
            team=self.team,
            filters={
                "groups": [
                    {"properties": [{"key": "key", "value": "value", "type": "person"}], "rollout_percentage": 100}
                ],
                "multivariate": None,
            },
            name="some feature",
            key="some-feature2",
            created_by=self.user,
        )

        _create_person(
            team=self.team,
            distinct_ids=[f"person1"],
            properties={"key": "value"},
        )
        _create_person(
            team=self.team,
            distinct_ids=[f"person2"],
            properties={"key": "value"},
        )
        _create_person(
            team=self.team,
            distinct_ids=[f"person3"],
            properties={"key": "value"},
        )
        _create_person(
            team=self.team,
            distinct_ids=[f"person4"],
            properties={"key": "valuu3"},
        )
        flush_persons_and_events()

        cohort = Cohort.objects.create(
            team=self.team,
            is_static=True,
            name="some cohort",
        )

        # Extra queries because each batch adds its own queries
        with snapshot_postgres_queries_context(self), self.assertNumQueries(14):
            get_cohort_actors_for_feature_flag(cohort.pk, "some-feature2", self.team.pk, batchsize=2)

        cohort.refresh_from_db()
        self.assertEqual(cohort.name, "some cohort")
        self.assertEqual(cohort.count, 3)

        response = self.client.get(f"/api/cohort/{cohort.pk}/persons")
        self.assertEqual(len(response.json()["results"]), 3, response)

        # if the batch is big enough, it's fewer queries
        with self.assertNumQueries(9):
            get_cohort_actors_for_feature_flag(cohort.pk, "some-feature2", self.team.pk, batchsize=10)

        cohort.refresh_from_db()
        self.assertEqual(cohort.name, "some cohort")
        self.assertEqual(cohort.count, 3)

        response = self.client.get(f"/api/cohort/{cohort.pk}/persons")
        self.assertEqual(len(response.json()["results"]), 3, response)

    def test_creating_static_cohort_with_default_person_properties_adjustment(self):
        FeatureFlag.objects.create(
            team=self.team,
            filters={
                "groups": [
                    {
                        "properties": [{"key": "key", "value": "value", "type": "person", "operator": "icontains"}],
                        "rollout_percentage": 100,
                    }
                ],
                "multivariate": None,
            },
            name="some feature",
            key="some-feature2",
            created_by=self.user,
            ensure_experience_continuity=False,
        )
        FeatureFlag.objects.create(
            team=self.team,
            filters={
                "groups": [
                    {
                        "properties": [{"key": "key", "value": "value", "type": "person", "operator": "is_set"}],
                        "rollout_percentage": 100,
                    }
                ],
                "multivariate": None,
            },
            name="some feature",
            key="some-feature-new",
            created_by=self.user,
            ensure_experience_continuity=False,
        )

        _create_person(team=self.team, distinct_ids=[f"person1"], properties={"key": "value"})
        _create_person(
            team=self.team,
            distinct_ids=[f"person2"],
            properties={"key": "vaalue"},
        )
        _create_person(
            team=self.team,
            distinct_ids=[f"person3"],
            properties={"key22": "value"},
        )
        flush_persons_and_events()

        cohort = Cohort.objects.create(
            team=self.team,
            is_static=True,
            name="some cohort",
        )

        with snapshot_postgres_queries_context(self), self.assertNumQueries(9):
            # no queries to evaluate flags, because all evaluated using override properties
            get_cohort_actors_for_feature_flag(cohort.pk, "some-feature2", self.team.pk)

        cohort.refresh_from_db()
        self.assertEqual(cohort.name, "some cohort")
        self.assertEqual(cohort.count, 1)

        response = self.client.get(f"/api/cohort/{cohort.pk}/persons")
        self.assertEqual(len(response.json()["results"]), 1, response)

        cohort2 = Cohort.objects.create(
            team=self.team,
            is_static=True,
            name="some cohort2",
        )

        with snapshot_postgres_queries_context(self), self.assertNumQueries(9):
            # person3 doesn't match filter conditions so is pre-filtered out
            get_cohort_actors_for_feature_flag(cohort2.pk, "some-feature-new", self.team.pk)

        cohort2.refresh_from_db()
        self.assertEqual(cohort2.name, "some cohort2")
        self.assertEqual(cohort2.count, 2)

    def test_creating_static_cohort_with_cohort_flag_adds_cohort_props_as_default_too(self):
        cohort_nested = Cohort.objects.create(
            team=self.team,
            filters={
                "properties": {
                    "type": "OR",
                    "values": [
                        {
                            "type": "OR",
                            "values": [
                                {"key": "does-not-exist", "value": "none", "type": "person"},
                            ],
                        }
                    ],
                }
            },
        )
        cohort_static = Cohort.objects.create(
            team=self.team,
            is_static=True,
        )
        cohort_existing = Cohort.objects.create(
            team=self.team,
            filters={
                "properties": {
                    "type": "OR",
                    "values": [
                        {
                            "type": "OR",
                            "values": [
                                {"key": "group", "value": "none", "type": "person"},
                                {"key": "group2", "value": [1, 2, 3], "type": "person"},
                                {"key": "id", "value": cohort_static.pk, "type": "cohort"},
                                {"key": "id", "value": cohort_nested.pk, "type": "cohort"},
                            ],
                        }
                    ],
                }
            },
            name="cohort1",
        )
        FeatureFlag.objects.create(
            team=self.team,
            filters={
                "groups": [
                    {
                        "properties": [{"key": "id", "value": cohort_existing.pk, "type": "cohort"}],
                        "rollout_percentage": 100,
                    },
                    {"properties": [{"key": "key", "value": "value", "type": "person"}], "rollout_percentage": 100},
                ],
                "multivariate": None,
            },
            name="some feature",
            key="some-feature-new",
            created_by=self.user,
            ensure_experience_continuity=False,
        )

        _create_person(team=self.team, distinct_ids=[f"person1"], properties={"key": "value"})
        _create_person(
            team=self.team,
            distinct_ids=[f"person2"],
            properties={"group": "none"},
        )
        _create_person(
            team=self.team,
            distinct_ids=[f"person3"],
            properties={"key22": "value", "group2": 2},
        )
        _create_person(
            team=self.team,
            distinct_ids=[f"person4"],
            properties={},
        )
        flush_persons_and_events()

        cohort_static.insert_users_by_list([f"person4"])

        cohort = Cohort.objects.create(
            team=self.team,
            is_static=True,
            name="some cohort",
        )

        with snapshot_postgres_queries_context(self), self.assertNumQueries(26):
            # forced to evaluate flags by going to db, because cohorts need db query to evaluate
            get_cohort_actors_for_feature_flag(cohort.pk, "some-feature-new", self.team.pk)

        cohort.refresh_from_db()
        self.assertEqual(cohort.name, "some cohort")
        self.assertEqual(cohort.count, 4)


class TestBlastRadius(ClickhouseTestMixin, APIBaseTest):
    @snapshot_clickhouse_queries
    def test_user_blast_radius(self):
        for i in range(10):
            _create_person(
                team_id=self.team.pk,
                distinct_ids=[f"person{i}"],
                properties={"group": f"{i}"},
            )

        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/user_blast_radius",
            {
                "condition": {
                    "properties": [
                        {
                            "key": "group",
                            "type": "person",
                            "value": [0, 1, 2, 3],
                            "operator": "exact",
                        }
                    ],
                    "rollout_percentage": 25,
                }
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response_json = response.json()
        self.assertDictContainsSubset({"users_affected": 4, "total_users": 10}, response_json)

    @freeze_time("2024-01-11")
    def test_user_blast_radius_with_relative_date_filters(self):
        for i in range(8):
            _create_person(
                team_id=self.team.pk,
                distinct_ids=[f"person{i}"],
                properties={"group": f"{i}", "created_at": f"2023-0{i+1}-04"},
            )

        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/user_blast_radius",
            {
                "condition": {
                    "properties": [
                        {
                            "key": "created_at",
                            "type": "person",
                            "value": "-10m",
                            "operator": "is_date_before",
                        }
                    ],
                    "rollout_percentage": 100,
                }
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response_json = response.json()
        self.assertDictContainsSubset({"users_affected": 3, "total_users": 8}, response_json)

    def test_user_blast_radius_with_zero_users(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/user_blast_radius",
            {
                "condition": {
                    "properties": [
                        {
                            "key": "group",
                            "type": "person",
                            "value": [0, 1, 2, 3],
                            "operator": "exact",
                        }
                    ],
                    "rollout_percentage": 25,
                }
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response_json = response.json()
        self.assertDictContainsSubset({"users_affected": 0, "total_users": 0}, response_json)

    def test_user_blast_radius_with_zero_selected_users(self):
        for i in range(5):
            _create_person(
                team_id=self.team.pk,
                distinct_ids=[f"person{i}"],
                properties={"group": f"{i}"},
            )

        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/user_blast_radius",
            {
                "condition": {
                    "properties": [
                        {
                            "key": "group",
                            "type": "person",
                            "value": [8],
                            "operator": "exact",
                        }
                    ],
                    "rollout_percentage": 25,
                }
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response_json = response.json()
        self.assertDictContainsSubset({"users_affected": 0, "total_users": 5}, response_json)

    def test_user_blast_radius_with_all_selected_users(self):
        for i in range(5):
            _create_person(
                team_id=self.team.pk,
                distinct_ids=[f"person{i}"],
                properties={"group": f"{i}"},
            )

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
            _create_person(
                team_id=self.team.pk,
                distinct_ids=[f"person{i}"],
                properties={"group": f"{i}"},
            )

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
            _create_person(
                team_id=self.team.pk,
                distinct_ids=[f"person{i}"],
                properties={"group": f"{i}"},
            )

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
                                {
                                    "key": "group",
                                    "value": [1, 2, 4, 5, 6],
                                    "type": "person",
                                },
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
            _create_person(
                team_id=self.team.pk,
                distinct_ids=[f"person{i}"],
                properties={"group": f"{i}"},
            )

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
                                {
                                    "key": "group",
                                    "value": [1, 2, 4, 5, 6],
                                    "type": "person",
                                },
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
                team_id=self.team.pk,
                group_type_index=0,
                group_key=f"org:{i}",
                properties={"industry": f"{i}"},
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
                team_id=self.team.pk,
                group_type_index=0,
                group_key=f"org:{i}",
                properties={"industry": f"{i}"},
            )

        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/user_blast_radius",
            {
                "condition": {
                    "properties": [
                        {
                            "key": "industry",
                            "type": "group",
                            "value": [8],
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
        self.assertDictContainsSubset({"users_affected": 0, "total_users": 5}, response_json)

    def test_user_blast_radius_with_groups_all_selected(self):
        GroupTypeMapping.objects.create(team=self.team, group_type="organization", group_type_index=0)
        GroupTypeMapping.objects.create(team=self.team, group_type="company", group_type_index=1)

        for i in range(5):
            create_group(
                team_id=self.team.pk,
                group_type_index=1,
                group_key=f"org:{i}",
                properties={"industry": f"{i}"},
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
                team_id=self.team.pk,
                group_type_index=0,
                group_key=f"org:{i}",
                properties={"industry": f"{i}"},
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
                team_id=self.team.pk,
                group_type_index=0,
                group_key=f"org:{i}",
                properties={"industry": f"{i}"},
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
        # execute so we capture queries in snapshots
        execute(*args, **kwargs)
        raise OperationalError("canceling statement due to statement timeout")


def slow_query(execute, sql, *args, **kwargs):
    if "statement_timeout" in sql:
        return execute(sql, *args, **kwargs)
    return execute(f"SELECT pg_sleep(1); {sql}", *args, **kwargs)


@patch(
    "posthog.models.feature_flag.flag_matching.postgres_healthcheck.is_connected",
    return_value=True,
)
class TestResiliency(TransactionTestCase, QueryMatchingTest):
    def setUp(self) -> None:
        return super().setUp()

    def test_feature_flags_v3_with_group_properties(self, *args):
        self.organization = Organization.objects.create(name="test")
        self.team = Team.objects.create(organization=self.organization)
        self.user = User.objects.create_and_join(self.organization, "random@test.com", "password", "first_name")

        team_id = self.team.pk
        rf = RequestFactory()
        create_request = rf.post(f"api/projects/{self.team.pk}/feature_flags/", {"name": "xyz"})
        create_request.user = self.user

        GroupTypeMapping.objects.create(team=self.team, group_type="organization", group_type_index=0)

        create_group(
            team_id=self.team.pk,
            group_type_index=0,
            group_key=f"org:1",
            properties={"industry": f"finance"},
        )

        serialized_data = FeatureFlagSerializer(
            data={
                "name": "Alpha feature",
                "key": "group-flag",
                "filters": {
                    "aggregation_group_type_index": 0,
                    "groups": [
                        {
                            "properties": [
                                {
                                    "key": "industry",
                                    "value": "finance",
                                    "type": "group",
                                    "group_type_index": 0,
                                }
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

        with self.assertNumQueries(8):
            # one query to get group type mappings, another to get group properties
            # 2 to set statement timeout
            all_flags, _, _, errors = get_all_feature_flags(team_id, "example_id", groups={"organization": "org:1"})
            self.assertTrue(all_flags["group-flag"])
            self.assertTrue(all_flags["default-flag"])
            self.assertFalse(errors)

        # now db is down
        with snapshot_postgres_queries_context(self), connection.execute_wrapper(QueryTimeoutWrapper()):
            with self.assertNumQueries(3):
                all_flags, _, _, errors = get_all_feature_flags(team_id, "example_id", groups={"organization": "org:1"})

                self.assertTrue("group-flag" not in all_flags)
                # can't be true unless we cache group type mappings as well
                self.assertTrue("default-flag" not in all_flags)
                self.assertTrue(errors)

            # # now db is down, but decide was sent correct group property overrides
            with self.assertNumQueries(3):
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
            with self.assertNumQueries(3):
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

    @patch("posthog.models.feature_flag.flag_matching.FLAG_EVALUATION_ERROR_COUNTER")
    def test_feature_flags_v3_with_person_properties(self, mock_counter, *args):
        self.organization = Organization.objects.create(name="test")
        self.team = Team.objects.create(organization=self.organization)
        self.user = User.objects.create_and_join(self.organization, "random@test.com", "password", "first_name")

        team_id = self.team.pk
        rf = RequestFactory()
        create_request = rf.post(f"api/projects/{self.team.pk}/feature_flags/", {"name": "xyz"})
        create_request.user = self.user

        Person.objects.create(
            team=self.team,
            distinct_ids=["example_id"],
            properties={"email": "tim@posthog.com"},
        )

        serialized_data = FeatureFlagSerializer(
            data={
                "name": "Alpha feature",
                "key": "property-flag",
                "filters": {
                    "groups": [
                        {
                            "properties": [
                                {
                                    "key": "email",
                                    "value": "tim@posthog.com",
                                    "type": "person",
                                    "operator": "exact",
                                }
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

        with self.assertNumQueries(4):
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
                    team_id,
                    "random",
                    property_value_overrides={"email": "tim@posthog.com"},
                )
                self.assertTrue(all_flags["property-flag"])
                self.assertTrue(all_flags["default-flag"])
                self.assertFalse(errors)

                mock_counter.labels.assert_called_once_with(reason="timeout")
                mock_counter.labels.return_value.inc.assert_called_once_with()

            mock_counter.reset_mock()
            # # now db is down, but decide was sent email parameter with different email
            with self.assertNumQueries(0):
                all_flags, _, _, errors = get_all_feature_flags(
                    team_id,
                    "example_id",
                    property_value_overrides={"email": "tom@posthog.com"},
                )
                self.assertFalse(all_flags["property-flag"])
                self.assertTrue(all_flags["default-flag"])
                self.assertFalse(errors)

                mock_counter.labels.assert_not_called()

    def test_feature_flags_v3_with_a_working_slow_db(self, mock_postgres_check):
        self.organization = Organization.objects.create(name="test")
        self.team = Team.objects.create(organization=self.organization)
        self.user = User.objects.create_and_join(self.organization, "random@test.com", "password", "first_name")

        team_id = self.team.pk
        rf = RequestFactory()
        create_request = rf.post(f"api/projects/{self.team.pk}/feature_flags/", {"name": "xyz"})
        create_request.user = self.user

        Person.objects.create(
            team=self.team,
            distinct_ids=["example_id"],
            properties={"email": "tim@posthog.com"},
        )

        serialized_data = FeatureFlagSerializer(
            data={
                "name": "Alpha feature",
                "key": "property-flag",
                "filters": {
                    "groups": [
                        {
                            "properties": [
                                {
                                    "key": "email",
                                    "value": "tim@posthog.com",
                                    "type": "person",
                                    "operator": "exact",
                                }
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

        with self.assertNumQueries(4):
            # 1 query to set statement timeout
            # 1 query to get person properties
            all_flags, _, _, errors = get_all_feature_flags(team_id, "example_id")

            self.assertTrue(all_flags["property-flag"])
            self.assertTrue(all_flags["default-flag"])
            self.assertFalse(errors)

        # now db is slow and times out
        with (
            snapshot_postgres_queries_context(self),
            connection.execute_wrapper(slow_query),
            patch(
                "posthog.models.feature_flag.flag_matching.FLAG_MATCHING_QUERY_TIMEOUT_MS",
                500,
            ),
        ):
            mock_postgres_check.return_value = False
            all_flags, _, _, errors = get_all_feature_flags(team_id, "example_id")

            self.assertTrue("property-flag" not in all_flags)
            self.assertTrue(all_flags["default-flag"])
            self.assertTrue(errors)

            # # now db is down, but decide was sent email parameter with correct email
            with self.assertNumQueries(0):
                all_flags, _, _, errors = get_all_feature_flags(
                    team_id,
                    "random",
                    property_value_overrides={"email": "tim@posthog.com"},
                )
                self.assertTrue(all_flags["property-flag"])
                self.assertTrue(all_flags["default-flag"])
                self.assertFalse(errors)

            # # now db is down, but decide was sent email parameter with different email
            with self.assertNumQueries(0):
                all_flags, _, _, errors = get_all_feature_flags(
                    team_id,
                    "example_id",
                    property_value_overrides={"email": "tom@posthog.com"},
                )
                self.assertFalse(all_flags["property-flag"])
                self.assertTrue(all_flags["default-flag"])
                self.assertFalse(errors)

    def test_feature_flags_v3_with_skip_database_setting(self, mock_postgres_check):
        self.organization = Organization.objects.create(name="test")
        self.team = Team.objects.create(organization=self.organization)
        self.user = User.objects.create_and_join(self.organization, "random@test.com", "password", "first_name")

        team_id = self.team.pk
        rf = RequestFactory()
        create_request = rf.post(f"api/projects/{self.team.pk}/feature_flags/", {"name": "xyz"})
        create_request.user = self.user

        Person.objects.create(
            team=self.team,
            distinct_ids=["example_id"],
            properties={"email": "tim@posthog.com"},
        )

        serialized_data = FeatureFlagSerializer(
            data={
                "name": "Alpha feature",
                "key": "property-flag",
                "filters": {
                    "groups": [
                        {
                            "properties": [
                                {
                                    "key": "email",
                                    "value": "tim@posthog.com",
                                    "type": "person",
                                    "operator": "exact",
                                }
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

        with self.assertNumQueries(0), self.settings(DECIDE_SKIP_POSTGRES_FLAGS=True):
            # No queries because of config parameter
            all_flags, _, _, errors = get_all_feature_flags(team_id, "example_id")
            mock_postgres_check.assert_not_called()
            self.assertTrue("property-flag" not in all_flags)
            self.assertTrue(all_flags["default-flag"])
            self.assertTrue(errors)

        # db is slow and times out, but shouldn't matter to us
        with (
            self.assertNumQueries(0),
            connection.execute_wrapper(slow_query),
            patch(
                "posthog.models.feature_flag.flag_matching.FLAG_MATCHING_QUERY_TIMEOUT_MS",
                500,
            ),
            self.settings(DECIDE_SKIP_POSTGRES_FLAGS=True),
        ):
            mock_postgres_check.return_value = False
            all_flags, _, _, errors = get_all_feature_flags(team_id, "example_id")

            self.assertTrue("property-flag" not in all_flags)
            self.assertTrue(all_flags["default-flag"])
            self.assertTrue(errors)
            mock_postgres_check.assert_not_called()

            # decide was sent email parameter with correct email
            with self.assertNumQueries(0):
                all_flags, _, _, errors = get_all_feature_flags(
                    team_id,
                    "random",
                    property_value_overrides={"email": "tim@posthog.com"},
                )
                self.assertTrue(all_flags["property-flag"])
                self.assertTrue(all_flags["default-flag"])
                self.assertFalse(errors)
                mock_postgres_check.assert_not_called()

            # # now db is down, but decide was sent email parameter with different email
            with self.assertNumQueries(0):
                all_flags, _, _, errors = get_all_feature_flags(
                    team_id,
                    "example_id",
                    property_value_overrides={"email": "tom@posthog.com"},
                )
                self.assertFalse(all_flags["property-flag"])
                self.assertTrue(all_flags["default-flag"])
                self.assertFalse(errors)
                mock_postgres_check.assert_not_called()

    @patch("posthog.models.feature_flag.flag_matching.FLAG_EVALUATION_ERROR_COUNTER")
    def test_feature_flags_v3_with_slow_db_doesnt_try_to_compute_conditions_again(self, mock_counter, *args):
        self.organization = Organization.objects.create(name="test")
        self.team = Team.objects.create(organization=self.organization)
        self.user = User.objects.create_and_join(self.organization, "random@test.com", "password", "first_name")

        team_id = self.team.pk

        Person.objects.create(
            team=self.team,
            distinct_ids=["example_id"],
            properties={"email": "tim@posthog.com"},
        )

        FeatureFlag.objects.create(
            name="Alpha feature",
            key="property-flag",
            filters={
                "groups": [
                    {
                        "properties": [
                            {
                                "key": "email",
                                "value": "tim@posthog.com",
                                "type": "person",
                                "operator": "exact",
                            }
                        ],
                        "rollout_percentage": None,
                    }
                ]
            },
            team=self.team,
            created_by=self.user,
        )

        FeatureFlag.objects.create(
            name="Alpha feature",
            key="property-flag2",
            filters={
                "groups": [
                    {
                        "properties": [
                            {
                                "key": "email",
                                "value": "tim@posthog.com",
                                "type": "person",
                                "operator": "exact",
                            }
                        ],
                        "rollout_percentage": None,
                    }
                ]
            },
            team=self.team,
            created_by=self.user,
        )

        # Should be enabled for everyone
        FeatureFlag.objects.create(
            name="Alpha feature",
            key="default-flag",
            filters={"groups": [{"properties": [], "rollout_percentage": None}]},
            team=self.team,
            created_by=self.user,
        )

        with self.assertNumQueries(4):
            # 1 query to get person properties
            # 1 query to set statement timeout
            all_flags, _, _, errors = get_all_feature_flags(team_id, "example_id")

            self.assertTrue(all_flags["property-flag"])
            self.assertTrue(all_flags["default-flag"])
            self.assertFalse(errors)

        # now db is slow and times out
        with (
            snapshot_postgres_queries_context(self),
            connection.execute_wrapper(slow_query),
            patch(
                "posthog.models.feature_flag.flag_matching.FLAG_MATCHING_QUERY_TIMEOUT_MS",
                500,
            ),
            self.assertNumQueries(4),
        ):
            # no extra queries to get person properties for the second flag after first one failed
            all_flags, _, _, errors = get_all_feature_flags(team_id, "example_id")

            self.assertTrue("property-flag" not in all_flags)
            self.assertTrue("property-flag2" not in all_flags)
            self.assertTrue(all_flags["default-flag"])
            self.assertTrue(errors)

            mock_counter.labels.assert_has_calls(
                [
                    call(reason="timeout"),
                    call().inc(),
                    call(reason="flag_condition_retry"),
                    call().inc(),
                ]
            )

    @patch("posthog.models.feature_flag.flag_matching.FLAG_EVALUATION_ERROR_COUNTER")
    def test_feature_flags_v3_with_group_properties_and_slow_db(self, mock_counter, *args):
        self.organization = Organization.objects.create(name="test")
        self.team = Team.objects.create(organization=self.organization)
        self.user = User.objects.create_and_join(self.organization, "randomXYZ@test.com", "password", "first_name")

        team_id = self.team.pk
        rf = RequestFactory()
        create_request = rf.post(f"api/projects/{self.team.pk}/feature_flags/", {"name": "xyz"})
        create_request.user = self.user

        GroupTypeMapping.objects.create(team=self.team, group_type="organization", group_type_index=0)

        create_group(
            team_id=self.team.pk,
            group_type_index=0,
            group_key=f"org:1",
            properties={"industry": f"finance"},
        )

        serialized_data = FeatureFlagSerializer(
            data={
                "name": "Alpha feature",
                "key": "group-flag",
                "filters": {
                    "aggregation_group_type_index": 0,
                    "groups": [
                        {
                            "properties": [
                                {
                                    "key": "industry",
                                    "value": "finance",
                                    "type": "group",
                                    "group_type_index": 0,
                                }
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

        with self.assertNumQueries(8):
            # one query to get group type mappings, another to get group properties
            # 2 queries to set statement timeout
            all_flags, _, _, errors = get_all_feature_flags(team_id, "example_id", groups={"organization": "org:1"})
            self.assertTrue(all_flags["group-flag"])
            self.assertTrue(all_flags["default-flag"])
            self.assertFalse(errors)

        # now db is slow
        with (
            snapshot_postgres_queries_context(self),
            connection.execute_wrapper(slow_query),
            patch(
                "posthog.models.feature_flag.flag_matching.FLAG_MATCHING_QUERY_TIMEOUT_MS",
                500,
            ),
        ):
            with self.assertNumQueries(4):
                all_flags, _, _, errors = get_all_feature_flags(team_id, "example_id", groups={"organization": "org:1"})

                self.assertTrue("group-flag" not in all_flags)
                # can't be true unless we cache group type mappings as well
                self.assertTrue("default-flag" not in all_flags)
                self.assertTrue(errors)

            # # now db is slow, but decide was sent correct group property overrides
            with self.assertNumQueries(4):
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

                mock_counter.labels.assert_has_calls(
                    [
                        call(reason="timeout"),
                        call().inc(),
                        call(reason="group_mapping_retry"),
                        call().inc(),
                    ]
                )

            # # now db is down, but decide was sent different group property overrides
            with self.assertNumQueries(4):
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

    @patch("posthog.models.feature_flag.flag_matching.FLAG_EVALUATION_ERROR_COUNTER")
    def test_feature_flags_v3_with_experience_continuity_working_slow_db(self, mock_counter, *args):
        self.organization = Organization.objects.create(name="test")
        self.team = Team.objects.create(organization=self.organization)
        self.user = User.objects.create_and_join(self.organization, "random12@test.com", "password", "first_name")

        team_id = self.team.pk
        rf = RequestFactory()
        create_request = rf.post(f"api/projects/{self.team.pk}/feature_flags/", {"name": "xyz"})
        create_request.user = self.user

        Person.objects.create(
            team=self.team,
            distinct_ids=["example_id", "random"],
            properties={"email": "tim@posthog.com"},
        )

        serialized_data = FeatureFlagSerializer(
            data={
                "name": "Alpha feature",
                "key": "property-flag",
                "filters": {
                    "groups": [
                        {
                            "properties": [
                                {
                                    "key": "email",
                                    "value": "tim@posthog.com",
                                    "type": "person",
                                    "operator": "exact",
                                }
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

        with snapshot_postgres_queries_context(self), self.assertNumQueries(17):
            all_flags, _, _, errors = get_all_feature_flags(team_id, "example_id", hash_key_override="random")

            self.assertTrue(all_flags["property-flag"])
            self.assertTrue(all_flags["default-flag"])
            self.assertFalse(errors)

        # db is slow and times out
        with (
            snapshot_postgres_queries_context(self),
            connection.execute_wrapper(slow_query),
            patch(
                "posthog.models.feature_flag.flag_matching.FLAG_MATCHING_QUERY_TIMEOUT_MS",
                500,
            ),
        ):
            all_flags, _, _, errors = get_all_feature_flags(team_id, "example_id", hash_key_override="random")

            self.assertTrue("property-flag" not in all_flags)
            self.assertTrue(all_flags["default-flag"])
            self.assertTrue(errors)

            # # now db is slow, but decide was sent email parameter with correct email
            # still need to get hash key override from db, so should time out
            with self.assertNumQueries(4):
                all_flags, _, _, errors = get_all_feature_flags(
                    team_id,
                    "random",
                    property_value_overrides={"email": "tim@posthog.com"},
                )
                self.assertTrue("property-flag" not in all_flags)
                self.assertTrue(all_flags["default-flag"])
                self.assertTrue(errors)

            mock_counter.labels.assert_has_calls(
                [
                    call(reason="timeout"),
                    call().inc(),
                ]
            )

    @patch("posthog.models.feature_flag.flag_matching.FLAG_EVALUATION_ERROR_COUNTER")
    def test_feature_flags_v3_with_experience_continuity_and_incident_mode(self, mock_counter, *args):
        self.organization = Organization.objects.create(name="test")
        self.team = Team.objects.create(organization=self.organization)
        self.user = User.objects.create_and_join(self.organization, "random12@test.com", "password", "first_name")

        team_id = self.team.pk
        rf = RequestFactory()
        create_request = rf.post(f"api/projects/{self.team.pk}/feature_flags/", {"name": "xyz"})
        create_request.user = self.user

        Person.objects.create(
            team=self.team,
            distinct_ids=["example_id", "random"],
            properties={"email": "tim@posthog.com"},
        )

        serialized_data = FeatureFlagSerializer(
            data={
                "name": "Alpha feature",
                "key": "property-flag",
                "filters": {
                    "groups": [
                        {
                            "properties": [
                                {
                                    "key": "email",
                                    "value": "tim@posthog.com",
                                    "type": "person",
                                    "operator": "exact",
                                }
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

        with self.assertNumQueries(9), self.settings(DECIDE_SKIP_HASH_KEY_OVERRIDE_WRITES=True):
            all_flags, _, _, errors = get_all_feature_flags(team_id, "example_id", hash_key_override="random")

            self.assertTrue(all_flags["property-flag"])
            self.assertTrue(all_flags["default-flag"])
            self.assertFalse(errors)

        # should've been false because of the override, but incident mode, so not
        all_flags, _, _, errors = get_all_feature_flags(team_id, "example_id", hash_key_override="other_id")

        self.assertTrue(all_flags["property-flag"])
        self.assertTrue(all_flags["default-flag"])
        self.assertFalse(errors)
