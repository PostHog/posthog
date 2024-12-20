from rest_framework import status

from posthog.models import AlertConfiguration, EarlyAccessFeature, Feature, FeatureAlertConfiguration, Insight
from posthog.test.base import APIBaseTest


class TestFeatureAPI(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.early_access_feature = EarlyAccessFeature.objects.create(
            team=self.team,
            name="Test EAF",
            description="Test Description",
        )
        self.feature = Feature.objects.create(
            team=self.team,
            name="Test Feature",
            description="Test Description",
            primary_early_access_feature=self.early_access_feature,
        )

    def test_list_features(self):
        response = self.client.get(f"/api/projects/{self.team.id}/features/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["results"]), 1)
        self.assertEqual(response.json()["results"][0]["name"], "Test Feature")
        self.assertEqual(
            response.json()["results"][0]["primary_early_access_feature_id"], f"{self.early_access_feature.id}"
        )

        # Ensure we are not returning joined data
        with self.assertRaises(KeyError):
            response.json()["results"][0]["alerts"]
        with self.assertRaises(KeyError):
            response.json()["results"][0]["primary_early_access_feature"]

    def test_retrieve_feature(self):
        eaf = EarlyAccessFeature.objects.create(
            team=self.team,
            name="Test EAF",
            description="Test Description",
        )
        self.feature.primary_early_access_feature = eaf

        response = self.client.get(f"/api/projects/{self.team.id}/features/{self.feature.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["name"], "Test Feature")
        self.assertEqual(response.json()["description"], "Test Description")

        # Ensure we are not returning joined data
        with self.assertRaises(KeyError):
            response.json()["results"][0]["alerts"]
        with self.assertRaises(KeyError):
            response.json()["results"][0]["primary_early_access_feature"]

    def test_create_feature(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/features/",
            {
                "name": "New Feature",
                "team_id": self.team.id,
                "description": "New Description",
                "primary_early_access_feature_id": self.early_access_feature.id,
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
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["name"], "Updated Feature")

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
        self.assertEqual(response.json()["name"], "Test Flag")

    def test_get_alerts(self):
        insight = Insight.objects.create(
            team=self.team,
            filters={"events": [{"id": "$pageview", "type": "events", "name": "pageview"}]},
        )
        alert = AlertConfiguration.objects.create(team=self.team, name="Test Alert", insight=insight)
        FeatureAlertConfiguration.objects.create(
            team=self.team,
            feature=self.feature,
            alert_configuration=alert,
            feature_insight_type="success_metric",
        )

        response = self.client.get(f"/api/projects/{self.team.id}/features/{self.feature.id}/alerts/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()), 1)
        self.assertEqual(response.json()[0]["feature_insight_type"], "success_metric")
