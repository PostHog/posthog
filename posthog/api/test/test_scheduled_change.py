from rest_framework import status
from posthog.test.base import (
    APIBaseTest,
)
from posthog.models import ScheduledChange


class TestScheduledChange(APIBaseTest):
    def test_can_create_flag_change(self):
        payload = {"field": "active", "value": "false"}

        response = self.client.post(
            f"/api/projects/{self.team.id}/scheduled_changes/",
            data={
                "id": 6,
                "record_id": "119",
                "model_name": "FeatureFlag",
                "payload": payload,
                "scheduled_at": "2023-12-08T12:00:00Z",
                "executed_at": None,
                "failure_reason": "",
            },
        )

        response_data = response.json()

        assert response.status_code == status.HTTP_201_CREATED, response_data
        assert ScheduledChange.objects.filter(id=response_data["id"]).exists()
        assert response_data["model_name"] == "FeatureFlag"
        assert response_data["record_id"] == "119"
        assert response_data["payload"] == payload
        assert response_data["created_by"]["id"] == self.user.id
