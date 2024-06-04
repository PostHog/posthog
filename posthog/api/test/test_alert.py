from unittest import mock

from rest_framework import status

from posthog.test.base import APIBaseTest, QueryMatchingTest
from posthog.models.team import Team
from posthog.models.insight import Insight
from posthog.models.filters.filter import Filter


class TestAlert(APIBaseTest, QueryMatchingTest):
    insight: Insight = None  # type: ignore

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.insight = Insight.objects.create(
            filters=Filter(data={}).to_dict(),
            team=cls.team,
            created_by=cls.user,
        )

    def test_create_and_delete_alert(self) -> None:
        creation_request = {
            "insight": self.insight.id,
            "target_value": "test@posthog.com",
            "name": "alert name",
            "anomaly_condition": {},
        }
        response = self.client.post(f"/api/projects/{self.team.id}/alerts", creation_request)

        expected_alert_json = {
            "id": mock.ANY,
            "insight": self.insight.id,
            "target_value": "test@posthog.com",
            "name": "alert name",
            "anomaly_condition": {},
        }
        assert response.status_code == status.HTTP_201_CREATED
        assert response.json() == expected_alert_json

        alerts = self.client.get(f"/api/projects/{self.team.id}/alerts")
        assert alerts.json()["results"] == [expected_alert_json]

        alert_id = response.json()["id"]
        self.client.delete(f"/api/projects/{self.team.id}/alerts/{alert_id}")

        alerts = self.client.get(f"/api/projects/{self.team.id}/alerts")
        assert len(alerts.json()["results"]) == 0

    def test_incorrect_creation(self) -> None:
        creation_request = {
            "target_value": "test@posthog.com",
            "name": "alert name",
            "anomaly_condition": {},
        }
        response = self.client.post(f"/api/projects/{self.team.id}/alerts", creation_request)
        assert response.status_code == status.HTTP_400_BAD_REQUEST

        another_team = Team.objects.create(
            organization=self.organization,
            api_token=self.CONFIG_API_TOKEN + "2",
        )
        another_team_insight = Insight.objects.create(
            filters=Filter(data={}).to_dict(),
            team=another_team,
            created_by=self.user,
        )
        creation_request = {
            "insight": str(another_team_insight.id),
            "target_value": "test@posthog.com",
            "name": "alert name",
            "anomaly_condition": {},
        }
        response = self.client.post(f"/api/projects/{self.team.id}/alerts", creation_request)
        assert response.status_code == status.HTTP_400_BAD_REQUEST
