from datetime import timedelta

from freezegun import freeze_time
from posthog.test.base import APIBaseTest

from django.utils import timezone

from rest_framework import status
from rest_framework.test import APIClient

from posthog.models import User
from posthog.redis import get_client

from products.conversations.backend.models import Ticket
from products.conversations.backend.models.constants import Channel, Status
from products.conversations.backend.presence import PRESENCE_TTL_SECONDS

from ee.models.rbac.access_control import AccessControl


class TestTicketPresenceAPI(APIBaseTest):
    def setUp(self):
        super().setUp()
        # Presence lives in fakeredis, which is a single process-wide store.
        get_client().flushall()
        self.ticket = Ticket.objects.create_with_number(
            team=self.team, channel_source=Channel.WIDGET, widget_session_id="s", distinct_id="d", status=Status.NEW
        )
        self.other_user = User.objects.create_and_join(self.organization, "teammate@posthog.com", None)
        self.other_client = APIClient()
        self.other_client.force_login(self.other_user)
        self.heartbeat_url = f"/api/projects/{self.team.id}/conversations/tickets/{self.ticket.id}/presence/"
        self.presence_url = f"/api/projects/{self.team.id}/conversations/tickets/presence/?ticket_ids={self.ticket.id}"

    def test_reports_other_viewers_only(self):
        assert self.other_client.post(self.heartbeat_url).json()["viewers"] == []

        mine = self.client.post(self.heartbeat_url)
        assert [viewer["id"] for viewer in mine.json()["viewers"]] == [self.other_user.id]

        listing = self.client.get(self.presence_url).json()["viewers"]
        assert [viewer["id"] for viewer in listing[str(self.ticket.id)]] == [self.other_user.id]

        assert self.client.get(self.presence_url.split("=")[0] + "=nope").status_code == status.HTTP_400_BAD_REQUEST

    def test_viewers_age_out_after_ttl(self):
        started_at = timezone.now()
        with freeze_time(started_at):
            self.other_client.post(self.heartbeat_url)
        with freeze_time(started_at + timedelta(seconds=PRESENCE_TTL_SECONDS + 1)):
            assert self.client.get(self.presence_url).json()["viewers"] == {}

    def test_object_level_access_control_hides_viewers_and_blocks_heartbeat(self):
        self.organization.available_product_features = [{"key": "access_control", "name": "Access control"}]
        self.organization.save()
        AccessControl.objects.create(
            resource="ticket",
            resource_id=str(self.ticket.id),
            organization_member=self.user.organization_memberships.get(organization=self.organization),
            team=self.team,
            access_level="none",
        )
        self.other_client.post(self.heartbeat_url)

        assert self.client.get(self.presence_url).json()["viewers"] == {}
        assert self.client.post(self.heartbeat_url).status_code == status.HTTP_403_FORBIDDEN
