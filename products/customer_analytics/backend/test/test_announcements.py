from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.db import connection
from django.test.utils import CaptureQueriesContext

from rest_framework import status

from posthog.models.team import Team

from products.conversations.backend.facade.api import SupportChannel, SupportSlackNotConfigured
from products.customer_analytics.backend.models import Account, Announcement, AnnouncementDelivery

HELPER = "products.customer_analytics.backend.logic.announcements.list_support_bot_channels"


class TestAnnouncementAPI(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.base_url = f"/api/projects/{self.team.pk}/announcements/"

    def _member_channels(self):
        return [
            SupportChannel(id="C1", name="acme-corp", is_member=True),
            SupportChannel(id="C2", name="globex", is_member=True),
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
        assert {(d["slack_channel_id"], d["slack_channel_name"]) for d in data["deliveries"]} == {
            ("C1", "acme-corp"),
            ("C2", "globex"),
        }
        announcement = Announcement.all_teams.get(id=data["id"])
        assert AnnouncementDelivery.all_teams.filter(announcement=announcement).count() == 2

    @patch("products.customer_analytics.backend.facade.api.send_announcement")
    @patch(HELPER)
    def test_create_enqueues_send_task_after_commit(self, mock_channels, mock_task):
        mock_channels.return_value = self._member_channels()

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(self.base_url, {"message": "hi", "channels": ["C1"]}, format="json")

        assert response.status_code == status.HTTP_201_CREATED
        mock_task.delay.assert_called_once_with(response.json()["id"], self.team.pk)

    @patch("products.customer_analytics.backend.logic.announcements.post_support_message")
    @patch(HELPER)
    def test_create_isolates_non_member_channel_and_never_posts_to_it(self, mock_channels, mock_post):
        mock_channels.return_value = self._member_channels()
        mock_post.return_value = "1.0"

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                self.base_url, {"message": "hi", "channels": ["C1", "D_secret_dm"]}, format="json"
            )

        assert response.status_code == status.HTTP_201_CREATED
        assert [call.args[1] for call in mock_post.call_args_list] == ["C1"]
        announcement = Announcement.all_teams.get(id=response.json()["id"])
        assert announcement.status == Announcement.Status.PARTIALLY_FAILED
        by_channel = {d.slack_channel_id: d for d in AnnouncementDelivery.all_teams.filter(announcement=announcement)}
        assert by_channel["D_secret_dm"].status == AnnouncementDelivery.Status.FAILED
        assert by_channel["D_secret_dm"].error == "not_in_channel"
        assert by_channel["C1"].status == AnnouncementDelivery.Status.SENT

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

    def test_list_query_count_does_not_grow_with_announcements(self):
        def create_announcement_with_deliveries(index: int) -> None:
            announcement = Announcement.all_teams.create(
                team=self.team, message=f"msg {index}", created_by=self.user, total_channels=2
            )
            AnnouncementDelivery.all_teams.bulk_create(
                AnnouncementDelivery(
                    team=self.team, announcement=announcement, slack_channel_id=f"C{index}-{n}", slack_channel_name="ch"
                )
                for n in range(2)
            )

        create_announcement_with_deliveries(0)
        self.client.get(self.base_url)  # warm request-scoped caches so both captures compare equal work
        with CaptureQueriesContext(connection) as small_list:
            assert self.client.get(self.base_url).status_code == status.HTTP_200_OK

        for index in range(1, 5):
            create_announcement_with_deliveries(index)
        with CaptureQueriesContext(connection) as large_list:
            response = self.client.get(self.base_url)

        assert response.status_code == status.HTTP_200_OK
        assert len(response.json()["results"]) == 5
        assert len(large_list) == len(small_list)

    @patch(HELPER)
    def test_channels_action_labels_by_customer_and_sorts_mapped_first(self, mock_channels):
        mock_channels.return_value = [
            SupportChannel(id="C1", name="zzz-internal", is_member=True),
            SupportChannel(id="C2", name="acme-shared", is_member=True),
        ]
        Account.objects.create_account(team=self.team, name="Acme", properties={"slack_channel_id": "C2"})

        response = self.client.get(f"{self.base_url}channels/")

        assert response.status_code == status.HTTP_200_OK
        channels = response.json()
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
