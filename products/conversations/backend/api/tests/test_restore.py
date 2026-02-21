import uuid
from datetime import timedelta

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.utils import timezone

from rest_framework import status
from rest_framework.test import APIClient

from products.conversations.backend.models import ConversationRestoreToken, Ticket
from products.conversations.backend.models.restore_token import hash_token
from products.conversations.backend.services.restore import RestoreService


class TestRestoreTokenModel(BaseTest):
    def setUp(self):
        super().setUp()
        self.team.conversations_enabled = True
        self.team.conversations_settings = {"widget_public_token": "test_token"}
        self.team.save()

    def test_create_token_generates_hash(self):
        token_record, raw_token = ConversationRestoreToken.create_token(
            team=self.team,
            recipient_email="test@example.com",
        )

        self.assertIsNotNone(raw_token)
        self.assertEqual(len(raw_token), 43)  # 32 bytes base64url encoded
        self.assertEqual(token_record.token_hash, hash_token(raw_token))
        self.assertEqual(token_record.recipient_email, "test@example.com")

    def test_token_expiry(self):
        token_record, _ = ConversationRestoreToken.create_token(
            team=self.team,
            recipient_email="test@example.com",
            ttl_minutes=1,
        )

        self.assertFalse(token_record.is_expired)

        # Manually expire the token
        token_record.expires_at = timezone.now() - timedelta(minutes=1)
        token_record.save()

        self.assertTrue(token_record.is_expired)

    def test_token_consumed(self):
        token_record, _ = ConversationRestoreToken.create_token(
            team=self.team,
            recipient_email="test@example.com",
        )

        self.assertFalse(token_record.is_consumed)

        token_record.consumed_at = timezone.now()
        token_record.save()

        self.assertTrue(token_record.is_consumed)


