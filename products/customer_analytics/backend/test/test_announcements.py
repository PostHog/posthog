from posthog.test.base import APIBaseTest
from unittest.mock import patch

from rest_framework import status

from posthog.models.team import Team

from products.conversations.backend.support_slack_channels import SupportSlackNotConfigured
from products.customer_analytics.backend.models import Account, Announcement, AnnouncementDelivery

HELPER = "products.customer_analytics.backend.presentation.views.announcements.list_support_bot_channels"


class TestAnnouncementAPI(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.base_url = f"/api/projects/{self.team.pk}/announcements/"

    def _member_channels(self):
        return [
            {"id": "C1", "name": "acme-corp", "is_member": True},
            {"id": "C2", "name": "globex", "is_member": True},
        ]

    @patch("products.customer_analytics.backend.presentation.views.announcements.report_user_action")
    @patch(HELPER)
    def test_create_persists_announcement_and_resolves_channel_names(self, mock_channels, _mock_report):
        mock_channels.return_value = self._member_channels()

        response = self.client.post(
            self.base_url, {"message": "Offsite this week, slower replies.", "channels": ["C1", "C2"]}, format="json"
        )

        assert response.status_code == status.HTTP_201_CREATED, response.json()
        data = response.json()
        assert data["status"] == "pending"
        assert data["total_channels"] == 2
        assert data["created_by"]["id"] == self.user.pk
        # Names are resolved server-side from the member-channel lookup, not from the request body.
        assert {(d["slack_channel_id"], d["slack_channel_name"]) for d in data["deliveries"]} == {
            ("C1", "acme-corp"),
            ("C2", "globex"),
        }
        announcement = Announcement.all_teams.get(id=data["id"])
        assert AnnouncementDelivery.all_teams.filter(announcement=announcement).count() == 2

    @patch(HELPER)
    def test_create_rejects_non_member_channel_and_creates_no_rows(self, mock_channels):
        # Pentest fix: a caller crafting a channel ID the bot isn't in (a DM, private channel,
        # App Home) must be rejected outright, with nothing persisted.
        mock_channels.return_value = self._member_channels()

        response = self.client.post(self.base_url, {"message": "hi", "channels": ["C1", "D_secret_dm"]}, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert Announcement.all_teams.count() == 0
        assert AnnouncementDelivery.all_teams.count() == 0

    @patch(HELPER)
    def test_create_rejects_when_slack_not_connected(self, mock_channels):
        mock_channels.side_effect = SupportSlackNotConfigured()

        response = self.client.post(self.base_url, {"message": "hi", "channels": ["C1"]}, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert Announcement.all_teams.count() == 0

    @patch(HELPER)
    def test_create_validates_message_and_channels(self, mock_channels):
        mock_channels.return_value = self._member_channels()

        assert (
            self.client.post(self.base_url, {"message": "  ", "channels": ["C1"]}, format="json").status_code
            == status.HTTP_400_BAD_REQUEST
        )
        assert (
            self.client.post(self.base_url, {"message": "hi", "channels": []}, format="json").status_code
            == status.HTTP_400_BAD_REQUEST
        )
        assert Announcement.all_teams.count() == 0

    @patch(HELPER)
    def test_create_dedupes_channels(self, mock_channels):
        mock_channels.return_value = self._member_channels()

        response = self.client.post(self.base_url, {"message": "hi", "channels": ["C1", "C1"]}, format="json")

        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["total_channels"] == 1

    @patch(HELPER)
    def test_list_and_retrieve_scoped_to_team(self, mock_channels):
        mock_channels.return_value = self._member_channels()
        created = self.client.post(self.base_url, {"message": "A", "channels": ["C1"]}, format="json").json()

        other_team = Team.objects.create(organization=self.organization, name="Other")
        other = Announcement.all_teams.create(team=other_team, message="secret", total_channels=0)

        list_resp = self.client.get(self.base_url)
        assert list_resp.status_code == status.HTTP_200_OK
        assert {r["message"] for r in list_resp.json()["results"]} == {"A"}

        assert self.client.get(f"{self.base_url}{created['short_id']}/").status_code == status.HTTP_200_OK
        assert self.client.get(f"{self.base_url}{other.short_id}/").status_code == status.HTTP_404_NOT_FOUND

    @patch(HELPER)
    def test_channels_action_labels_by_customer_and_sorts_mapped_first(self, mock_channels):
        mock_channels.return_value = [
            {"id": "C1", "name": "zzz-internal", "is_member": True},
            {"id": "C2", "name": "acme-shared", "is_member": True},
        ]
        # C2 is mapped to a customer account; C1 is an unmapped (e.g. internal) channel.
        Account.objects.create_account(team=self.team, name="Acme", properties={"slack_channel_id": "C2"})

        response = self.client.get(f"{self.base_url}channels/")

        assert response.status_code == status.HTTP_200_OK
        channels = response.json()
        # Mapped channel sorts first with its customer name; unmapped falls below with null.
        assert channels[0]["id"] == "C2"
        assert channels[0]["customer_name"] == "Acme"
        assert channels[1]["id"] == "C1"
        assert channels[1]["customer_name"] is None

    @patch(HELPER)
    def test_channels_action_returns_empty_when_slack_not_connected(self, mock_channels):
        mock_channels.side_effect = SupportSlackNotConfigured()

        response = self.client.get(f"{self.base_url}channels/")

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == []
