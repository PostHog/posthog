import json
from datetime import timedelta
from decimal import Decimal

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

from parameterized import parameterized
from rest_framework import status

from posthog.schema import HogQLQueryModifiers, MaterializationMode

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.models import ActivityLog, Comment, Organization, Tag, User
from posthog.test.persons import create_person

from products.conversations.backend.api.tickets import TicketReplyRequestSerializer
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

    def _ticket_with_tags(self, *tag_names):
        ticket = Ticket.objects.create_with_number(
            team=self.team,
            channel_source=Channel.WIDGET,
            widget_session_id="-".join(tag_names) or "untagged",
            distinct_id="user-123",
            status=Status.NEW,
        )
        for name in tag_names:
            tag, _ = Tag.objects.get_or_create(name=name, team_id=self.team.id)
            ticket.tagged_items.create(tag=tag)
        return ticket

    def _list_ids(self, **params):
        response = self.client.get(f"/api/projects/{self.team.id}/conversations/tickets/", data=params)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        return {r["id"] for r in response.json()["results"]}

    @parameterized.expand(
        [
            ("tags_matches_any", {"tags": '["alpha", "beta"]'}, {"alpha_beta", "alpha", "beta_gamma"}),
            ("tags_all_matches_every", {"tags_all": '["alpha", "beta"]'}, {"alpha_beta"}),
            ("tags_exclude_drops_tagged", {"tags_exclude": '["gamma"]'}, {"alpha_beta", "alpha"}),
            (
                "tags_all_composes_with_tags_exclude",
                {"tags_all": '["alpha"]', "tags_exclude": '["beta"]'},
                {"alpha"},
            ),
            ("malformed_json_ignored", {"tags_all": "not-json"}, {"alpha_beta", "alpha", "beta_gamma"}),
            ("oversized_list_capped_not_500", {"tags_all": json.dumps([f"t{i}" for i in range(200)])}, set()),
        ]
    )
    def test_filter_tags(self, mock_on_commit, _name, params, expected_keys):
        # Expectations are fixture keys rather than ids (tickets don't exist at decorator
        # time); the response is projected onto the fixture, which also keeps the untagged
        # setUp ticket out of the comparison.
        fixture = {
            "alpha_beta": self._ticket_with_tags("alpha", "beta"),
            "alpha": self._ticket_with_tags("alpha"),
            "beta_gamma": self._ticket_with_tags("beta", "gamma"),
        }
        ids = self._list_ids(**params)
        self.assertEqual({key for key, ticket in fixture.items() if str(ticket.id) in ids}, expected_keys)

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
            create_person(
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
        # count query, tickets query, tagged_items prefetch, and the session-activity metadata
        # write (deferred to on_commit, which this test class patches to run synchronously)
        # Note: person reads go through personhog (no DB queries)
        with self.assertNumQueries(12):
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


@patch.object(transaction, "on_commit", side_effect=immediate_on_commit)
class TestBulkUpdateStatus(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.tickets = [
            Ticket.objects.create_with_number(
                team=self.team,
                channel_source=Channel.WIDGET,
                widget_session_id=f"sess-{i}",
                distinct_id=f"user-{i}",
                status=Status.NEW,
            )
            for i in range(3)
        ]

    def _bulk_url(self) -> str:
        return f"/api/projects/{self.team.id}/conversations/tickets/bulk_update_status/"

    def test_bulk_update_status(self, mock_on_commit):
        ids = [str(t.id) for t in self.tickets]
        response = self.client.post(
            self._bulk_url(),
            {"ids": ids, "status": "open"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["updated"], 3)
        self.assertEqual(set(data["ids"]), set(ids))
        for t in self.tickets:
            t.refresh_from_db()
            self.assertEqual(t.status, Status.OPEN)

    def test_skips_tickets_already_in_target_status(self, mock_on_commit):
        self.tickets[0].status = Status.OPEN
        self.tickets[0].save(update_fields=["status"])
        ids = [str(t.id) for t in self.tickets]
        response = self.client.post(
            self._bulk_url(),
            {"ids": ids, "status": "open"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["updated"], 2)
        self.assertNotIn(str(self.tickets[0].id), response.json()["ids"])

    def test_ignores_other_team_ids(self, mock_on_commit):
        other_org = Organization.objects.create(name="Other Org")
        other_team = self.create_team_with_organization(organization=other_org)
        other_ticket = Ticket.objects.create_with_number(
            team=other_team,
            channel_source=Channel.WIDGET,
            widget_session_id="other-sess",
            distinct_id="other-user",
            status=Status.NEW,
        )
        ids = [str(self.tickets[0].id), str(other_ticket.id)]
        response = self.client.post(
            self._bulk_url(),
            {"ids": ids, "status": "open"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["updated"], 1)
        self.assertEqual(response.json()["ids"], [str(self.tickets[0].id)])
        other_ticket.refresh_from_db()
        self.assertEqual(other_ticket.status, Status.NEW)

    def test_creates_activity_log_entries(self, mock_on_commit):
        ids = [str(t.id) for t in self.tickets[:2]]
        self.client.post(
            self._bulk_url(),
            {"ids": ids, "status": "resolved"},
            format="json",
        )
        logs = ActivityLog.objects.filter(
            team_id=self.team.id,
            scope="Ticket",
            activity="updated",
        )
        self.assertEqual(logs.count(), 2)
        logged_ids = {log.item_id for log in logs}
        self.assertEqual(logged_ids, set(ids))

    @patch("products.conversations.backend.api.tickets.invalidate_unread_count_cache")
    def test_invalidates_cache_on_resolved_transition(self, mock_invalidate, mock_on_commit):
        ids = [str(self.tickets[0].id)]
        self.client.post(
            self._bulk_url(),
            {"ids": ids, "status": "resolved"},
            format="json",
        )
        mock_invalidate.assert_called_once_with(self.team.id)

    @patch("products.conversations.backend.api.tickets.invalidate_unread_count_cache")
    def test_no_cache_invalidation_without_resolved(self, mock_invalidate, mock_on_commit):
        ids = [str(self.tickets[0].id)]
        self.client.post(
            self._bulk_url(),
            {"ids": ids, "status": "open"},
            format="json",
        )
        mock_invalidate.assert_not_called()

    def test_rejects_empty_ids(self, mock_on_commit):
        response = self.client.post(
            self._bulk_url(),
            {"ids": [], "status": "open"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_rejects_invalid_status(self, mock_on_commit):
        response = self.client.post(
            self._bulk_url(),
            {"ids": [str(self.tickets[0].id)], "status": "bogus"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


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


@patch.object(transaction, "on_commit", side_effect=immediate_on_commit)
class TestTicketPersonData(APIBaseTest):
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
        person = create_person(
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
        create_person(
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

    def test_list_tickets_person_null_when_no_person(self, mock_on_commit):
        response = self.client.get(f"/api/projects/{self.team.id}/conversations/tickets/")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["count"] == 1
        assert response.json()["results"][0]["person"] is None

    def test_person_data_scoped_to_team(self, mock_on_commit):
        other_team = self.organization.teams.create(name="Other Team")
        create_person(
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

    def test_composed_ticket_is_not_born_verified(self, mock_on_commit):
        # The team typed the recipient address; the recipient never proved they control it,
        # so an outbound ticket must start with unknown identity (None) — never verified.
        response = self._compose(
            {
                "recipient_email": "someone@test.com",
                "email_config_id": str(self.email_config.id),
                "message": "Hello!",
            }
        )
        assert response.status_code == status.HTTP_201_CREATED
        ticket = Ticket.objects.get(team=self.team)
        assert ticket.identity_verified is None


class TestTicketPersonalAPIKeyScopes(APIBaseTest):
    def _auth_with_pak(self, scopes: list[str]) -> None:
        key = self.create_personal_api_key_with_scopes(scopes)
        self.client.logout()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {key}")

    def setUp(self):
        super().setUp()
        self.team.conversations_enabled = True
        self.team.save()
        self.ticket = Ticket.objects.create_with_number(
            team=self.team,
            channel_source=Channel.WIDGET,
            widget_session_id="test-session",
            distinct_id="user-1",
            status=Status.NEW,
        )

    @parameterized.expand(
        [
            ("list_with_read", "list", "get", None, ["ticket:read"], status.HTTP_200_OK),
            ("list_with_write", "list", "get", None, ["ticket:write"], status.HTTP_200_OK),
            ("retrieve_with_read", "retrieve", "get", True, ["ticket:read"], status.HTTP_200_OK),
            ("retrieve_with_write", "retrieve", "get", True, ["ticket:write"], status.HTTP_200_OK),
            ("unread_count_with_read", "unread_count", "get", None, ["ticket:read"], status.HTTP_200_OK),
            ("unread_count_with_write", "unread_count", "get", None, ["ticket:write"], status.HTTP_200_OK),
            ("list_wrong_scope", "list", "get", None, ["insight:read"], status.HTTP_403_FORBIDDEN),
            ("retrieve_wrong_scope", "retrieve", "get", True, ["insight:read"], status.HTTP_403_FORBIDDEN),
            ("unread_count_wrong_scope", "unread_count", "get", None, ["insight:read"], status.HTTP_403_FORBIDDEN),
        ]
    )
    def test_read_actions(self, _name, action, method, use_detail, scopes, expected_status):
        self._auth_with_pak(scopes)

        base = f"/api/projects/{self.team.id}/conversations/tickets/"
        if use_detail:
            url = f"{base}{self.ticket.id}/"
        elif action in ("list",):
            url = base
        else:
            url = f"{base}{action}/"

        response = getattr(self.client, method)(url)
        assert response.status_code == expected_status, f"{_name}: {response.status_code} != {expected_status}"

    @parameterized.expand(
        [
            ("compose_with_write", "compose", ["ticket:write"], status.HTTP_400_BAD_REQUEST),
            ("compose_with_read", "compose", ["ticket:read"], status.HTTP_403_FORBIDDEN),
            ("compose_wrong_scope", "compose", ["insight:write"], status.HTTP_403_FORBIDDEN),
        ]
    )
    def test_write_actions(self, _name, action, scopes, expected_status):
        self._auth_with_pak(scopes)
        url = f"/api/projects/{self.team.id}/conversations/tickets/{action}/"
        response = self.client.post(url, {}, format="json")
        assert response.status_code == expected_status, f"{_name}: {response.status_code} != {expected_status}"

    @parameterized.expand(
        [
            ("messages_with_read", "messages", "get", ["ticket:read"], status.HTTP_200_OK),
            ("messages_with_write", "messages", "get", ["ticket:write"], status.HTTP_200_OK),
            ("messages_wrong_scope", "messages", "get", ["insight:read"], status.HTTP_403_FORBIDDEN),
            ("reply_with_write", "reply", "post", ["ticket:write"], status.HTTP_201_CREATED),
            ("reply_with_read_only", "reply", "post", ["ticket:read"], status.HTTP_403_FORBIDDEN),
            ("reply_wrong_scope", "reply", "post", ["insight:write"], status.HTTP_403_FORBIDDEN),
        ]
    )
    def test_messages_and_reply_scopes(self, _name, action, method, scopes, expected_status):
        self._auth_with_pak(scopes)

        url = f"/api/projects/{self.team.id}/conversations/tickets/{self.ticket.id}/{action}/"
        if method == "post":
            response = self.client.post(url, {"message": "test reply"}, format="json")
        else:
            response = getattr(self.client, method)(url)
        assert response.status_code == expected_status, f"{_name}: {response.status_code} != {expected_status}"


@patch.object(transaction, "on_commit", side_effect=immediate_on_commit)
class TestTicketMessagesAPI(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.ticket = Ticket.objects.create_with_number(
            team=self.team,
            channel_source=Channel.EMAIL,
            widget_session_id="test-session",
            distinct_id="user-1",
            status=Status.OPEN,
            anonymous_traits={"name": "Alice", "email": "alice@example.com"},
        )
        self.url = f"/api/projects/{self.team.id}/conversations/tickets/{self.ticket.id}/messages/"

    def test_messages_returns_thread_in_order(self, mock_on_commit):
        base = timezone.now()
        # Stamp explicit, strictly-increasing created_at so ordering can't tie on fast DBs.
        for offset, (content, author_type, is_private, author) in enumerate(
            [
                ("Hello from customer", "customer", False, None),
                ("Hi there!", "support", False, self.user),
                ("Internal note", "support", True, self.user),
            ]
        ):
            comment = Comment.objects.create(
                team=self.team,
                created_by=author,
                scope="conversations_ticket",
                item_id=str(self.ticket.id),
                content=content,
                item_context={"author_type": author_type, "is_private": is_private},
            )
            Comment.objects.filter(id=comment.id).update(created_at=base + timedelta(seconds=offset))

        response = self.client.get(self.url)
        assert response.status_code == status.HTTP_200_OK
        body = response.json()["results"]
        assert len(body) == 3
        assert body[0]["content"] == "Hello from customer"
        assert body[0]["author_type"] == "customer"
        assert body[0]["author_name"] == "Alice"
        assert body[0]["is_private"] is False
        assert body[1]["content"] == "Hi there!"
        assert body[1]["author_type"] == "support"
        assert body[1]["is_private"] is False
        assert body[2]["content"] == "Internal note"
        assert body[2]["is_private"] is True

    def test_messages_includes_private_notes(self, mock_on_commit):
        Comment.objects.create(
            team=self.team,
            created_by=self.user,
            scope="conversations_ticket",
            item_id=str(self.ticket.id),
            content="Secret internal note",
            item_context={"author_type": "support", "is_private": True},
        )

        response = self.client.get(self.url)
        assert response.status_code == status.HTTP_200_OK
        results = response.json()["results"]
        assert len(results) == 1
        assert results[0]["is_private"] is True
        assert results[0]["content"] == "Secret internal note"

    def test_messages_excludes_deleted(self, mock_on_commit):
        Comment.objects.create(
            team=self.team,
            scope="conversations_ticket",
            item_id=str(self.ticket.id),
            content="Visible",
            item_context={"author_type": "customer"},
        )
        Comment.objects.create(
            team=self.team,
            scope="conversations_ticket",
            item_id=str(self.ticket.id),
            content="Deleted",
            item_context={"author_type": "customer"},
            deleted=True,
        )

        response = self.client.get(self.url)
        assert response.status_code == status.HTTP_200_OK
        results = response.json()["results"]
        assert len(results) == 1
        assert results[0]["content"] == "Visible"

    def test_messages_correct_response_shape(self, mock_on_commit):
        Comment.objects.create(
            team=self.team,
            scope="conversations_ticket",
            item_id=str(self.ticket.id),
            content="test",
            item_context={"author_type": "customer"},
        )

        response = self.client.get(self.url)
        assert response.status_code == status.HTTP_200_OK
        msg = response.json()["results"][0]
        assert set(msg.keys()) == {
            "id",
            "content",
            "rich_content",
            "author_type",
            "author_name",
            "is_private",
            "created_at",
        }

    def test_messages_lookup_by_ticket_number(self, mock_on_commit):
        Comment.objects.create(
            team=self.team,
            scope="conversations_ticket",
            item_id=str(self.ticket.id),
            content="msg",
            item_context={"author_type": "customer"},
        )

        url = f"/api/projects/{self.team.id}/conversations/tickets/{self.ticket.ticket_number}/messages/"
        response = self.client.get(url)
        assert response.status_code == status.HTTP_200_OK
        assert len(response.json()["results"]) == 1

    @parameterized.expand(
        [
            ("customer_with_name", {"name": "Bob", "email": "bob@example.com"}, "customer", "Bob"),
            ("customer_email_fallback", {"email": "bob@example.com"}, "customer", "bob@example.com"),
            ("customer_default", {}, "customer", "Customer"),
            ("ai_author", {}, "AI", "PostHog Assistant"),
            ("support_without_user", {}, "support", "Support"),
        ]
    )
    def test_messages_author_name_resolution(self, mock_on_commit, _name, traits, author_type, expected_name):
        self.ticket.anonymous_traits = traits
        self.ticket.save(update_fields=["anonymous_traits"])
        Comment.objects.create(
            team=self.team,
            scope="conversations_ticket",
            item_id=str(self.ticket.id),
            content="msg",
            item_context={"author_type": author_type},
        )

        response = self.client.get(self.url)
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["results"][0]["author_name"] == expected_name

    @parameterized.expand(
        [
            ("real_true", True, True),
            ("string_false_is_not_private", "false", False),
            ("string_true_is_not_private", "true", False),
            ("missing", None, False),
        ]
    )
    def test_messages_is_private_only_exact_true(self, mock_on_commit, _name, stored_value, expected):
        item_context: dict = {"author_type": "support"}
        if stored_value is not None:
            item_context["is_private"] = stored_value
        Comment.objects.create(
            team=self.team,
            created_by=self.user,
            scope="conversations_ticket",
            item_id=str(self.ticket.id),
            content="msg",
            item_context=item_context,
        )

        response = self.client.get(self.url)
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["results"][0]["is_private"] is expected

    def test_messages_cross_team_404(self, mock_on_commit):
        from posthog.models.team import Team

        other_team = Team.objects.create_with_data(
            organization=self.organization, initiating_user=self.user, name="Other"
        )
        other_ticket = Ticket.objects.create_with_number(
            team=other_team,
            channel_source=Channel.WIDGET,
            widget_session_id="other",
            distinct_id="other-user",
            status=Status.NEW,
        )

        url = f"/api/projects/{self.team.id}/conversations/tickets/{other_ticket.id}/messages/"
        response = self.client.get(url)
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_messages_empty_thread(self, mock_on_commit):
        response = self.client.get(self.url)
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["results"] == []
        assert body["count"] == 0

    def test_messages_pagination(self, mock_on_commit):
        base = timezone.now()
        for i in range(5):
            comment = Comment.objects.create(
                team=self.team,
                scope="conversations_ticket",
                item_id=str(self.ticket.id),
                content=f"msg-{i}",
                item_context={"author_type": "customer"},
            )
            Comment.objects.filter(id=comment.id).update(created_at=base + timedelta(seconds=i))

        response = self.client.get(self.url, {"limit": 2})
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["count"] == 5
        assert len(body["results"]) == 2
        assert body["results"][0]["content"] == "msg-0"
        assert body["next"] is not None

        response = self.client.get(self.url, {"limit": 2, "offset": 4})
        body = response.json()
        assert len(body["results"]) == 1
        assert body["results"][0]["content"] == "msg-4"


@patch.object(transaction, "on_commit", side_effect=immediate_on_commit)
class TestTicketReplyAPI(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.team.conversations_enabled = True
        self.team.save()
        self.ticket = Ticket.objects.create_with_number(
            team=self.team,
            channel_source=Channel.EMAIL,
            widget_session_id="test-session",
            distinct_id="user-1",
            status=Status.OPEN,
        )
        self.url = f"/api/projects/{self.team.id}/conversations/tickets/{self.ticket.id}/reply/"

    @parameterized.expand(
        [
            ("public", False),
            ("private", True),
        ]
    )
    def test_reply_creates_comment(self, mock_on_commit, _name, is_private):
        response = self.client.post(self.url, {"message": "A reply", "is_private": is_private}, format="json")
        assert response.status_code == status.HTTP_201_CREATED
        body = response.json()
        assert body["content"] == "A reply"
        assert body["author_type"] == "support"
        assert body["is_private"] is is_private
        assert body["author_name"] == (self.user.first_name or self.user.email)

        comment = Comment.objects.get(id=body["id"])
        assert comment.created_by == self.user
        assert comment.scope == "conversations_ticket"
        assert comment.item_id == str(self.ticket.id)
        assert comment.item_context == {"author_type": "support", "is_private": is_private}

    def test_reply_defaults_is_private_to_false(self, mock_on_commit):
        response = self.client.post(self.url, {"message": "Hi"}, format="json")
        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["is_private"] is False

    def test_reply_with_rich_content(self, mock_on_commit):
        rich = {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Hi"}]}]}
        response = self.client.post(self.url, {"message": "Hi", "rich_content": rich}, format="json")
        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["rich_content"] == rich

    @parameterized.expand(
        [
            ("blank", {"message": "   "}),
            ("missing", {}),
            ("rich_content_too_large", {"message": "hi", "rich_content": {"x": "y" * 200_000}}),
        ]
    )
    def test_reply_invalid_payload_rejected(self, mock_on_commit, _name, payload):
        response = self.client.post(self.url, payload, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_reply_cross_team_404(self, mock_on_commit):
        from posthog.models.team import Team

        other_team = Team.objects.create_with_data(
            organization=self.organization, initiating_user=self.user, name="Other"
        )
        other_ticket = Ticket.objects.create_with_number(
            team=other_team,
            channel_source=Channel.WIDGET,
            widget_session_id="other",
            distinct_id="other-user",
            status=Status.NEW,
        )

        url = f"/api/projects/{self.team.id}/conversations/tickets/{other_ticket.id}/reply/"
        response = self.client.post(url, {"message": "hi"}, format="json")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    @parameterized.expand(
        [
            ("public_reply_is_emailed", False, True),
            ("private_note_is_not_emailed", True, False),
        ]
    )
    @patch("products.conversations.backend.signals.send_email_reply")
    def test_reply_fans_out_to_customer_only_when_public(
        self, _name, is_private, expect_delivery, mock_send_email_reply, mock_on_commit
    ):
        # The post_save signal only delivers over email when the ticket is an
        # email channel with email enabled and a sender address.
        self.ticket.email_from = "customer@example.com"
        self.ticket.save(update_fields=["email_from"])
        self.team.conversations_settings = {"email_enabled": True}
        self.team.save(update_fields=["conversations_settings"])

        response = self.client.post(self.url, {"message": "Reply body", "is_private": is_private}, format="json")
        assert response.status_code == status.HTTP_201_CREATED

        if expect_delivery:
            mock_send_email_reply.delay.assert_called_once()
        else:
            mock_send_email_reply.delay.assert_not_called()

    @patch("products.conversations.backend.signals.send_email_reply")
    def test_reply_rejected_when_conversations_disabled(self, mock_send_email_reply, mock_on_commit):
        self.team.conversations_enabled = False
        self.team.save()

        response = self.client.post(self.url, {"message": "Hi"}, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        # Guard runs before the comment is created, so no fan-out is triggered.
        assert not Comment.objects.filter(scope="conversations_ticket", item_id=str(self.ticket.id)).exists()
        mock_send_email_reply.delay.assert_not_called()

    def test_reply_rich_content_non_json_serializable_rejected(self, mock_on_commit):
        # A non-JSON-serializable value can't arrive over HTTP (the body is already
        # parsed JSON), so validate at the serializer level directly.
        serializer = TicketReplyRequestSerializer(data={"message": "hi", "rich_content": {"amount": Decimal("1.2")}})
        assert not serializer.is_valid()
        assert "rich_content" in serializer.errors


@patch.object(transaction, "on_commit", side_effect=immediate_on_commit)
class TestAiFeedbackAPI(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.ticket = Ticket.objects.create_with_number(
            team=self.team,
            channel_source=Channel.WIDGET,
            widget_session_id="ai-feedback-session",
            distinct_id="user-123",
            status=Status.OPEN,
            ai_triage={
                "status": "done",
                "result": "persisted",
                "confidence": 0.92,
                "ai_trace_id": "trace-abc",
            },
        )
        self.url = f"/api/projects/{self.team.id}/conversations/tickets/{self.ticket.id}/ai_feedback/"

    @patch("products.conversations.backend.api.tickets.posthoganalytics.capture")
    def test_ai_feedback_captures_metric_on_rating(self, mock_capture, mock_on_commit):
        response = self.client.post(
            self.url,
            {"message_id": "msg-1", "rating": "good"},
            format="json",
        )
        assert response.status_code == status.HTTP_202_ACCEPTED
        mock_capture.assert_called_once()
        _, kwargs = mock_capture.call_args
        assert kwargs["event"] == "$ai_metric"
        assert kwargs["properties"]["$ai_metric_name"] == "reviewer_quality"
        assert kwargs["properties"]["$ai_metric_value"] == 1
        assert kwargs["properties"]["$ai_trace_id"] == "trace-abc"
        assert kwargs["properties"]["ticket_id"] == str(self.ticket.id)
        assert kwargs["properties"]["message_id"] == "msg-1"
        assert kwargs["properties"]["ai_triage_result"] == "persisted"
        assert kwargs["properties"]["confidence"] == 0.92

    @parameterized.expand(
        [
            ("bad_without_text", {"message_id": "msg-1", "rating": "bad"}, "$ai_metric", 0),
            (
                "bad_with_text",
                {"message_id": "msg-1", "rating": "bad", "feedback_text": "Wrong answer"},
                "$ai_feedback",
                None,
            ),
        ]
    )
    @patch("products.conversations.backend.api.tickets.posthoganalytics.capture")
    def test_ai_feedback_metric_vs_text_are_mutually_exclusive(
        self, _name, payload, expected_event, expected_metric_value, mock_capture, mock_on_commit
    ):
        response = self.client.post(self.url, payload, format="json")
        assert response.status_code == status.HTTP_202_ACCEPTED
        mock_capture.assert_called_once()
        _, kwargs = mock_capture.call_args
        assert kwargs["event"] == expected_event
        if expected_event == "$ai_metric":
            assert kwargs["properties"]["$ai_metric_value"] == expected_metric_value
            assert "$ai_feedback_text" not in kwargs["properties"]
        else:
            assert kwargs["properties"]["$ai_feedback_text"] == "Wrong answer"
            assert "$ai_metric_name" not in kwargs["properties"]
            assert kwargs["properties"]["$ai_trace_id"] == "trace-abc"

    def test_ai_feedback_rejects_invalid_rating(self, mock_on_commit):
        response = self.client.post(
            self.url,
            {"message_id": "msg-1", "rating": "meh"},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST


class TestTicketResolvedAtStamping(BaseTest):
    def test_resolved_at_follows_status_across_update_fields_saves(self):
        ticket = Ticket.objects.create_with_number(
            team=self.team,
            widget_session_id="session-resolved-at",
            distinct_id="user-123",
            channel_source="widget",
        )
        assert ticket.resolved_at is None

        # update_fields-limited save is what the API/tasks transition paths use
        ticket.status = Status.RESOLVED
        ticket.save(update_fields=["status", "updated_at"])
        # re-fetch instead of refresh_from_db so mypy drops its is-None narrowing of resolved_at
        ticket = Ticket.objects.get(pk=ticket.pk)
        assert ticket.status == Status.RESOLVED
        assert ticket.resolved_at is not None

        ticket.status = Status.OPEN
        ticket.save(update_fields=["status", "updated_at"])
        ticket = Ticket.objects.get(pk=ticket.pk)
        assert ticket.resolved_at is None
