from rest_framework import status
from reversion import is_registered
from reversion.models import Version

from posthog.models import FeatureFlag, Insight, Person
from posthog.test.base import APIBaseTest


class TestTeamAwareVersioningMiddleware(APIBaseTest):
    def _create_feature_flag(self) -> int:
        response = self.client.post(
            f"/api/projects/{self.team.pk}/feature_flags", {"name": "Beta feature", "key": "red_button"}
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        return response.json()["id"]

    def _update_feature_flag(self, feature_flag_id) -> None:
        update_response = self.client.patch(
            f"/api/projects/{self.team.pk}/feature_flags/{feature_flag_id}",
            {"name": "Beta feature", "key": "red_button"},
        )
        self.assertEqual(update_response.status_code, status.HTTP_200_OK)

    def test_we_can_create_a_revision_of_feature_flags(self):
        feature_flag_id = self._create_feature_flag()
        versions = Version.objects.get_for_object(FeatureFlag.objects.get(pk=feature_flag_id))
        self.assertEqual(len(versions), 1)

    def test_we_can_create_two_revisions_of_feature_flags(self):
        feature_flag_id = self._create_feature_flag()

        self._update_feature_flag(feature_flag_id)

        versions = Version.objects.get_for_object(FeatureFlag.objects.get(pk=feature_flag_id))
        self.assertEqual(len(versions), 2)

    def test_gets_are_ignored(self):
        feature_flag_id = self._create_feature_flag()

        get_response = self.client.get(
            f"/api/projects/{self.team.pk}/feature_flags/{feature_flag_id}",
            {"name": "Beta feature", "key": "red_button"},
        )
        self.assertEqual(get_response.status_code, status.HTTP_200_OK)

        versions = Version.objects.get_for_object(FeatureFlag.objects.get(pk=feature_flag_id))
        self.assertEqual(len(versions), 1)

    def test_option_is_ignored(self):
        feature_flag_id = self._create_feature_flag()

        get_response = self.client.options(
            f"/api/projects/{self.team.pk}/feature_flags/{feature_flag_id}",
            {"name": "Beta feature", "key": "red_button"},
        )
        self.assertEqual(get_response.status_code, status.HTTP_200_OK)

        versions = Version.objects.get_for_object(FeatureFlag.objects.get(pk=feature_flag_id))
        self.assertEqual(len(versions), 1)

    def test_head_is_ignored(self):
        feature_flag_id = self._create_feature_flag()

        get_response = self.client.head(
            f"/api/projects/{self.team.pk}/feature_flags/{feature_flag_id}",
            {"name": "Beta feature", "key": "red_button"},
        )
        self.assertEqual(get_response.status_code, 200)

        versions = Version.objects.get_for_object(FeatureFlag.objects.get(pk=feature_flag_id))
        self.assertEqual(len(versions), 1)

    def test_can_create_a_revision_of_an_insight(self):
        post_response = self.client.post(f"/api/projects/{self.team.id}/insights/")
        self.assertEqual(post_response.status_code, status.HTTP_201_CREATED)
        insight_id = post_response.json()["id"]

        versions = Version.objects.get_for_object(Insight.objects.get(pk=insight_id))
        self.assertEqual(len(versions), 1)

        patch_response = self.client.patch(f"/api/projects/{self.team.id}/insights/{insight_id}")
        self.assertEqual(patch_response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(Version.objects.get_for_object(Insight.objects.get(pk=insight_id))), 2)

    def test_no_revisions_other_than_for_known_models(self):
        """
        Instead of testing all seven registered plugins individually test that they are all registered with Reversion
        """
        from django.apps import apps

        all_models = apps.all_models["posthog"]

        registered_models = ["insight", "team", "organization", "user", "featureflag", "plugin", "pluginconfig"]

        for model in [m for m in all_models.items() if m[0] not in registered_models]:
            is_model_registered = is_registered(model[1])
            self.assertFalse(is_model_registered, msg=f"expected {model[0]} not to be registered with reversion")
