import json
import uuid
from datetime import timedelta

from posthog.test.base import BaseTest

from django.test import override_settings
from django.utils import timezone

from parameterized import parameterized
from prometheus_client import REGISTRY
from rest_framework import status
from rest_framework.test import APIClient

from posthog.jwt import PosthogJwtAudience
from posthog.models import ActivityLog, Comment, Team
from posthog.models.utils import generate_random_token_secret
from posthog.scoped_service_jwt import ScopedServiceJwtPurpose
from posthog.test.authentication_checks import covers_authentication

from products.conversations.backend.api.internal import (
    CONVERSATIONS_TICKETS_PURPOSE,
    ConversationsTicketJWTAuthentication,
)
from products.conversations.backend.api.ticket_actions import TICKET_RESPONSE_MAX_BYTES
from products.conversations.backend.models import Ticket
from products.conversations.backend.models.constants import WORKFLOW_AUTHOR_NAME, WORKFLOW_AUTHOR_TYPE, Priority, Status

_IMAGE_ATTACHMENT = "![image001.png](https://us.posthog.com/uploaded_media/0199a0b1-2c3d-4e5f-8a9b-0c1d2e3f4a5b)"

# Signed with this route's key but carrying another surface's audience — a token minted for a
# different purpose must never authenticate here even when the signing key checks out.
OTHER_AUDIENCE_PURPOSE = ScopedServiceJwtPurpose(
    audience=PosthogJwtAudience.RECORDING_API,
    settings_name="CONVERSATIONS_TICKETS_JWT_SECRETS",
)


class InternalTicketAPITestCase(BaseTest):
    def setUp(self):
        super().setUp()
        self.team.conversations_enabled = True
        self.team.secret_api_token = generate_random_token_secret()
        self.team.save(update_fields=["conversations_enabled", "secret_api_token"])
        self.client = APIClient()
        self.ticket = Ticket.objects.create_with_number(
            team=self.team,
            widget_session_id=str(uuid.uuid4()),
            distinct_id="user-int-123",
            channel_source="widget",
            status=Status.NEW,
        )
        self.url = f"/api/projects/{self.team.id}/internal/conversations/tickets/{self.ticket.id}"

    def _claims(self) -> dict:
        return {"team_id": self.team.id, "ticket_id": str(self.ticket.id)}

    def _headers(self, claims: dict | None = None) -> dict:
        return self._bearer(CONVERSATIONS_TICKETS_PURPOSE.mint(claims if claims is not None else self._claims()))

    @staticmethod
    def _bearer(token: str) -> dict:
        return {"HTTP_AUTHORIZATION": f"Bearer {token}"}


