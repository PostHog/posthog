import uuid
from datetime import timedelta

from posthog.test.base import BaseTest

from django.core.cache import cache
from django.db import connection
from django.test import SimpleTestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from parameterized import parameterized
from prometheus_client import REGISTRY
from rest_framework import status
from rest_framework.test import APIClient

from posthog.models import Comment, Team
from posthog.models.organization_ip_restrictions import OrganizationIPRestrictions
from posthog.models.utils import generate_random_token_secret
from posthog.test.api_keys import create_project_secret_api_key
from posthog.test.authentication_checks import covers_authentication

from products.conversations.backend.api.external import ExternalTicketProjectSecretAPIKeyAuthentication
from products.conversations.backend.api.ticket_actions import _truncate_bytes, _truncate_json_bytes
from products.conversations.backend.models import Ticket
from products.conversations.backend.models.constants import Status

# Shaped like the markdown _build_content_with_attachments appends for an inbound email image.
_IMAGE_ATTACHMENT = "![image001.png](https://us.posthog.com/uploaded_media/0199a0b1-2c3d-4e5f-8a9b-0c1d2e3f4a5b)"


class TestExternalTicketAPI(BaseTest):
    def setUp(self):
        super().setUp()
        self.team.conversations_enabled = True
        self.team.save(update_fields=["conversations_enabled"])
        _, self.secret_token = create_project_secret_api_key(self.team, label="default", scopes=["support_ticket:read"])
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
        return {"HTTP_AUTHORIZATION": f"Bearer {token or self.secret_token}"}

    def _create_psak_token(self, scopes, team=None, label="external-ticket"):
        _, token = create_project_secret_api_key(team or self.team, label=label, scopes=scopes)
        return token

    # -- Authentication ---------------------------------------------------

    @covers_authentication(ExternalTicketProjectSecretAPIKeyAuthentication)
    def test_get_accepts_project_secret_api_key_with_support_ticket_read_scope(self):
        OrganizationIPRestrictions.objects.create(organization=self.organization, ip_restrictions=["203.0.113.0/24"])
        cache.clear()
        self.client.force_login(self.user)
        response = self.client.get(self.url, **self._auth_headers(self._create_psak_token(["support_ticket:read"])))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["id"], str(self.ticket.id))

    def test_get_rejects_project_secret_api_key_without_support_ticket_scope(self):
        response = self.client.get(self.url, **self._auth_headers(self._create_psak_token(["endpoint:read"])))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_patch_not_allowed_on_external_route(self):
        # Ticket updates moved to the scoped-JWT internal route (#82564); the external
        # route is read-only.
        response = self.client.patch(
            self.url,
            {"status": "resolved"},
            content_type="application/json",
            **self._auth_headers(self._create_psak_token(["support_ticket:read"])),
        )
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, Status.NEW)

    def test_migrated_legacy_token_reads_through_its_psak_row(self) -> None:
        # The #63111 backfill's mirror row authenticates the legacy token string with
        # support_ticket:read, so GET keeps working for migrated tokens.
        token = generate_random_token_secret()
        self.team.secret_api_token = token
        self.team.save(update_fields=["secret_api_token"])
        create_project_secret_api_key(
            self.team,
            label="Migrated legacy secret API key",
            scopes=["feature_flag:read", "support_ticket:read"],
            value=token,
        )

        response = self.client.get(self.url, **self._auth_headers(token))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    @parameterized.expand(
        [
            ("conversations_disabled", {"team": {"conversations_enabled": False}}),
            ("organization_deactivated", {"organization": {"is_active": False}}),
            ("organization_active_null", {"organization": {"is_active": None}}),
            ("organization_pending_deletion", {"organization": {"is_pending_deletion": True}}),
        ]
    )
    def test_psak_is_invisible_when_the_team_or_organization_is_blocked(self, _name, changes):
        token = self._create_psak_token(["support_ticket:read"])
        for field, value in changes.get("team", {}).items():
            setattr(self.team, field, value)
            self.team.save(update_fields=[field])
        for field, value in changes.get("organization", {}).items():
            setattr(self.organization, field, value)
            self.organization.save(update_fields=[field])

        response = self.client.get(self.url, **self._auth_headers(token))
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_get_requires_auth(self):
        response = self.client.get(self.url)
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

    def test_rejects_when_conversations_disabled(self):
        self.team.conversations_enabled = False
        self.team.save(update_fields=["conversations_enabled"])
        response = self.client.get(self.url, **self._auth_headers())
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_authenticated_requests_increment_the_auth_counter(self):
        auth_labels = {"auth_method": "project_secret_api_key", "http_method": "get"}
        auth_before = REGISTRY.get_sample_value("posthog_conversations_ticket_action_auth_total", auth_labels) or 0
        self.client.get(self.url, **self._auth_headers())
        auth_after = REGISTRY.get_sample_value("posthog_conversations_ticket_action_auth_total", auth_labels)
        self.assertEqual(auth_after, auth_before + 1)

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
        # first_customer_message_text is opt-in, so it is absent unless the caller asks for it.
        self.assertNotIn("first_customer_message_text", data)
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
        other_team = Team.objects.create(organization=self.organization, name="Other team", conversations_enabled=True)
        other_team_psak = self._create_psak_token(["support_ticket:read"], team=other_team)
        response = self.client.get(self.url, **self._auth_headers(token=other_team_psak))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

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

    # -- GET first_customer_message_text ----------------------------------

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

    def _get_first_customer_message_text(self, max_bytes: int | None = None):
        """GET the ticket with the opt-in flag and return the first_customer_message_text value."""
        params: dict[str, str | int] = {"include_first_customer_message_text": "true"}
        if max_bytes is not None:
            params["first_customer_message_max_bytes"] = max_bytes
        response = self.client.get(self.url, params, **self._auth_headers())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        return response.json()["first_customer_message_text"]

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

        self.assertEqual(self._get_first_customer_message_text(), expected)

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

        self.assertEqual(self._get_first_customer_message_text(), "Actual question")

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

        self.assertEqual(self._get_first_customer_message_text(), expected)

    @parameterized.expand(
        [
            # The widget escapes the customer's punctuation on the way in; the preview shows it as
            # the customer typed it. These are the stored strings, with the escaping the widget adds.
            ("parentheses_and_period", "Please don't tag it \\(yet\\)\\.", "Please don't tag it (yet)."),
            ("emphasis_chars_the_customer_typed", "2 \\* 3 \\* 4", "2 * 3 * 4"),
            # A backslash the customer actually typed is stored doubled, so it comes back single.
            ("typed_backslash_survives", "path C:\\\\Users", "path C:\\Users"),
            # Link-shaped text the customer typed is stored escaped, so the attachment strip does
            # not treat it as a link; unescaping runs after that strip and restores it intact.
            ("typed_link_shaped_text_survives", "see \\[the docs\\]\\(here\\)", "see [the docs](here)"),
        ]
    )
    def test_get_ticket_first_message_unescapes_widget_markdown(self, _name, content, expected):
        self._create_message(content, minutes_ago=10, item_context={"author_type": "customer"})

        self.assertEqual(self._get_first_customer_message_text(), expected)

    @parameterized.expand([("email",), ("slack",), ("teams",)])
    def test_get_ticket_first_message_keeps_backslashes_for_non_widget_channels(self, channel_source):
        # Only the widget editor escapes the customer's punctuation on input. On other channels a
        # backslash is the customer's own, so a regex or a UNC path must survive the preview intact.
        ticket = Ticket.objects.create_with_number(
            team=self.team,
            widget_session_id=str(uuid.uuid4()),
            distinct_id=f"user-{channel_source}-1",
            channel_source=channel_source,
            status=Status.NEW,
        )
        Comment.objects.create(
            team=self.team,
            scope="conversations_ticket",
            item_id=str(ticket.id),
            content="Match \\. and path \\\\server\\share",
            item_context={"author_type": "customer"},
        )

        response = self.client.get(
            f"/api/conversations/external/ticket/{ticket.id}",
            {"include_first_customer_message_text": "true"},
            **self._auth_headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["first_customer_message_text"], "Match \\. and path \\\\server\\share")

    def test_get_ticket_first_message_keeps_bracketed_prose_in_a_body_long_enough_to_cut(self):
        # Only a body past the scan window reaches the severed-attachment strip, so a shorter
        # message cannot show whether that strip leaves a customer's own brackets alone.
        self._create_message(
            "[2026-01-01] ERROR failed on a[0]. " + "Padding sentence. " * 200,
            minutes_ago=10,
            item_context={"author_type": "customer"},
        )

        self.assertTrue(self._get_first_customer_message_text().startswith("[2026-01-01] ERROR failed on a[0]."))

    @parameterized.expand(
        [
            # A cut message ends with an ellipsis in place of its last three characters, so the
            # 200-byte result is 197 "x" plus "...".
            ("ascii", "x" * 900, None, "x" * 197 + "..."),
            # 3 bytes per character, so the cap lands at 66 characters (198 bytes); the ellipsis
            # replaces the last three, leaving 63 characters plus "...". A character-based cap
            # would emit 600 bytes against the workflow variable budget.
            ("multibyte", "あ" * 300, None, "あ" * 63 + "..."),
            ("length_ignored_on_this_route", "x" * 900, 3000, "x" * 197 + "..."),
        ]
    )
    def test_get_ticket_truncates_first_message_to_its_byte_budget(self, _name, content, max_bytes, expected):
        self._create_message(content, minutes_ago=10, item_context={"author_type": "customer"})

        self.assertEqual(self._get_first_customer_message_text(max_bytes), expected)

    def test_get_ticket_first_message_that_fits_has_no_ellipsis(self):
        # The ellipsis only marks a cut, so a message inside the budget is returned unchanged.
        self._create_message("All done, thanks!", minutes_ago=10, item_context={"author_type": "customer"})

        self.assertEqual(self._get_first_customer_message_text(), "All done, thanks!")

    def test_get_ticket_omits_first_customer_message_text_without_opt_in(self):
        # A customer message exists, but a caller that does not ask for the preview must not get
        # the field at all, so an existing Get ticket node keeps its response shape and cost.
        self._create_message("Hello there", minutes_ago=10, item_context={"author_type": "customer"})

        response = self.client.get(self.url, **self._auth_headers())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertNotIn("first_customer_message_text", response.json())

    def test_get_ticket_first_customer_message_text_is_null_when_no_customer_message(self):
        # Opted in, but nothing quotable from the customer: the field is present and null so the
        # workflow can tell "asked for, none found" apart from "did not ask".
        self.assertIsNone(self._get_first_customer_message_text())

    def test_default_get_skips_the_first_customer_message_query(self):
        # The opt-in exists to keep the extra message lookup off every Get ticket call. Pin that:
        # the opted-in path runs the lookup, the default path must not.
        self._create_message("Hello there", minutes_ago=10, item_context={"author_type": "customer"})
        # Warm per-connection caches so the comparison reflects only the opt-in query.
        self.client.get(self.url, **self._auth_headers())
        with CaptureQueriesContext(connection) as default_queries:
            self.client.get(self.url, **self._auth_headers())
        with CaptureQueriesContext(connection) as opted_in_queries:
            self.client.get(self.url, {"include_first_customer_message_text": "true"}, **self._auth_headers())
        self.assertLess(len(default_queries), len(opted_in_queries))

    def test_get_ticket_returns_tags(self):
        from posthog.models import Tag

        tag = Tag.objects.create(name="bug", team_id=self.team.id)
        self.ticket.tagged_items.create(tag=tag)
        response = self.client.get(self.url, **self._auth_headers())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["tags"], ["bug"])

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


class TestTruncateBytes(SimpleTestCase):
    @parameterized.expand([("utf8_bytes", _truncate_bytes), ("json_bytes", _truncate_json_bytes)])
    def test_drops_a_joiner_the_cut_left_dangling(self, _name, truncate):
        # The cut lands inside the emoji following a joiner, so errors="ignore" drops the
        # partial character and would otherwise end the preview on the joiner itself.
        truncated = truncate("xxx" + "👨‍👩‍👧" * 20, 200)

        self.assertFalse(truncated.endswith("‍"))
        self.assertTrue(truncated.endswith("..."))
        self.assertLessEqual(len(truncated.encode("utf-8")), 200)

    @parameterized.expand([("utf8_bytes", _truncate_bytes), ("json_bytes", _truncate_json_bytes)])
    def test_returns_text_within_budget_unchanged(self, _name, truncate):
        self.assertEqual(truncate("short enough", 200), "short enough")

    def test_json_budget_counts_escaped_quotes(self):
        self.assertEqual(_truncate_json_bytes('"' * 300, 200), '"' * 98 + "...")
