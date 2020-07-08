from .base import BaseTest, TransactionBaseTest
from posthog.models import FeatureFlag


class TestFeatureFlagApi(TransactionBaseTest):
    TESTS_API = True

    def test_key_exists(self):
        feature_flag = self.client.post(
            "/api/feature_flag/",
            data={"name": "Beta feature", "key": "beta-feature", "rollout_percentage": 50,},
            content_type="application/json",
        ).json()
        self.assertEqual(FeatureFlag.objects.get(pk=feature_flag["id"]).name, "Beta feature")

        response = self.client.post(
            "/api/feature_flag/", data={"name": "Beta feature", "key": "beta-feature"}, content_type="application/json",
        ).json()

        self.assertEqual(response[0], "key-exists")

        another_feature_flag = FeatureFlag.objects.create(
            team=self.team, rollout_percentage=50, name="some feature", key="some-feature", created_by=self.user,
        )
        # try updating into an existing feature flag
        response = self.client.patch(
            "/api/feature_flag/%s/" % another_feature_flag.pk,
            data={"name": "Beta feature", "key": "beta-feature"},
            content_type="application/json",
        ).json()
        self.assertEqual(response[0], "key-exists")

        # try updating the existing one
        response = self.client.patch(
            "/api/feature_flag/%s/" % feature_flag["id"],
            data={"name": "Beta feature 3", "key": "beta-feature"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(FeatureFlag.objects.get(pk=feature_flag["id"]).name, "Beta feature 3")
