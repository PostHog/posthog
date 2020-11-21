from unittest.mock import patch

from rest_framework import status

from posthog.models import FeatureFlag, User

from .base import APIBaseTest, TransactionBaseTest


class TestFeatureFlag(TransactionBaseTest):
    TESTS_API = True

    def test_key_exists(self):
        feature_flag = self.create_feature_flag()
        self.assertEqual(FeatureFlag.objects.get(pk=feature_flag["id"]).name, "Beta feature")
        self.assertTrue(feature_flag["is_simple_flag"])

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
        response = self.update_feature_flag(another_feature_flag.pk, name="Beta feature", key="beta-feature")
        self.assertEqual(
            response,
            {"type": "validation_error", "code": "key-exists", "detail": "This key already exists.", "attr": None},
        )

        # try updating the existing one
        response = self.update_feature_flag(
            feature_flag["id"], formatAsJson=False, name="Beta feature 3", key="beta-feature"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(FeatureFlag.objects.get(pk=feature_flag["id"]).name, "Beta feature 3")

    def test_re_adding_feature_flag_after_deleting(self):
        # Adding new feature flag
        feature_flag = self.create_feature_flag()
        self.assertEqual(FeatureFlag.objects.get(pk=feature_flag["id"]).name, "Beta feature")

        # Deleting the feature flag
        self.delete_feature_flag(feature_flag["id"])
        self.assertEqual(FeatureFlag.objects.get(pk=feature_flag["id"]).deleted, True)

        # Adding new feature flag with same key, diffrent name
        re_adding_feature_flag = self.create_feature_flag(name="diffrent name", key="beta-feature")
        self.assertNotEqual(
            re_adding_feature_flag,
            {"type": "validation_error", "code": "key-exists", "detail": "This key already exists.", "attr": None},
        )
        self.assertEqual(FeatureFlag.objects.get(pk=re_adding_feature_flag["id"]).name, "diffrent name")

    def test_is_simple_flag(self):
        feature_flag = self.client.post(
            "/api/feature_flag/",
            data={
                "name": "Beta feature",
                "key": "beta-feature",
                "rollout_percentage": 50,
                "filters": {"properties": [{"key": "email", "value": "tim@posthog.com"}]},
            },
            content_type="application/json",
        ).json()
        self.assertFalse(feature_flag["is_simple_flag"])

    def create_feature_flag(
        self, name: str = "Beta feature", key: str = "beta-feature", rollout_percentage: int = 50, **kwargs
    ):
        return self.client.post(
            "/api/feature_flag/",
            data={"name": name, "key": key, "rollout_percentage": rollout_percentage, **kwargs},
            content_type="application/json",
        ).json()

    def update_feature_flag(self, id: int, formatAsJson: bool = True, **kwargs):
        response = self.client.patch("/api/feature_flag/%s/" % id, data=kwargs, content_type="application/json",)

        return response.json() if formatAsJson else response

    def delete_feature_flag(self, id: int):
        return self.update_feature_flag(id, deleted=True)


class TestAPIFeatureFlag(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.organization, self.team, self.user = User.objects.bootstrap("Feature Flags", "ff@posthog.com", None)
        self.feature_flag = FeatureFlag.objects.create(team=self.team, created_by=self.user, key="red_button",)

    @patch("posthoganalytics.capture")
    def test_creating_feature_flag(self, mock_capture):
        self.client.force_login(self.user)

        response = self.client.post(
            "/api/feature_flag/", {"name": "Alpha feature", "key": "alpha-feature", "rollout_percentage": 50,},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        instance = FeatureFlag.objects.get(id=response.data["id"])  # type: ignore
        self.assertEqual(instance.key, "alpha-feature")

        # Assert analytics are sent
        mock_capture.assert_called_once_with(
            self.user.distinct_id,
            "feature flag created",
            {"rollout_percentage": 50, "has_filters": False, "filter_count": 0, "created_at": instance.created_at,},
        )

    @patch("posthoganalytics.capture")
    def test_updating_feature_flag(self, mock_capture):
        instance = self.feature_flag
        self.client.force_login(self.user)

        response = self.client.patch(
            f"/api/feature_flag/{instance.pk}",
            {
                "name": "Updated name",
                "rollout_percentage": 65,
                "filters": {
                    "properties": [
                        {"key": "email", "type": "person", "value": "@posthog.com", "operator": "icontains",},
                    ],
                },
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        instance.refresh_from_db()
        self.assertEqual(instance.name, "Updated name")
        self.assertEqual(instance.rollout_percentage, 65)

        # Assert analytics are sent
        mock_capture.assert_called_once_with(
            self.user.distinct_id,
            "feature flag updated",
            {"rollout_percentage": 65, "has_filters": True, "filter_count": 1, "created_at": instance.created_at,},
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
            {"rollout_percentage": None, "has_filters": False, "filter_count": 0, "created_at": instance.created_at,},
        )

    @patch("posthoganalytics.capture")
    def test_cannot_delete_feature_flag_on_another_team(self, mock_capture):
        organization, team, user = User.objects.bootstrap("Test", "team2@posthog.com", None)

        self.client.force_login(user)

        response = self.client.delete(f"/api/feature_flag/{self.feature_flag.pk}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertTrue(FeatureFlag.objects.filter(pk=self.feature_flag.pk).exists())

        mock_capture.assert_not_called()
