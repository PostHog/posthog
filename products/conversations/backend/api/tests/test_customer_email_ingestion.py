import json
from datetime import UTC, datetime, timedelta

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.test import Client, RequestFactory, SimpleTestCase
from django.utils import timezone

from parameterized import parameterized

from posthog.models.comment import Comment
from posthog.models.organization import OrganizationMembership
from posthog.models.user import User

from products.conversations.backend.api.email_events import MAX_RECIPIENTS, _parse_addresses, _parse_sent_at
from products.conversations.backend.models import (
    EMAIL_THREAD_COMMENT_SCOPE,
    EmailChannel,
    EmailChannelConnectionStatus,
    EmailChannelKind,
    EmailChannelSetup,
    EmailChannelSetupProvider,
    EmailOutboxMessage,
    EmailThread,
    EmailThreadMessage,
    Ticket,
)


class TestCustomerEmailIngestion(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.client = Client()
        self.channel = EmailChannel.objects.create(
            team=self.team,
            kind=EmailChannelKind.CUSTOMER_COMMUNICATION,
            owner=self.user,
            inbound_token="c0570a111",
            from_email="csm@example.com",
            from_name="Customer success",
            domain="example.com",
            domain_verified=True,
            connection_status=EmailChannelConnectionStatus.ACTIVE,
        )
        signature_patcher = patch(
            "products.conversations.backend.api.email_events.validate_webhook_signature",
            return_value=True,
        )
        signature_patcher.start()
        self.addCleanup(signature_patcher.stop)

    def _post_email(
        self,
        *,
        message_id: str,
        recipient: str = "team-c0570a111@mg.posthog.com",
        **overrides: str,
    ):
        data = {
            "token": "webhook-token",
            "timestamp": "1749565800",
            "signature": "webhook-signature",
            "recipient": recipient,
            "from": "Example customer <customer@customer.example>",
            "sender": "customer@customer.example",
            "To": "CSM <csm@example.com>",
            "Message-Id": message_id,
            "Date": "Tue, 10 Jun 2025 14:30:00 +0000",
            "subject": "Account question",
            "stripped-text": "Can you help?",
            "body-plain": "Can you help?",
        }
        data.update(overrides)
        return self.client.post("/api/conversations/v1/email/inbound", data)

    def _start_google_setup(self, *, expires_at=None) -> EmailChannelSetup:
        self.channel.connection_status = EmailChannelConnectionStatus.PENDING_CONFIRMATION
        self.channel.save(update_fields=["connection_status"])
        return EmailChannelSetup.objects.for_team(self.team.id).create(
            team=self.team,
            channel=self.channel,
            provider=EmailChannelSetupProvider.GOOGLE,
            expires_at=expires_at or timezone.now() + timedelta(hours=24),
        )

    def _valid_google_confirmation(self, *, action_suffix: str = "expected") -> dict[str, str]:
        action = f"https://mail-settings.google.com/mail/vf-{action_suffix}"
        return {
            "from": "Gmail forwarding <forwarding-noreply@google.com>",
            "sender": "forwarding-noreply@google.com",
            "subject": "(#12345678) Gmail Forwarding Confirmation - Receive Mail from csm@example.com",
            "body-plain": f"Confirm forwarding by visiting {action}",
            "stripped-text": f"Confirm forwarding by visiting {action}",
            "X-Mailgun-Spf": "pass",
            "X-Mailgun-Dkim-Check-Result": "pass",
            "DKIM-Signature": ("v=1; a=rsa-sha256; d=google.com; s=20230601; h=from:to:subject:date; b=signature"),
        }

    def test_pending_channel_stores_only_the_first_authenticated_google_confirmation(self) -> None:
        setup = self._start_google_setup()

        first_response = self._post_email(
            message_id="<forwarding-confirmation@gmail.com>",
            **self._valid_google_confirmation(),
        )
        second_response = self._post_email(
            message_id="<second-forwarding-confirmation@gmail.com>",
            **self._valid_google_confirmation(action_suffix="replacement"),
        )

        assert first_response.status_code == 200
        assert second_response.status_code == 200
        setup.refresh_from_db()
        assert setup.confirmation_action == "https://mail-settings.google.com/mail/vf-expected"
        assert setup.confirmation_message_id_hash
        assert setup.confirmation_received_at is not None
        assert not EmailThread.objects.for_team(self.team.id).exists()
        assert not Ticket.objects.filter(team=self.team).exists()
        assert not EmailOutboxMessage.objects.filter(team=self.team).exists()

    def test_pending_channel_accepts_live_mailgun_confirmation_shape(self) -> None:
        setup = self._start_google_setup()
        payload = self._valid_google_confirmation()
        payload["subject"] = "(PostHog Forwarding Confirmation - Receive Mail from csm@example.com"
        payload["body-plain"] = (
            "Confirm forwarding at https://mail.google.com/mail/vf-%5Blive_token%5D-value or reject it at "
            "https://mail.google.com/mail/uf-live-token"
        )
        payload["stripped-text"] = payload["body-plain"]
        payload["message-headers"] = json.dumps(
            [
                ["X-Mailgun-Spf", payload.pop("X-Mailgun-Spf")],
                ["X-Mailgun-Dkim-Check-Result", payload.pop("X-Mailgun-Dkim-Check-Result")],
                ["DKIM-Signature", payload.pop("DKIM-Signature")],
            ]
        )

        response = self._post_email(message_id="<live-forwarding-confirmation@gmail.com>", **payload)

        assert response.status_code == 200
        setup.refresh_from_db()
        assert setup.confirmation_action == "https://mail.google.com/mail/vf-%5Blive_token%5D-value"
        assert setup.confirmation_received_at is not None

    @parameterized.expand(
        [
            ("missing_spf", {"X-Mailgun-Spf": ""}),
            ("wrong_source", {"subject": "Gmail Forwarding Confirmation - Receive Mail from attacker@example.com"}),
            (
                "wrong_dkim_domain",
                {"DKIM-Signature": "v=1; d=attacker.example; h=from:subject; b=signature"},
            ),
            (
                "unsigned_subject",
                {"DKIM-Signature": "v=1; d=google.com; h=from:to:date; b=signature"},
            ),
            (
                "conflicting_mailgun_results",
                {
                    "X-Mailgun-Spf": "fail",
                    "X-Mailgun-Dkim-Check-Result": "fail",
                    "DKIM-Signature": "",
                    "message-headers": json.dumps(
                        [
                            ["X-Mailgun-Spf", "pass"],
                            ["X-Mailgun-Dkim-Check-Result", "pass"],
                            ["DKIM-Signature", "v=1; d=google.com; h=from:subject; b=forged"],
                        ]
                    ),
                },
            ),
            (
                "mixed_dkim_domains",
                {
                    "DKIM-Signature": "",
                    "message-headers": json.dumps(
                        [
                            ["DKIM-Signature", "v=1; d=google.com; h=from:subject; b=forged"],
                            ["DKIM-Signature", "v=1; d=attacker.example; h=from:subject; b=valid"],
                        ]
                    ),
                },
            ),
            (
                "lookalike_action_host",
                {
                    "body-plain": "https://mail-settings.google.com.attacker.example/mail/vf-token",
                    "stripped-text": "https://mail-settings.google.com.attacker.example/mail/vf-token",
                },
            ),
        ]
    )
    def test_pending_channel_discards_untrusted_confirmation_candidates(
        self, _name: str, overrides: dict[str, str]
    ) -> None:
        setup = self._start_google_setup()
        payload = self._valid_google_confirmation()
        payload.update(overrides)

        response = self._post_email(message_id=f"<{_name}@gmail.com>", **payload)

        assert response.status_code == 200
        setup.refresh_from_db()
        assert setup.confirmation_action is None
        assert not EmailThread.objects.for_team(self.team.id).exists()

    def test_expired_setup_is_deleted_and_discards_email(self) -> None:
        setup = self._start_google_setup(expires_at=timezone.now() - timedelta(seconds=1))

        response = self._post_email(
            message_id="<expired-forwarding-confirmation@gmail.com>",
            **self._valid_google_confirmation(),
        )

        assert response.status_code == 200
        assert not EmailChannelSetup.objects.for_team(self.team.id).filter(id=setup.id).exists()
        self.channel.refresh_from_db()
        assert self.channel.connection_status == EmailChannelConnectionStatus.CONFIRMATION_EXPIRED
        assert not EmailThread.objects.for_team(self.team.id).exists()

    @parameterized.expand(["in_reply_to", "references"])
    def test_rfc_reply_headers_continue_the_existing_thread(self, header_kind: str) -> None:
        root_message_id = f"<root-{header_kind}@customer.example>"
        root_response = self._post_email(
            message_id=root_message_id,
            **{
                "X-Mailgun-Spf": "pass",
                "body-plain": "Initial message with forwarded context",
                "stripped-text": "Initial message",
            },
        )
        reply_fields = {
            "Date": "Tue, 10 Jun 2025 15:30:00 +0000",
            "body-plain": "Reply only\n\nOn Tuesday, Customer success wrote:\n> Initial message",
            "stripped-text": "Reply only",
        }
        if header_kind == "in_reply_to":
            reply_fields["In-Reply-To"] = root_message_id
        else:
            reply_fields["References"] = f"<older@customer.example> {root_message_id}"

        reply_response = self._post_email(
            message_id=f"<reply-{header_kind}@customer.example>",
            **reply_fields,
        )

        assert root_response.status_code == 200
        assert reply_response.status_code == 200
        thread = EmailThread.objects.for_team(self.team.id).get()
        messages = list(
            EmailThreadMessage.objects.for_team(self.team.id).filter(thread=thread).select_related("comment")
        )
        assert thread.message_count == 2
        assert thread.preview == "Reply only"
        assert len(messages) == 2
        assert messages[0].sender_authenticated is True
        assert messages[0].comment.content == "Initial message with forwarded context"
        assert messages[1].comment.content == "Reply only"
        assert messages[1].in_reply_to == (root_message_id if header_kind == "in_reply_to" else None)
        assert messages[1].references == (
            [] if header_kind == "in_reply_to" else ["<older@customer.example>", root_message_id]
        )

    def test_duplicate_delivery_creates_one_message_across_customer_channels(self) -> None:
        message_id = "<duplicate@customer.example>"
        first_response = self._post_email(message_id=message_id)
        retry_response = self._post_email(message_id=message_id)

        second_owner = User.objects.create(email="second-csm@example.com", current_team=self.team)
        OrganizationMembership.objects.create(
            organization=self.organization,
            user=second_owner,
            level=OrganizationMembership.Level.MEMBER,
        )
        EmailChannel.objects.create(
            team=self.team,
            kind=EmailChannelKind.CUSTOMER_COMMUNICATION,
            owner=second_owner,
            inbound_token="5ec00dc5a",
            from_email=second_owner.email,
            from_name="Second CSM",
            domain="example.com",
            domain_verified=True,
            connection_status=EmailChannelConnectionStatus.ACTIVE,
        )
        second_owner_response = self._post_email(
            message_id=message_id,
            recipient="team-5ec00dc5a@mg.posthog.com",
        )

        assert first_response.status_code == 200
        assert retry_response.status_code == 200
        assert second_owner_response.status_code == 200
        thread = EmailThread.objects.for_team(self.team.id).get()
        assert thread.message_count == 1
        assert EmailThreadMessage.objects.for_team(self.team.id).filter(thread=thread).count() == 1
        assert (
            Comment.objects.filter(team=self.team, scope=EMAIL_THREAD_COMMENT_SCOPE, item_id=str(thread.id)).count()
            == 1
        )

    def test_dangling_owner_is_acked_without_a_server_error(self) -> None:
        # owner is a db_constraint=False FK, so a deleted owner leaves owner_id pointing at a missing
        # user while satisfying the not-null check constraint; channel.owner then resolves to None and
        # ingestion raises. The webhook must ack (200) rather than 500 into a Mailgun retry loop.
        EmailChannel.objects.filter(id=self.channel.id).update(owner_id=987654321)

        response = self._post_email(message_id="<dangling-owner@customer.example>")

        assert response.status_code == 200
        assert not EmailThread.objects.for_team(self.team.id).exists()


class TestParseAddresses(SimpleTestCase):
    def test_recipient_count_is_capped(self) -> None:
        header = ", ".join(f"user{index}@example.com" for index in range(MAX_RECIPIENTS + 50))

        parsed = _parse_addresses(header)

        assert len(parsed) == MAX_RECIPIENTS


class TestParseSentAt(SimpleTestCase):
    factory = RequestFactory()

    @parameterized.expand(
        [
            # A far-future Date header is rejected and falls back to the authenticated timestamp.
            ("future_date_rejected", "Mon, 1 Jan 2999 00:00:00 +0000", datetime(2025, 6, 10, 14, 30, tzinfo=UTC)),
            # A plausible past Date header is kept as-is, not overridden by the timestamp.
            ("valid_past_date_kept", "Wed, 1 Jan 2025 00:00:00 +0000", datetime(2025, 1, 1, 0, 0, tzinfo=UTC)),
        ]
    )
    def test_parse_sent_at(self, _name: str, date_header: str, expected: datetime) -> None:
        request = self.factory.post("/", {"Date": date_header, "timestamp": "1749565800"})

        assert _parse_sent_at(request) == expected
