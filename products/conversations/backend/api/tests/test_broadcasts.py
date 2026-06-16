from posthog.test.base import APIBaseTest
from unittest.mock import patch

from rest_framework import status

from posthog.models.team.team import Team

from products.conversations.backend.models import Broadcast, BroadcastDelivery


class TestBroadcastAPI(APIBaseTest):
    base_url: str

    def setUp(self):
        super().setUp()
        self.base_url = f"/api/projects/{self.team.pk}/conversations/broadcasts/"

    def _valid_payload(self, **overrides) -> dict:
        defaults = {
            "message": "Heads up: scheduled maintenance tonight.",
            "channels": [{"id": "C1", "name": "general"}, {"id": "C2", "name": "random"}],
        }
        defaults.update(overrides)
        return defaults

    @patch("products.conversations.backend.api.broadcasts.report_user_action")
    @patch("products.conversations.backend.api.broadcasts.send_broadcast")
    def test_create_persists_broadcast_and_deliveries_and_enqueues(self, mock_send, mock_report):
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(self.base_url, self._valid_payload(), format="json")

        assert response.status_code == status.HTTP_201_CREATED, response.json()
        data = response.json()
        assert data["message"] == "Heads up: scheduled maintenance tonight."
        assert data["status"] == "pending"
        assert data["total_channels"] == 2
        assert {d["slack_channel_id"] for d in data["deliveries"]} == {"C1", "C2"}
        assert all(d["status"] == "pending" for d in data["deliveries"])
        assert data["created_by"]["id"] == self.user.pk

        broadcast = Broadcast.all_teams.get(id=data["id"])
        assert broadcast.team_id == self.team.pk
        assert BroadcastDelivery.all_teams.filter(broadcast=broadcast).count() == 2

        mock_send.delay.assert_called_once_with(str(broadcast.id), self.team.pk)
        mock_report.assert_called_once()

    @patch("products.conversations.backend.api.broadcasts.send_broadcast")
    def test_create_rejects_empty_message(self, _mock_send):
        response = self.client.post(self.base_url, self._valid_payload(message="   "), format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @patch("products.conversations.backend.api.broadcasts.send_broadcast")
    def test_create_rejects_empty_channels(self, _mock_send):
        response = self.client.post(self.base_url, self._valid_payload(channels=[]), format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @patch("products.conversations.backend.api.broadcasts.send_broadcast")
    def test_create_dedupes_channels(self, _mock_send):
        payload = self._valid_payload(channels=[{"id": "C1", "name": "general"}, {"id": "C1", "name": "general"}])
        response = self.client.post(self.base_url, payload, format="json")
        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["total_channels"] == 1

    @patch("products.conversations.backend.api.broadcasts.send_broadcast")
    def test_list_is_scoped_to_team(self, _mock_send):
        self.client.post(self.base_url, self._valid_payload(message="A"), format="json")
        self.client.post(self.base_url, self._valid_payload(message="B"), format="json")

        response = self.client.get(self.base_url)
        assert response.status_code == status.HTTP_200_OK
        results = response.json()["results"]
        assert {r["message"] for r in results} == {"A", "B"}

    @patch("products.conversations.backend.api.broadcasts.send_broadcast")
    def test_retrieve(self, _mock_send):
        created = self.client.post(self.base_url, self._valid_payload(), format="json").json()
        response = self.client.get(f"{self.base_url}{created['short_id']}/")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["short_id"] == created["short_id"]

    @patch("products.conversations.backend.api.broadcasts.send_broadcast")
    def test_cannot_access_other_teams_broadcast(self, _mock_send):
        other_team = Team.objects.create(organization=self.organization, name="Other")
        broadcast = Broadcast.all_teams.create(team=other_team, message="secret", total_channels=0)

        response = self.client.get(f"{self.base_url}{broadcast.short_id}/")
        assert response.status_code == status.HTTP_404_NOT_FOUND
