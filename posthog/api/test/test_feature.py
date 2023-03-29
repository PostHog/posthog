from unittest.mock import ANY

from rest_framework import status

from posthog.models.feature import Feature
from posthog.test.base import APIBaseTest


class TestFeatureFlag(APIBaseTest):
    maxDiff = None

    def test_can_create_feature(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/features/",
            data={
                "name": "Hick bondoogling",
                "description": 'Boondoogle your hicks with one click. Just click "bazinga"!',
                "status": "concept",
            },
            format="json",
        )
        response_data = response.json()

        assert response.status_code == status.HTTP_201_CREATED, response_data
        assert Feature.objects.filter(id=response_data["id"]).exists()
        assert response_data["name"] == "Hick bondoogling"
        assert response_data["description"] == 'Boondoogle your hicks with one click. Just click "bazinga"!'
        assert response_data["status"] == "concept"
        assert isinstance(response_data["created_at"], str)

    def test_can_edit_feature(self):
        feature = Feature.objects.create(
            team=self.team,
            name="Click counter",
            description="A revolution in usability research: now you can count clicks!",
            status="beta",
        )

        response = self.client.patch(
            f"/api/projects/{self.team.id}/features/{feature.id}",
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
        assert response_data["status"] == "beta"
        assert feature.name == "Mouse-up counter"

    def test_can_list_features(self):
        Feature.objects.create(
            team=self.team,
            name="Click counter",
            description="A revolution in usability research: now you can count clicks!",
            status="beta",
        )

        response = self.client.get(f"/api/projects/{self.team.id}/features/")
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
                    "documentation_url": None,
                    "feature_flag": None,
                    "id": ANY,
                    "image_url": None,
                    "name": "Click counter",
                    "status": "beta",
                },
            ],
        }
