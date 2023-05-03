from unittest.mock import ANY

from rest_framework import status
from django.core.cache import cache
from django.test.client import Client

from posthog.models.early_access_feature import EarlyAccessFeature
from posthog.models import FeatureFlag, Person
from posthog.test.base import APIBaseTest, BaseTest, QueryMatchingTest, snapshot_postgres_queries


class TestEarlyAccessFeature(APIBaseTest):
    maxDiff = None

    def test_can_create_early_access_feature(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/early_access_feature/",
            data={
                "name": "Hick bondoogling",
                "description": 'Boondoogle your hicks with one click. Just click "bazinga"!',
                "stage": "concept",
                "feature_flag_key": "hick-bondoogling",
            },
            format="json",
        )
        response_data = response.json()

        assert response.status_code == status.HTTP_201_CREATED, response_data
        assert EarlyAccessFeature.objects.filter(id=response_data["id"]).exists()
        assert FeatureFlag.objects.filter(key=response_data["feature_flag"]["key"]).exists()
        assert response_data["name"] == "Hick bondoogling"
        assert response_data["description"] == 'Boondoogle your hicks with one click. Just click "bazinga"!'
        assert response_data["stage"] == "concept"
        assert response_data["feature_flag"]["key"] == "hick-bondoogling"
        assert response_data["feature_flag"]["active"]
        assert len(response_data["feature_flag"]["filters"]["super_groups"]) == 2
        assert len(response_data["feature_flag"]["filters"]["groups"]) == 1
        assert isinstance(response_data["created_at"], str)

    def test_can_promote_early_access_feature(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/early_access_feature/",
            data={
                "name": "Hick bondoogling",
                "description": 'Boondoogle your hicks with one click. Just click "bazinga"!',
                "stage": "concept",
                "feature_flag_key": "hick-bondoogling",
            },
            format="json",
        )
        response_data = response.json()

        assert response.status_code == status.HTTP_201_CREATED, response_data

        response = self.client.post(
            f"/api/projects/{self.team.id}/early_access_feature/" + str(response_data["id"]) + "/promote/",
            format="json",
        )
        response_data = response.json()

        assert len(response_data["feature_flag"]["filters"]["super_groups"]) == 1
        assert response_data["feature_flag"]["filters"]["super_groups"][0]["properties"] == []
        assert response_data["feature_flag"]["filters"]["super_groups"][0]["rollout_percentage"] == 100

    def test_can_edit_feature(self):
        feature = EarlyAccessFeature.objects.create(
            team=self.team,
            name="Click counter",
            description="A revolution in usability research: now you can count clicks!",
            stage="beta",
        )

        response = self.client.patch(
            f"/api/projects/{self.team.id}/early_access_feature/{feature.id}",
            data={
                "name": "Mouse-up counter",
                "description": "Oops, we made a mistake, it actually only counts mouse-up events.",
            },
            format="json",
        )
        response_data = response.json()

        feature.refresh_from_db()
        assert response.status_code == status.HTTP_200_OK, response_data
        assert response_data["name"] == "Mouse-up counter"
        assert response_data["description"] == "Oops, we made a mistake, it actually only counts mouse-up events."
        assert response_data["stage"] == "beta"
        assert feature.name == "Mouse-up counter"

    def test_can_list_features(self):
        EarlyAccessFeature.objects.create(
            team=self.team,
            name="Click counter",
            description="A revolution in usability research: now you can count clicks!",
            stage="beta",
        )

        response = self.client.get(f"/api/projects/{self.team.id}/early_access_feature/")
        response_data = response.json()

        assert response.status_code == status.HTTP_200_OK, response_data
        assert response_data == {
            "count": 1,
            "next": None,
            "previous": None,
            "results": [
                {
                    "created_at": ANY,
                    "description": "A revolution in usability research: now you can count clicks!",
                    "documentation_url": "",
                    "feature_flag": None,
                    "id": ANY,
                    "name": "Click counter",
                    "stage": "beta",
                },
            ],
        }


class TestPreviewList(BaseTest, QueryMatchingTest):
    def setUp(self):
        cache.clear()
        super().setUp()
        # it is really important to know that /decide is CSRF exempt. Enforce checking in the client
        self.client = Client(enforce_csrf_checks=True)
        self.client.force_login(self.user)

    def _get_features(
        self,
        token=None,
        origin="http://127.0.0.1:8000",
        ip="127.0.0.1",
    ):
        return self.client.get(
            f"/api/early_access_features/",
            data={"token": token or self.team.api_token},
            HTTP_ORIGIN=origin,
            REMOTE_ADDR=ip,
        )

    @snapshot_postgres_queries
    def test_early_access_features(self):
        Person.objects.create(team=self.team, distinct_ids=["example_id"], properties={"email": "example@posthog.com"})

        feature_flag = FeatureFlag.objects.create(
            team=self.team,
            name=f"Feature Flag for Feature Sprocket",
            key="sprocket",
            rollout_percentage=0,
            created_by=self.user,
        )
        feature_flag2 = FeatureFlag.objects.create(
            team=self.team,
            name=f"Feature Flag for Feature Sprocket",
            key="sprocket2",
            rollout_percentage=10,
            created_by=self.user,
        )
        feature = EarlyAccessFeature.objects.create(
            team=self.team,
            name="Sprocket",
            description="A fancy new sprocket.",
            stage="beta",
            feature_flag=feature_flag,
        )
        feature2 = EarlyAccessFeature.objects.create(
            team=self.team,
            name="Sprocket",
            description="A fancy new sprocket.",
            stage="alpha",
            feature_flag=feature_flag2,
        )

        self.client.logout()

        with self.assertNumQueries(2):
            response = self._get_features()
            self.assertEqual(response.status_code, 200)
            self.assertListEqual(
                response.json()["earlyAccessFeatures"],
                [
                    {
                        "id": str(feature.id),
                        "name": "Sprocket",
                        "description": "A fancy new sprocket.",
                        "stage": "beta",
                        "documentationUrl": "",
                        "flagKey": "sprocket",
                    },
                    {
                        "id": str(feature2.id),
                        "name": "Sprocket",
                        "description": "A fancy new sprocket.",
                        "stage": "alpha",
                        "documentationUrl": "",
                        "flagKey": "sprocket2",
                    },
                ],
            )

    def test_early_access_features_errors_out_on_random_token(self):
        self.client.logout()

        with self.assertNumQueries(1):
            response = self._get_features(token="random_token")
            self.assertEqual(response.status_code, 401)
            self.assertEqual(
                response.json()["detail"],
                "Project API key invalid. You can find your project API key in PostHog project settings.",
            )

    def test_early_access_features_errors_out_on_no_token(self):
        self.client.logout()

        with self.assertNumQueries(0):
            response = self.client.get(f"/api/early_access_features/")
            self.assertEqual(response.status_code, 401)
            self.assertEqual(
                response.json()["detail"],
                "API key not provided. You can find your project API key in PostHog project settings.",
            )
