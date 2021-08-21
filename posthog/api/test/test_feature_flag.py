from unittest.mock import patch

from rest_framework import status

from posthog.models import FeatureFlag, User
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
        response = self.client.post("/api/feature_flag", {"name": "Beta feature", "key": "red_button"})
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
            f"/api/feature_flag/{another_feature_flag.pk}", {"name": "Beta feature", "key": "red_button"},
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
            f"/api/feature_flag/{self.feature_flag.id}/", {"name": "Beta feature 3", "key": "red_button"},
        )
        self.assertEqual(response.status_code, 200)
        self.feature_flag.refresh_from_db()
        self.assertEqual(self.feature_flag.name, "Beta feature 3")

    def test_is_simple_flag(self):
        feature_flag = self.client.post(
            "/api/feature_flag/",
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
        self.assertIsNone(feature_flag["rollout_percentage"])

    @patch("posthoganalytics.capture")
    def test_create_feature_flag(self, mock_capture):

        response = self.client.post(
            "/api/feature_flag/",
            {"name": "Alpha feature", "key": "alpha-feature", "filters": {"groups": [{"rollout_percentage": 50}]}},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        instance = FeatureFlag.objects.get(id=response.json()["id"])
        self.assertEqual(instance.key, "alpha-feature")

        # Assert analytics are sent
        mock_capture.assert_called_once_with(
            self.user.distinct_id,
            "feature flag created",
            {
                "groups_count": 1,
                "has_variants": False,
                "variants_count": 0,
                "has_rollout_percentage": True,
                "has_filters": False,
                "filter_count": 0,
                "created_at": instance.created_at,
            },
        )

    @patch("posthoganalytics.capture")
    def test_create_minimal_feature_flag(self, mock_capture):

        response = self.client.post("/api/feature_flag/", {"key": "omega-feature"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["key"], "omega-feature")
        self.assertEqual(response.json()["name"], "")
        instance = FeatureFlag.objects.get(id=response.json()["id"])
        self.assertEqual(instance.key, "omega-feature")
        self.assertEqual(instance.name, "")

        # Assert analytics are sent
        mock_capture.assert_called_once_with(
            self.user.distinct_id,
            "feature flag created",
            {
                "groups_count": 1,  # 1 is always created by default
                "has_variants": False,
                "variants_count": 0,
                "has_rollout_percentage": False,
                "has_filters": False,
                "filter_count": 0,
                "created_at": instance.created_at,
            },
        )

    @patch("posthoganalytics.capture")
    def test_create_multivariate_feature_flag(self, mock_capture):

        response = self.client.post(
            "/api/feature_flag/",
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
            self.user.distinct_id,
            "feature flag created",
            {
                "groups_count": 1,
                "has_variants": True,
                "variants_count": 3,
                "has_filters": False,
                "has_rollout_percentage": False,
                "filter_count": 0,
                "created_at": instance.created_at,
            },
        )

    def test_cant_create_multivariate_feature_flag_with_variant_rollout_lt_100(self):
        response = self.client.post(
            "/api/feature_flag/",
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
            "/api/feature_flag/",
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
        response = self.client.post("/api/feature_flag/", format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            {"type": "validation_error", "code": "required", "detail": "This field is required.", "attr": "key"},
        )
        self.assertEqual(FeatureFlag.objects.count(), count)

    @patch("posthoganalytics.capture")
    def test_updating_feature_flag(self, mock_capture):
        instance = self.feature_flag

        response = self.client.patch(
            f"/api/feature_flag/{instance.pk}",
            {
                "name": "Updated name",
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
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        instance.refresh_from_db()
        self.assertEqual(instance.name, "Updated name")
        self.assertEqual(instance.groups[0]["rollout_percentage"], 65)

        # Assert analytics are sent
        mock_capture.assert_called_once_with(
            self.user.distinct_id,
            "feature flag updated",
            {
                "groups_count": 1,
                "has_variants": False,
                "variants_count": 0,
                "has_rollout_percentage": True,
                "has_filters": True,
                "filter_count": 1,
                "created_at": instance.created_at,
            },
        )

    def test_deleting_feature_flag(self):
        new_user = User.objects.create_and_join(self.organization, "new_annotations@posthog.com", None)

        instance = FeatureFlag.objects.create(team=self.team, created_by=self.user)
        self.client.force_login(new_user)

        with patch("posthoganalytics.capture") as mock_capture:
            response = self.client.delete(f"/api/feature_flag/{instance.pk}/")

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(FeatureFlag.objects.filter(pk=instance.pk).exists())

        # Assert analytics are sent (notice the event is sent on the user that executed the deletion, not the creator)
        mock_capture.assert_called_once_with(
            new_user.distinct_id,
            "feature flag deleted",
            {
                "groups_count": 1,
                "has_variants": False,
                "variants_count": 0,
                "has_rollout_percentage": False,
                "has_filters": False,
                "filter_count": 0,
                "created_at": instance.created_at,
            },
        )

    @patch("posthoganalytics.capture")
    def test_cannot_delete_feature_flag_on_another_team(self, mock_capture):
        _, _, user = User.objects.bootstrap("Test", "team2@posthog.com", None)
        self.client.force_login(user)

        response = self.client.delete(f"/api/feature_flag/{self.feature_flag.pk}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertTrue(FeatureFlag.objects.filter(pk=self.feature_flag.pk).exists())

        mock_capture.assert_not_called()

    def test_get_flags_with_specified_token(self):
        _, _, user = User.objects.bootstrap("Test", "team2@posthog.com", None)
        self.client.force_login(user)
        assert user.team is not None
        assert self.team is not None
        self.assertNotEqual(user.team.id, self.team.id)

        response_team_1 = self.client.get(f"/api/feature_flag")
        response_team_1_token = self.client.get(f"/api/feature_flag?token={user.team.api_token}")
        response_team_2 = self.client.get(f"/api/feature_flag?token={self.team.api_token}")

        self.assertEqual(response_team_1.json(), response_team_1_token.json())
        self.assertNotEqual(response_team_1.json(), response_team_2.json())

        response_invalid_token = self.client.get(f"/api/feature_flag?token=invalid")
        self.assertEqual(response_invalid_token.status_code, 401)

    def test_creating_a_feature_flag_with_same_team_and_key_after_deleting(self):
        FeatureFlag.objects.create(team=self.team, created_by=self.user, key="alpha-feature", deleted=True)

        response = self.client.post("/api/feature_flag/", {"name": "Alpha feature", "key": "alpha-feature"})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        instance = FeatureFlag.objects.get(id=response.json()["id"])
        self.assertEqual(instance.key, "alpha-feature")

    def test_updating_a_feature_flag_with_same_team_and_key_of_a_deleted_one(self):
        FeatureFlag.objects.create(team=self.team, created_by=self.user, key="alpha-feature", deleted=True)

        instance = FeatureFlag.objects.create(team=self.team, created_by=self.user, key="beta-feature")

        response = self.client.patch(f"/api/feature_flag/{instance.pk}", {"key": "alpha-feature",}, format="json",)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        instance.refresh_from_db()
        self.assertEqual(instance.key, "alpha-feature")

    @patch("posthoganalytics.capture")
    def test_for_user(self, mock_capture):
        self.client.post(
            "/api/feature_flag/",
            {"name": "Alpha feature", "key": "alpha-feature", "filters": {"groups": [{"rollout_percentage": 20}]}},
            format="json",
        )

        # alpha-feature is set for "distinct_id"
        response = self.client.get("/api/feature_flag/for_user?distinct_id=distinct_id")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["distinct_id"], "distinct_id")
        self.assertEqual(sorted(response.json()["flags_enabled"]), ["alpha-feature", "red_button"])

        # alpha-feature is not set for "distinct_id_0"
        response = self.client.get("/api/feature_flag/for_user?distinct_id=distinct_id_0")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["distinct_id"], "distinct_id_0")
        self.assertEqual(sorted(response.json()["flags_enabled"]), ["red_button"])

        # error if no distinct_id
        response = self.client.get("/api/feature_flag/for_user?distinct_id=")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["type"], "validation_error")
        self.assertEqual(response.json()["code"], "invalid_input")
        self.assertEqual(response.json()["detail"], "Please provide a distinct_id to continue.")
