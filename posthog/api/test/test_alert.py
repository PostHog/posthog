from unittest import mock

from rest_framework import status

from posthog.test.base import APIBaseTest, QueryMatchingTest
from posthog.models.team import Team


class TestAlert(APIBaseTest, QueryMatchingTest):
    def setUp(self):
        super().setUp()
        self.default_insight_data = {
            "filters": {
                "events": [{"id": "$pageview"}],
                "display": "BoldNumber",
            }
        }
        self.insight = self.client.post(f"/api/projects/{self.team.id}/insights", data=self.default_insight_data).json()

    def test_create_and_delete_alert(self) -> None:
        creation_request = {
            "insight": self.insight["id"],
            "target_value": "test@posthog.com",
            "name": "alert name",
            "anomaly_condition": {},
        }
        response = self.client.post(f"/api/projects/{self.team.id}/alerts", creation_request)

        expected_alert_json = {
            "id": mock.ANY,
            "insight": self.insight["id"],
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
        another_team_insight = self.client.post(
            f"/api/projects/{another_team.id}/insights", data=self.default_insight_data
        ).json()
        creation_request = {
            "insight": str(another_team_insight["id"]),
            "target_value": "test@posthog.com",
            "name": "alert name",
            "anomaly_condition": {},
        }
        response = self.client.post(f"/api/projects/{self.team.id}/alerts", creation_request)
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_alert_is_deleted_on_insight_update(self) -> None:
        another_insight = self.client.post(
            f"/api/projects/{self.team.id}/insights", data=self.default_insight_data
        ).json()
        creation_request = {
            "insight": another_insight["id"],
            "target_value": "test@posthog.com",
            "name": "alert name",
            "anomaly_condition": {},
        }
        alert = self.client.post(f"/api/projects/{self.team.id}/alerts", creation_request).json()

        self.client.patch(
            f"/api/projects/{self.team.id}/insights/{another_insight['id']}",
            data={"filters": {"events": [{"id": "$anotherEvent"}], "display": "BoldNumber"}},
        ).json()

        response = self.client.get(f"/api/projects/{self.team.id}/alerts/{alert['id']}")
        assert response.status_code == status.HTTP_200_OK

        self.client.patch(
            f"/api/projects/{self.team.id}/insights/{another_insight['id']}",
            data={
                "filters": {
                    "events": [{"id": "$pageview"}],
                    "display": "ActionsLineGraph",
                }
            },
        ).json()

        response = self.client.get(f"/api/projects/{self.team.id}/alerts/{alert['id']}")
        assert response.status_code == status.HTTP_404_NOT_FOUND
