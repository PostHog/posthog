from rest_framework import status

from posthog.models import Feature, FeatureFlag, Experiment, EarlyAccessFeature, Team
from posthog.test.base import APIBaseTest


class TestFeatureAPI(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.feature = Feature.objects.create(
            team=self.team,
            name="Test Feature",
            description="Test Description",
            documentation_url="http://example.com",
            issue_url="http://github.com/example",
        )

    def test_list_features(self):
        # Create a feature flag and experiment for the feature, ensure they are not returned in the response
        Experiment.objects.create(
            team=self.team,
            name="Test Experiment",
            feature_management=self.feature,
            feature_flag=FeatureFlag.objects.create(
                team=self.team,
                name="Test Flag for Experiment",
                key="test-flag-for-experiment-list",
                feature_management=self.feature,
            ),
        )
        EarlyAccessFeature.objects.create(
            team=self.team,
            name="Test EAF",
            description="Test Description",
            feature_management=self.feature,
        )

        response = self.client.get(f"/api/projects/{self.team.id}/features/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["results"]), 1)
        self.assertEqual(response.json()["results"][0]["name"], "Test Feature")

        # Ensure we are not returning joined data
        with self.assertRaises(KeyError):
            response.json()["results"][0]["experiments"]
        with self.assertRaises(KeyError):
            response.json()["results"][0]["feature_flags"]
        with self.assertRaises(KeyError):
            response.json()["results"][0]["early_access_features"]

    def test_retrieve_feature(self):
        Experiment.objects.create(
            team=self.team,
            name="Test Experiment",
            feature_management=self.feature,
            feature_flag=FeatureFlag.objects.create(
                team=self.team,
                name="Test Flag for Experiment",
                key="test-flag-for-experiment-retrieve",
                feature_management=self.feature,
            ),
        )
        EarlyAccessFeature.objects.create(
            team=self.team,
            name="Test EAF",
            description="Test Description",
            feature_management=self.feature,
        )

        response = self.client.get(f"/api/projects/{self.team.id}/features/{self.feature.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["name"], "Test Feature")
        self.assertEqual(response.json()["description"], "Test Description")

        # Ensure we are not returning joined data
        with self.assertRaises(KeyError):
            response.json()["experiments"]
        with self.assertRaises(KeyError):
            response.json()["feature_flags"]
        with self.assertRaises(KeyError):
            response.json()["early_access_features"]

    def test_create_feature(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/features/",
            {
                "name": "New Feature",
                "team_id": self.team.id,
                "description": "New Description",
                "documentation_url": "http://example.com/new",
                "issue_url": "http://github.com/example/new",
                "status": "alpha",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["name"], "New Feature")
        self.assertEqual(Feature.objects.count(), 2)

    def test_update_feature(self):
        response = self.client.patch(
            f"/api/projects/{self.team.id}/features/{self.feature.id}/",
            {
                "name": "Updated Feature",
                "status": "beta",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["name"], "Updated Feature")
        self.assertEqual(response.json()["status"], "beta")

    def test_delete_not_allowed(self):
        response = self.client.delete(f"/api/projects/{self.team.id}/features/{self.feature.id}/")
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_get_primary_early_access_feature(self):
        eaf = EarlyAccessFeature.objects.create(
            team=self.team,
            name="Test Flag",
        )
        self.feature.primary_early_access_feature = eaf
        self.feature.save()

        response = self.client.get(
            f"/api/projects/{self.team.id}/features/{self.feature.id}/primary_early_access_feature/"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["key"], "test-flag")

    def test_get_experiments(self):
        Experiment.objects.create(
            team=self.team,
            name="Test Experiment",
            feature_flag=FeatureFlag.objects.create(
                team=self.team,
                name="Test Flag",
                key="test-flag",
            ),
            feature_management=self.feature,
            description="Test Description",
        )

        response = self.client.get(f"/api/projects/{self.team.id}/features/{self.feature.id}/experiments/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()), 1)
        self.assertEqual(response.json()[0]["name"], "Test Experiment")

    def test_get_early_access_features(self):
        EarlyAccessFeature.objects.create(
            team=self.team,
            name="Test EAF",
            description="Test Description",
            feature_management=self.feature,
        )

        response = self.client.get(f"/api/projects/{self.team.id}/features/{self.feature.id}/early_access_features/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()), 1)
        self.assertEqual(response.json()[0]["name"], "Test EAF")

    def test_get_feature_flags(self):
        FeatureFlag.objects.create(
            team=self.team,
            name="Test Flag",
            key="test-flag",
            feature_management=self.feature,
        )

        response = self.client.get(f"/api/projects/{self.team.id}/features/{self.feature.id}/feature_flags/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()), 1)
        self.assertEqual(response.json()[0]["key"], "test-flag")

    def test_cannot_create_feature_without_name(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/features/",
            {
                "team": self.team.id,
                "description": "New Description",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("name", response.json()["attr"])

    def test_cannot_access_feature_from_another_team(self):
        other_team = Team.objects.create(
            organization=self.organization,
            api_token=self.CONFIG_API_TOKEN + "2",
            test_account_filters=[
                {
                    "key": "email",
                    "value": "@posthog.com",
                    "operator": "not_icontains",
                    "type": "person",
                }
            ],
        )
        other_feature = Feature.objects.create(
            team=other_team,
            name="Other Feature",
        )

        response = self.client.get(f"/api/projects/{self.team.id}/features/{other_feature.id}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
