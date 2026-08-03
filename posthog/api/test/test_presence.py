from posthog.test.base import APIBaseTest
from unittest import mock

from rest_framework import status

from posthog.models import User
from posthog.presence import service

from products.conversations.backend.models import Ticket
from products.conversations.backend.models.constants import Channel, Status

from ee.models.rbac.access_control import AccessControl


def _flag(enabled: bool):
    return mock.patch("posthog.api.presence.posthoganalytics.feature_enabled", return_value=enabled)


class TestPresence(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.ticket = Ticket.objects.create_with_number(
            team=self.team,
            channel_source=Channel.WIDGET,
            widget_session_id="presence-session",
            distinct_id="presence-user",
            status=Status.OPEN,
        )
        self.url = f"/api/projects/{self.team.id}/presence"

    def _heartbeat(self, **overrides):
        payload = {
            "scope": "conversations_ticket",
            "item_id": str(self.ticket.id),
            "client_id": "tab-1",
            **overrides,
        }
        return self.client.post(f"{self.url}/heartbeat/", payload)

    def test_heartbeat_returns_other_viewers_with_user_details(self) -> None:
        colleague = User.objects.create_and_join(self.organization, "colleague@posthog.com", "password")
        service.heartbeat(
            self.team.id,
            "conversations_ticket",
            str(self.ticket.id),
            client_id="their-tab",
            user_id=colleague.pk,
            activity="composing",
        )

        with _flag(True):
            response = self._heartbeat()

        assert response.status_code == status.HTTP_200_OK
        results = response.json()["results"]
        viewer = next(result for result in results if result["client_id"] == "their-tab")
        assert viewer["user"]["email"] == "colleague@posthog.com"
        assert viewer["activity"] == "composing"
        assert viewer["last_seen_at"]

    def test_unregistered_scope_is_not_found(self) -> None:
        # Presence is opt-in per scope. Returning an empty list instead would make this endpoint an
        # existence oracle for arbitrary ids in scopes nobody enabled.
        with _flag(True):
            response = self._heartbeat(scope="MadeUpScope")

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_disabled_feature_flag_hides_the_endpoint(self) -> None:
        with _flag(False):
            assert self._heartbeat().status_code == status.HTTP_404_NOT_FOUND
            list_response = self.client.get(
                f"{self.url}/?scope=conversations_ticket&item_id={self.ticket.id}",
            )
        assert list_response.status_code == status.HTTP_404_NOT_FOUND

    def test_leave_removes_this_client(self) -> None:
        with _flag(True):
            self._heartbeat()
            leave_response = self.client.post(
                f"{self.url}/leave/",
                {"scope": "conversations_ticket", "item_id": str(self.ticket.id), "client_id": "tab-1"},
            )

        assert leave_response.status_code == status.HTTP_204_NO_CONTENT
        assert service.get_viewers(self.team.id, "conversations_ticket", str(self.ticket.id)) == []


class TestPresenceTicketAccessControl(APIBaseTest):
    """Presence says who is looking at a ticket, so it has to respect the ticket's own object-level
    access control rather than settling for team membership."""

    def setUp(self) -> None:
        super().setUp()
        self.organization.available_product_features = [{"key": "access_control", "name": "Access control"}]
        self.organization.save()
        self.member = User.objects.create_and_join(self.organization, "presence-member@posthog.com", "password")
        self.client.force_login(self.member)
        self.ticket = Ticket.objects.create_with_number(
            team=self.team,
            channel_source=Channel.WIDGET,
            widget_session_id="presence-acl-session",
            distinct_id="presence-acl-user",
            status=Status.OPEN,
        )
        self.access_control = AccessControl.objects.create(
            resource="ticket",
            resource_id=str(self.ticket.id),
            organization_member=self.member.organization_memberships.get(organization=self.organization),
            team=self.team,
            access_level="none",
        )
        self.url = f"/api/projects/{self.team.id}/presence"

    def _get_viewers(self):
        return self.client.get(f"{self.url}/?scope=conversations_ticket&item_id={self.ticket.id}")

    def test_denied_member_cannot_see_or_join_presence(self) -> None:
        with _flag(True):
            assert self._get_viewers().status_code == status.HTTP_403_FORBIDDEN
            heartbeat_response = self.client.post(
                f"{self.url}/heartbeat/",
                {"scope": "conversations_ticket", "item_id": str(self.ticket.id), "client_id": "tab-1"},
            )

        assert heartbeat_response.status_code == status.HTTP_403_FORBIDDEN
        assert service.get_viewers(self.team.id, "conversations_ticket", str(self.ticket.id)) == []

    def test_viewer_can_see_presence(self) -> None:
        # Viewer, not editor: knowing someone else is already on a ticket is a read-shaped signal.
        AccessControl.objects.filter(resource_id=str(self.ticket.id)).update(access_level="viewer")

        with _flag(True):
            response = self._get_viewers()

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["results"] == []

    def test_unknown_ticket_is_not_found(self) -> None:
        with _flag(True):
            response = self.client.get(
                f"{self.url}/?scope=conversations_ticket&item_id=fc3a4e2c-0000-0000-0000-000000000000"
            )

        assert response.status_code == status.HTTP_404_NOT_FOUND
