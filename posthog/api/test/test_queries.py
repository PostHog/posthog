import freezegun
from rest_framework import status

from posthog.test.base import APIBaseTest


class TestPropertyDefinitionAPI(APIBaseTest):
    @freezegun.freeze_time("2021-01-01T12:00:00Z")
    def test_legacy_trends_query(self) -> None:
        query_params = "&".join(["type=legacy_trends", "filters={'insight'='trends'}"])
        response = self.client.get(f"/api/projects/{self.team.id}/query/q?{query_params}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        assert response.json() == {
            "is_cached": False,
            "last_refresh": "2021-01-01T12:00:00Z",
            "next": None,
            "result": [],
            "timezone": "UTC",
        }

    def test_unknown_query_type(self) -> None:
        query_params = "&".join(["type=next_episode", "filters={'not':'known'}"])
        response = self.client.get(f"/api/projects/{self.team.id}/query/q?{query_params}")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
