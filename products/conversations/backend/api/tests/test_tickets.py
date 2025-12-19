from posthog.test.base import APIBaseTest

from rest_framework import status

from posthog.models.comment import Comment

from products.conversations.backend.models import Ticket
from products.conversations.backend.models.constants import Channel, Priority, Status


class TestTicketAPI(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.ticket = Ticket.objects.create(
            team=self.team,
            channel_source=Channel.WIDGET,
            widget_session_id="test-session-123",
            distinct_id="user-123",
            status=Status.NEW,
        )

    def test_list_tickets(self):
        response = self.client.get(f"/api/environments/{self.team.id}/conversations/tickets/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 1)
        self.assertEqual(response.json()["results"][0]["id"], str(self.ticket.id))

    def test_list_tickets_only_returns_team_tickets(self):
        other_ticket = Ticket.objects.create(
            team=self.team,
            channel_source=Channel.EMAIL,
            widget_session_id="other-session",
            distinct_id="other-user",
        )
        response = self.client.get(f"/api/environments/{self.team.id}/conversations/tickets/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 2)
        ticket_ids = {t["id"] for t in response.json()["results"]}
        self.assertIn(str(self.ticket.id), ticket_ids)
        self.assertIn(str(other_ticket.id), ticket_ids)

    def test_retrieve_ticket(self):
        response = self.client.get(f"/api/environments/{self.team.id}/conversations/tickets/{self.ticket.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["id"], str(self.ticket.id))
        self.assertEqual(response.json()["status"], Status.NEW)

    def test_retrieve_ticket_marks_as_read(self):
        self.ticket.unread_team_count = 5
        self.ticket.save()

        response = self.client.get(f"/api/environments/{self.team.id}/conversations/tickets/{self.ticket.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["unread_team_count"], 0)

        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.unread_team_count, 0)

    def test_update_ticket_status(self):
        response = self.client.patch(
            f"/api/environments/{self.team.id}/conversations/tickets/{self.ticket.id}/",
            {"status": Status.RESOLVED},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["status"], Status.RESOLVED)

        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, Status.RESOLVED)

    def test_update_ticket_priority(self):
        response = self.client.patch(
            f"/api/environments/{self.team.id}/conversations/tickets/{self.ticket.id}/",
            {"priority": Priority.HIGH},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["priority"], Priority.HIGH)

    def test_update_ticket_assigned_to(self):
        response = self.client.patch(
            f"/api/environments/{self.team.id}/conversations/tickets/{self.ticket.id}/",
            {"assigned_to": self.user.id},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["assigned_to"], self.user.id)
        self.assertEqual(response.json()["assigned_to_user"]["id"], self.user.id)

    def test_filter_by_status(self):
        Ticket.objects.create(
            team=self.team,
            channel_source=Channel.WIDGET,
            widget_session_id="resolved-session",
            distinct_id="user-456",
            status=Status.RESOLVED,
        )
        response = self.client.get(f"/api/environments/{self.team.id}/conversations/tickets/?status={Status.NEW}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 1)
        self.assertEqual(response.json()["results"][0]["status"], Status.NEW)

    def test_filter_by_priority(self):
        self.ticket.priority = Priority.HIGH
        self.ticket.save()
        Ticket.objects.create(
            team=self.team,
            channel_source=Channel.WIDGET,
            widget_session_id="low-priority",
            distinct_id="user-789",
            priority=Priority.LOW,
        )
        response = self.client.get(f"/api/environments/{self.team.id}/conversations/tickets/?priority={Priority.HIGH}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 1)
        self.assertEqual(response.json()["results"][0]["priority"], Priority.HIGH)

    def test_filter_by_channel_source(self):
        Ticket.objects.create(
            team=self.team,
            channel_source=Channel.EMAIL,
            widget_session_id="email-session",
            distinct_id="user-email",
        )
        response = self.client.get(
            f"/api/environments/{self.team.id}/conversations/tickets/?channel_source={Channel.WIDGET}"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 1)
        self.assertEqual(response.json()["results"][0]["channel_source"], Channel.WIDGET)

    def test_filter_by_assigned_to_unassigned(self):
        Ticket.objects.create(
            team=self.team,
            channel_source=Channel.WIDGET,
            widget_session_id="assigned-session",
            distinct_id="user-assigned",
            assigned_to=self.user,
        )
        response = self.client.get(f"/api/environments/{self.team.id}/conversations/tickets/?assigned_to=unassigned")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 1)
        self.assertIsNone(response.json()["results"][0]["assigned_to"])

    def test_filter_by_assigned_to_user(self):
        self.ticket.assigned_to = self.user
        self.ticket.save()
        Ticket.objects.create(
            team=self.team,
            channel_source=Channel.WIDGET,
            widget_session_id="unassigned-session",
            distinct_id="user-unassigned",
        )
        response = self.client.get(
            f"/api/environments/{self.team.id}/conversations/tickets/?assigned_to={self.user.id}"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 1)
        self.assertEqual(response.json()["results"][0]["assigned_to"], self.user.id)

    def test_filter_by_distinct_id(self):
        Ticket.objects.create(
            team=self.team,
            channel_source=Channel.WIDGET,
            widget_session_id="other-session",
            distinct_id="different-user",
        )
        response = self.client.get(f"/api/environments/{self.team.id}/conversations/tickets/?distinct_id=user-123")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 1)
        self.assertEqual(response.json()["results"][0]["distinct_id"], "user-123")

    def test_invalid_status_filter_ignored(self):
        response = self.client.get(f"/api/environments/{self.team.id}/conversations/tickets/?status=invalid")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 1)

    def test_invalid_priority_filter_ignored(self):
        response = self.client.get(f"/api/environments/{self.team.id}/conversations/tickets/?priority=invalid")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 1)

    def test_message_count_annotation(self):
        Comment.objects.create(
            team=self.team,
            scope="conversations_ticket",
            item_id=str(self.ticket.id),
            content="First message",
        )
        Comment.objects.create(
            team=self.team,
            scope="conversations_ticket",
            item_id=str(self.ticket.id),
            content="Second message",
        )
        response = self.client.get(f"/api/environments/{self.team.id}/conversations/tickets/{self.ticket.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["message_count"], 2)

    def test_last_message_annotation(self):
        Comment.objects.create(
            team=self.team,
            scope="conversations_ticket",
            item_id=str(self.ticket.id),
            content="First message",
        )
        Comment.objects.create(
            team=self.team,
            scope="conversations_ticket",
            item_id=str(self.ticket.id),
            content="Latest message",
        )
        response = self.client.get(f"/api/environments/{self.team.id}/conversations/tickets/{self.ticket.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["last_message_text"], "Latest message")
        self.assertIsNotNone(response.json()["last_message_at"])

    def test_deleted_messages_not_counted(self):
        Comment.objects.create(
            team=self.team,
            scope="conversations_ticket",
            item_id=str(self.ticket.id),
            content="Active message",
            deleted=False,
        )
        Comment.objects.create(
            team=self.team,
            scope="conversations_ticket",
            item_id=str(self.ticket.id),
            content="Deleted message",
            deleted=True,
        )
        response = self.client.get(f"/api/environments/{self.team.id}/conversations/tickets/{self.ticket.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["message_count"], 1)
