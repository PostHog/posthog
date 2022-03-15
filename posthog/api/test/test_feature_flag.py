import datetime
import json
from dataclasses import asdict
from unittest.mock import patch

from freezegun.api import freeze_time
from rest_framework import status

from posthog.models import FeatureFlag, GroupTypeMapping, User
from posthog.models.cohort import Cohort
from posthog.models.feature_flag import FeatureFlagOverride
from posthog.models.history_logging import Change, HistoryListItem
from posthog.test.base import APIBaseTest


class TestFeatureFlag(APIBaseTest):
    feature_flag: FeatureFlag = None  # type: ignore

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
            team=self.team, rollout_percentage=50, name="some feature", key="some-feature", created_by=self.user,
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
            data={"name": "Beta feature", "key": "beta-feature", "filters": {"groups": [{"rollout_percentage": 65,}]},},
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
                                {"key": "email", "type": "person", "value": "@posthog.com", "operator": "icontains",},
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
                "filters": {"aggregation_group_type_index": 0, "groups": [{"rollout_percentage": 65,}]},
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
            },
        )

        self.assert_feature_flag_history(
            flag_id,
            [
                {
                    "changes": [
                        {
                            "type": "FeatureFlag",
                            "action": "created",
                            "key": None,
                            "detail": {"id": str(flag_id), "key": "alpha-feature"},
                        }
                    ],
                    "created_at": "2021-08-25T22:09:14.252000+00:00",
                    "email": "user1@posthog.com",
                    "name": "",
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
                        ],
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
                        ],
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
                        ],
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
                                    },
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
            },
        )

        self.assert_feature_flag_history(
            flag_id,
            [
                {
                    "email": self.user.email,
                    "name": "",
                    "changes": [
                        {
                            "type": "FeatureFlag",
                            "action": "changed",
                            "key": "name",
                            "detail": {
                                "id": str(flag_id),
                                "key": "a-feature-flag-that-is-updated",
                                "from": "original name",
                                "to": "Updated name",
                            },
                        },
                        {
                            "type": "FeatureFlag",
                            "action": "changed",
                            "key": "filters",
                            "detail": {
                                "id": str(flag_id),
                                "key": "a-feature-flag-that-is-updated",
                                "from": {"groups": [{"properties": [], "rollout_percentage": None}]},
                                "to": {
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
                        },
                        {
                            "type": "FeatureFlag",
                            "action": "changed",
                            "key": "is_simple_flag",
                            "detail": {
                                "id": str(flag_id),
                                "key": "a-feature-flag-that-is-updated",
                                "from": True,
                                "to": False,
                            },
                        },
                    ],
                    "created_at": "2021-08-25T22:19:14.252000+00:00",
                },
                {
                    "email": self.user.email,
                    "name": "",
                    "changes": [
                        {
                            "type": "FeatureFlag",
                            "key": None,
                            "action": "created",
                            "detail": {"id": str(flag_id), "key": "a-feature-flag-that-is-updated"},
                        }
                    ],
                    "created_at": "2021-08-25T22:09:14.252000+00:00",
                },
            ],
        )

    @freeze_time("2021-08-25T22:09:14.252Z")
    def test_deleting_feature_flag(self):
        """
        NB Feature flags have a soft delete which writes to the "deleted" property.

        This is testing calling the HTTP delete endpoint which is a hard delete,
        so the "deleted" property captured for history will be false
        but the model instance will have been deleted from the DB
        """

        new_user = User.objects.create_and_join(self.organization, "new_annotations@posthog.com", None)

        instance = FeatureFlag.objects.create(team=self.team, created_by=self.user, key="potato")
        self.client.force_login(new_user)

        with patch("posthog.mixins.report_user_action") as mock_capture:
            response = self.client.delete(f"/api/projects/{self.team.id}/feature_flags/{instance.pk}/")

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(FeatureFlag.objects.filter(pk=instance.pk).exists())

        # Assert analytics are sent (notice the event is sent on the user that executed the deletion, not the creator)
        mock_capture.assert_called_once_with(
            new_user,
            "feature flag deleted",
            {
                "groups_count": 1,
                "has_variants": False,
                "variants_count": 0,
                "has_rollout_percentage": False,
                "has_filters": False,
                "filter_count": 0,
                "created_at": instance.created_at,
                "aggregating_by_groups": False,
            },
        )

        flag_history = self._get_feature_flag_history(instance.pk)["results"]

        self.assertEqual(
            flag_history,
            [
                {
                    "changes": [
                        {
                            "action": "deleted",
                            "detail": {"id": str(instance.pk), "key": "potato"},
                            "key": None,
                            "type": "FeatureFlag",
                        }
                    ],
                    "created_at": "2021-08-25T22:09:14.252000+00:00",
                    "email": "new_annotations@posthog.com",
                    "name": "",
                }
            ],
        )

    @freeze_time("2021-08-25T22:09:14.252Z")
    def test_get_feature_flag_that_needs_importing(self):
        """
        The first time we load history for a feature flag that existed before starting history logging
        Import its current state
        """
        new_user = User.objects.create_and_join(self.organization, "new_annotations@posthog.com", None)

        instance = FeatureFlag.objects.create(team=self.team, created_by=self.user)
        self.client.force_login(new_user)

        response = self.client.get(f"/api/projects/{self.team.id}/feature_flags/{instance.pk}/history")

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        history = response.json()["results"]

        expected = [
            asdict(
                HistoryListItem(
                    email="history.hog@posthog.com",
                    name="History Hog",
                    changes=[Change(type="FeatureFlag", key=None, action="imported", detail={})],
                    created_at="2021-08-25T22:09:14.252000",
                )
            )
        ]

        self.assertEqual(
            history, expected,
        )

    def test_get_feature_flag_history(self):
        """
        The first time we load history for a feature flag that existed before starting history logging
        Import its current state
        """
        new_user = User.objects.create_and_join(
            self.organization, "person_acting_and_then_viewing_history@posthog.com", None
        )
        self.client.force_login(new_user)

        with freeze_time("2021-08-25T22:09:14.252Z") as frozen_datetime:
            create_response = self.client.post(
                f"/api/projects/{self.team.id}/feature_flags/",
                {"name": "feature flag with history", "key": "feature_with_history"},
            )

            self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
            flag_id = create_response.json()["id"]

            frozen_datetime.tick(delta=datetime.timedelta(minutes=10))

            update_response = self.client.patch(
                f"/api/projects/{self.team.id}/feature_flags/{flag_id}",
                {
                    "name": "feature flag with history",
                    "filters": {"groups": [{"properties": [], "rollout_percentage": 74}]},
                },
                format="json",
            )

        self.assertEqual(update_response.status_code, status.HTTP_200_OK)

        self.assert_feature_flag_history(
            flag_id,
            [
                {
                    "email": "person_acting_and_then_viewing_history@posthog.com",
                    "name": "",
                    "changes": [
                        {
                            "type": "FeatureFlag",
                            "key": "filters",
                            "action": "changed",
                            "detail": {
                                "id": str(flag_id),
                                "key": "feature_with_history",
                                "from": {"groups": [{"properties": [], "rollout_percentage": None}]},
                                "to": {"groups": [{"properties": [], "rollout_percentage": 74}]},
                            },
                        },
                        {
                            "type": "FeatureFlag",
                            "key": "rollout_percentage",
                            "action": "changed",
                            "detail": {"id": str(flag_id), "key": "feature_with_history", "from": None, "to": 74},
                        },
                    ],
                    "created_at": "2021-08-25T22:19:14.252000+00:00",
                },
                {
                    "email": "person_acting_and_then_viewing_history@posthog.com",
                    "name": "",
                    "changes": [
                        {
                            "type": "FeatureFlag",
                            "key": None,
                            "action": "created",
                            "detail": {"id": str(flag_id), "key": "feature_with_history"},
                        }
                    ],
                    "created_at": "2021-08-25T22:09:14.252000+00:00",
                },
            ],
        )

    @patch("posthog.api.feature_flag.report_user_action")
    def test_cannot_delete_feature_flag_on_another_team(self, mock_capture):
        _, other_team, other_user = User.objects.bootstrap("Test", "team2@posthog.com", None)
        self.client.force_login(other_user)

        response = self.client.delete(f"/api/projects/{other_team.id}/feature_flags/{self.feature_flag.pk}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertTrue(FeatureFlag.objects.filter(pk=self.feature_flag.pk).exists())

        mock_capture.assert_not_called()

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
            f"/api/projects/{self.team.id}/feature_flags/{instance.pk}", {"key": "alpha-feature",}, format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        instance.refresh_from_db()
        self.assertEqual(instance.key, "alpha-feature")

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
                        ],
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
        self.assertEqual(first_flag["value_for_user_without_override"], "third-variant")
        self.assertEqual(first_flag["override"], None)

        second_flag = response_data[1]
        self.assertEqual(second_flag["feature_flag"]["key"], "red_button")
        self.assertEqual(second_flag["value_for_user_without_override"], True)
        self.assertEqual(second_flag["override"], None)

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
        self.assertEqual(first_flag["value_for_user_without_override"], False)
        self.assertEqual(first_flag["override"], None)

    @patch("posthoganalytics.capture")
    def test_my_flags_groups(self, mock_capture):
        self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {
                "name": "groups flag",
                "key": "groups-flag",
                "filters": {"aggregation_group_type_index": 0, "groups": [{"rollout_percentage": 100,}]},
            },
            format="json",
        )

        GroupTypeMapping.objects.create(team=self.team, group_type="organization", group_type_index=0)

        response = self.client.get(f"/api/projects/{self.team.id}/feature_flags/my_flags")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        groups_flag = response.json()[0]
        self.assertEqual(groups_flag["feature_flag"]["key"], "groups-flag")
        self.assertEqual(groups_flag["value_for_user_without_override"], False)

        response = self.client.get(
            f"/api/projects/{self.team.id}/feature_flags/my_flags", data={"groups": json.dumps({"organization": "7"})}
        )
        groups_flag = response.json()[0]
        self.assertEqual(groups_flag["feature_flag"]["key"], "groups-flag")
        self.assertEqual(groups_flag["value_for_user_without_override"], True)

    def test_create_override(self):
        # Boolean override value
        feature_flag_instance = FeatureFlag.objects.create(team=self.team, created_by=self.user, key="beta-feature")
        response = self.client.post(
            "/api/projects/@current/feature_flag_overrides/my_overrides",
            {"feature_flag": feature_flag_instance.id, "override_value": True},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIsNotNone(
            FeatureFlagOverride.objects.get(
                team=self.team, user=self.user, feature_flag=feature_flag_instance, override_value=True
            )
        )

        # String override value
        feature_flag_instance_2 = FeatureFlag.objects.create(team=self.team, created_by=self.user, key="beta-feature-2")
        response = self.client.post(
            "/api/projects/@current/feature_flag_overrides/my_overrides",
            {"feature_flag": feature_flag_instance_2.id, "override_value": "hey-hey"},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIsNotNone(
            FeatureFlagOverride.objects.get(
                team=self.team, user=self.user, feature_flag=feature_flag_instance_2, override_value="hey-hey"
            )
        )

        response = self.client.get(f"/api/projects/{self.team.id}/feature_flags/my_flags")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()

        first_flag = response_data[0]
        self.assertEqual(first_flag["feature_flag"]["key"], "beta-feature-2")
        self.assertEqual(first_flag["override"]["override_value"], "hey-hey")

        second_flag = response_data[1]
        self.assertEqual(second_flag["feature_flag"]["key"], "beta-feature")
        self.assertEqual(second_flag["override"]["override_value"], True)

        third_flag = response_data[2]
        self.assertEqual(third_flag["feature_flag"]["key"], "red_button")
        self.assertEqual(third_flag["override"], None)

    def test_update_override(self):
        # Create an override and, and make sure the my_flags response shows it
        feature_flag_instance = FeatureFlag.objects.create(team=self.team, created_by=self.user, key="beta-feature")
        response = self.client.post(
            "/api/projects/@current/feature_flag_overrides/my_overrides",
            {"feature_flag": feature_flag_instance.id, "override_value": "hey-hey"},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        response = self.client.get(f"/api/projects/{self.team.id}/feature_flags/my_flags")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        first_flag = response_data[0]
        self.assertEqual(first_flag["feature_flag"]["key"], "beta-feature")
        self.assertEqual(first_flag["override"]["override_value"], "hey-hey")

        # Update the override, and make sure the my_flags response reflects the update
        response = self.client.post(
            "/api/projects/@current/feature_flag_overrides/my_overrides",
            {"feature_flag": feature_flag_instance.id, "override_value": "new-override"},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        response = self.client.get(f"/api/projects/{self.team.id}/feature_flags/my_flags")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        first_flag = response_data[0]
        self.assertEqual(first_flag["feature_flag"]["key"], "beta-feature")
        self.assertEqual(first_flag["override"]["override_value"], "new-override")

        # Ensure only 1 override exists in the DB for the feature_flag/user combo
        self.assertEqual(
            FeatureFlagOverride.objects.filter(user=self.user, feature_flag=feature_flag_instance).count(), 1
        )

    def test_delete_override(self):
        # Create an override and, and make sure the my_flags response shows it
        feature_flag_instance = FeatureFlag.objects.create(team=self.team, created_by=self.user, key="beta-feature")
        response = self.client.post(
            "/api/projects/@current/feature_flag_overrides/my_overrides",
            {"feature_flag": feature_flag_instance.id, "override_value": "hey-hey"},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        response = self.client.get(f"/api/projects/{self.team.id}/feature_flags/my_flags")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        first_flag = response_data[0]
        self.assertEqual(first_flag["feature_flag"]["key"], "beta-feature")
        self.assertEqual(first_flag["override"]["override_value"], "hey-hey")

        # Delete the override, and make sure the my_flags response reflects the update
        existing_override_id = first_flag["override"]["id"]
        response = self.client.delete(f"/api/projects/@current/feature_flag_overrides/{existing_override_id}",)
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        response = self.client.get(f"/api/projects/{self.team.id}/feature_flags/my_flags")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        first_flag = response_data[0]
        self.assertEqual(first_flag["feature_flag"]["key"], "beta-feature")
        self.assertEqual(first_flag["override"], None)

    def test_create_override_with_invalid_override(self):
        feature_flag_instance = FeatureFlag.objects.create(team=self.team, created_by=self.user, key="beta-feature")
        response = self.client.post(
            "/api/projects/@current/feature_flag_overrides/my_overrides",
            {"feature_flag": feature_flag_instance.id, "override_value": {"key": "a dict"}},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_override_for_feature_flag_in_another_team(self):
        feature_flag_instance = FeatureFlag.objects.create(team=self.team, created_by=self.user, key="beta-feature")
        _, _, team_2_user = User.objects.bootstrap("Test", "team2@posthog.com", None)
        self.client.force_login(team_2_user)
        response = self.client.post(
            "/api/projects/@current/feature_flag_overrides/my_overrides",
            {"feature_flag": feature_flag_instance.id, "override_value": True},
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_delete_another_users_override(self):
        feature_flag_instance = FeatureFlag.objects.create(team=self.team, created_by=self.user, key="beta-feature")
        feature_flag_override = FeatureFlagOverride.objects.create(
            team=self.team, user=self.user, feature_flag=feature_flag_instance, override_value=True
        )
        feature_flag_override_id = feature_flag_override.id
        _, _, user_2 = User.objects.bootstrap(self.organization.name, "user2@posthog.com", None)
        self.client.force_login(user_2)
        response = self.client.delete(f"/api/projects/@current/feature_flag_overrides/{feature_flag_override_id}",)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_standard_viewset_endpoints_are_not_available(self):
        feature_flag_instance = FeatureFlag.objects.create(team=self.team, created_by=self.user, key="beta-feature")
        feature_flag_override = FeatureFlagOverride.objects.create(
            team=self.team, user=self.user, feature_flag=feature_flag_instance, override_value=True
        )
        feature_flag_override_id = feature_flag_override.id

        response = self.client.put(
            f"/api/projects/@current/feature_flag_overrides/{feature_flag_override_id}",
            {"feature_flag": feature_flag_instance.id, "override_value": True},
        )
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

        response = self.client.patch(
            f"/api/projects/@current/feature_flag_overrides/{feature_flag_override_id}",
            {"feature_flag": feature_flag_instance.id, "override_value": True},
        )
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

        response = self.client.get(f"/api/projects/@current/feature_flag_overrides/{feature_flag_override_id}")
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

        response = self.client.get(f"/api/projects/@current/feature_flag_overrides/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        response = self.client.post(
            f"/api/projects/@current/feature_flag_overrides/",
            {"feature_flag": feature_flag_instance.id, "override_value": True},
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_validation_person_properties(self):
        person_request = self._create_flag_with_properties(
            "person-flag", [{"key": "email", "type": "person", "value": "@posthog.com", "operator": "icontains",},]
        )
        self.assertEqual(person_request.status_code, status.HTTP_201_CREATED)

        cohort_request = self._create_flag_with_properties(
            "cohort-flag", [{"key": "id", "type": "cohort", "value": 5},]
        )
        self.assertEqual(cohort_request.status_code, status.HTTP_201_CREATED)

        event_request = self._create_flag_with_properties("illegal-event-flag", [{"key": "id", "value": 5},])
        self.assertEqual(event_request.status_code, status.HTTP_400_BAD_REQUEST)
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
            "illegal-groups-flag", [{"key": "industry", "value": "finance", "type": "group", "group_type_index": 0}]
        )
        self.assertEqual(groups_request.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            groups_request.json(),
            {
                "type": "validation_error",
                "code": "invalid_input",
                "detail": "Filters are not valid (can only use person and cohort properties)",
                "attr": "filters",
            },
        )

    @patch("posthog.tasks.calculate_cohort.calculate_cohort_ch.delay")
    def test_cohort_is_calculated(self, calculate_cohort_ch):
        cohort = Cohort.objects.create(
            team=self.team,
            groups=[{"properties": {"$some_prop": "something", "$another_prop": "something"}}],
            name="cohort1",
        )
        cohort_request = self._create_flag_with_properties(
            "cohort-flag", [{"key": "id", "type": "cohort", "value": cohort.pk},]
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
        )
        self.assertEqual(illegal_groups_request.status_code, status.HTTP_400_BAD_REQUEST)
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
            [{"key": "email", "type": "person", "value": "@posthog.com", "operator": "icontains",},],
            aggregation_group_type_index=0,
        )
        self.assertEqual(person_request.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            person_request.json(),
            {
                "type": "validation_error",
                "code": "invalid_input",
                "detail": "Filters are not valid (can only use group properties)",
                "attr": "filters",
            },
        )

    def _create_flag_with_properties(self, name, properties, **kwargs):
        return self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            data={"name": name, "key": name, "filters": {**kwargs, "groups": [{"properties": properties,}],},},
            format="json",
        )

    def _get_feature_flag_history(self, flag_id: int, expected_status: int = status.HTTP_200_OK):
        history_response = self.client.get(f"/api/projects/{self.team.id}/feature_flags/{flag_id}/history")
        self.assertEqual(history_response.status_code, expected_status)
        return history_response.json()

    def assert_feature_flag_history(self, flag_id: int, expected):
        history_response = self._get_feature_flag_history(flag_id)

        history = history_response["results"]
        self.maxDiff = None
        self.assertEqual(
            history, expected,
        )