class TestRestoreService(BaseTest):
    def setUp(self):
        super().setUp()
        self.team.conversations_enabled = True
        self.team.conversations_settings = {"widget_public_token": "test_token"}
        self.team.save()

        self.widget_session_id = str(uuid.uuid4())
        self.customer_email = "customer@example.com"

    def test_find_tickets_by_email(self):
        Ticket.objects.create_with_number(
            team=self.team,
            widget_session_id=self.widget_session_id,
            distinct_id="user-1",
            anonymous_traits={"email": self.customer_email},
        )
        Ticket.objects.create_with_number(
            team=self.team,
            widget_session_id="other-session",
            distinct_id="user-2",
            anonymous_traits={"email": "other@example.com"},
        )

        tickets = RestoreService.find_tickets_by_email(self.team, self.customer_email)
        self.assertEqual(len(tickets), 1)
        self.assertEqual(tickets[0].anonymous_traits["email"], self.customer_email)

    def test_find_tickets_by_email_case_insensitive(self):
        Ticket.objects.create_with_number(
            team=self.team,
            widget_session_id=self.widget_session_id,
            distinct_id="user-1",
            anonymous_traits={"email": "Customer@Example.COM"},
        )

        tickets = RestoreService.find_tickets_by_email(self.team, "customer@example.com")
        self.assertEqual(len(tickets), 1)

    @patch("products.conversations.backend.services.restore.PersonDistinctId")
    @patch("products.conversations.backend.services.restore.Person")
    def test_find_tickets_by_person_email(self, mock_person_class, mock_pdi_class):
        """Find tickets where user is identified (email on Person, not anonymous_traits)."""
        # Step 1 mock: Person query returns person IDs (plain list supports [:1000] slicing)
        mock_person_class.objects.db_manager.return_value.filter.return_value.values_list.return_value = [1]
        # Step 2 mock: PersonDistinctId resolves person IDs to distinct_ids
        mock_pdi_class.objects.db_manager.return_value.filter.return_value.values_list.return_value = [
            "identified-user-1"
        ]

        Ticket.objects.create_with_number(
            team=self.team,
            widget_session_id=self.widget_session_id,
            distinct_id="identified-user-1",
            anonymous_traits={},
        )

        tickets = RestoreService.find_tickets_by_email(self.team, self.customer_email)
        self.assertEqual(len(tickets), 1)
        self.assertEqual(tickets[0].distinct_id, "identified-user-1")

    @patch("products.conversations.backend.services.restore.PersonDistinctId")
    @patch("products.conversations.backend.services.restore.Person")
    def test_find_tickets_by_email_finds_both_anonymous_and_identified(self, mock_person_class, mock_pdi_class):
        """Find tickets from both anonymous_traits and Person properties."""
        mock_person_class.objects.db_manager.return_value.filter.return_value.values_list.return_value = [1]
        mock_pdi_class.objects.db_manager.return_value.filter.return_value.values_list.return_value = [
            "identified-user"
        ]

        Ticket.objects.create_with_number(
            team=self.team,
            widget_session_id=self.widget_session_id,
            distinct_id="anon-user",
            anonymous_traits={"email": self.customer_email},
        )

        Ticket.objects.create_with_number(
            team=self.team,
            widget_session_id="other-session",
            distinct_id="identified-user",
            anonymous_traits={},
        )

        tickets = RestoreService.find_tickets_by_email(self.team, self.customer_email)
        self.assertEqual(len(tickets), 2)

    def test_request_restore_link_no_tickets(self):
        result = RestoreService.request_restore_link(
            team=self.team,
            email="nonexistent@example.com",
        )
        self.assertIsNone(result)

    def test_request_restore_link_with_tickets(self):
        Ticket.objects.create_with_number(
            team=self.team,
            widget_session_id=self.widget_session_id,
            distinct_id="user-1",
            anonymous_traits={"email": self.customer_email},
        )

        raw_token = RestoreService.request_restore_link(
            team=self.team,
            email=self.customer_email,
        )

        assert raw_token is not None
        self.assertEqual(len(raw_token), 43)  # 32 bytes base64url encoded

    def test_request_restore_link_does_not_invalidate_existing_tokens(self):
        """Requesting a new link should NOT invalidate existing tokens."""
        Ticket.objects.create_with_number(
            team=self.team,
            widget_session_id=self.widget_session_id,
            distinct_id="user-1",
            anonymous_traits={"email": self.customer_email},
        )

        # Create first token
        first_raw = RestoreService.request_restore_link(
            team=self.team,
            email=self.customer_email,
        )
        assert first_raw is not None
        first_token = ConversationRestoreToken.objects.get(token_hash=hash_token(first_raw))

        # Create second token (should NOT invalidate first)
        second_raw = RestoreService.request_restore_link(
            team=self.team,
            email=self.customer_email,
        )
        assert second_raw is not None
        second_token = ConversationRestoreToken.objects.get(token_hash=hash_token(second_raw))

        # Both tokens should be valid
        first_token.refresh_from_db()
        self.assertIsNone(first_token.consumed_at)
        self.assertIsNone(second_token.consumed_at)

    def test_redeem_token_invalidates_other_tokens(self):
        """Redeeming a token should invalidate other unused tokens for the same email."""
        old_session_id = str(uuid.uuid4())
        new_session_id = str(uuid.uuid4())

        Ticket.objects.create_with_number(
            team=self.team,
            widget_session_id=old_session_id,
            distinct_id="user-1",
            anonymous_traits={"email": self.customer_email},
        )

        # Create two tokens for the same email
        first_raw = RestoreService.request_restore_link(
            team=self.team,
            email=self.customer_email,
        )
        assert first_raw is not None
        first_token = ConversationRestoreToken.objects.get(token_hash=hash_token(first_raw))

        second_raw = RestoreService.request_restore_link(
            team=self.team,
            email=self.customer_email,
        )
        assert second_raw is not None
        second_token = ConversationRestoreToken.objects.get(token_hash=hash_token(second_raw))

        # Redeem the first token
        RestoreService.redeem_token(
            team=self.team,
            raw_token=first_raw,
            widget_session_id=new_session_id,
        )

        # First token should be consumed (redeemed)
        first_token.refresh_from_db()
        self.assertIsNotNone(first_token.consumed_at)
        self.assertEqual(first_token.consumed_by_widget_session_id, new_session_id)

        # Second token should also be consumed (invalidated, no widget_session_id)
        second_token.refresh_from_db()
        self.assertIsNotNone(second_token.consumed_at)
        self.assertIsNone(second_token.consumed_by_widget_session_id)

    def test_redeem_token_success(self):
        old_session_id = str(uuid.uuid4())
        new_session_id = str(uuid.uuid4())

        ticket = Ticket.objects.create_with_number(
            team=self.team,
            widget_session_id=old_session_id,
            distinct_id="user-1",
            anonymous_traits={"email": self.customer_email},
        )

        _, raw_token = ConversationRestoreToken.create_token(
            team=self.team,
            recipient_email=self.customer_email,
        )

        result = RestoreService.redeem_token(
            team=self.team,
            raw_token=raw_token,
            widget_session_id=new_session_id,
        )

        self.assertEqual(result.status, "success")
        self.assertEqual(result.widget_session_id, new_session_id)
        assert result.migrated_ticket_ids is not None
        self.assertEqual(len(result.migrated_ticket_ids), 1)

        # Verify ticket ownership transferred
        ticket.refresh_from_db()
        self.assertEqual(ticket.widget_session_id, new_session_id)

    def test_redeem_token_invalid(self):
        result = RestoreService.redeem_token(
            team=self.team,
            raw_token="invalid_token",
            widget_session_id=str(uuid.uuid4()),
        )

        self.assertEqual(result.status, "invalid")
        self.assertEqual(result.code, "token_invalid")

    def test_redeem_token_expired(self):
        token_record, raw_token = ConversationRestoreToken.create_token(
            team=self.team,
            recipient_email=self.customer_email,
        )

        # Expire the token
        token_record.expires_at = timezone.now() - timedelta(minutes=1)
        token_record.save()

        result = RestoreService.redeem_token(
            team=self.team,
            raw_token=raw_token,
            widget_session_id=str(uuid.uuid4()),
        )

        self.assertEqual(result.status, "expired")
        self.assertEqual(result.code, "token_expired")

    def test_redeem_token_already_used(self):
        token_record, raw_token = ConversationRestoreToken.create_token(
            team=self.team,
            recipient_email=self.customer_email,
        )

        # Mark as consumed
        token_record.consumed_at = timezone.now()
        token_record.save()

        result = RestoreService.redeem_token(
            team=self.team,
            raw_token=raw_token,
            widget_session_id=str(uuid.uuid4()),
        )

        self.assertEqual(result.status, "used")
        self.assertEqual(result.code, "token_already_used")

    def test_redeem_token_wrong_team(self):
        from posthog.models import Organization, Team

        other_org = Organization.objects.create(name="Other Org")
        other_team = Team.objects.create(organization=other_org, name="Other Team")

        _, raw_token = ConversationRestoreToken.create_token(
            team=self.team,
            recipient_email=self.customer_email,
        )

        result = RestoreService.redeem_token(
            team=other_team,
            raw_token=raw_token,
            widget_session_id=str(uuid.uuid4()),
        )

        self.assertEqual(result.status, "invalid")
        self.assertEqual(result.code, "token_invalid")