class TestInternalTicketAPI(InternalTicketAPITestCase):
    @covers_authentication(ConversationsTicketJWTAuthentication)
    def test_get_returns_ticket_for_minted_token(self):
        response = self.client.get(self.url, **self._headers())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["id"], str(self.ticket.id))
        self.assertEqual(data["status"], "new")
        self.assertEqual(data["distinct_id"], "user-int-123")

    def test_get_returns_first_customer_message_text_when_opted_in(self):
        # The field is shared with the external route but gated behind a query param, so confirm
        # the JWT route reads that param and returns the preview through the same handler.
        self._create_customer_message("How do I export my data?")
        response = self.client.get(self.url, {"include_first_customer_message_text": "true"}, **self._headers())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["first_customer_message_text"], "How do I export my data?")

    def _create_customer_message(self, content: str) -> None:
        Comment.objects.create(
            team=self.team,
            scope="conversations_ticket",
            item_id=str(self.ticket.id),
            content=content,
            item_context={"author_type": "customer"},
        )

    def _get_first_message(self, max_bytes: int | str):
        return self.client.get(
            self.url,
            {"include_first_customer_message_text": "true", "first_customer_message_max_bytes": max_bytes},
            **self._headers(),
        )

    @parameterized.expand(
        [
            ("longer_budget", "x" * 9000, 2200, "x" * 2197 + "..."),
            ("clamped_up_to_the_preview", "x" * 900, 50, "x" * 197 + "..."),
            ("window_cut_is_marked", "It broke " + _IMAGE_ATTACHMENT * 70, 2200, "It broke..."),
            (
                "invisible_padding_stripped",
                "Refund\u034f\u034f please\u00ad now\u200b\u2060\ufeff ok"
                + "\u200c\u00a0" * 50
                + "\u200b\u200c" * 20
                + " می\u200cخواهم",
                2200,
                "Refund please now ok می\u200cخواهم",
            ),
        ]
    )
    def test_get_returns_a_longer_first_message_when_asked(self, _name, content, max_bytes, expected):
        self._create_customer_message(content)

        response = self._get_first_message(max_bytes)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["first_customer_message_text"], expected)

    def test_get_skips_a_first_message_that_is_only_a_cut_link(self):
        self._create_customer_message("[report.pdf](https://example.com/files/" + "a" * 5000 + ")")
        Comment.objects.filter(item_id=str(self.ticket.id)).update(created_at=timezone.now() - timedelta(minutes=10))
        self._create_customer_message("Actual question")

        response = self._get_first_message(2200)

        self.assertEqual(response.json()["first_customer_message_text"], "Actual question")

    def test_get_fits_a_longer_first_message_into_the_response_budget(self):
        self._create_customer_message("あ" * 3000)
        Ticket.objects.filter(id=self.ticket.id).update(email_subject="件名" * 100, last_message_text="あ" * 500)

        response = self._get_first_message(5000)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertLessEqual(
            len(json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()), TICKET_RESPONSE_MAX_BYTES
        )
        self.assertTrue(body["first_customer_message_text"].endswith("..."))

    def test_get_rejects_a_first_message_length_that_is_not_a_number(self):
        self._create_customer_message("Hello")

        response = self._get_first_message("lots")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("first_customer_message_max_bytes", response.json()["error"])

    def test_post_sends_a_public_message(self):
        response = self.client.post(
            self.url,
            {"message": "  We are on it.  ", "idempotency_key": "run-1:send:0"},
            content_type="application/json",
            **self._headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        body = response.json()
        self.assertEqual(body["is_private"], False)
        comment = Comment.objects.get(id=body["id"], team_id=self.team.id)
        self.assertEqual(comment.content, "We are on it.")
        self.assertEqual(comment.item_id, str(self.ticket.id))
        self.assertIsNone(comment.created_by_id)
        item_context = comment.item_context
        assert item_context is not None
        self.assertEqual(item_context["author_type"], WORKFLOW_AUTHOR_TYPE)
        self.assertEqual(item_context["author_name"], WORKFLOW_AUTHOR_NAME)
        self.assertFalse(item_context["is_private"])

    def test_post_private_note(self):
        response = self.client.post(
            self.url,
            {"message": "Internal only", "is_private": True, "idempotency_key": "run-1:note:0"},
            content_type="application/json",
            **self._headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(response.json()["is_private"])
        comment = Comment.objects.get(id=response.json()["id"], team_id=self.team.id)
        item_context = comment.item_context
        assert item_context is not None
        self.assertTrue(item_context["is_private"])
        self.assertEqual(item_context["author_type"], WORKFLOW_AUTHOR_TYPE)

    def test_post_deduplicates_by_workflow_step_execution(self):
        payload = {"message": "We are on it.", "is_private": False, "idempotency_key": "run-1:send:0"}
        first = self.client.post(self.url, payload, content_type="application/json", **self._headers())
        second = self.client.post(
            self.url,
            {**payload, "message": "Changed after retry"},
            content_type="application/json",
            **self._headers(),
        )
        self.assertEqual(first.status_code, status.HTTP_201_CREATED)
        self.assertEqual(second.status_code, status.HTTP_200_OK)
        self.assertEqual(second.json()["id"], first.json()["id"])
        self.assertEqual(Comment.objects.filter(team_id=self.team.id, item_id=str(self.ticket.id)).count(), 1)

        next_run = self.client.post(
            self.url,
            {"message": "We are on it.", "is_private": False, "idempotency_key": "run-2:send:0"},
            content_type="application/json",
            **self._headers(),
        )
        self.assertEqual(next_run.status_code, status.HTTP_201_CREATED)
        self.assertNotEqual(next_run.json()["id"], first.json()["id"])
        self.assertEqual(Comment.objects.filter(team_id=self.team.id, item_id=str(self.ticket.id)).count(), 2)

    def test_post_rejects_blank_message(self):
        response = self.client.post(
            self.url,
            {"message": "   ", "idempotency_key": "run-1:send:0"},
            content_type="application/json",
            **self._headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(Comment.objects.filter(team_id=self.team.id, item_id=str(self.ticket.id)).exists())

    def test_post_unknown_ticket_creates_nothing(self):
        missing = uuid.uuid4()
        url = f"/api/projects/{self.team.id}/internal/conversations/tickets/{missing}"
        headers = self._headers({"team_id": self.team.id, "ticket_id": str(missing)})
        response = self.client.post(
            url,
            {"message": "hello", "idempotency_key": "run-1:send:0"},
            content_type="application/json",
            **headers,
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertFalse(Comment.objects.filter(team_id=self.team.id, item_id=str(missing)).exists())

    @parameterized.expand(
        [
            (
                "token_for_another_team",
                lambda self: self._headers({"team_id": self.team.id + 1, "ticket_id": str(self.ticket.id)}),
                status.HTTP_401_UNAUTHORIZED,
            ),
            (
                "legacy_secret_api_token",
                lambda self: {"HTTP_AUTHORIZATION": f"Bearer {self.team.secret_api_token}"},
                status.HTTP_401_UNAUTHORIZED,
            ),
            (
                "expired_token",
                lambda self: self._bearer(
                    CONVERSATIONS_TICKETS_PURPOSE.mint(self._claims(), ttl=timedelta(minutes=-1))
                ),
                status.HTTP_401_UNAUTHORIZED,
            ),
            (
                "token_for_another_purpose",
                lambda self: self._bearer(OTHER_AUDIENCE_PURPOSE.mint(self._claims())),
                status.HTTP_401_UNAUTHORIZED,
            ),
            (
                "missing_ticket_claim",
                lambda self: self._headers({"team_id": self.team.id}),
                status.HTTP_403_FORBIDDEN,
            ),
            (
                "token_for_another_ticket",
                lambda self: self._headers({"team_id": self.team.id, "ticket_id": str(uuid.uuid4())}),
                status.HTTP_403_FORBIDDEN,
            ),
            ("no_credentials", lambda self: {}, status.HTTP_401_UNAUTHORIZED),
        ]
    )
    def test_rejected_credentials(self, _name, make_headers, expected_status):
        headers = make_headers(self)
        get_response = self.client.get(self.url, **headers)
        self.assertEqual(get_response.status_code, expected_status)
        patch_response = self.client.patch(self.url, {"status": "resolved"}, content_type="application/json", **headers)
        self.assertEqual(patch_response.status_code, expected_status)
        post_response = self.client.post(
            self.url, {"message": "should not land"}, content_type="application/json", **headers
        )
        self.assertEqual(post_response.status_code, expected_status)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, Status.NEW)
        self.assertFalse(Comment.objects.filter(team_id=self.team.id, item_id=str(self.ticket.id)).exists())

    def test_unprovisioned_secret_rejects_even_a_well_formed_token(self):
        headers = self._headers()
        with override_settings(CONVERSATIONS_TICKETS_JWT_SECRETS=[]):
            response = self.client.get(self.url, **headers)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_conversations_disabled_is_rejected(self):
        self.team.conversations_enabled = False
        self.team.save(update_fields=["conversations_enabled"])
        response = self.client.get(self.url, **self._headers())
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        post_response = self.client.post(
            self.url, {"message": "should not land"}, content_type="application/json", **self._headers()
        )
        self.assertEqual(post_response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(Comment.objects.filter(team_id=self.team.id, item_id=str(self.ticket.id)).exists())

    def test_authenticated_get_increments_the_scoped_jwt_counter(self):
        labels = {"auth_method": "scoped_jwt", "http_method": "get"}
        before = REGISTRY.get_sample_value("posthog_conversations_ticket_action_auth_total", labels) or 0
        self.client.get(self.url, **self._headers())
        after = REGISTRY.get_sample_value("posthog_conversations_ticket_action_auth_total", labels)
        self.assertEqual(after, before + 1)


class TestInternalTicketUpdates(InternalTicketAPITestCase):
    # -- PATCH ticket -----------------------------------------------------

    @parameterized.expand([(s.value,) for s in Status])
    def test_patch_status_valid(self, new_status):
        response = self.client.patch(
            self.url, {"status": new_status}, content_type="application/json", **self._headers()
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, new_status)

    @parameterized.expand([(p.value,) for p in Priority])
    def test_patch_priority_valid(self, new_priority):
        response = self.client.patch(
            self.url, {"priority": new_priority}, content_type="application/json", **self._headers()
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.priority, new_priority)

    def test_patch_status_and_priority_together(self):
        response = self.client.patch(
            self.url,
            {"status": "pending", "priority": "high"},
            content_type="application/json",
            **self._headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, "pending")
        self.assertEqual(self.ticket.priority, "high")

    def test_patch_invalid_status(self):
        response = self.client.patch(
            self.url, {"status": "nonexistent"}, content_type="application/json", **self._headers()
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_patch_invalid_priority(self):
        response = self.client.patch(
            self.url, {"priority": "nonexistent"}, content_type="application/json", **self._headers()
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_patch_empty_body_is_noop(self):
        response = self.client.patch(self.url, {}, content_type="application/json", **self._headers())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, "new")

    def test_patch_ticket_not_found(self):
        missing = str(uuid.uuid4())
        url = f"/api/projects/{self.team.id}/internal/conversations/tickets/{missing}"
        response = self.client.patch(
            url,
            {"status": "resolved"},
            content_type="application/json",
            **self._headers({"team_id": self.team.id, "ticket_id": missing}),
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_patch_cross_team_isolation(self):
        # A token scoped to this team must not update another team's ticket of the same id.
        other_team = Team.objects.create(organization=self.organization, name="Other team", conversations_enabled=True)
        other_ticket = Ticket.objects.create_with_number(
            team=other_team,
            widget_session_id=str(uuid.uuid4()),
            distinct_id="user-other-1",
            channel_source="widget",
            status=Status.NEW,
        )
        url = f"/api/projects/{self.team.id}/internal/conversations/tickets/{other_ticket.id}"
        response = self.client.patch(
            url,
            {"status": "resolved"},
            content_type="application/json",
            **self._headers({"team_id": self.team.id, "ticket_id": str(other_ticket.id)}),
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        other_ticket.refresh_from_db()
        self.assertEqual(other_ticket.status, "new")

    def test_patch_ignores_unknown_fields(self):
        response = self.client.patch(
            self.url,
            {"status": "resolved", "hacked": True},
            content_type="application/json",
            **self._headers(),
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
            **self._headers(),
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
            **self._headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.ticket.refresh_from_db()
        self.assertIsNone(self.ticket.sla_due_at)

    def test_patch_sla_due_at_invalid_format(self):
        response = self.client.patch(
            self.url,
            {"sla_due_at": "not-a-date"},
            content_type="application/json",
            **self._headers(),
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
                **self._headers(),
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
                **self._headers(),
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
            **self._headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_patch_rejects_both_sla_due_at_and_sla_amount(self):
        response = self.client.patch(
            self.url,
            {"sla_due_at": "2026-03-15T14:30:00Z", "sla_amount": 5},
            content_type="application/json",
            **self._headers(),
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
            **self._headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    # -- PATCH tags --------------------------------------------------------

    def test_patch_tags_add_mode_preserves_existing(self):
        from posthog.models import Tag

        existing_tag = Tag.objects.create(name="bug", team_id=self.team.id)
        self.ticket.tagged_items.create(tag=existing_tag)

        response = self.client.patch(
            self.url,
            {"tags": ["urgent"], "tags_mode": "add"},
            content_type="application/json",
            **self._headers(),
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
            **self._headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(self.ticket.tagged_items.count(), 1)

    def test_patch_tags_concurrent_add_produces_union(self):
        self.client.patch(
            self.url,
            {"tags": ["urgent"], "tags_mode": "add"},
            content_type="application/json",
            **self._headers(),
        )
        self.client.patch(
            self.url,
            {"tags": ["billing"], "tags_mode": "add"},
            content_type="application/json",
            **self._headers(),
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
            **self._headers(),
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
            **self._headers(),
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
            **self._headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        tags = list(self.ticket.tagged_items.values_list("tag__name", flat=True))
        self.assertEqual(tags, ["urgent"])


class TestInternalTicketWorkflowAttribution(InternalTicketAPITestCase):
    # -- Workflow (HogFlow) attribution -----------------------------------

    def _workflow_headers(self, flow_id="0191d3e0-0000-7000-8000-000000000001"):
        return {
            **self._headers(),
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
            **self._headers(),
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
            **self._headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNone(self._latest_ticket_activity(activity="assigned"))

        for _ in range(2):
            response = self.client.patch(
                self.url,
                {"assignee": {"type": "user", "id": self.user.id}},
                content_type="application/json",
                **self._headers(),
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            ActivityLog.objects.filter(
                team_id=self.team.id, scope="Ticket", item_id=str(self.ticket.id), activity="assigned"
            ).count(),
            1,
        )
