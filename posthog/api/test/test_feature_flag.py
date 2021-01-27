from unittest.mock import patch

from rest_framework import status

from posthog.models import FeatureFlag, User
from posthog.test.base import APIBaseTest, TransactionBaseTest


class TestFeatureFlag(TransactionBaseTest):
    TESTS_API = True

    def test_key_exists(self):
        feature_flag = self.client.post(
            "/api/feature_flag/",
            data={"name": "Beta feature", "key": "beta-feature", "filters": {"groups": [{"rollout_percentage": 50}]}},
            content_type="application/json",
        ).json()
        self.assertEqual(FeatureFlag.objects.get(pk=feature_flag["id"]).name, "Beta feature")
        self.assertTrue(feature_flag["is_simple_flag"])
        self.assertEqual(feature_flag["rollout_percentage"], 50)

        # Make sure the endpoint works with and without the trailing slash
        response = self.client.post(
            "/api/feature_flag", data={"name": "Beta feature", "key": "beta-feature"}, content_type="application/json",
        ).json()

        self.assertEqual(
            response,
            {"type": "validation_error", "code": "key-exists", "detail": "This key already exists.", "attr": None},
        )

        another_feature_flag = FeatureFlag.objects.create(
            team=self.team, rollout_percentage=50, name="some feature", key="some-feature", created_by=self.user,
        )
        # try updating into an existing feature flag
        response = self.client.patch(
            "/api/feature_flag/%s/" % another_feature_flag.pk,
            data={"name": "Beta feature", "key": "beta-feature"},
            content_type="application/json",
        ).json()
        self.assertEqual(
            response,
            {"type": "validation_error", "code": "key-exists", "detail": "This key already exists.", "attr": None},
        )

        # try updating the existing one
        response = self.client.patch(
            "/api/feature_flag/%s/" % feature_flag["id"],
            data={"name": "Beta feature 3", "key": "beta-feature"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(FeatureFlag.objects.get(pk=feature_flag["id"]).name, "Beta feature 3")

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
            content_type="application/json",
            format="json",
        ).json()
        self.assertFalse(feature_flag["is_simple_flag"])
        self.assertIsNone(feature_flag["rollout_percentage"])


class TestAPIFeatureFlag(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.organization, self.team, self.user = User.objects.bootstrap("Feature Flags", "ff@posthog.com", None)
        self.feature_flag = FeatureFlag.objects.create(team=self.team, created_by=self.user, key="red_button",)

    @patch("posthoganalytics.capture")
    def test_creating_feature_flag(self, mock_capture):
        self.client.force_login(self.user)

        response = self.client.post(
            "/api/feature_flag/",
            {"name": "Alpha feature", "key": "alpha-feature", "filters": {"groups": [{"rollout_percentage": 50}]}},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        instance = FeatureFlag.objects.get(id=response.data["id"])  # type: ignore
        self.assertEqual(instance.key, "alpha-feature")

        # Assert analytics are sent
        mock_capture.assert_called_once_with(
            self.user.distinct_id,
            "feature flag created",
            {
                "groups_count": 1,
                "has_rollout_percentage": True,
                "has_filters": False,
                "filter_count": 0,
                "created_at": instance.created_at,
            },
        )

    @patch("posthoganalytics.capture")
    def test_updating_feature_flag(self, mock_capture):
        instance = self.feature_flag
        self.client.force_login(self.user)

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
                "has_rollout_percentage": False,
                "has_filters": False,
                "filter_count": 0,
                "created_at": instance.created_at,
            },
        )

    @patch("posthoganalytics.capture")
    def test_cannot_delete_feature_flag_on_another_team(self, mock_capture):
        organization, team, user = User.objects.bootstrap("Test", "team2@posthog.com", None)

        self.client.force_login(user)

        response = self.client.delete(f"/api/feature_flag/{self.feature_flag.pk}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertTrue(FeatureFlag.objects.filter(pk=self.feature_flag.pk).exists())

        mock_capture.assert_not_called()

    def test_creating_a_feature_flag_with_same_team_and_key_after_deleting(self):
        FeatureFlag.objects.create(team=self.team, created_by=self.user, key="alpha-feature", deleted=True)

        self.client.force_login(self.user)

        response = self.client.post("/api/feature_flag/", {"name": "Alpha feature", "key": "alpha-feature"},)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        instance = FeatureFlag.objects.get(id=response.data["id"])  # type: ignore
        self.assertEqual(instance.key, "alpha-feature")

    def test_updating_a_feature_flag_with_same_team_and_key_of_a_deleted_one(self):
        FeatureFlag.objects.create(team=self.team, created_by=self.user, key="alpha-feature", deleted=True)

        self.client.force_login(self.user)

        instance = FeatureFlag.objects.create(team=self.team, created_by=self.user, key="beta-feature")

        response = self.client.patch(f"/api/feature_flag/{instance.pk}", {"key": "alpha-feature",}, format="json",)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        instance.refresh_from_db()
        self.assertEqual(instance.key, "alpha-feature")
