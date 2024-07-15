from unittest.mock import ANY

from rest_framework import status
from django.core.cache import cache
from django.test.client import Client

from posthog.models.early_access_feature import EarlyAccessFeature
from posthog.models import FeatureFlag, Person
from posthog.test.base import (
    APIBaseTest,
    BaseTest,
    QueryMatchingTest,
    snapshot_postgres_queries,
)


class TestEarlyAccessFeature(APIBaseTest):
    maxDiff = None

    def test_can_create_early_access_feature(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/early_access_feature/",
            data={
                "name": "Hick bondoogling",
                "description": 'Boondoogle your hicks with one click. Just click "bazinga"!',
                "stage": "concept",
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
        assert not response_data["feature_flag"]["filters"].get("super_groups", None)
        assert len(response_data["feature_flag"]["filters"]["groups"]) == 1
        assert response_data["feature_flag"]["filters"]["groups"][0]["rollout_percentage"] == 0
        assert isinstance(response_data["created_at"], str)

    def test_promote_to_beta(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/early_access_feature/",
            data={
                "name": "Hick bondoogling",
                "description": 'Boondoogle your hicks with one click. Just click "bazinga"!',
                "stage": "concept",
            },
            format="json",
        )
        response_data = response.json()

        assert response.status_code == status.HTTP_201_CREATED, response_data

        feature_id = response_data["id"]

        response = self.client.patch(
            f"/api/projects/{self.team.id}/early_access_feature/{feature_id}",
            data={
                "stage": EarlyAccessFeature.Stage.BETA,
            },
            format="json",
        )
        response_data = response.json()

        assert response.status_code == status.HTTP_200_OK, response_data
        assert response_data["stage"] == EarlyAccessFeature.Stage.BETA
        assert len(response_data["feature_flag"]["filters"]["super_groups"]) == 1

    def test_archive(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/early_access_feature/",
            data={
                "name": "Hick bondoogling",
                "description": 'Boondoogle your hicks with one click. Just click "bazinga"!',
                "stage": "beta",
            },
            format="json",
        )
        response_data = response.json()

        assert response.status_code == status.HTTP_201_CREATED, response_data
        assert len(response_data["feature_flag"]["filters"]["super_groups"]) == 1

        feature_id = response_data["id"]

        response = self.client.patch(
            f"/api/projects/{self.team.id}/early_access_feature/{feature_id}",
            data={
                "stage": EarlyAccessFeature.Stage.ARCHIVED,
            },
            format="json",
        )
        response_data = response.json()

        assert response.status_code == status.HTTP_200_OK, response_data
        assert response_data["stage"] == EarlyAccessFeature.Stage.ARCHIVED
        assert not response_data["feature_flag"]["filters"].get("super_groups", None)

    def test_update_doesnt_remove_super_condition(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/early_access_feature/",
            data={
                "name": "Hick bondoogling",
                "description": 'Boondoogle your hicks with one click. Just click "bazinga"!',
                "stage": "beta",
            },
            format="json",
        )
        response_data = response.json()

        assert response.status_code == status.HTTP_201_CREATED, response_data
        assert len(response_data["feature_flag"]["filters"]["super_groups"]) == 1

        feature_id = response_data["id"]

        response = self.client.patch(
            f"/api/projects/{self.team.id}/early_access_feature/{feature_id}",
            data={
                "description": "Something else!",
            },
            format="json",
        )
        response_data = response.json()

        assert response.status_code == status.HTTP_200_OK, response_data
        assert response_data["stage"] == EarlyAccessFeature.Stage.BETA
        assert response_data["description"] == "Something else!"
        assert len(response_data["feature_flag"]["filters"]["super_groups"]) == 1

    def test_we_dont_delete_existing_flag_information_when_creating_early_access_feature(self):
        flag = FeatureFlag.objects.create(
            team=self.team,
            filters={
                "groups": [
                    {
                        "properties": [{"key": "xyz", "value": "ok", "type": "person"}],
                        "rollout_percentage": None,
                    }
                ],
                "payloads": {"true": "Hick bondoogling? ????"},
            },
            key="hick-bondoogling",
            created_by=self.user,
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/early_access_feature/",
            data={
                "name": "Hick bondoogling",
                "description": 'Boondoogle your hicks with one click. Just click "bazinga"!',
                "stage": "beta",
                "feature_flag_id": flag.id,
            },
            format="json",
        )
        response_data = response.json()

        assert response.status_code == status.HTTP_201_CREATED, response_data
        assert EarlyAccessFeature.objects.filter(id=response_data["id"]).exists()
        assert FeatureFlag.objects.filter(key=response_data["feature_flag"]["key"]).exists()

        flag.refresh_from_db()
        self.assertEqual(
            flag.filters,
            {
                "groups": [
                    {
                        "properties": [{"key": "xyz", "value": "ok", "type": "person"}],
                        "rollout_percentage": None,
                    }
                ],
                "payloads": {"true": "Hick bondoogling? ????"},
                "super_groups": [
                    {
                        "properties": [
                            {
                                "key": "$feature_enrollment/hick-bondoogling",
                                "operator": "exact",
                                "type": "person",
                                "value": ["true"],
                            }
                        ],
                        "rollout_percentage": 100,
                    }
                ],
            },
        )

    def test_cant_create_early_access_feature_with_duplicate_key(self):
        FeatureFlag.objects.create(
            team=self.team,
            filters={"groups": [{"properties": [], "rollout_percentage": None}]},
            key="hick-bondoogling",
            created_by=self.user,
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/early_access_feature/",
            data={
                "name": "Hick bondoogling",
                "description": 'Boondoogle your hicks with one click. Just click "bazinga"!',
                "stage": "beta",
            },
            format="json",
        )
        response_data = response.json()

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response_data

        self.assertEqual(
            response_data["detail"],
            "There is already a feature flag with this key.",
        )

    def test_can_create_new_early_access_feature_with_soft_deleted_flag(self):
        FeatureFlag.objects.create(
            team=self.team,
            filters={"groups": [{"properties": [], "rollout_percentage": None}]},
            key="hick-bondoogling",
            created_by=self.user,
            deleted=True,
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/early_access_feature/",
            data={
                "name": "Hick bondoogling",
                "description": 'Boondoogle your hicks with one click. Just click "bazinga"!',
                "stage": "beta",
            },
            format="json",
        )
        response_data = response.json()

        assert response.status_code == status.HTTP_201_CREATED, response_data

        assert response.status_code == status.HTTP_201_CREATED, response_data
        assert EarlyAccessFeature.objects.filter(id=response_data["id"]).exists()
        assert FeatureFlag.objects.filter(key=response_data["feature_flag"]["key"]).exists()
        assert response_data["name"] == "Hick bondoogling"
        assert response_data["description"] == 'Boondoogle your hicks with one click. Just click "bazinga"!'
        assert response_data["stage"] == "beta"
        assert response_data["feature_flag"]["key"] == "hick-bondoogling"
        assert response_data["feature_flag"]["active"]
        assert len(response_data["feature_flag"]["filters"]["super_groups"]) == 1
        assert len(response_data["feature_flag"]["filters"]["groups"]) == 1
        assert response_data["feature_flag"]["filters"]["groups"][0]["rollout_percentage"] == 0
        assert isinstance(response_data["created_at"], str)

    def test_deleting_early_access_feature_removes_super_condition_from_flag(self):
        existing_flag = FeatureFlag.objects.create(
            team=self.team,
            filters={
                "groups": [
                    {
                        "properties": [{"key": "xyz", "value": "ok", "type": "person"}],
                        "rollout_percentage": None,
                    }
                ]
            },
            key="hick-bondoogling",
            created_by=self.user,
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/early_access_feature/",
            data={
                "name": "Hick bondoogling",
                "description": 'Boondoogle your hicks with one click. Just click "bazinga"!',
                "stage": "beta",
                "feature_flag_id": existing_flag.id,
            },
            format="json",
        )
        response_data = response.json()

        assert response.status_code == status.HTTP_201_CREATED, response_data

        response = self.client.delete(
            f"/api/projects/{self.team.id}/early_access_feature/{response_data['id']}/",
            format="json",
        )

        assert response.status_code == status.HTTP_204_NO_CONTENT
        flag = FeatureFlag.objects.filter(key=response_data["feature_flag"]["key"]).all()[0]

        self.assertEqual(
            flag.filters,
            {
                "groups": [
                    {
                        "properties": [{"key": "xyz", "value": "ok", "type": "person"}],
                        "rollout_percentage": None,
                    }
                ],
                "super_groups": None,
            },
        )

    def test_cant_soft_delete_flag_with_early_access_feature(self):
        existing_flag = FeatureFlag.objects.create(
            team=self.team,
            filters={
                "groups": [
                    {
                        "properties": [{"key": "xyz", "value": "ok", "type": "person"}],
                        "rollout_percentage": None,
                    }
                ]
            },
            key="hick-bondoogling",
            created_by=self.user,
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/early_access_feature/",
            data={
                "name": "Hick bondoogling",
                "description": 'Boondoogle your hicks with one click. Just click "bazinga"!',
                "stage": "beta",
                "feature_flag_id": existing_flag.id,
            },
            format="json",
        )
        response_data = response.json()

        assert response.status_code == status.HTTP_201_CREATED, response_data

        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{existing_flag.id}/",
            data={
                "deleted": True,
            },
            format="json",
        )
        response_data = response.json()

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response_data

        assert (
            response_data["detail"]
            == "Cannot delete a feature flag that is in use with early access features. Please delete the early access feature before deleting the flag."
        )

    def test_cant_create_early_access_feature_with_group_flag(self):
        flag = FeatureFlag.objects.create(
            team=self.team,
            filters={
                "groups": [{"properties": [], "rollout_percentage": None}],
                "aggregation_group_type_index": 1,
            },
            key="hick-bondoogling",
            created_by=self.user,
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/early_access_feature/",
            data={
                "name": "Hick bondoogling",
                "description": 'Boondoogle your hicks with one click. Just click "bazinga"!',
                "stage": "beta",
                "feature_flag_id": flag.id,
            },
            format="json",
        )
        response_data = response.json()

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response_data

        self.assertEqual(
            response_data["detail"],
            "Group-based feature flags are not supported for Early Access Features.",
        )

    def test_cant_create_early_access_feature_with_multivariate_flag(self):
        flag = FeatureFlag.objects.create(
            team=self.team,
            filters={
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
            key="hick-bondoogling",
            created_by=self.user,
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/early_access_feature/",
            data={
                "name": "Hick bondoogling",
                "description": 'Boondoogle your hicks with one click. Just click "bazinga"!',
                "stage": "beta",
                "feature_flag_id": flag.id,
            },
            format="json",
        )
        response_data = response.json()

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response_data

        self.assertEqual(
            response_data["detail"],
            "Multivariate feature flags are not supported for Early Access Features.",
        )

    def test_cant_create_early_access_feature_with_flag_with_existing_early_access_feature(self):
        flag = FeatureFlag.objects.create(
            team=self.team,
            filters={
                "groups": [{"properties": [], "rollout_percentage": None}],
            },
            key="hick-bondoogling",
            created_by=self.user,
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/early_access_feature/",
            data={
                "name": "Hick bondoogling",
                "description": 'Boondoogle your hicks with one click. Just click "bazinga"!',
                "stage": "beta",
                "feature_flag_id": flag.id,
            },
            format="json",
        )

        # Request for new feature with same flag id should fail
        response = self.client.post(
            f"/api/projects/{self.team.id}/early_access_feature/",
            data={
                "name": "Another feature",
                "description": 'Boondoogle your hicks AGAIN with one click. Just click "bazinga"!',
                "stage": "beta",
                "feature_flag_id": flag.id,
            },
            format="json",
        )
        response_data = response.json()

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response_data

        self.assertEqual(
            response_data["detail"],
            "Linked feature flag hick-bondoogling already has a feature attached to it.",
        )

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
            headers={"origin": origin},
            REMOTE_ADDR=ip,
        )

    @snapshot_postgres_queries
    def test_early_access_features(self):
        Person.objects.create(
            team=self.team,
            distinct_ids=["example_id"],
            properties={"email": "example@posthog.com"},
        )

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
        EarlyAccessFeature.objects.create(
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
            self.assertEqual(response.get("access-control-allow-origin"), "http://127.0.0.1:8000")

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
                    }
                ],
            )

    def test_early_access_features_beta_only(self):
        Person.objects.create(
            team=self.team,
            distinct_ids=["example_id"],
            properties={"email": "example@posthog.com"},
        )

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
        feature_flag3 = FeatureFlag.objects.create(
            team=self.team,
            name=f"Feature Flag for Feature Sprocket",
            key="sprocket3",
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
        EarlyAccessFeature.objects.create(
            team=self.team,
            name="Sprocket",
            description="A fancy new sprocket.",
            stage="alpha",
            feature_flag=feature_flag2,
        )
        EarlyAccessFeature.objects.create(
            team=self.team,
            name="Sprocket",
            description="A fancy new sprocket.",
            stage="draft",
            feature_flag=feature_flag3,
        )

        self.client.logout()

        with self.assertNumQueries(2):
            response = self._get_features()
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get("access-control-allow-origin"), "http://127.0.0.1:8000")

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
                    }
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
