import uuid
from datetime import timedelta

from posthog.test.base import BaseTest

from django.test import SimpleTestCase
from django.utils import timezone

from parameterized import parameterized
from prometheus_client import REGISTRY
from rest_framework import status
from rest_framework.test import APIClient

from posthog.models import ActivityLog, Comment, Team
from posthog.models.utils import generate_random_token_secret

from products.conversations.backend.api.ticket_actions import _truncate_bytes
from products.conversations.backend.models import Ticket
from products.conversations.backend.models.constants import Priority, Status

# Shaped like the markdown _build_content_with_attachments appends for an inbound email image.
_IMAGE_ATTACHMENT = "![image001.png](https://us.posthog.com/uploaded_media/0199a0b1-2c3d-4e5f-8a9b-0c1d2e3f4a5b)"


class TestExternalTicketAPI(BaseTest):
    def setUp(self):
        super().setUp()
        self.team.conversations_enabled = True
        self.team.secret_api_token = generate_random_token_secret()
        self.team.save(update_fields=["conversations_enabled", "secret_api_token"])
        self.client = APIClient()
        self.ticket = Ticket.objects.create_with_number(
            team=self.team,
            widget_session_id=str(uuid.uuid4()),
            distinct_id="user-ext-123",
            channel_source="widget",
            status=Status.NEW,
        )
        self.url = f"/api/conversations/external/ticket/{self.ticket.id}"

    def _auth_headers(self, token=None):
        return {"HTTP_AUTHORIZATION": f"Bearer {token or self.team.secret_api_token}"}

    # -- Authentication ---------------------------------------------------

    def test_get_requires_auth(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_patch_requires_auth(self):
        response = self.client.patch(self.url, {"status": "resolved"}, content_type="application/json")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    @parameterized.expand(
        [
            ("no_header", ""),
            ("bad_scheme", "Basic abc123"),
            ("empty_bearer", "Bearer "),
            ("wrong_token", "Bearer phc_wrong_token"),
        ]
    )
    def test_get_rejects_invalid_auth(self, _name, auth_value):
        headers = {"HTTP_AUTHORIZATION": auth_value} if auth_value else {}
        response = self.client.get(self.url, **headers)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_rejects_public_api_token(self):
        response = self.client.get(self.url, **self._auth_headers(token=self.team.api_token))
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_accepts_backup_token(self):
        backup_token = generate_random_token_secret()
        self.team.secret_api_token_backup = backup_token
        self.team.save(update_fields=["secret_api_token_backup"])
        response = self.client.get(self.url, **self._auth_headers(token=backup_token))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_rejects_when_conversations_disabled(self):
        self.team.conversations_enabled = False
        self.team.save(update_fields=["conversations_enabled"])
        response = self.client.get(self.url, **self._auth_headers())
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_authenticated_requests_increment_the_legacy_auth_counter(self):
        labels = {"auth_method": "secret_api_token", "http_method": "get"}
        before = REGISTRY.get_sample_value("posthog_conversations_ticket_action_auth_total", labels) or 0
        self.client.get(self.url, **self._auth_headers())
        after = REGISTRY.get_sample_value("posthog_conversations_ticket_action_auth_total", labels)
        self.assertEqual(after, before + 1)

    # -- GET ticket -------------------------------------------------------

    def test_get_ticket_returns_all_fields(self):
        response = self.client.get(self.url, **self._auth_headers())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["id"], str(self.ticket.id))
        self.assertEqual(data["number"], self.ticket.ticket_number)
        self.assertEqual(data["status"], "new")
        self.assertIsNone(data["priority"])
        self.assertEqual(data["channel_source"], "widget")
        self.assertIsNone(data["channel_detail"])
        self.assertEqual(data["distinct_id"], "user-ext-123")
        self.assertEqual(data["message_count"], 0)
        self.assertIsNone(data["last_message_at"])
        self.assertIsNone(data["last_message_text"])
        self.assertIsNone(data["first_message_text"])
        self.assertEqual(data["unread_team_count"], 0)
        self.assertEqual(data["unread_customer_count"], 0)
        self.assertIsNone(data["sla"])
        self.assertIsNone(data["assignee"])
        self.assertIsNone(data["url"])
        self.assertIsNone(data["slack_channel_id"])
        self.assertIsNone(data["slack_thread_ts"])
        self.assertIsNone(data["slack_team_id"])
        self.assertIsNone(data["email_subject"])
        self.assertIsNone(data["email_from"])
        self.assertIsNone(data["email_to"])
        self.assertEqual(data["cc_participants"], [])
        self.assertEqual(data["tags"], [])
        self.assertIn("created_at", data)
        self.assertIn("updated_at", data)

    def test_get_ticket_not_found(self):
        url = f"/api/conversations/external/ticket/{uuid.uuid4()}"
        response = self.client.get(url, **self._auth_headers())
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_get_ticket_cross_team_isolation(self):
        other_token = generate_random_token_secret()
        other_team = Team.objects.create(
            organization=self.organization, name="Other team", conversations_enabled=True, secret_api_token=other_token
        )
        response = self.client.get(self.url, **self._auth_headers(token=other_team.secret_api_token))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    # -- PATCH ticket -----------------------------------------------------

    @parameterized.expand([(s.value,) for s in Status])
    def test_patch_status_valid(self, new_status):
        response = self.client.patch(
            self.url, {"status": new_status}, content_type="application/json", **self._auth_headers()
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, new_status)

    @parameterized.expand([(p.value,) for p in Priority])
    def test_patch_priority_valid(self, new_priority):
        response = self.client.patch(
            self.url, {"priority": new_priority}, content_type="application/json", **self._auth_headers()
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.priority, new_priority)

    def test_patch_status_and_priority_together(self):
        response = self.client.patch(
            self.url,
            {"status": "pending", "priority": "high"},
            content_type="application/json",
            **self._auth_headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, "pending")
        self.assertEqual(self.ticket.priority, "high")

    def test_patch_invalid_status(self):
        response = self.client.patch(
            self.url, {"status": "nonexistent"}, content_type="application/json", **self._auth_headers()
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_patch_invalid_priority(self):
        response = self.client.patch(
            self.url, {"priority": "nonexistent"}, content_type="application/json", **self._auth_headers()
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_patch_empty_body_is_noop(self):
        response = self.client.patch(self.url, {}, content_type="application/json", **self._auth_headers())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, "new")

    def test_patch_ticket_not_found(self):
        url = f"/api/conversations/external/ticket/{uuid.uuid4()}"
        response = self.client.patch(
            url, {"status": "resolved"}, content_type="application/json", **self._auth_headers()
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_patch_cross_team_isolation(self):
        other_token = generate_random_token_secret()
        other_team = Team.objects.create(
            organization=self.organization, name="Other team", conversations_enabled=True, secret_api_token=other_token
        )
        response = self.client.patch(
            self.url,
            {"status": "resolved"},
            content_type="application/json",
            **self._auth_headers(token=other_team.secret_api_token),
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, "new")

    def test_patch_ignores_unknown_fields(self):
        response = self.client.patch(
            self.url,
            {"status": "resolved", "hacked": True},
            content_type="application/json",
            **self._auth_headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, "resolved")

    # -- SLA updates --------------------------------------------------------

    def test_patch_sla_due_at_valid(self):
        response = self.client.patch(
            self.url,
            {"sla_due_at": "2026-03-15T14:30:00Z"},
            content_type="application/json",
            **self._auth_headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.ticket.refresh_from_db()
        self.assertIsNotNone(self.ticket.sla_due_at)
        self.assertEqual(self.ticket.sla_due_at.isoformat(), "2026-03-15T14:30:00+00:00")

    def test_patch_sla_due_at_null_clears_sla(self):
        from django.utils import timezone

        self.ticket.sla_due_at = timezone.now()
        self.ticket.save()

        response = self.client.patch(
            self.url,
            {"sla_due_at": None},
            content_type="application/json",
            **self._auth_headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.ticket.refresh_from_db()
        self.assertIsNone(self.ticket.sla_due_at)

    def test_patch_sla_due_at_invalid_format(self):
        response = self.client.patch(
            self.url,
            {"sla_due_at": "not-a-date"},
            content_type="application/json",
            **self._auth_headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_patch_sla_amount_calendar_hours(self):
        from datetime import UTC, datetime

        from unittest.mock import patch

        # 2026-01-05 10:00 UTC is a Monday.
        frozen_now = datetime(2026, 1, 5, 10, 0, tzinfo=UTC)
        with patch("products.conversations.backend.api.ticket_actions.timezone.now", return_value=frozen_now):
            response = self.client.patch(
                self.url,
                {"sla_amount": 4, "sla_unit": "hour"},
                content_type="application/json",
                **self._auth_headers(),
            )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.ticket.refresh_from_db()
        self.assertIsNotNone(self.ticket.sla_due_at)
        self.assertEqual(self.ticket.sla_due_at.isoformat(), "2026-01-05T14:00:00+00:00")

    def test_patch_sla_amount_business_hours(self):
        from datetime import UTC, datetime

        from unittest.mock import patch

        frozen_now = datetime(2026, 1, 8, 16, 0, tzinfo=UTC)  # Thursday 16:00 UTC
        with patch("products.conversations.backend.api.ticket_actions.timezone.now", return_value=frozen_now):
            response = self.client.patch(
                self.url,
                {
                    "sla_amount": 10,
                    "sla_unit": "hour",
                    "sla_business_hours": {
                        "days": ["monday", "tuesday", "wednesday", "thursday", "friday"],
                        "time": ["09:00", "17:00"],
                        "timezone": "UTC",
                    },
                },
                content_type="application/json",
                **self._auth_headers(),
            )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.ticket.refresh_from_db()
        # 1h Thursday + 8h Friday + 1h Monday -> Monday 10:00 UTC
        self.assertEqual(self.ticket.sla_due_at.isoformat(), "2026-01-12T10:00:00+00:00")

    def test_patch_sla_amount_rejects_zero(self):
        response = self.client.patch(
            self.url,
            {"sla_amount": 0, "sla_unit": "hour"},
            content_type="application/json",
            **self._auth_headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_patch_rejects_both_sla_due_at_and_sla_amount(self):
        response = self.client.patch(
            self.url,
            {"sla_due_at": "2026-03-15T14:30:00Z", "sla_amount": 5},
            content_type="application/json",
            **self._auth_headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @parameterized.expand(
        [
            ("empty_days", {"days": [], "time": ["09:00", "17:00"], "timezone": "UTC"}),
            ("inverted_range", {"days": ["monday"], "time": ["17:00", "09:00"], "timezone": "UTC"}),
            ("unknown_timezone", {"days": ["monday"], "time": "any", "timezone": "Mars/Olympus"}),
            ("unknown_weekday", {"days": ["funday"], "time": "any", "timezone": "UTC"}),
        ]
    )
    def test_patch_rejects_invalid_business_hours(self, _name, business_hours):
        response = self.client.patch(
            self.url,
            {"sla_amount": 1, "sla_unit": "hour", "sla_business_hours": business_hours},
            content_type="application/json",
            **self._auth_headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_get_ticket_returns_sla_due_at(self):
        from django.utils import timezone

        self.ticket.sla_due_at = timezone.now()
        self.ticket.save()

        response = self.client.get(self.url, **self._auth_headers())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNotNone(response.json()["sla"])

    # -- GET enriched fields -----------------------------------------------

    def test_get_ticket_returns_assignee(self):
        from products.conversations.backend.models import TicketAssignment

        TicketAssignment.objects.create(ticket=self.ticket, user=self.user)
        response = self.client.get(self.url, **self._auth_headers())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        assignee = response.json()["assignee"]
        self.assertIsNotNone(assignee)
        self.assertEqual(assignee["type"], "user")
        self.assertEqual(assignee["id"], self.user.id)
        self.assertEqual(assignee["user"]["email"], self.user.email)

    def test_get_ticket_returns_role_assignee(self):
        from products.access_control.backend.models.role import Role
        from products.conversations.backend.models import TicketAssignment

        role = Role.objects.create(name="Support", organization=self.organization)
        TicketAssignment.objects.create(ticket=self.ticket, role=role)
        response = self.client.get(self.url, **self._auth_headers())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        assignee = response.json()["assignee"]
        self.assertEqual(assignee["type"], "role")
        self.assertEqual(assignee["id"], str(role.id))
        self.assertEqual(assignee["role"]["name"], "Support")
        self.assertIsNone(assignee["user"])

    def test_get_ticket_returns_url(self):
        self.ticket.session_context = {"current_url": "https://example.com/page"}
        self.ticket.save(update_fields=["session_context"])
        response = self.client.get(self.url, **self._auth_headers())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["url"], "https://example.com/page")

    def test_get_ticket_returns_slack_fields(self):
        self.ticket.slack_channel_id = "C1234567890"
        self.ticket.slack_thread_ts = "1234567890.123456"
        self.ticket.slack_team_id = "T0987654321"
        self.ticket.save(update_fields=["slack_channel_id", "slack_thread_ts", "slack_team_id"])
        response = self.client.get(self.url, **self._auth_headers())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["slack_channel_id"], "C1234567890")
        self.assertEqual(data["slack_thread_ts"], "1234567890.123456")
        self.assertEqual(data["slack_team_id"], "T0987654321")

    def test_get_ticket_returns_email_fields(self):
        from products.conversations.backend.models.team_conversations_email_config import EmailChannel

        channel = EmailChannel.objects.create(
            team=self.team, inbound_token="abc123", from_email="support@example.com", from_name="Support"
        )
        self.ticket.email_config = channel
        self.ticket.email_subject = "Need help with billing"
        self.ticket.email_from = "customer@example.com"
        self.ticket.cc_participants = ["cc1@example.com", "cc2@example.com"]
        self.ticket.save(update_fields=["email_config", "email_subject", "email_from", "cc_participants"])
        response = self.client.get(self.url, **self._auth_headers())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["email_subject"], "Need help with billing")
        self.assertEqual(data["email_from"], "customer@example.com")
        self.assertEqual(data["email_to"], "support@example.com")
        self.assertEqual(data["cc_participants"], ["cc1@example.com", "cc2@example.com"])

    # -- GET first_message_text -------------------------------------------

    def _create_message(
        self,
        content: str | None,
        *,
        minutes_ago: int,
        item_context: dict | None = None,
        deleted: bool = False,
    ) -> Comment:
        comment = Comment.objects.create(
            team=self.team,
            scope="conversations_ticket",
            item_id=str(self.ticket.id),
            content=content,
            item_context=item_context,
            deleted=deleted,
        )
        # created_at is auto_now_add, so pin it after the fact to keep ordering deterministic.
        Comment.objects.filter(pk=comment.pk).update(created_at=timezone.now() - timedelta(minutes=minutes_ago))
        return comment

    @parameterized.expand(
        [
            ("team_authored", {"is_private": False, "author_type": "support"}, False, "Second message"),
            ("soft_deleted", {"author_type": "customer"}, True, "Second message"),
            ("no_item_context", None, False, "Second message"),
            ("customer_missing_is_private_key", {"author_type": "customer"}, False, "First message"),
            ("customer_not_private", {"is_private": False, "author_type": "customer"}, False, "First message"),
        ]
    )
    def test_get_ticket_first_message_only_quotes_the_customer(self, _name, item_context, deleted, expected):
        self._create_message("First message", minutes_ago=10, item_context=item_context, deleted=deleted)
        self._create_message("Second message", minutes_ago=5, item_context={"author_type": "customer"})

        response = self.client.get(self.url, **self._auth_headers())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["first_message_text"], expected)

    @parameterized.expand(
        [
            ("empty_string", ""),
            ("null", None),
            ("whitespace_only", "\n\n  "),
            # An inbound email carrying only a screenshot has no body text at all.
            ("image_attachment_only", _IMAGE_ATTACHMENT),
            # Enough inline images to run past the scan window, so the window cuts the last one
            # in half. The fragment left behind must not become the preview.
            ("images_past_the_scan_window", _IMAGE_ATTACHMENT * 30),
        ]
    )
    def test_get_ticket_first_message_skips_messages_with_nothing_to_quote(self, _name, unquotable):
        self._create_message(unquotable, minutes_ago=10, item_context={"author_type": "customer"})
        self._create_message("Actual question", minutes_ago=5, item_context={"author_type": "customer"})

        response = self.client.get(self.url, **self._auth_headers())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["first_message_text"], "Actual question")

    @parameterized.expand(
        [
            ("image_stripped", "Why is this broken?\n\n![shot.png](/uploaded_media/abc)", "Why is this broken?"),
            ("file_label_kept", "See\n\n[report.pdf](/uploaded_media/abc)", "See report.pdf"),
            ("prose_kept_when_images_run_past_the_scan_window", "It broke\n\n" + _IMAGE_ATTACHMENT * 30, "It broke"),
            # Brackets are ordinary in a support message, so nothing here may be treated as a
            # severed attachment.
            ("bracketed_prose_kept", "[2026-01-01] ERROR failed on a[0]", "[2026-01-01] ERROR failed on a[0]"),
        ]
    )
    def test_get_ticket_first_message_strips_attachment_markdown(self, _name, content, expected):
        self._create_message(content, minutes_ago=10, item_context={"author_type": "customer"})

        response = self.client.get(self.url, **self._auth_headers())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["first_message_text"], expected)

    def test_get_ticket_first_message_keeps_bracketed_prose_in_a_body_long_enough_to_cut(self):
        # Only a body past the scan window reaches the severed-attachment strip, so a shorter
        # message cannot show whether that strip leaves a customer's own brackets alone.
        self._create_message(
            "[2026-01-01] ERROR failed on a[0]. " + "Padding sentence. " * 200,
            minutes_ago=10,
            item_context={"author_type": "customer"},
        )

        response = self.client.get(self.url, **self._auth_headers())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.json()["first_message_text"].startswith("[2026-01-01] ERROR failed on a[0]."))

    @parameterized.expand(
        [
            ("ascii", "x" * 900, "x" * 200),
            # 3 bytes per character, so the cap lands at 66 characters (198 bytes). A
            # character-based cap would emit 600 bytes against the workflow variable budget.
            ("multibyte", "あ" * 300, "あ" * 66),
        ]
    )
    def test_get_ticket_truncates_first_message_to_200_bytes(self, _name, content, expected):
        self._create_message(content, minutes_ago=10, item_context={"author_type": "customer"})

        response = self.client.get(self.url, **self._auth_headers())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["first_message_text"], expected)

    def test_get_ticket_returns_tags(self):
        from posthog.models import Tag

        tag = Tag.objects.create(name="bug", team_id=self.team.id)
        self.ticket.tagged_items.create(tag=tag)
        response = self.client.get(self.url, **self._auth_headers())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["tags"], ["bug"])

    # -- PATCH tags --------------------------------------------------------

    def test_patch_tags_add_mode_preserves_existing(self):
        from posthog.models import Tag

        existing_tag = Tag.objects.create(name="bug", team_id=self.team.id)
        self.ticket.tagged_items.create(tag=existing_tag)

        response = self.client.patch(
            self.url,
            {"tags": ["urgent"], "tags_mode": "add"},
            content_type="application/json",
            **self._auth_headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        tags = sorted(self.ticket.tagged_items.values_list("tag__name", flat=True))
        self.assertEqual(tags, ["bug", "urgent"])

    def test_patch_tags_add_is_idempotent(self):
        from posthog.models import Tag

        existing_tag = Tag.objects.create(name="bug", team_id=self.team.id)
        self.ticket.tagged_items.create(tag=existing_tag)

        response = self.client.patch(
            self.url,
            {"tags": ["bug"], "tags_mode": "add"},
            content_type="application/json",
            **self._auth_headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(self.ticket.tagged_items.count(), 1)

    def test_patch_tags_concurrent_add_produces_union(self):
        self.client.patch(
            self.url,
            {"tags": ["urgent"], "tags_mode": "add"},
            content_type="application/json",
            **self._auth_headers(),
        )
        self.client.patch(
            self.url,
            {"tags": ["billing"], "tags_mode": "add"},
            content_type="application/json",
            **self._auth_headers(),
        )
        tags = sorted(self.ticket.tagged_items.values_list("tag__name", flat=True))
        self.assertEqual(tags, ["billing", "urgent"])

    def test_patch_tags_default_mode_is_add(self):
        from posthog.models import Tag

        existing_tag = Tag.objects.create(name="bug", team_id=self.team.id)
        self.ticket.tagged_items.create(tag=existing_tag)

        response = self.client.patch(
            self.url,
            {"tags": ["feature"]},
            content_type="application/json",
            **self._auth_headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        tags = sorted(self.ticket.tagged_items.values_list("tag__name", flat=True))
        self.assertEqual(tags, ["bug", "feature"])

    def test_patch_tags_set_mode_replaces_all(self):
        from posthog.models import Tag

        existing_tag = Tag.objects.create(name="bug", team_id=self.team.id)
        self.ticket.tagged_items.create(tag=existing_tag)

        response = self.client.patch(
            self.url,
            {"tags": ["urgent"], "tags_mode": "set"},
            content_type="application/json",
            **self._auth_headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        tags = list(self.ticket.tagged_items.values_list("tag__name", flat=True))
        self.assertEqual(tags, ["urgent"])

    def test_patch_tags_remove_mode_strips_named(self):
        from posthog.models import Tag

        for name in ["bug", "urgent", "billing"]:
            tag = Tag.objects.create(name=name, team_id=self.team.id)
            self.ticket.tagged_items.create(tag=tag)

        response = self.client.patch(
            self.url,
            {"tags": ["bug", "billing"], "tags_mode": "remove"},
            content_type="application/json",
            **self._auth_headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        tags = list(self.ticket.tagged_items.values_list("tag__name", flat=True))
        self.assertEqual(tags, ["urgent"])

    # -- URL validation ---------------------------------------------------

    def test_invalid_uuid_in_url_returns_404(self):
        response = self.client.get("/api/conversations/external/ticket/not-a-uuid", **self._auth_headers())
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    # -- HTTP methods not allowed -----------------------------------------

    def test_post_not_allowed(self):
        response = self.client.post(self.url, {}, content_type="application/json", **self._auth_headers())
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_delete_not_allowed(self):
        response = self.client.delete(self.url, **self._auth_headers())
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_put_not_allowed(self):
        response = self.client.put(
            self.url, {"status": "resolved"}, content_type="application/json", **self._auth_headers()
        )
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    # -- Workflow (HogFlow) attribution -----------------------------------

    def _workflow_headers(self, flow_id="0191d3e0-0000-7000-8000-000000000001", token=None):
        return {
            **self._auth_headers(token),
            "HTTP_X_POSTHOG_HOG_FLOW_ID": flow_id,
        }

    def _latest_ticket_activity(self, activity="updated"):
        return (
            ActivityLog.objects.filter(
                team_id=self.team.id, scope="Ticket", item_id=str(self.ticket.id), activity=activity
            )
            .order_by("-created_at")
            .first()
        )

    @parameterized.expand(
        [
            ("status", {"status": Status.RESOLVED}),
            ("priority", {"priority": Priority.HIGH}),
        ]
    )
    def test_patch_records_workflow_trigger(self, _name, payload):
        flow_id = "0191d3e0-0000-7000-8000-000000000001"
        response = self.client.patch(
            self.url,
            payload,
            content_type="application/json",
            **self._workflow_headers(flow_id=flow_id),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        activity = self._latest_ticket_activity()
        assert activity is not None
        trigger = activity.detail.get("trigger")
        assert trigger is not None
        self.assertEqual(trigger["job_type"], "hog_flow")
        self.assertEqual(trigger["job_id"], flow_id)
        # Only the id is stored; the display name is resolved from the workflow on the frontend.
        self.assertNotIn("name", trigger["payload"])

    def test_patch_without_workflow_header_has_no_trigger(self):
        response = self.client.patch(
            self.url,
            {"status": Status.RESOLVED},
            content_type="application/json",
            **self._auth_headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        activity = self._latest_ticket_activity()
        assert activity is not None
        self.assertIsNone(activity.detail.get("trigger"))

    def test_patch_ignores_malformed_workflow_id(self):
        # A non-UUID header id is rejected so we never store a job_id that can't resolve to a link.
        response = self.client.patch(
            self.url,
            {"status": Status.RESOLVED},
            content_type="application/json",
            **self._workflow_headers(flow_id="not-a-uuid"),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        activity = self._latest_ticket_activity()
        assert activity is not None
        self.assertIsNone(activity.detail.get("trigger"))

    @parameterized.expand(
        [
            ("add", {"tags": ["urgent"], "tags_mode": "add"}, "created", "after", "urgent"),
            ("remove", {"tags": ["bug"], "tags_mode": "remove"}, "deleted", "before", "bug"),
        ]
    )
    def test_patch_tag_changes_record_workflow_trigger(self, _name, payload, action, direction, tag_name):
        # Both directions flow through the TaggedItem activity signal: adds fire it on save,
        # removes only because the endpoint deletes per-instance (a bulk delete would skip it).
        # The signal picks the workflow trigger up from ActivityTriggerContext; without that,
        # workflow tag changes render as an anonymous "PostHog" on the ticket timeline.
        from posthog.models import Tag

        existing_tag = Tag.objects.create(name="bug", team_id=self.team.id)
        self.ticket.tagged_items.create(tag=existing_tag)

        response = self.client.patch(
            self.url,
            payload,
            content_type="application/json",
            **self._workflow_headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        activity = self._latest_ticket_activity()
        assert activity is not None
        tag_change = next((c for c in activity.detail.get("changes", []) if c["field"] == "tag"), None)
        assert tag_change is not None
        self.assertEqual(tag_change["action"], action)
        self.assertEqual(tag_change[direction], tag_name)
        self.assertEqual(activity.detail["trigger"]["job_type"], "hog_flow")

    def test_patch_tag_changes_write_tag_audit_entries(self):
        # Removals used to go through a bulk queryset delete, which skips the TaggedItem signal
        # and left them out of the global Tag audit stream entirely. Both directions must now
        # produce a TaggedItem-scope entry, attributed to the workflow.
        response = self.client.patch(
            self.url,
            {"tags": ["urgent"], "tags_mode": "add"},
            content_type="application/json",
            **self._workflow_headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response = self.client.patch(
            self.url,
            {"tags": ["urgent"], "tags_mode": "remove"},
            content_type="application/json",
            **self._workflow_headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        audit_activities = {
            entry.activity: entry for entry in ActivityLog.objects.filter(team_id=self.team.id, scope="TaggedItem")
        }
        self.assertIn("created", audit_activities)
        self.assertIn("deleted", audit_activities)
        deleted_detail = audit_activities["deleted"].detail
        assert deleted_detail is not None
        self.assertEqual(deleted_detail["trigger"]["job_type"], "hog_flow")

    def test_workflow_trigger_does_not_leak_after_request(self):
        # The trigger thread-local must be cleared by the context manager, or attribution
        # would bleed into unrelated activity logged later on a reused worker thread.
        from posthog.models.activity_logging.utils import activity_storage

        response = self.client.patch(
            self.url,
            {"tags": ["urgent"], "tags_mode": "add"},
            content_type="application/json",
            **self._workflow_headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNone(activity_storage.get_trigger())

    def test_patch_assignee_records_workflow_trigger(self):
        response = self.client.patch(
            self.url,
            {"assignee": {"type": "user", "id": self.user.id}},
            content_type="application/json",
            **self._workflow_headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        activity = self._latest_ticket_activity(activity="assigned")
        assert activity is not None
        self.assertEqual(activity.detail["trigger"]["job_type"], "hog_flow")

    def test_patch_unchanged_assignee_logs_no_activity(self):
        # Callers send the assignee whenever it's in the payload (the ticket UI always sends the
        # full form), so a no-op assignment must not write "assigned to unassigned" entries or
        # fire assignment-triggered workflows on every save.
        response = self.client.patch(
            self.url,
            {"assignee": None},
            content_type="application/json",
            **self._auth_headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNone(self._latest_ticket_activity(activity="assigned"))

        for _ in range(2):
            response = self.client.patch(
                self.url,
                {"assignee": {"type": "user", "id": self.user.id}},
                content_type="application/json",
                **self._auth_headers(),
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            ActivityLog.objects.filter(
                team_id=self.team.id, scope="Ticket", item_id=str(self.ticket.id), activity="assigned"
            ).count(),
            1,
        )


class TestTruncateBytes(SimpleTestCase):
    def test_drops_a_joiner_the_cut_left_dangling(self):
        # The cut lands inside the emoji following a joiner, so errors="ignore" drops the
        # partial character and would otherwise end the preview on the joiner itself.
        truncated = _truncate_bytes("xxx" + "👨‍👩‍👧" * 20, 200)

        self.assertFalse(truncated.endswith("‍"))
        self.assertLessEqual(len(truncated.encode("utf-8")), 200)
