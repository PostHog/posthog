import uuid
from datetime import timedelta

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.db import transaction
from django.utils import timezone

from rest_framework import status

from posthog.models import ActivityLog
from posthog.models.async_deletion import AsyncDeletion, DeletionType

from products.conversations.backend.models import Ticket
from products.conversations.backend.models.constants import Channel, Status
from products.conversations.backend.tasks.maintenance import wake_tickets_awaiting_deletion


def immediate_on_commit(func):
    func()


class DeletionHoldBaseTest(APIBaseTest):
    def _make_deletion(self, team=None, **kwargs) -> AsyncDeletion:
        defaults = {
            "deletion_type": DeletionType.Person,
            "team_id": (team or self.team).id,
            "key": str(uuid.uuid4()),
        }
        defaults.update(kwargs)
        return AsyncDeletion.objects.create(**defaults)

    def _make_ticket(self, **kwargs) -> Ticket:
        defaults = {
            "team": self.team,
            "channel_source": Channel.WIDGET,
            "widget_session_id": str(uuid.uuid4()),
            "distinct_id": str(uuid.uuid4()),
        }
        defaults.update(kwargs)
        return Ticket.objects.create_with_number(**defaults)


# -- Internal ticket API: linking a deletion ------------------------------------


@patch.object(transaction, "on_commit", side_effect=immediate_on_commit)
class TestTicketDeletionLinkAPI(DeletionHoldBaseTest):
    def setUp(self):
        super().setUp()
        self.ticket = self._make_ticket(status=Status.NEW)
        self.url = f"/api/projects/{self.team.id}/conversations/tickets/{self.ticket.id}/"

    def test_linking_a_deletion_puts_the_ticket_on_hold(self, _):
        deletion = self._make_deletion()

        response = self.client.patch(self.url, {"awaiting_deletion_id": deletion.id}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, Status.ON_HOLD)
        self.assertEqual(self.ticket.awaiting_deletion_id, deletion.id)
        self.assertIsNotNone(self.ticket.awaiting_deletion_linked_at)

    def test_explicit_status_wins_over_the_implied_hold(self, _):
        deletion = self._make_deletion()

        response = self.client.patch(
            self.url, {"awaiting_deletion_id": deletion.id, "status": Status.PENDING}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, Status.PENDING)
        self.assertEqual(self.ticket.awaiting_deletion_id, deletion.id)

    def test_unlinking_reopens_the_ticket(self, _):
        deletion = self._make_deletion()
        self.client.patch(self.url, {"awaiting_deletion_id": deletion.id}, format="json")

        response = self.client.patch(self.url, {"awaiting_deletion_id": None}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, Status.OPEN)
        self.assertIsNone(self.ticket.awaiting_deletion_id)
        self.assertIsNone(self.ticket.awaiting_deletion_linked_at)

    def test_rejects_a_deletion_from_another_team(self, _):
        other_team = self.organization.teams.create(name="Other Team")
        deletion = self._make_deletion(team=other_team)

        response = self.client.patch(self.url, {"awaiting_deletion_id": deletion.id}, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.ticket.refresh_from_db()
        self.assertIsNone(self.ticket.awaiting_deletion_id)

    def test_rejects_an_unknown_deletion(self, _):
        response = self.client.patch(self.url, {"awaiting_deletion_id": 987654321}, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_linked_at_is_not_caller_supplied(self, _):
        deletion = self._make_deletion()
        stale = timezone.now() - timedelta(days=30)

        self.client.patch(
            self.url,
            {"awaiting_deletion_id": deletion.id, "awaiting_deletion_linked_at": stale.isoformat()},
            format="json",
        )

        self.ticket.refresh_from_db()
        assert self.ticket.awaiting_deletion_linked_at is not None
        self.assertGreater(self.ticket.awaiting_deletion_linked_at, stale)


# -- Wake task: verified deletions ----------------------------------------------


class TestWakeTicketsAwaitingDeletion(DeletionHoldBaseTest):
    def _link(self, ticket: Ticket, deletion: AsyncDeletion, linked_at=None) -> None:
        ticket.awaiting_deletion_id = deletion.id
        ticket.awaiting_deletion_linked_at = linked_at or timezone.now()
        ticket.save(update_fields=["awaiting_deletion_id", "awaiting_deletion_linked_at"])

    @patch("products.conversations.backend.tasks.maintenance.capture_ticket_status_changed")
    def test_verified_deletion_reopens_the_ticket(self, mock_capture):
        deletion = self._make_deletion()
        ticket = self._make_ticket(status=Status.ON_HOLD)
        self._link(ticket, deletion, linked_at=timezone.now() - timedelta(days=2))
        deletion.delete_verified_at = timezone.now()
        deletion.save(update_fields=["delete_verified_at"])

        wake_tickets_awaiting_deletion()

        ticket.refresh_from_db()
        self.assertEqual(ticket.status, Status.OPEN)
        self.assertIsNone(ticket.awaiting_deletion_id)
        self.assertIsNone(ticket.awaiting_deletion_linked_at)
        mock_capture.assert_called_once_with(ticket, Status.ON_HOLD, Status.OPEN, actor_type="system")

    @patch("products.conversations.backend.tasks.maintenance.capture_ticket_status_changed")
    def test_pending_deletion_leaves_the_ticket_on_hold(self, mock_capture):
        deletion = self._make_deletion()
        ticket = self._make_ticket(status=Status.ON_HOLD)
        self._link(ticket, deletion)

        wake_tickets_awaiting_deletion()

        ticket.refresh_from_db()
        self.assertEqual(ticket.status, Status.ON_HOLD)
        self.assertEqual(ticket.awaiting_deletion_id, deletion.id)
        mock_capture.assert_not_called()

    @patch("products.conversations.backend.tasks.maintenance.capture_ticket_status_changed")
    def test_verification_older_than_the_link_does_not_wake(self, mock_capture):
        """AsyncDeletion is unique on (deletion_type, key), so a re-request reuses a verified row."""
        deletion = self._make_deletion(delete_verified_at=timezone.now() - timedelta(days=7))
        ticket = self._make_ticket(status=Status.ON_HOLD)
        self._link(ticket, deletion, linked_at=timezone.now())

        wake_tickets_awaiting_deletion()

        ticket.refresh_from_db()
        self.assertEqual(ticket.status, Status.ON_HOLD)
        self.assertEqual(ticket.awaiting_deletion_id, deletion.id)
        mock_capture.assert_not_called()

    @patch("products.conversations.backend.tasks.maintenance.capture_ticket_status_changed")
    def test_active_ticket_only_loses_the_link(self, mock_capture):
        deletion = self._make_deletion(delete_verified_at=timezone.now())
        ticket = self._make_ticket(status=Status.OPEN)
        self._link(ticket, deletion, linked_at=timezone.now() - timedelta(minutes=5))

        wake_tickets_awaiting_deletion()

        ticket.refresh_from_db()
        self.assertEqual(ticket.status, Status.OPEN)
        self.assertIsNone(ticket.awaiting_deletion_id)
        mock_capture.assert_not_called()

    @patch("products.conversations.backend.tasks.maintenance.capture_ticket_status_changed")
    def test_one_deletion_wakes_every_ticket_linked_to_it(self, mock_capture):
        deletion = self._make_deletion(delete_verified_at=timezone.now())
        linked_at = timezone.now() - timedelta(minutes=5)
        first = self._make_ticket(status=Status.ON_HOLD)
        second = self._make_ticket(status=Status.PENDING)
        self._link(first, deletion, linked_at=linked_at)
        self._link(second, deletion, linked_at=linked_at)

        wake_tickets_awaiting_deletion()

        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(first.status, Status.OPEN)
        self.assertEqual(second.status, Status.OPEN)
        self.assertEqual(mock_capture.call_count, 2)

    @patch("products.conversations.backend.tasks.maintenance.DELETION_LOOKUP_BATCH_SIZE", 1)
    @patch("products.conversations.backend.tasks.maintenance.capture_ticket_status_changed")
    def test_pending_deletions_do_not_stall_the_scan(self, mock_capture):
        """The cursor has to step past still-linked pending rows, or later ones never wake."""
        pending = self._make_deletion()
        verified = self._make_deletion(delete_verified_at=timezone.now())
        self.assertGreater(verified.id, pending.id)
        held = self._make_ticket(status=Status.ON_HOLD)
        wakeable = self._make_ticket(status=Status.ON_HOLD)
        self._link(held, pending)
        self._link(wakeable, verified, linked_at=timezone.now() - timedelta(minutes=5))

        wake_tickets_awaiting_deletion()

        held.refresh_from_db()
        wakeable.refresh_from_db()
        self.assertEqual(held.status, Status.ON_HOLD)
        self.assertEqual(wakeable.status, Status.OPEN)
        mock_capture.assert_called_once()

    @patch("products.conversations.backend.tasks.maintenance.capture_ticket_status_changed")
    def test_wake_logs_system_activity(self, _):
        deletion = self._make_deletion(delete_verified_at=timezone.now())
        ticket = self._make_ticket(status=Status.ON_HOLD)
        self._link(ticket, deletion, linked_at=timezone.now() - timedelta(minutes=5))

        wake_tickets_awaiting_deletion()

        activity = ActivityLog.objects.filter(
            team_id=self.team.id, scope="Ticket", item_id=str(ticket.id), activity="updated"
        ).first()
        assert activity is not None
        assert activity.detail is not None
        self.assertTrue(activity.is_system)
        self.assertIsNone(activity.user_id)
        changes = activity.detail.get("changes", [])

        deletion_change = next((c for c in changes if c["field"] == "awaiting_deletion_id"), None)
        assert deletion_change is not None
        self.assertEqual(deletion_change["before"], deletion.id)
        self.assertIsNone(deletion_change["after"])

        status_change = next((c for c in changes if c["field"] == "status"), None)
        assert status_change is not None
        self.assertEqual(status_change["before"], Status.ON_HOLD)
        self.assertEqual(status_change["after"], Status.OPEN)

    @patch("products.conversations.backend.tasks.maintenance.capture_ticket_status_changed")
    def test_noop_when_nothing_is_linked(self, mock_capture):
        self._make_ticket(status=Status.ON_HOLD)

        wake_tickets_awaiting_deletion()

        mock_capture.assert_not_called()
