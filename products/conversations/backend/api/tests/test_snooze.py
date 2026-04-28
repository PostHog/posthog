import uuid
from datetime import timedelta

from posthog.test.base import APIBaseTest, BaseTest
from unittest.mock import patch

from django.db import transaction
from django.utils import timezone

from parameterized import parameterized
from rest_framework import status
from rest_framework.test import APIClient

from posthog.models import ActivityLog
from posthog.models.utils import generate_random_token_secret

from products.conversations.backend.models import Ticket
from products.conversations.backend.models.constants import Channel, Status
from products.conversations.backend.tasks import wake_snoozed_tickets


def immediate_on_commit(func):
    func()


# -- Internal ticket API: snooze ------------------------------------------------


@patch.object(transaction, "on_commit", side_effect=immediate_on_commit)
class TestTicketSnoozeAPI(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.ticket = Ticket.objects.create_with_number(
            team=self.team,
            channel_source=Channel.WIDGET,
            widget_session_id="snooze-session",
            distinct_id="snooze-user",
            status=Status.NEW,
        )
        self.url = f"/api/projects/{self.team.id}/conversations/tickets/{self.ticket.id}/"

    def test_set_snoozed_until(self, _):
        snooze_time = (timezone.now() + timedelta(hours=2)).isoformat()
        response = self.client.patch(self.url, {"snoozed_until": snooze_time})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNotNone(response.json()["snoozed_until"])

        self.ticket.refresh_from_db()
        self.assertIsNotNone(self.ticket.snoozed_until)

    def test_clear_snoozed_until(self, _):
        self.ticket.snoozed_until = timezone.now() + timedelta(hours=2)
        self.ticket.status = Status.ON_HOLD
        self.ticket.save(update_fields=["snoozed_until", "status"])

        response = self.client.patch(self.url, {"snoozed_until": None})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.ticket.refresh_from_db()
        self.assertIsNone(self.ticket.snoozed_until)

    def test_snooze_auto_sets_on_hold(self, _):
        snooze_time = (timezone.now() + timedelta(hours=2)).isoformat()
        response = self.client.patch(self.url, {"snoozed_until": snooze_time})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, Status.ON_HOLD)

    def test_unsnooze_auto_sets_open(self, _):
        self.ticket.snoozed_until = timezone.now() + timedelta(hours=2)
        self.ticket.status = Status.ON_HOLD
        self.ticket.save(update_fields=["snoozed_until", "status"])

        response = self.client.patch(self.url, {"snoozed_until": None})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, Status.OPEN)

    def test_snooze_with_explicit_status_respects_status(self, _):
        snooze_time = (timezone.now() + timedelta(hours=2)).isoformat()
        response = self.client.patch(self.url, {"snoozed_until": snooze_time, "status": Status.PENDING})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, Status.PENDING)

    def test_unsnooze_with_explicit_status_respects_status(self, _):
        self.ticket.snoozed_until = timezone.now() + timedelta(hours=2)
        self.ticket.status = Status.ON_HOLD
        self.ticket.save(update_fields=["snoozed_until", "status"])

        response = self.client.patch(self.url, {"snoozed_until": None, "status": Status.RESOLVED})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, Status.RESOLVED)

    def test_snooze_logs_activity(self, _):
        snooze_time = (timezone.now() + timedelta(hours=2)).isoformat()
        self.client.patch(self.url, {"snoozed_until": snooze_time})

        activity = ActivityLog.objects.filter(
            team_id=self.team.id,
            scope="Ticket",
            item_id=str(self.ticket.id),
            activity="updated",
        ).first()
        assert activity is not None
        assert activity.detail is not None
        changes = activity.detail.get("changes", [])

        snooze_change = next((c for c in changes if c["field"] == "snoozed_until"), None)
        assert snooze_change is not None
        self.assertIsNone(snooze_change["before"])
        self.assertIsNotNone(snooze_change["after"])

        status_change = next((c for c in changes if c["field"] == "status"), None)
        assert status_change is not None
        self.assertEqual(status_change["after"], Status.ON_HOLD)

    def test_retrieve_includes_snoozed_until(self, _):
        snooze_time = timezone.now() + timedelta(hours=2)
        self.ticket.snoozed_until = snooze_time
        self.ticket.save(update_fields=["snoozed_until"])

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNotNone(response.json()["snoozed_until"])

    def test_list_includes_snoozed_until(self, _):
        snooze_time = timezone.now() + timedelta(hours=2)
        self.ticket.snoozed_until = snooze_time
        self.ticket.save(update_fields=["snoozed_until"])

        response = self.client.get(f"/api/projects/{self.team.id}/conversations/tickets/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNotNone(response.json()["results"][0]["snoozed_until"])

    @parameterized.expand([("true", True), ("false", False)])
    def test_filter_by_snoozed(self, _, param_value, expect_snoozed):
        self.ticket.snoozed_until = timezone.now() + timedelta(hours=2)
        self.ticket.save(update_fields=["snoozed_until"])

        unsnoozed = Ticket.objects.create_with_number(
            team=self.team,
            channel_source=Channel.WIDGET,
            widget_session_id="unsnoozed-session",
            distinct_id="unsnoozed-user",
        )

        response = self.client.get(f"/api/projects/{self.team.id}/conversations/tickets/?snoozed={param_value}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 1)

        returned_id = response.json()["results"][0]["id"]
        if expect_snoozed:
            self.assertEqual(returned_id, str(self.ticket.id))
        else:
            self.assertEqual(returned_id, str(unsnoozed.id))


# -- External ticket API: snooze -----------------------------------------------


class TestExternalTicketSnoozeAPI(BaseTest):
    def setUp(self):
        super().setUp()
        self.team.conversations_enabled = True
        self.team.secret_api_token = generate_random_token_secret()
        self.team.save(update_fields=["conversations_enabled", "secret_api_token"])
        self.client = APIClient()
        self.ticket = Ticket.objects.create_with_number(
            team=self.team,
            widget_session_id=str(uuid.uuid4()),
            distinct_id="ext-snooze-user",
            channel_source="widget",
            status=Status.NEW,
        )
        self.url = f"/api/conversations/external/ticket/{self.ticket.id}"

    def _auth(self):
        return {"HTTP_AUTHORIZATION": f"Bearer {self.team.secret_api_token}"}

    def test_get_returns_snoozed_until(self):
        self.ticket.snoozed_until = timezone.now() + timedelta(hours=2)
        self.ticket.save(update_fields=["snoozed_until"])

        response = self.client.get(self.url, **self._auth())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNotNone(response.json()["snoozed_until"])

    def test_get_returns_null_when_not_snoozed(self):
        response = self.client.get(self.url, **self._auth())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNone(response.json()["snoozed_until"])

    def test_patch_set_snoozed_until(self):
        snooze_time = (timezone.now() + timedelta(hours=3)).isoformat()
        response = self.client.patch(
            self.url, {"snoozed_until": snooze_time}, content_type="application/json", **self._auth()
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.ticket.refresh_from_db()
        self.assertIsNotNone(self.ticket.snoozed_until)

    def test_patch_clear_snoozed_until(self):
        self.ticket.snoozed_until = timezone.now() + timedelta(hours=2)
        self.ticket.status = Status.ON_HOLD
        self.ticket.save(update_fields=["snoozed_until", "status"])

        response = self.client.patch(self.url, {"snoozed_until": None}, content_type="application/json", **self._auth())
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.ticket.refresh_from_db()
        self.assertIsNone(self.ticket.snoozed_until)

    def test_patch_snooze_auto_sets_on_hold(self):
        snooze_time = (timezone.now() + timedelta(hours=3)).isoformat()
        self.client.patch(self.url, {"snoozed_until": snooze_time}, content_type="application/json", **self._auth())

        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, Status.ON_HOLD)

    def test_patch_unsnooze_auto_sets_open(self):
        self.ticket.snoozed_until = timezone.now() + timedelta(hours=2)
        self.ticket.status = Status.ON_HOLD
        self.ticket.save(update_fields=["snoozed_until", "status"])

        self.client.patch(self.url, {"snoozed_until": None}, content_type="application/json", **self._auth())

        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, Status.OPEN)

    def test_patch_snooze_with_explicit_status_respects_status(self):
        snooze_time = (timezone.now() + timedelta(hours=3)).isoformat()
        self.client.patch(
            self.url,
            {"snoozed_until": snooze_time, "status": "pending"},
            content_type="application/json",
            **self._auth(),
        )

        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, Status.PENDING)

    def test_patch_snooze_logs_activity(self):
        snooze_time = (timezone.now() + timedelta(hours=3)).isoformat()
        self.client.patch(self.url, {"snoozed_until": snooze_time}, content_type="application/json", **self._auth())

        activity = ActivityLog.objects.filter(
            team_id=self.team.id,
            scope="Ticket",
            item_id=str(self.ticket.id),
            activity="updated",
        ).first()
        assert activity is not None
        assert activity.detail is not None
        changes = activity.detail.get("changes", [])

        snooze_change = next((c for c in changes if c["field"] == "snoozed_until"), None)
        assert snooze_change is not None

        status_change = next((c for c in changes if c["field"] == "status"), None)
        assert status_change is not None
        self.assertEqual(status_change["after"], "on_hold")

    def test_patch_invalid_snoozed_until(self):
        response = self.client.patch(
            self.url, {"snoozed_until": "not-a-date"}, content_type="application/json", **self._auth()
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


# -- Wake task -----------------------------------------------------------------


class TestWakeSnoozedTickets(BaseTest):
    def _make_ticket(self, **kwargs):
        defaults = {
            "team": self.team,
            "channel_source": Channel.WIDGET,
            "widget_session_id": str(uuid.uuid4()),
            "distinct_id": str(uuid.uuid4()),
        }
        defaults.update(kwargs)
        return Ticket.objects.create_with_number(**defaults)

    @patch("products.conversations.backend.tasks.capture_ticket_status_changed")
    def test_wakes_expired_on_hold_ticket(self, mock_capture):
        ticket = self._make_ticket(
            status=Status.ON_HOLD,
            snoozed_until=timezone.now() - timedelta(minutes=5),
        )

        wake_snoozed_tickets()

        ticket.refresh_from_db()
        self.assertEqual(ticket.status, Status.OPEN)
        self.assertIsNone(ticket.snoozed_until)
        mock_capture.assert_called_once_with(ticket, Status.ON_HOLD, Status.OPEN)

    @patch("products.conversations.backend.tasks.capture_ticket_status_changed")
    def test_clears_snooze_but_preserves_resolved_status(self, mock_capture):
        ticket = self._make_ticket(
            status=Status.RESOLVED,
            snoozed_until=timezone.now() - timedelta(minutes=5),
        )

        wake_snoozed_tickets()

        ticket.refresh_from_db()
        self.assertEqual(ticket.status, Status.RESOLVED)
        self.assertIsNone(ticket.snoozed_until)
        mock_capture.assert_not_called()

    @patch("products.conversations.backend.tasks.capture_ticket_status_changed")
    def test_ignores_future_snoozed_tickets(self, mock_capture):
        ticket = self._make_ticket(
            status=Status.ON_HOLD,
            snoozed_until=timezone.now() + timedelta(hours=1),
        )

        wake_snoozed_tickets()

        ticket.refresh_from_db()
        self.assertEqual(ticket.status, Status.ON_HOLD)
        self.assertIsNotNone(ticket.snoozed_until)
        mock_capture.assert_not_called()

    @patch("products.conversations.backend.tasks.capture_ticket_status_changed")
    def test_ignores_tickets_without_snooze(self, mock_capture):
        ticket = self._make_ticket(status=Status.ON_HOLD, snoozed_until=None)

        wake_snoozed_tickets()

        ticket.refresh_from_db()
        self.assertEqual(ticket.status, Status.ON_HOLD)
        mock_capture.assert_not_called()

    @patch("products.conversations.backend.tasks.capture_ticket_status_changed")
    def test_wakes_multiple_tickets_across_teams(self, mock_capture):
        other_team = self.organization.teams.create(name="Other Team")
        expired = timezone.now() - timedelta(minutes=5)

        t1 = self._make_ticket(status=Status.ON_HOLD, snoozed_until=expired)
        t2 = self._make_ticket(team=other_team, status=Status.ON_HOLD, snoozed_until=expired)

        wake_snoozed_tickets()

        t1.refresh_from_db()
        t2.refresh_from_db()
        self.assertEqual(t1.status, Status.OPEN)
        self.assertIsNone(t1.snoozed_until)
        self.assertEqual(t2.status, Status.OPEN)
        self.assertIsNone(t2.snoozed_until)
        self.assertEqual(mock_capture.call_count, 2)

    @patch("products.conversations.backend.tasks.capture_ticket_status_changed")
    def test_noop_when_no_expired_tickets(self, mock_capture):
        wake_snoozed_tickets()
        mock_capture.assert_not_called()
