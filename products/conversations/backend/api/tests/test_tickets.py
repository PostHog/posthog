from datetime import timedelta

from posthog.test.base import (
    APIBaseTest,
    BaseTest,
    ClickhouseTestMixin,
    _create_person,
    get_index_from_explain,
    get_inner_person_subquery_clickhouse_sql,
    materialized,
    snapshot_clickhouse_queries,
)
from unittest.mock import patch

from django.db import transaction
from django.utils import timezone

from parameterized import parameterized, parameterized_class
from rest_framework import status

from posthog.schema import HogQLQueryModifiers, MaterializationMode

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.models import ActivityLog, Comment, Organization, User
from posthog.models.person import Person
from posthog.personhog_client.test_helpers import PersonhogTestMixin

from products.conversations.backend.models import Ticket, TicketAssignment
from products.conversations.backend.models.constants import Channel, ChannelDetail, Priority, Status
from products.conversations.backend.person_lookup import PERSON_EMAIL_LOOKUP_QUERY, _get_persons_by_email

from ee.clickhouse.materialized_columns.columns import get_bloom_filter_lower_index_name
from ee.models.rbac.role import Role


# Patch on_commit to execute immediately in tests
def immediate_on_commit(func):
    func()


@patch.object(transaction, "on_commit", side_effect=immediate_on_commit)
class TestTicketAPI(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.ticket = Ticket.objects.create_with_number(
            team=self.team,
            channel_source=Channel.WIDGET,
            widget_session_id="test-session-123",
            distinct_id="user-123",
            status=Status.NEW,
        )

    def test_list_tickets(self, mock_on_commit):
        response = self.client.get(f"/api/projects/{self.team.id}/conversations/tickets/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 1)
        self.assertEqual(response.json()["results"][0]["id"], str(self.ticket.id))

    def test_list_tickets_only_returns_team_tickets(self, mock_on_commit):
        other_ticket = Ticket.objects.create_with_number(
            team=self.team,
            channel_source=Channel.EMAIL,
            widget_session_id="other-session",
            distinct_id="other-user",
        )
        response = self.client.get(f"/api/projects/{self.team.id}/conversations/tickets/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 2)
        ticket_ids = {t["id"] for t in response.json()["results"]}
        self.assertIn(str(self.ticket.id), ticket_ids)
        self.assertIn(str(other_ticket.id), ticket_ids)

    def test_retrieve_ticket(self, mock_on_commit):
        response = self.client.get(f"/api/projects/{self.team.id}/conversations/tickets/{self.ticket.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["id"], str(self.ticket.id))
        self.assertEqual(response.json()["status"], Status.NEW)

    def test_retrieve_ticket_by_ticket_number(self, mock_on_commit):
        """Test retrieving a ticket by ticket_number instead of UUID."""
        response = self.client.get(f"/api/projects/{self.team.id}/conversations/tickets/{self.ticket.ticket_number}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["id"], str(self.ticket.id))
        self.assertEqual(response.json()["ticket_number"], self.ticket.ticket_number)

    def test_retrieve_ticket_by_uuid_still_works(self, mock_on_commit):
        """Test that UUID lookup still works for backward compatibility."""
        response = self.client.get(f"/api/projects/{self.team.id}/conversations/tickets/{self.ticket.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["id"], str(self.ticket.id))

    def test_retrieve_ticket_invalid_identifier_returns_404(self, mock_on_commit):
        """Test that invalid identifier returns 404."""
        response = self.client.get(f"/api/projects/{self.team.id}/conversations/tickets/invalid/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_update_ticket_by_ticket_number(self, mock_on_commit):
        """Test updating a ticket using ticket_number."""
        response = self.client.patch(
            f"/api/projects/{self.team.id}/conversations/tickets/{self.ticket.ticket_number}/",
            {"status": "resolved"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["status"], "resolved")

    def test_retrieve_ticket_marks_as_read(self, mock_on_commit):
        self.ticket.unread_team_count = 5
        self.ticket.save()

        response = self.client.get(f"/api/projects/{self.team.id}/conversations/tickets/{self.ticket.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["unread_team_count"], 0)

        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.unread_team_count, 0)

    def test_retrieve_ticket_includes_anonymous_traits(self, mock_on_commit):
        """Test that retrieve includes anonymous_traits."""
        self.ticket.anonymous_traits = {"name": "John Doe", "email": "john@example.com"}
        self.ticket.save()

        response = self.client.get(f"/api/projects/{self.team.id}/conversations/tickets/{self.ticket.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("anonymous_traits", response.json())
        self.assertEqual(response.json()["anonymous_traits"]["name"], "John Doe")
        self.assertEqual(response.json()["anonymous_traits"]["email"], "john@example.com")

    def test_list_tickets_includes_anonymous_traits(self, mock_on_commit):
        """Test that list includes anonymous_traits."""
        self.ticket.anonymous_traits = {"name": "Jane Doe", "company": "ACME"}
        self.ticket.save()

        response = self.client.get(f"/api/projects/{self.team.id}/conversations/tickets/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 1)
        self.assertIn("anonymous_traits", response.json()["results"][0])
        self.assertEqual(response.json()["results"][0]["anonymous_traits"]["name"], "Jane Doe")
        self.assertEqual(response.json()["results"][0]["anonymous_traits"]["company"], "ACME")

    def test_update_sla_due_at(self, mock_on_commit):
        sla_time = timezone.now() + timedelta(hours=5)
        response = self.client.patch(
            f"/api/projects/{self.team.id}/conversations/tickets/{self.ticket.id}/",
            {"sla_due_at": sla_time.isoformat()},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNotNone(response.json()["sla_due_at"])

        self.ticket.refresh_from_db()
        self.assertIsNotNone(self.ticket.sla_due_at)

    def test_update_sla_due_at_logs_activity(self, mock_on_commit):
        sla_time = timezone.now() + timedelta(hours=5)
        response = self.client.patch(
            f"/api/projects/{self.team.id}/conversations/tickets/{self.ticket.id}/",
            {"sla_due_at": sla_time.isoformat()},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        activity = ActivityLog.objects.filter(
            team_id=self.team.id,
            scope="Ticket",
            item_id=str(self.ticket.id),
            activity="updated",
        ).first()

        assert activity is not None
        assert activity.detail is not None
        changes = activity.detail.get("changes", [])
        sla_change = next((c for c in changes if c["field"] == "sla_due_at"), None)
        assert sla_change is not None
        self.assertIsNone(sla_change["before"])
        self.assertIsNotNone(sla_change["after"])

    @parameterized.expand(
        [
            ("status", Status.RESOLVED, Status.RESOLVED),
            ("priority", Priority.HIGH, Priority.HIGH),
        ]
    )
    def test_update_ticket_field(self, mock_on_commit, field_name, update_value, expected_response_value):
        response = self.client.patch(
            f"/api/projects/{self.team.id}/conversations/tickets/{self.ticket.id}/",
            {field_name: update_value},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()[field_name], expected_response_value)

        self.ticket.refresh_from_db()
        self.assertEqual(getattr(self.ticket, field_name), expected_response_value)

    @parameterized.expand(
        [
            (f"status={Status.NEW}", Status.NEW, "status", Status.NEW, {"status": Status.RESOLVED}),
            (f"priority={Priority.HIGH}", Priority.HIGH, "priority", Priority.HIGH, {"priority": Priority.LOW}),
            (
                f"channel_source={Channel.WIDGET}",
                Channel.WIDGET,
                "channel_source",
                Channel.WIDGET,
                {"channel_source": Channel.EMAIL},
            ),
            (
                f"channel_detail={ChannelDetail.WIDGET_EMBEDDED}",
                ChannelDetail.WIDGET_EMBEDDED,
                "channel_detail",
                ChannelDetail.WIDGET_EMBEDDED,
                {"channel_detail": ChannelDetail.WIDGET_API},
            ),
            ("distinct_ids=user-123", "user-123", "distinct_id", "user-123", {}),
        ]
    )
    def test_filter_tickets(
        self, mock_on_commit, filter_param, expected_value, response_field, expected_response_value, other_ticket_attrs
    ):
        """Test filtering tickets by various fields."""
        if expected_value and expected_value != "user-123":
            setattr(self.ticket, response_field, expected_value)
            self.ticket.save()

        other_channel = other_ticket_attrs.pop("channel_source", Channel.WIDGET)
        other_distinct_id = other_ticket_attrs.pop("distinct_id", "other-user")

        Ticket.objects.create_with_number(
            team=self.team,
            channel_source=other_channel,
            widget_session_id="other-session",
            distinct_id=other_distinct_id,
            **other_ticket_attrs,
        )

        response = self.client.get(f"/api/projects/{self.team.id}/conversations/tickets/?{filter_param}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 1)

        result = response.json()["results"][0]
        if expected_response_value is None:
            self.assertIsNone(result[response_field])
        else:
            self.assertEqual(result[response_field], expected_response_value)

    @parameterized.expand([("status", "invalid"), ("priority", "invalid")])
    def test_invalid_filter_ignored(self, mock_on_commit, filter_name, invalid_value):
        """Test that invalid filter values are ignored and all tickets are returned."""
        response = self.client.get(f"/api/projects/{self.team.id}/conversations/tickets/?{filter_name}={invalid_value}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 1)

    def test_filter_by_multiple_statuses(self, mock_on_commit):
        """Test filtering tickets by multiple statuses (comma-separated)."""
        self.ticket.status = Status.NEW
        self.ticket.save()

        open_ticket = Ticket.objects.create_with_number(
            team=self.team,
            channel_source=Channel.WIDGET,
            widget_session_id="open-session",
            distinct_id="open-user",
            status=Status.OPEN,
        )
        resolved_ticket = Ticket.objects.create_with_number(
            team=self.team,
            channel_source=Channel.WIDGET,
            widget_session_id="resolved-session",
            distinct_id="resolved-user",
            status=Status.RESOLVED,
        )

        response = self.client.get(f"/api/projects/{self.team.id}/conversations/tickets/?status=new,open")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 2)
        ticket_ids = {t["id"] for t in response.json()["results"]}
        self.assertIn(str(self.ticket.id), ticket_ids)
        self.assertIn(str(open_ticket.id), ticket_ids)
        self.assertNotIn(str(resolved_ticket.id), ticket_ids)

    def test_filter_by_multiple_priorities(self, mock_on_commit):
        """Test filtering tickets by multiple priorities (comma-separated)."""
        self.ticket.priority = Priority.LOW
        self.ticket.save()

        high_ticket = Ticket.objects.create_with_number(
            team=self.team,
            channel_source=Channel.WIDGET,
            widget_session_id="high-session",
            distinct_id="high-user",
            priority=Priority.HIGH,
        )
        medium_ticket = Ticket.objects.create_with_number(
            team=self.team,
            channel_source=Channel.WIDGET,
            widget_session_id="medium-session",
            distinct_id="medium-user",
            priority=Priority.MEDIUM,
        )

        response = self.client.get(f"/api/projects/{self.team.id}/conversations/tickets/?priority=low,high")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 2)
        ticket_ids = {t["id"] for t in response.json()["results"]}
        self.assertIn(str(self.ticket.id), ticket_ids)
        self.assertIn(str(high_ticket.id), ticket_ids)
        self.assertNotIn(str(medium_ticket.id), ticket_ids)

    def test_filter_multiple_statuses_and_priorities(self, mock_on_commit):
        """Test filtering tickets by multiple statuses AND multiple priorities."""
        self.ticket.status = Status.NEW
        self.ticket.priority = Priority.HIGH
        self.ticket.save()

        open_low = Ticket.objects.create_with_number(
            team=self.team,
            channel_source=Channel.WIDGET,
            widget_session_id="open-low-session",
            distinct_id="open-low-user",
            status=Status.OPEN,
            priority=Priority.LOW,
        )
        resolved_high = Ticket.objects.create_with_number(
            team=self.team,
            channel_source=Channel.WIDGET,
            widget_session_id="resolved-high-session",
            distinct_id="resolved-high-user",
            status=Status.RESOLVED,
            priority=Priority.HIGH,
        )

        response = self.client.get(
            f"/api/projects/{self.team.id}/conversations/tickets/?status=new,open&priority=high,low"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 2)
        ticket_ids = {t["id"] for t in response.json()["results"]}
        self.assertIn(str(self.ticket.id), ticket_ids)
        self.assertIn(str(open_low.id), ticket_ids)
        self.assertNotIn(str(resolved_high.id), ticket_ids)

    def test_filter_multiple_statuses_with_invalid_value(self, mock_on_commit):
        """Test that invalid values in comma-separated list are ignored."""
        self.ticket.status = Status.NEW
        self.ticket.save()

        open_ticket = Ticket.objects.create_with_number(
            team=self.team,
            channel_source=Channel.WIDGET,
            widget_session_id="open-session",
            distinct_id="open-user",
            status=Status.OPEN,
        )

        response = self.client.get(f"/api/projects/{self.team.id}/conversations/tickets/?status=new,invalid,open")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 2)
        ticket_ids = {t["id"] for t in response.json()["results"]}
        self.assertIn(str(self.ticket.id), ticket_ids)
        self.assertIn(str(open_ticket.id), ticket_ids)

    def test_filter_empty_status_returns_all(self, mock_on_commit):
        """Test that empty status param returns all tickets."""
        Ticket.objects.create_with_number(
            team=self.team,
            channel_source=Channel.WIDGET,
            widget_session_id="other-session",
            distinct_id="other-user",
        )

        response = self.client.get(f"/api/projects/{self.team.id}/conversations/tickets/?status=")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 2)

    def test_filter_single_status_backward_compatible(self, mock_on_commit):
        """Test that single status filter still works (backward compatibility)."""
        self.ticket.status = Status.NEW
        self.ticket.save()

        Ticket.objects.create_with_number(
            team=self.team,
            channel_source=Channel.WIDGET,
            widget_session_id="open-session",
            distinct_id="open-user",
            status=Status.OPEN,
        )

        response = self.client.get(f"/api/projects/{self.team.id}/conversations/tickets/?status=new")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 1)
        self.assertEqual(response.json()["results"][0]["id"], str(self.ticket.id))

    def test_filter_date_from_all_returns_all_tickets(self, mock_on_commit):
        """Test that date_from=all returns all tickets without date filtering."""
        Ticket.objects.create_with_number(
            team=self.team,
            channel_source=Channel.WIDGET,
            widget_session_id="other-session",
            distinct_id="other-user",
        )

        response = self.client.get(f"/api/projects/{self.team.id}/conversations/tickets/?date_from=all")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 2)

    def test_filter_sla_breached(self, mock_on_commit):
        """Test filtering tickets by breached SLA."""
        self.ticket.sla_due_at = timezone.now() - timedelta(hours=1)
        self.ticket.save()

        Ticket.objects.create_with_number(
            team=self.team,
            channel_source=Channel.WIDGET,
            widget_session_id="on-track-session",
            distinct_id="on-track-user",
            sla_due_at=timezone.now() + timedelta(hours=5),
        )

        response = self.client.get(f"/api/projects/{self.team.id}/conversations/tickets/?sla=breached")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 1)
        self.assertEqual(response.json()["results"][0]["id"], str(self.ticket.id))

    def test_filter_sla_at_risk(self, mock_on_commit):
        """Test filtering tickets by at-risk SLA (within 1 hour)."""
        self.ticket.sla_due_at = timezone.now() + timedelta(minutes=30)
        self.ticket.save()

        Ticket.objects.create_with_number(
            team=self.team,
            channel_source=Channel.WIDGET,
            widget_session_id="on-track-session",
            distinct_id="on-track-user",
            sla_due_at=timezone.now() + timedelta(hours=5),
        )

        response = self.client.get(f"/api/projects/{self.team.id}/conversations/tickets/?sla=at-risk")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 1)
        self.assertEqual(response.json()["results"][0]["id"], str(self.ticket.id))

    def test_filter_sla_on_track(self, mock_on_commit):
        """Test filtering tickets by on-track SLA (more than 1 hour remaining)."""
        self.ticket.sla_due_at = timezone.now() + timedelta(hours=5)
        self.ticket.save()

        Ticket.objects.create_with_number(
            team=self.team,
            channel_source=Channel.WIDGET,
            widget_session_id="breached-session",
            distinct_id="breached-user",
            sla_due_at=timezone.now() - timedelta(hours=1),
        )

        response = self.client.get(f"/api/projects/{self.team.id}/conversations/tickets/?sla=on-track")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 1)
        self.assertEqual(response.json()["results"][0]["id"], str(self.ticket.id))

    def test_order_by_sla_due_at(self, mock_on_commit):
        """Test ordering tickets by SLA deadline."""
        self.ticket.sla_due_at = timezone.now() + timedelta(hours=5)
        self.ticket.save()

        urgent_ticket = Ticket.objects.create_with_number(
            team=self.team,
            channel_source=Channel.WIDGET,
            widget_session_id="urgent-session",
            distinct_id="urgent-user",
            sla_due_at=timezone.now() + timedelta(hours=1),
        )

        response = self.client.get(f"/api/projects/{self.team.id}/conversations/tickets/?order_by=sla_due_at")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.json()["results"]
        self.assertEqual(results[0]["id"], str(urgent_ticket.id))
        self.assertEqual(results[1]["id"], str(self.ticket.id))

    def test_filter_multiple_priorities_excludes_null(self, mock_on_commit):
        """Test that multiple priority filter excludes tickets with NULL priority."""
        self.ticket.priority = Priority.LOW
        self.ticket.save()

        high_ticket = Ticket.objects.create_with_number(
            team=self.team,
            channel_source=Channel.WIDGET,
            widget_session_id="high-session",
            distinct_id="high-user",
            priority=Priority.HIGH,
        )
        Ticket.objects.create_with_number(
            team=self.team,
            channel_source=Channel.WIDGET,
            widget_session_id="null-session",
            distinct_id="null-user",
            priority=None,
        )

        response = self.client.get(f"/api/projects/{self.team.id}/conversations/tickets/?priority=low,high")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 2)
        ticket_ids = {t["id"] for t in response.json()["results"]}
        self.assertIn(str(self.ticket.id), ticket_ids)
        self.assertIn(str(high_ticket.id), ticket_ids)

    def test_search_by_ticket_number(self, mock_on_commit):
        response = self.client.get(
            f"/api/projects/{self.team.id}/conversations/tickets/?search={self.ticket.ticket_number}"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 1)
        self.assertEqual(response.json()["results"][0]["id"], str(self.ticket.id))

    @parameterized.expand(
        [
            ("anonymous_name", {"anonymous_traits": {"name": "Alice Wonder"}}, "alice"),
            ("anonymous_email", {"anonymous_traits": {"email": "bob@example.com"}}, "bob@example"),
            ("email_subject", {"email_subject": "Billing issue", "channel_source": Channel.EMAIL}, "billing"),
        ]
    )
    def test_search_by_field(self, mock_on_commit, _name, field_overrides, query):
        for field, value in field_overrides.items():
            setattr(self.ticket, field, value)
        self.ticket.save()

        response = self.client.get(f"/api/projects/{self.team.id}/conversations/tickets/?search={query}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 1)
        self.assertEqual(response.json()["results"][0]["id"], str(self.ticket.id))

    def test_search_by_comment_content(self, mock_on_commit):
        Comment.objects.create(
            team=self.team,
            scope="conversations_ticket",
            item_id=str(self.ticket.id),
            content="I need help with the API integration",
        )

        response = self.client.get(f"/api/projects/{self.team.id}/conversations/tickets/?search=API+integration")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 1)
        self.assertEqual(response.json()["results"][0]["id"], str(self.ticket.id))

    def test_search_matches_older_comment_not_just_last(self, mock_on_commit):
        Comment.objects.create(
            team=self.team,
            scope="conversations_ticket",
            item_id=str(self.ticket.id),
            content="First message about passwords",
        )
        Comment.objects.create(
            team=self.team,
            scope="conversations_ticket",
            item_id=str(self.ticket.id),
            content="Thanks, all sorted now",
        )

        response = self.client.get(f"/api/projects/{self.team.id}/conversations/tickets/?search=passwords")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 1)

    def test_search_excludes_deleted_comments(self, mock_on_commit):
        comment = Comment.objects.create(
            team=self.team,
            scope="conversations_ticket",
            item_id=str(self.ticket.id),
            content="Secret deleted message",
        )
        comment.deleted = True
        comment.save()

        response = self.client.get(f"/api/projects/{self.team.id}/conversations/tickets/?search=secret+deleted")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 0)

    def test_search_no_match_returns_empty(self, mock_on_commit):
        response = self.client.get(
            f"/api/projects/{self.team.id}/conversations/tickets/?search=nonexistent_query_xyzzy"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 0)

    def test_search_ignores_too_long_query(self, mock_on_commit):
        long_query = "a" * 201
        response = self.client.get(f"/api/projects/{self.team.id}/conversations/tickets/?search={long_query}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 1)

    @parameterized.expand(
        [
            (
                "message_count",
                [("First message", False), ("Second message", False)],
                {"message_count": 2},
            ),
            (
                "last_message",
                [("First message", False), ("Latest message", False)],
                {"last_message_text": "Latest message", "last_message_at": "not_none"},
            ),
            (
                "deleted_messages_excluded",
                [("Active message", False), ("Deleted message", "soft_delete")],
                {"message_count": 1},
            ),
        ]
    )
    def test_message_annotations(self, mock_on_commit, test_name, messages, expected_fields):
        """Test that denormalized message stats are correctly maintained on tickets."""
        for content, should_delete in messages:
            comment = Comment.objects.create(
                team=self.team,
                scope="conversations_ticket",
                item_id=str(self.ticket.id),
                content=content,
            )
            # Soft-delete after creation (realistic flow)
            if should_delete == "soft_delete":
                comment.deleted = True
                comment.save()

        response = self.client.get(f"/api/projects/{self.team.id}/conversations/tickets/{self.ticket.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        for field_name, expected_value in expected_fields.items():
            if expected_value == "not_none":
                self.assertIsNotNone(response.json()[field_name])
            else:
                self.assertEqual(response.json()[field_name], expected_value)

    def test_list_tickets_no_n_plus_one_queries(self, mock_on_commit):
        """Verify ticket list doesn't trigger N+1 queries for assigned users or persons.
        Message stats (message_count, last_message_at, last_message_text) are now
        denormalized on the Ticket model, so no subqueries needed.
        Person data is batch-fetched in a single query.
        """
        # Create 10 tickets with messages, assignments, and persons
        for i in range(10):
            ticket = Ticket.objects.create_with_number(
                team=self.team,
                channel_source=Channel.WIDGET,
                widget_session_id=f"session-{i}",
                distinct_id=f"user-{i}",
            )
            # Create person for this ticket
            Person.objects.create(
                team=self.team,
                distinct_ids=[f"user-{i}"],
                properties={"email": f"user{i}@example.com"},
            )
            # Assign user to ticket
            TicketAssignment.objects.create(ticket=ticket, user=self.user)
            # Add 2 messages per ticket (updates denormalized fields via signal)
            Comment.objects.create(
                team=self.team,
                scope="conversations_ticket",
                item_id=str(ticket.id),
                content=f"Message 1 for ticket {i}",
                created_by=self.user,
            )
            Comment.objects.create(
                team=self.team,
                scope="conversations_ticket",
                item_id=str(ticket.id),
                content=f"Message 2 for ticket {i}",
                created_by=self.user,
            )

        # Query count should be constant regardless of number of tickets
        # Includes: session, user, org, team, permissions, feature flag permission org lookup,
        # count query, tickets query, persons query (batch), distinct_ids prefetch,
        # tagged_items prefetch
        # Note: message stats are denormalized, no subqueries needed
        with self.assertNumQueries(14):
            response = self.client.get(f"/api/projects/{self.team.id}/conversations/tickets/")
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            # Should have original ticket + 10 new tickets = 11 total
            self.assertEqual(response.json()["count"], 11)
            # Verify all denormalized fields are present
            for ticket_data in response.json()["results"]:
                self.assertIn("message_count", ticket_data)
                self.assertIn("last_message_at", ticket_data)
                self.assertIn("last_message_text", ticket_data)
                self.assertIn("assignee", ticket_data)
                self.assertIn("person", ticket_data)


class TestTicketAssignment(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.ticket = Ticket.objects.create_with_number(
            team=self.team,
            channel_source=Channel.WIDGET,
            widget_session_id="test-session-123",
            distinct_id="user-123",
            status=Status.NEW,
        )
        self.role = Role.objects.create(name="Support Team", organization=self.organization)

    def test_assign_ticket_to_user(self):
        """Test assigning a ticket to a user."""
        self.assertEqual(TicketAssignment.objects.count(), 0)

        response = self.client.patch(
            f"/api/projects/{self.team.id}/conversations/tickets/{self.ticket.id}/",
            {"assignee": {"id": self.user.id, "type": "user"}},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["assignee"]["id"], self.user.id)
        self.assertEqual(response.json()["assignee"]["type"], "user")

        self.assertEqual(TicketAssignment.objects.count(), 1)
        assignment = TicketAssignment.objects.get(ticket=self.ticket)
        self.assertEqual(assignment.user_id, self.user.id)
        self.assertIsNone(assignment.role_id)

    def test_assign_ticket_to_role(self):
        """Test assigning a ticket to a role."""
        self.assertEqual(TicketAssignment.objects.count(), 0)

        response = self.client.patch(
            f"/api/projects/{self.team.id}/conversations/tickets/{self.ticket.id}/",
            {"assignee": {"id": str(self.role.id), "type": "role"}},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["assignee"]["id"], str(self.role.id))
        self.assertEqual(response.json()["assignee"]["type"], "role")

        self.assertEqual(TicketAssignment.objects.count(), 1)
        assignment = TicketAssignment.objects.get(ticket=self.ticket)
        self.assertIsNone(assignment.user_id)
        self.assertEqual(assignment.role_id, self.role.id)

    def test_update_assignment_from_user_to_role(self):
        """Test updating assignment from user to role."""
        TicketAssignment.objects.create(ticket=self.ticket, user=self.user)
        self.assertEqual(TicketAssignment.objects.count(), 1)

        response = self.client.patch(
            f"/api/projects/{self.team.id}/conversations/tickets/{self.ticket.id}/",
            {"assignee": {"id": str(self.role.id), "type": "role"}},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["assignee"]["type"], "role")

        self.assertEqual(TicketAssignment.objects.count(), 1)
        assignment = TicketAssignment.objects.get(ticket=self.ticket)
        self.assertIsNone(assignment.user_id)
        self.assertEqual(assignment.role_id, self.role.id)

    def test_remove_assignment(self):
        """Test removing assignment from ticket."""
        TicketAssignment.objects.create(ticket=self.ticket, user=self.user)
        self.assertEqual(TicketAssignment.objects.count(), 1)

        response = self.client.patch(
            f"/api/projects/{self.team.id}/conversations/tickets/{self.ticket.id}/",
            {"assignee": None},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNone(response.json()["assignee"])
        self.assertEqual(TicketAssignment.objects.count(), 0)

    def test_serialization_returns_correct_format(self):
        """Test that assignee serialization returns correct {id, type} format."""
        TicketAssignment.objects.create(ticket=self.ticket, user=self.user)

        response = self.client.get(f"/api/projects/{self.team.id}/conversations/tickets/{self.ticket.id}/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("assignee", response.json())
        self.assertEqual(response.json()["assignee"]["id"], self.user.id)
        self.assertEqual(response.json()["assignee"]["type"], "user")

    def test_unassigned_ticket_returns_null_assignee(self):
        """Test that unassigned ticket returns null for assignee."""
        response = self.client.get(f"/api/projects/{self.team.id}/conversations/tickets/{self.ticket.id}/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNone(response.json()["assignee"])

    def test_filter_by_user_assignment(self):
        """Test filtering tickets by user assignment."""
        TicketAssignment.objects.create(ticket=self.ticket, user=self.user)

        Ticket.objects.create_with_number(
            team=self.team,
            channel_source=Channel.WIDGET,
            widget_session_id="other-session",
            distinct_id="other-user",
        )

        response = self.client.get(f"/api/projects/{self.team.id}/conversations/tickets/?assignee=user:{self.user.id}")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 1)
        self.assertEqual(response.json()["results"][0]["id"], str(self.ticket.id))

    def test_filter_by_role_assignment(self):
        """Test filtering tickets by role assignment."""
        TicketAssignment.objects.create(ticket=self.ticket, role=self.role)

        Ticket.objects.create_with_number(
            team=self.team,
            channel_source=Channel.WIDGET,
            widget_session_id="other-session",
            distinct_id="other-user",
        )

        response = self.client.get(f"/api/projects/{self.team.id}/conversations/tickets/?assignee=role:{self.role.id}")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 1)
        self.assertEqual(response.json()["results"][0]["id"], str(self.ticket.id))

    def test_filter_unassigned_tickets(self):
        """Test filtering for unassigned tickets."""
        assigned_ticket = Ticket.objects.create_with_number(
            team=self.team,
            channel_source=Channel.WIDGET,
            widget_session_id="assigned-session",
            distinct_id="assigned-user",
        )
        TicketAssignment.objects.create(ticket=assigned_ticket, user=self.user)

        response = self.client.get(f"/api/projects/{self.team.id}/conversations/tickets/?assignee=unassigned")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 1)
        self.assertEqual(response.json()["results"][0]["id"], str(self.ticket.id))

    def test_assignment_logs_activity(self):
        """Test that assignment changes are logged in activity log."""
        response = self.client.patch(
            f"/api/projects/{self.team.id}/conversations/tickets/{self.ticket.id}/",
            {"assignee": {"id": self.user.id, "type": "user"}},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        activity = ActivityLog.objects.filter(
            team_id=self.team.id,
            scope="Ticket",
            item_id=str(self.ticket.id),
            activity="assigned",
        ).first()

        assert activity is not None
        assert activity.detail is not None
        self.assertEqual(activity.detail["changes"][0]["field"], "assignee")
        self.assertIsNone(activity.detail["changes"][0]["before"])
        self.assertEqual(activity.detail["changes"][0]["after"]["id"], self.user.id)
        self.assertEqual(activity.detail["changes"][0]["after"]["type"], "user")

    @parameterized.expand(
        [
            ("missing_type", {"id": 1}, "must have 'type' and 'id'"),
            ("missing_id", {"type": "user"}, "must have 'type' and 'id'"),
            ("invalid_type", {"id": 1, "type": "invalid"}, "type must be 'user' or 'role'"),
            ("not_an_object", "invalid", "must be an object"),
        ]
    )
    def test_invalid_assignee_payload(self, name, payload, expected_error):
        response = self.client.patch(
            f"/api/projects/{self.team.id}/conversations/tickets/{self.ticket.id}/",
            {"assignee": payload},
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn(expected_error, str(response.json()))

    def test_assign_to_user_not_in_organization(self):
        other_user = User.objects.create(email="other@example.com")

        response = self.client.patch(
            f"/api/projects/{self.team.id}/conversations/tickets/{self.ticket.id}/",
            {"assignee": {"id": other_user.id, "type": "user"}},
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("not a member of this organization", str(response.json()))
        self.assertEqual(TicketAssignment.objects.count(), 0)

    def test_assign_to_role_not_in_organization(self):
        other_org = Organization.objects.create(name="Other Org")
        other_role = Role.objects.create(name="Other Role", organization=other_org)

        response = self.client.patch(
            f"/api/projects/{self.team.id}/conversations/tickets/{self.ticket.id}/",
            {"assignee": {"id": str(other_role.id), "type": "role"}},
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("does not belong to this organization", str(response.json()))
        self.assertEqual(TicketAssignment.objects.count(), 0)


@patch.object(transaction, "on_commit", side_effect=immediate_on_commit)
class TestUnreadCountEndpoint(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.team.conversations_enabled = True
        self.team.save()

    def test_unread_count_returns_zero_when_no_tickets(self, mock_on_commit):
        response = self.client.get(f"/api/projects/{self.team.id}/conversations/tickets/unread_count/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 0)

    def test_unread_count_returns_sum_of_unread_team_count(self, mock_on_commit):
        Ticket.objects.create_with_number(
            team=self.team,
            channel_source=Channel.WIDGET,
            widget_session_id="session-1",
            distinct_id="user-1",
            unread_team_count=3,
        )
        Ticket.objects.create_with_number(
            team=self.team,
            channel_source=Channel.WIDGET,
            widget_session_id="session-2",
            distinct_id="user-2",
            unread_team_count=2,
        )

        response = self.client.get(f"/api/projects/{self.team.id}/conversations/tickets/unread_count/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 5)

    def test_unread_count_excludes_resolved_tickets(self, mock_on_commit):
        Ticket.objects.create_with_number(
            team=self.team,
            channel_source=Channel.WIDGET,
            widget_session_id="session-1",
            distinct_id="user-1",
            unread_team_count=3,
            status=Status.NEW,
        )
        Ticket.objects.create_with_number(
            team=self.team,
            channel_source=Channel.WIDGET,
            widget_session_id="session-2",
            distinct_id="user-2",
            unread_team_count=5,
            status=Status.RESOLVED,
        )

        response = self.client.get(f"/api/projects/{self.team.id}/conversations/tickets/unread_count/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 3)

    def test_unread_count_returns_zero_when_conversations_disabled(self, mock_on_commit):
        self.team.conversations_enabled = False
        self.team.save()

        Ticket.objects.create_with_number(
            team=self.team,
            channel_source=Channel.WIDGET,
            widget_session_id="session-1",
            distinct_id="user-1",
            unread_team_count=5,
        )

        response = self.client.get(f"/api/projects/{self.team.id}/conversations/tickets/unread_count/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 0)

    @patch("products.conversations.backend.api.tickets.invalidate_unread_count_cache")
    def test_retrieve_ticket_invalidates_cache_when_marking_as_read(self, mock_invalidate, mock_on_commit):
        ticket = Ticket.objects.create_with_number(
            team=self.team,
            channel_source=Channel.WIDGET,
            widget_session_id="session-1",
            distinct_id="user-1",
            unread_team_count=3,
        )

        response = self.client.get(f"/api/projects/{self.team.id}/conversations/tickets/{ticket.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_invalidate.assert_called_once_with(self.team.id)

    @patch("products.conversations.backend.api.tickets.invalidate_unread_count_cache")
    def test_retrieve_ticket_does_not_invalidate_cache_when_already_read(self, mock_invalidate, mock_on_commit):
        ticket = Ticket.objects.create_with_number(
            team=self.team,
            channel_source=Channel.WIDGET,
            widget_session_id="session-1",
            distinct_id="user-1",
            unread_team_count=0,
        )

        response = self.client.get(f"/api/projects/{self.team.id}/conversations/tickets/{ticket.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_invalidate.assert_not_called()

    @patch("products.conversations.backend.api.tickets.invalidate_unread_count_cache")
    def test_update_ticket_invalidates_cache_when_resolved(self, mock_invalidate, mock_on_commit):
        ticket = Ticket.objects.create_with_number(
            team=self.team,
            channel_source=Channel.WIDGET,
            widget_session_id="session-1",
            distinct_id="user-1",
            status=Status.NEW,
        )

        response = self.client.patch(
            f"/api/projects/{self.team.id}/conversations/tickets/{ticket.id}/",
            {"status": Status.RESOLVED},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_invalidate.assert_called_once_with(self.team.id)

    @patch("products.conversations.backend.api.tickets.invalidate_unread_count_cache")
    def test_update_ticket_invalidates_cache_when_reopened(self, mock_invalidate, mock_on_commit):
        ticket = Ticket.objects.create_with_number(
            team=self.team,
            channel_source=Channel.WIDGET,
            widget_session_id="session-1",
            distinct_id="user-1",
            status=Status.RESOLVED,
        )

        response = self.client.patch(
            f"/api/projects/{self.team.id}/conversations/tickets/{ticket.id}/",
            {"status": Status.OPEN},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_invalidate.assert_called_once_with(self.team.id)

    @patch("products.conversations.backend.api.tickets.invalidate_unread_count_cache")
    def test_update_ticket_does_not_invalidate_cache_for_other_changes(self, mock_invalidate, mock_on_commit):
        ticket = Ticket.objects.create_with_number(
            team=self.team,
            channel_source=Channel.WIDGET,
            widget_session_id="session-1",
            distinct_id="user-1",
            status=Status.NEW,
        )

        response = self.client.patch(
            f"/api/projects/{self.team.id}/conversations/tickets/{ticket.id}/",
            {"priority": Priority.HIGH},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_invalidate.assert_not_called()


@patch.object(transaction, "on_commit", side_effect=immediate_on_commit)
class TestPrivateMessageAppAPI(APIBaseTest):
    """Test that authenticated App API users can create private messages."""

    def setUp(self):
        super().setUp()
        self.ticket = Ticket.objects.create_with_number(
            team=self.team,
            channel_source=Channel.WIDGET,
            widget_session_id="test-session-123",
            distinct_id="user-123",
            status=Status.NEW,
        )

    def test_app_api_can_create_private_message(self, mock_on_commit):
        """Verify authenticated users can create private messages via App API."""
        response = self.client.post(
            f"/api/projects/{self.team.id}/comments/",
            {
                "content": "Private internal note",
                "scope": "conversations_ticket",
                "item_id": str(self.ticket.id),
                "item_context": {"author_type": "support", "is_private": True},
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Verify comment was created with is_private=True
        comment = Comment.objects.get(id=response.json()["id"])
        assert comment.item_context is not None
        self.assertTrue(comment.item_context["is_private"])

        # Verify private message doesn't affect denormalized stats
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.message_count, 0)
        self.assertIsNone(self.ticket.last_message_text)

    def test_app_api_private_message_visible_in_comments_list(self, mock_on_commit):
        """Verify private messages are returned in App API comments list."""
        Comment.objects.create(
            team=self.team,
            scope="conversations_ticket",
            item_id=str(self.ticket.id),
            content="Private note",
            created_by=self.user,
            item_context={"author_type": "support", "is_private": True},
        )

        response = self.client.get(
            f"/api/projects/{self.team.id}/comments/?scope=conversations_ticket&item_id={self.ticket.id}"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["results"]), 1)
        self.assertEqual(response.json()["results"][0]["content"], "Private note")
        self.assertTrue(response.json()["results"][0]["item_context"]["is_private"])


class TestTicketManager(BaseTest):
    def test_requires_team(self):
        with self.assertRaises(ValueError) as ctx:
            Ticket.objects.create_with_number(
                channel_source=Channel.WIDGET,
                widget_session_id="test-session",
                distinct_id="user-123",
            )
        self.assertEqual(str(ctx.exception), "team is required")

    def test_auto_increments_ticket_number(self):
        ticket1 = Ticket.objects.create_with_number(
            team=self.team,
            channel_source=Channel.WIDGET,
            widget_session_id="session-1",
            distinct_id="user-1",
        )
        ticket2 = Ticket.objects.create_with_number(
            team=self.team,
            channel_source=Channel.WIDGET,
            widget_session_id="session-2",
            distinct_id="user-2",
        )

        self.assertEqual(ticket1.ticket_number, 1)
        self.assertEqual(ticket2.ticket_number, 2)


@parameterized_class(("personhog",), [(False,), (True,)])
@patch.object(transaction, "on_commit", side_effect=immediate_on_commit)
class TestTicketPersonData(PersonhogTestMixin, APIBaseTest):
    """Tests that ticket person enrichment produces identical results
    via the ORM and personhog paths."""

    def setUp(self):
        super().setUp()
        self.ticket = Ticket.objects.create_with_number(
            team=self.team,
            channel_source=Channel.WIDGET,
            widget_session_id="test-session-123",
            distinct_id="user-123",
            status=Status.NEW,
        )

    def test_retrieve_ticket_includes_person_data(self, mock_on_commit):
        person = self._seed_person(
            team=self.team,
            distinct_ids=["user-123", "user@example.com", "another-id"],
            properties={"email": "test@example.com", "name": "Test User"},
        )

        response = self.client.get(f"/api/projects/{self.team.id}/conversations/tickets/{self.ticket.id}/")

        assert response.status_code == status.HTTP_200_OK
        person_data = response.json()["person"]
        assert person_data is not None
        assert person_data["id"] == str(person.uuid)
        assert person_data["properties"]["email"] == "test@example.com"
        assert set(person_data["distinct_ids"]) == {"user-123", "user@example.com", "another-id"}

    def test_retrieve_ticket_person_null_when_no_person(self, mock_on_commit):
        response = self.client.get(f"/api/projects/{self.team.id}/conversations/tickets/{self.ticket.id}/")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["person"] is None

    def test_list_tickets_includes_person_data(self, mock_on_commit):
        self._seed_person(
            team=self.team,
            distinct_ids=["user-123", "user@example.com"],
            properties={"email": "test@example.com"},
        )

        response = self.client.get(f"/api/projects/{self.team.id}/conversations/tickets/")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["count"] == 1
        person_data = response.json()["results"][0]["person"]
        assert person_data is not None
        assert person_data["properties"]["email"] == "test@example.com"
        assert set(person_data["distinct_ids"]) == {"user-123", "user@example.com"}
        self._assert_personhog_called("get_persons_by_distinct_ids_in_team")

    def test_list_tickets_person_null_when_no_person(self, mock_on_commit):
        response = self.client.get(f"/api/projects/{self.team.id}/conversations/tickets/")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["count"] == 1
        assert response.json()["results"][0]["person"] is None

    def test_person_data_scoped_to_team(self, mock_on_commit):
        other_team = self.organization.teams.create(name="Other Team")
        self._seed_person(
            team=other_team,
            distinct_ids=["user-123"],
            properties={"email": "other@example.com"},
        )

        response = self.client.get(f"/api/projects/{self.team.id}/conversations/tickets/{self.ticket.id}/")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["person"] is None


@patch.object(transaction, "on_commit", side_effect=immediate_on_commit)
class TestTicketEmailFallbackPersonLookup(ClickhouseTestMixin, APIBaseTest):
    """Tests the email-property fallback in _attach_persons_to_tickets.

    When an email-channel ticket's distinct_id doesn't match any person,
    the fallback queries ClickHouse for persons whose properties.email
    matches the ticket's email_from field.
    """

    def _create_email_ticket(self, email_from, distinct_id=None):
        return Ticket.objects.create_with_number(
            team=self.team,
            channel_source=Channel.EMAIL,
            distinct_id=distinct_id or email_from,
            email_from=email_from,
            status=Status.NEW,
        )

    def test_email_fallback_matches_person_by_email_property(self, mock_on_commit):
        _create_person(
            team=self.team,
            distinct_ids=["some-other-id"],
            properties={"email": "alice@example.com"},
            immediate=True,
        )
        self._create_email_ticket(email_from="alice@example.com", distinct_id="alice@example.com")

        response = self.client.get(f"/api/projects/{self.team.id}/conversations/tickets/")

        assert response.status_code == status.HTTP_200_OK
        person_data = response.json()["results"][0]["person"]
        assert person_data is not None
        assert person_data["properties"]["email"] == "alice@example.com"

    def test_email_fallback_not_triggered_when_distinct_id_matches(self, mock_on_commit):
        person = _create_person(
            team=self.team,
            distinct_ids=["alice@example.com"],
            properties={"email": "alice@example.com"},
            immediate=True,
        )
        self._create_email_ticket(email_from="alice@example.com", distinct_id="alice@example.com")

        response = self.client.get(f"/api/projects/{self.team.id}/conversations/tickets/")

        assert response.status_code == status.HTTP_200_OK
        person_data = response.json()["results"][0]["person"]
        assert person_data is not None
        assert person_data["id"] == str(person.uuid)

    def test_email_fallback_no_match_returns_null_person(self, mock_on_commit):
        self._create_email_ticket(email_from="nobody@example.com", distinct_id="nobody@example.com")

        response = self.client.get(f"/api/projects/{self.team.id}/conversations/tickets/")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["results"][0]["person"] is None

    def test_email_fallback_batch_multiple_tickets(self, mock_on_commit):
        _create_person(
            team=self.team,
            distinct_ids=["uid-a"],
            properties={"email": "a@example.com"},
            immediate=True,
        )
        _create_person(
            team=self.team,
            distinct_ids=["uid-b"],
            properties={"email": "b@example.com"},
            immediate=True,
        )
        self._create_email_ticket(email_from="a@example.com", distinct_id="a@example.com")
        self._create_email_ticket(email_from="b@example.com", distinct_id="b@example.com")
        self._create_email_ticket(email_from="c@example.com", distinct_id="c@example.com")

        response = self.client.get(f"/api/projects/{self.team.id}/conversations/tickets/")

        assert response.status_code == status.HTTP_200_OK
        results = response.json()["results"]
        person_emails = {
            r["email_from"]: r["person"]["properties"]["email"] for r in results if r["person"] is not None
        }
        assert person_emails == {
            "a@example.com": "a@example.com",
            "b@example.com": "b@example.com",
        }
        no_person = [r for r in results if r["person"] is None]
        assert len(no_person) == 1
        assert no_person[0]["email_from"] == "c@example.com"

    def test_email_fallback_scoped_to_team(self, mock_on_commit):
        other_team = self.organization.teams.create(name="Other Team")
        _create_person(
            team=other_team,
            distinct_ids=["uid-other"],
            properties={"email": "scoped@example.com"},
            immediate=True,
        )
        self._create_email_ticket(email_from="scoped@example.com", distinct_id="scoped@example.com")

        response = self.client.get(f"/api/projects/{self.team.id}/conversations/tickets/")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["results"][0]["person"] is None

    def test_email_fallback_skipped_for_non_email_channels(self, mock_on_commit):
        _create_person(
            team=self.team,
            distinct_ids=["uid-widget"],
            properties={"email": "widget@example.com"},
            immediate=True,
        )
        Ticket.objects.create_with_number(
            team=self.team,
            channel_source=Channel.WIDGET,
            distinct_id="unmatched-did",
            status=Status.NEW,
        )

        response = self.client.get(f"/api/projects/{self.team.id}/conversations/tickets/")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["results"][0]["person"] is None

    @snapshot_clickhouse_queries
    def test_email_fallback_uses_bloom_filter_lower_skip_index(self, mock_on_commit):
        _create_person(
            team=self.team,
            distinct_ids=["idx-test-id"],
            properties={"email": "indexed@example.com"},
            immediate=True,
        )

        with materialized("person", "email", create_bloom_filter_lower_index=True) as mat_col:
            index_name = get_bloom_filter_lower_index_name(mat_col.name)
            modifiers = HogQLQueryModifiers(materializationMode=MaterializationMode.AUTO)

            assert "indexed@example.com" in _get_persons_by_email(
                self.team, ["indexed@example.com"], modifiers=modifiers
            )

            # EXPLAIN the person-filter subquery of the exact query that ran, not a hand-written approximation
            result = execute_hogql_query(
                PERSON_EMAIL_LOOKUP_QUERY,
                placeholders={"emails": ast.Constant(value=["indexed@example.com"])},
                team=self.team,
                modifiers=modifiers,
            )
            assert result.clickhouse
            subquery = get_inner_person_subquery_clickhouse_sql(result.clickhouse)
            index_info = get_index_from_explain(subquery, index_name)
            assert index_info is not None, f"Expected skip index {index_name} to be used:\n{subquery}"


@patch.object(transaction, "on_commit", side_effect=immediate_on_commit)
class TestComposeTicketAPI(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.team.conversations_enabled = True
        self.team.conversations_settings = {"email_enabled": True}
        self.team.save()
        from products.conversations.backend.models import EmailChannel

        self.email_config = EmailChannel.objects.create(
            team=self.team,
            from_email="support@example.com",
            from_name="Support",
            domain="example.com",
            domain_verified=True,
            inbound_token="test-token-compose",
        )

    def _compose(self, data):
        return self.client.post(
            f"/api/projects/{self.team.id}/conversations/tickets/compose/",
            data,
            format="json",
        )

    @parameterized.expand(
        [
            (
                "matching_email",
                ["user-abc"],
                {"email": "customer@test.com"},
                "customer@test.com",
                "user-abc",
                status.HTTP_201_CREATED,
                None,
            ),
            (
                "mismatched_email_rejected",
                ["user-abc"],
                {"email": "real@test.com"},
                "fake@other.com",
                "user-abc",
                status.HTTP_400_BAD_REQUEST,
                "does not match",
            ),
            (
                "person_has_no_email_allows_any",
                ["user-no-email"],
                {"name": "No Email User"},
                "anything@test.com",
                "user-no-email",
                status.HTTP_201_CREATED,
                None,
            ),
            (
                "person_not_found_allows_any",
                None,
                None,
                "someone@test.com",
                "nonexistent-user",
                status.HTTP_201_CREATED,
                None,
            ),
            (
                "no_distinct_id_no_validation",
                ["someone@test.com"],
                {"email": "someone@test.com"},
                "someone@test.com",
                None,
                status.HTTP_201_CREATED,
                None,
            ),
            (
                "case_insensitive_email_match",
                ["user-case"],
                {"email": "Customer@Test.COM"},
                "customer@test.com",
                "user-case",
                status.HTTP_201_CREATED,
                None,
            ),
        ]
    )
    def test_compose_email_validation(
        self,
        mock_on_commit,
        _name,
        distinct_ids,
        person_props,
        recipient_email,
        recipient_distinct_id,
        expected_status,
        expected_detail,
    ):
        if distinct_ids is not None:
            _create_person(
                team=self.team,
                distinct_ids=distinct_ids,
                properties=person_props or {},
                immediate=True,
            )

        data = {
            "recipient_email": recipient_email,
            "email_config_id": str(self.email_config.id),
            "message": "Hello!",
        }
        if recipient_distinct_id:
            data["recipient_distinct_id"] = recipient_distinct_id

        response = self._compose(data)

        assert response.status_code == expected_status
        if expected_detail:
            assert expected_detail in response.json()["detail"]