class TestRestoreAPI(BaseTest):
    def setUp(self):
        super().setUp()
        self.widget_token = "test_widget_token_123"
        self.team.conversations_enabled = True
        self.team.conversations_settings = {"widget_public_token": self.widget_token}
        self.team.save()

        self.widget_session_id = str(uuid.uuid4())
        self.customer_email = "customer@example.com"

        self.client = APIClient()

    def _get_headers(self):
        return {"HTTP_X_CONVERSATIONS_TOKEN": self.widget_token}

    def test_restore_request_authentication_required(self):
        response = self.client.post(
            "/api/conversations/v1/widget/restore/request",
            {
                "email": self.customer_email,
                "request_url": "https://example.com/support",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    @patch("products.conversations.backend.api.restore.send_conversation_restore_email")
    def test_restore_request_success_with_tickets(self, mock_send_email):
        Ticket.objects.create_with_number(
            team=self.team,
            widget_session_id=self.widget_session_id,
            distinct_id="user-1",
            anonymous_traits={"email": self.customer_email},
        )

        response = self.client.post(
            "/api/conversations/v1/widget/restore/request",
            {
                "email": self.customer_email,
                "request_url": "https://example.com/support",
            },
            **self._get_headers(),
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), {"ok": True})
        mock_send_email.delay.assert_called_once()
        # Verify the restore URL uses the request_url as base
        call_kwargs = mock_send_email.delay.call_args[1]
        self.assertIn("ph_conv_restore=", call_kwargs["restore_url"])
        self.assertTrue(call_kwargs["restore_url"].startswith("https://example.com/support"))

    @patch("products.conversations.backend.api.restore.send_conversation_restore_email")
    def test_restore_request_no_tickets_still_returns_ok(self, mock_send_email):
        response = self.client.post(
            "/api/conversations/v1/widget/restore/request",
            {
                "email": "nonexistent@example.com",
                "request_url": "https://example.com/support",
            },
            **self._get_headers(),
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), {"ok": True})
        mock_send_email.delay.assert_not_called()

    def test_restore_request_invalid_email(self):
        response = self.client.post(
            "/api/conversations/v1/widget/restore/request",
            {
                "email": "not_an_email",
                "request_url": "https://example.com/support",
            },
            **self._get_headers(),
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_restore_request_missing_request_url(self):
        response = self.client.post(
            "/api/conversations/v1/widget/restore/request",
            {"email": self.customer_email},
            **self._get_headers(),
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch("products.conversations.backend.api.restore.RestoreRequestThrottle.allow_request", return_value=True)
    @patch("products.conversations.backend.api.restore.validate_origin", return_value=True)
    def test_restore_request_url_domain_not_in_allowlist(self, mock_validate_origin, mock_throttle):
        """request_url domain must be in widget_domains allowlist when configured."""
        self.team.conversations_settings = {
            "widget_public_token": self.widget_token,
            "widget_domains": ["allowed.com", "*.trusted.org"],
        }
        self.team.save()

        response = self.client.post(
            "/api/conversations/v1/widget/restore/request",
            {
                "email": self.customer_email,
                "request_url": "https://evil.com/phishing",
            },
            **self._get_headers(),
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    @patch("products.conversations.backend.api.restore.RestoreRequestThrottle.allow_request", return_value=True)
    @patch("products.conversations.backend.api.restore.validate_origin", return_value=True)
    @patch("products.conversations.backend.api.restore.send_conversation_restore_email")
    def test_restore_request_url_domain_allowed(self, mock_send_email, mock_validate_origin, mock_throttle):
        """request_url domain in allowlist should be accepted."""
        self.team.conversations_settings = {
            "widget_public_token": self.widget_token,
            "widget_domains": ["allowed.com"],
        }
        self.team.save()

        Ticket.objects.create_with_number(
            team=self.team,
            widget_session_id=self.widget_session_id,
            distinct_id="user-1",
            anonymous_traits={"email": self.customer_email},
        )

        response = self.client.post(
            "/api/conversations/v1/widget/restore/request",
            {
                "email": self.customer_email,
                "request_url": "https://allowed.com/support",
            },
            **self._get_headers(),
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_send_email.delay.assert_called_once()

    def test_restore_redeem_success(self):
        old_session_id = str(uuid.uuid4())
        new_session_id = str(uuid.uuid4())

        Ticket.objects.create_with_number(
            team=self.team,
            widget_session_id=old_session_id,
            distinct_id="user-1",
            anonymous_traits={"email": self.customer_email},
        )

        _, raw_token = ConversationRestoreToken.create_token(
            team=self.team,
            recipient_email=self.customer_email,
        )

        response = self.client.post(
            "/api/conversations/v1/widget/restore",
            {"restore_token": raw_token, "widget_session_id": new_session_id},
            **self._get_headers(),
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["widget_session_id"], new_session_id)
        self.assertEqual(len(data["migrated_ticket_ids"]), 1)

    def test_restore_redeem_invalid_token(self):
        # Token must be 40-50 chars to pass validation, then fails lookup
        fake_token = "a" * 43
        response = self.client.post(
            "/api/conversations/v1/widget/restore",
            {"restore_token": fake_token, "widget_session_id": self.widget_session_id},
            **self._get_headers(),
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["status"], "invalid")
        self.assertEqual(data["code"], "token_invalid")

    def test_restore_redeem_expired_token(self):
        token_record, raw_token = ConversationRestoreToken.create_token(
            team=self.team,
            recipient_email=self.customer_email,
        )
        token_record.expires_at = timezone.now() - timedelta(minutes=1)
        token_record.save()

        response = self.client.post(
            "/api/conversations/v1/widget/restore",
            {"restore_token": raw_token, "widget_session_id": self.widget_session_id},
            **self._get_headers(),
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["status"], "expired")
        self.assertEqual(data["code"], "token_expired")

    def test_restore_redeem_used_token(self):
        token_record, raw_token = ConversationRestoreToken.create_token(
            team=self.team,
            recipient_email=self.customer_email,
        )
        token_record.consumed_at = timezone.now()
        token_record.save()

        response = self.client.post(
            "/api/conversations/v1/widget/restore",
            {"restore_token": raw_token, "widget_session_id": self.widget_session_id},
            **self._get_headers(),
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["status"], "used")
        self.assertEqual(data["code"], "token_already_used")

    def test_restore_redeem_authentication_required(self):
        response = self.client.post(
            "/api/conversations/v1/widget/restore",
            {"restore_token": "a" * 43, "widget_session_id": self.widget_session_id},
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_restore_redeem_empty_widget_session_id_rejected(self):
        """Empty widget_session_id should be rejected at validation."""
        response = self.client.post(
            "/api/conversations/v1/widget/restore",
            {"restore_token": "a" * 43, "widget_session_id": ""},
            **self._get_headers(),
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_restore_redeem_non_uuid_widget_session_id_rejected(self):
        response = self.client.post(
            "/api/conversations/v1/widget/restore",
            {"restore_token": "a" * 43, "widget_session_id": "not-a-uuid-string"},
            **self._get_headers(),
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_restore_redeem_token_too_short_rejected(self):
        """Token shorter than 40 chars should be rejected at validation."""
        response = self.client.post(
            "/api/conversations/v1/widget/restore",
            {"restore_token": "short", "widget_session_id": self.widget_session_id},
            **self._get_headers(),
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_restore_redeem_token_too_long_rejected(self):
        """Token longer than 50 chars should be rejected at validation."""
        response = self.client.post(
            "/api/conversations/v1/widget/restore",
            {"restore_token": "a" * 51, "widget_session_id": self.widget_session_id},
            **self._get_headers(),
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class TestBuildRestoreUrl(BaseTest):
    """Tests for _build_restore_url helper function."""

    def test_build_restore_url_simple(self):
        from products.conversations.backend.api.restore import _build_restore_url

        result = _build_restore_url("https://example.com/support", "test_token_123")
        self.assertEqual(result, "https://example.com/support?ph_conv_restore=test_token_123")

    def test_build_restore_url_preserves_existing_query_params(self):
        from products.conversations.backend.api.restore import _build_restore_url

        result = _build_restore_url("https://example.com/support?foo=bar&baz=qux", "test_token")
        self.assertIn("foo=bar", result)
        self.assertIn("baz=qux", result)
        self.assertIn("ph_conv_restore=test_token", result)

    def test_build_restore_url_preserves_path(self):
        from products.conversations.backend.api.restore import _build_restore_url

        result = _build_restore_url("https://example.com/app/support/page", "token")
        self.assertTrue(result.startswith("https://example.com/app/support/page?"))

    def test_build_restore_url_drops_fragment(self):
        """Fragments are intentionally dropped (not sent to server anyway)."""
        from products.conversations.backend.api.restore import _build_restore_url

        result = _build_restore_url("https://example.com/support#section", "token")
        self.assertNotIn("#section", result)
        self.assertIn("ph_conv_restore=token", result)
