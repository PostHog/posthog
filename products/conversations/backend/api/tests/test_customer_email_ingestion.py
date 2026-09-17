import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import time_machine
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.apps import apps
from django.db import OperationalError
from django.test import Client, SimpleTestCase
from django.utils import timezone

from parameterized import parameterized

from posthog.ingress.contracts import DeliveryOwnership
from posthog.models.comment import Comment
from posthog.models.organization import OrganizationMembership
from posthog.models.user import User

from products.conversations.backend.api.tests.mailgun_signing import (
    SENDER_STATUS_REQUEST,
    MailgunWebhookTestMixin,
    mailgun_delivery,
    post_mailgun,
    sender_status_response,
    signed_mailgun_fields,
)
from products.conversations.backend.models import (
    EMAIL_THREAD_COMMENT_SCOPE,
    EmailChannel,
    EmailChannelConnectionStatus,
    EmailChannelKind,
    EmailChannelSetup,
    EmailChannelSetupProvider,
    EmailOutboxMessage,
    EmailThread,
    EmailThreadAccountLink,
    EmailThreadMessage,
    EmailThreadMessageDirection,
    Ticket,
)
from products.conversations.backend.services.email_channel_setup import (
    FORWARDING_CHALLENGE_HEADER,
    FORWARDING_CHALLENGE_MARKER,
    create_forwarding_challenge,
)
from products.conversations.backend.services.mailgun_events import (
    MAX_FORWARDING_CHALLENGE_TOKENS,
    MAX_RECIPIENTS,
    MailgunMessage,
    _parse_addresses,
    mailgun_inbound_delivery_ownership,
    mailgun_outbound_delivery_ownership,
)
from products.customer_analytics.backend.facade.email_matching import recalculate_email_thread_links


class TestCustomerEmailIngestion(MailgunWebhookTestMixin, BaseTest):
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

    def _post_email(
        self,
        *,
        message_id: str,
        recipient: str = "team-c0570a111@mg.posthog.com",
        **overrides: str,
    ):
        data = {
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
        return post_mailgun(self.client, "/api/conversations/v1/email/inbound", data)

    def _post_outbound_email(self, *, message_id: str, **overrides: str):
        data = {
            "recipient": "sent@mg.posthog.com",
            "from": "Customer success <csm@example.com>",
            "sender": "csm@example.com",
            "To": "Prospect <prospect@future.example>",
            "Message-Id": message_id,
            "Date": "Tue, 10 Jun 2025 14:00:00 +0000",
            "subject": "Account update",
            "stripped-text": "Here is your account update.",
            "body-plain": "Here is your account update.",
            "message-headers": json.dumps(
                [
                    ["X-Mailgun-Spf", "Fail"],
                    ["X-Mailgun-Dkim-Check-Result", "Pass"],
                    ["DKIM-Signature", "v=1; a=rsa-sha256; d=example.com; s=mail"],
                ]
            ),
        }
        data.update(overrides)
        return post_mailgun(self.client, "/api/conversations/v1/email/capture", data)

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

        assert first_response.status_code == 202
        assert second_response.status_code == 202
        setup.refresh_from_db()
        assert setup.confirmation_action == "https://mail-settings.google.com/mail/vf-expected"
        assert setup.confirmation_message_id_hash
        assert setup.confirmation_received_at is not None
        assert not EmailThread.objects.for_team(self.team.id).exists()
        assert not Ticket.objects.filter(team=self.team).exists()
        assert not EmailOutboxMessage.objects.filter(team=self.team).exists()

    @parameterized.expand(["message_headers", "body_html"])
    def test_forwarding_challenge_activates_pending_channel_and_consumes_retries(self, transport: str) -> None:
        setup = self._start_google_setup()
        challenge = create_forwarding_challenge(
            team_id=self.team.id,
            channel_id=self.channel.id,
            setup_id=setup.id,
        )
        payload: dict[str, str] = {
            "from": "PostHog <noreply@posthog.com>",
            "sender": "noreply@posthog.com",
            "subject": "Verify email forwarding to PostHog",
            "body-plain": "PostHog is checking email forwarding.",
            "stripped-text": "PostHog is checking email forwarding.",
        }
        if transport == "message_headers":
            payload["message-headers"] = json.dumps([[FORWARDING_CHALLENGE_HEADER, challenge.token]])
        else:
            payload["body-html"] = f"<p>{FORWARDING_CHALLENGE_MARKER}{challenge.token}</p>"

        first_response = self._post_email(message_id=f"<challenge-{transport}@posthog.com>", **payload)
        retry_response = self._post_email(message_id=f"<challenge-{transport}-retry@posthog.com>", **payload)

        assert first_response.status_code == 202
        assert retry_response.status_code == 202
        self.channel.refresh_from_db()
        assert self.channel.connection_status == EmailChannelConnectionStatus.ACTIVE
        assert not EmailChannelSetup.objects.for_team(self.team.id).filter(id=setup.id).exists()
        assert not EmailThread.objects.for_team(self.team.id).exists()
        assert not Ticket.objects.filter(team=self.team).exists()

    @parameterized.expand(["wrong_team", "wrong_channel", "wrong_setup"])
    def test_pending_channel_rejects_signed_challenge_for_another_setup(self, mismatch: str) -> None:
        setup = self._start_google_setup()
        challenge = create_forwarding_challenge(
            team_id=self.team.id + 1 if mismatch == "wrong_team" else self.team.id,
            channel_id=uuid4() if mismatch == "wrong_channel" else self.channel.id,
            setup_id=uuid4() if mismatch == "wrong_setup" else setup.id,
        )

        response = self._post_email(
            message_id=f"<challenge-{mismatch}@posthog.com>",
            **{FORWARDING_CHALLENGE_HEADER: challenge.token},
        )

        assert response.status_code == 202
        self.channel.refresh_from_db()
        assert self.channel.connection_status == EmailChannelConnectionStatus.PENDING_CONFIRMATION
        assert EmailChannelSetup.objects.for_team(self.team.id).filter(id=setup.id).exists()
        assert not EmailThread.objects.for_team(self.team.id).exists()

    def test_active_channel_ingests_email_with_challenge_for_another_channel(self) -> None:
        challenge = create_forwarding_challenge(
            team_id=self.team.id,
            channel_id=uuid4(),
            setup_id=uuid4(),
        )

        response = self._post_email(
            message_id="<cross-channel-challenge@customer.example>",
            **{FORWARDING_CHALLENGE_HEADER: challenge.token},
        )

        assert response.status_code == 202
        thread = EmailThread.objects.for_team(self.team.id).get()
        message = EmailThreadMessage.objects.for_team(self.team.id).select_related("comment").get(thread=thread)
        assert message.comment.content == "Can you help?"

    def test_pending_channel_rejects_expired_signed_challenge(self) -> None:
        with time_machine.travel("2026-01-01 00:00:00", tick=False):
            setup = self._start_google_setup(expires_at=timezone.now() + timedelta(hours=48))
            challenge = create_forwarding_challenge(
                team_id=self.team.id,
                channel_id=self.channel.id,
                setup_id=setup.id,
            )

        with time_machine.travel("2026-01-02 00:00:01", tick=False):
            response = self._post_email(
                message_id="<expired-challenge@posthog.com>",
                **{FORWARDING_CHALLENGE_HEADER: challenge.token},
            )

        assert response.status_code == 202
        self.channel.refresh_from_db()
        assert self.channel.connection_status == EmailChannelConnectionStatus.PENDING_CONFIRMATION
        assert EmailChannelSetup.objects.for_team(self.team.id).filter(id=setup.id).exists()
        assert not EmailThread.objects.for_team(self.team.id).exists()

    def test_pending_channel_rejects_unsigned_direct_address_challenge(self) -> None:
        setup = self._start_google_setup()

        response = self._post_email(
            message_id="<forged-challenge@attacker.example>",
            **{FORWARDING_CHALLENGE_HEADER: "forged-token"},
        )

        assert response.status_code == 202
        self.channel.refresh_from_db()
        assert self.channel.connection_status == EmailChannelConnectionStatus.PENDING_CONFIRMATION
        assert EmailChannelSetup.objects.for_team(self.team.id).filter(id=setup.id).exists()
        assert not EmailThread.objects.for_team(self.team.id).exists()

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

        assert response.status_code == 202
        setup.refresh_from_db()
        assert setup.confirmation_action == "https://mail.google.com/mail/vf-%5Blive_token%5D-value"
        assert setup.confirmation_received_at is not None

    @parameterized.expand(
        [
            (
                "failed_spf_and_dkim",
                {
                    "X-Mailgun-Spf": "fail",
                    "X-Mailgun-Dkim-Check-Result": "fail",
                },
            ),
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

        assert response.status_code == 202
        setup.refresh_from_db()
        assert setup.confirmation_action is None
        assert not EmailThread.objects.for_team(self.team.id).exists()

    def test_expired_setup_is_deleted_and_discards_email(self) -> None:
        setup = self._start_google_setup(expires_at=timezone.now() - timedelta(seconds=1))

        response = self._post_email(
            message_id="<expired-forwarding-confirmation@gmail.com>",
            **self._valid_google_confirmation(),
        )

        assert response.status_code == 202
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

        assert root_response.status_code == 202
        assert reply_response.status_code == 202
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

    @patch(
        "products.conversations.backend.services.email_thread_ingestion.schedule_email_thread_link_recalculation_for_threads"
    )
    def test_forwarded_message_schedules_account_matching(self, mock_schedule: MagicMock) -> None:
        response = self._post_email(message_id="<linked@customer.example>")

        assert response.status_code == 202
        thread = EmailThread.objects.for_team(self.team.id).get()
        mock_schedule.assert_called_once_with(self.team.id, [str(thread.id)])

    @patch(
        "products.customer_analytics.backend.facade.email_matching.current_app.send_task",
        side_effect=Exception("account matching backend unavailable"),
    )
    def test_account_link_recalculation_failure_does_not_fail_ingestion(self, _mock_send_task: MagicMock) -> None:
        with self.captureOnCommitCallbacks(execute=True):
            response = self._post_email(message_id="<recalc-fails@customer.example>")

        assert response.status_code == 202
        thread = EmailThread.objects.for_team(self.team.id).get()
        assert EmailThreadMessage.objects.for_team(self.team.id).filter(thread=thread).count() == 1
        assert not EmailThreadAccountLink.objects.for_team(self.team.id).exists()

    def test_outbound_message_is_recovered_when_a_later_reply_matches_an_account(self) -> None:
        outbound_message_id = "<outbound@customer-success.example>"
        outbound_response = self._post_outbound_email(message_id=outbound_message_id)

        assert outbound_response.status_code == 202
        thread = EmailThread.objects.for_team(self.team.id).get()
        assert not EmailThreadAccountLink.objects.for_team(self.team.id).filter(thread=thread).exists()

        account_model = apps.get_model("customer_analytics", "Account")
        account = account_model.objects.for_team(self.team.id).create(
            team=self.team,
            name="Future account",
            external_id="future-account",
            _properties={"known_emails": ["prospect@future.example"]},
        )
        reply_response = self._post_email(
            message_id="<reply@future.example>",
            **{
                "from": "Prospect <prospect@future.example>",
                "sender": "prospect@future.example",
                "To": "Customer success <csm@example.com>",
                "In-Reply-To": outbound_message_id,
                "Date": "Tue, 10 Jun 2025 15:00:00 +0000",
                "body-plain": "Thanks for the update.",
                "stripped-text": "Thanks for the update.",
                "X-Mailgun-Spf": "pass",
            },
        )

        assert reply_response.status_code == 202
        recalculate_email_thread_links(self.team.id, thread_ids=[str(thread.id)])
        thread.refresh_from_db()
        messages = list(EmailThreadMessage.objects.for_team(self.team.id).filter(thread=thread))
        assert thread.message_count == 2
        assert [message.direction for message in messages] == [
            EmailThreadMessageDirection.OUTBOUND,
            EmailThreadMessageDirection.INBOUND,
        ]
        assert messages[0].sender_email == "csm@example.com"
        assert messages[0].sender_authenticated is True
        assert messages[1].in_reply_to == outbound_message_id
        link = EmailThreadAccountLink.objects.for_team(self.team.id).get(thread=thread)
        assert link.account_id == str(account.id)
        assert not Ticket.objects.filter(team=self.team).exists()
        assert not EmailOutboxMessage.objects.filter(team=self.team).exists()

    @parameterized.expand(
        [
            ("different_envelope", {"sender": "attacker@example.com"}),
            (
                "unaligned_dkim",
                {
                    "message-headers": json.dumps(
                        [
                            ["X-Mailgun-Spf", "Fail"],
                            ["X-Mailgun-Dkim-Check-Result", "Pass"],
                            ["DKIM-Signature", "v=1; a=rsa-sha256; d=attacker.example; s=mail"],
                        ]
                    )
                },
            ),
            (
                "conflicting_authentication_results",
                {
                    "message-headers": json.dumps(
                        [
                            ["X-Mailgun-Spf", "Fail"],
                            ["X-Mailgun-Spf", "Pass"],
                            ["X-Mailgun-Dkim-Check-Result", "Fail"],
                            ["X-Mailgun-Dkim-Check-Result", "Pass"],
                            ["DKIM-Signature", "v=1; a=rsa-sha256; d=example.com; s=mail"],
                        ]
                    )
                },
            ),
        ]
    )
    def test_outbound_capture_rejects_an_unauthenticated_sender(self, _name: str, overrides: dict[str, str]) -> None:
        with (
            patch("posthog.regions.PRIMARY_REGION_DOMAIN", "testserver"),
            patch("posthog.ingress.dispatch.forward.requests.request") as mock_forward,
        ):
            response = self._post_outbound_email(
                message_id=f"<spoofed-{_name}@customer-success.example>",
                **overrides,
            )

        assert response.status_code == 202
        # The From header is the only thing naming a channel, so an unauthenticated one must not
        # make this region replay the delivery to the other one.
        mock_forward.assert_not_called()
        assert not EmailThread.objects.for_team(self.team.id).exists()

    @parameterized.expand(
        [
            ("the owning region accepts it", 202, 202),
            # Mailgun redelivers on a non-2xx, so a forward that never landed must not be receipted.
            ("the owning region is unreachable", 500, 502),
        ]
    )
    def test_a_sender_another_region_owns_is_forwarded_from_the_primary(
        self, _name: str, secondary_status: int, expected_status: int
    ) -> None:
        self.channel.connection_status = EmailChannelConnectionStatus.PENDING_CONFIRMATION
        self.channel.save(update_fields=["connection_status"])

        with (
            patch("posthog.regions.PRIMARY_REGION_DOMAIN", "testserver"),
            patch("posthog.ingress.dispatch.forward.requests.request") as mock_forward,
        ):
            mock_forward.return_value = MagicMock(ok=200 <= secondary_status < 300, status_code=secondary_status)
            response = self._post_outbound_email(message_id=f"<region-{_name}@example.com>")

        assert response.status_code == expected_status
        mock_forward.assert_called_once()
        assert not EmailThread.objects.for_team(self.team.id).exists()

    def test_a_sender_this_region_owns_is_ingested_without_a_forward(self) -> None:
        with (
            patch("posthog.regions.PRIMARY_REGION_DOMAIN", "testserver"),
            patch("posthog.ingress.dispatch.forward.requests.request") as mock_forward,
        ):
            response = self._post_outbound_email(message_id="<region-local@example.com>")

        assert response.status_code == 202
        mock_forward.assert_not_called()
        assert EmailThread.objects.for_team(self.team.id).exists()

    @parameterized.expand(
        [
            # Channel uniqueness is per region, so a sender active in both would attach one team's
            # private outbound mail to the other team's thread.
            ("the sender is active in both regions", 204, None, 202, False),
            ("only this region holds the sender", 404, {"sender_active": False}, 202, True),
            # The question went unanswered, so Mailgun has to ask it again.
            ("the other region answers nothing useful", 500, None, 502, False),
            # A region that has not deployed this route yet answers Django's own 404 page. That is
            # an unanswered question, not an answer of "no channel there".
            ("the other region has no such route yet", 404, None, 502, False),
        ]
    )
    def test_the_primary_region_asks_the_other_region_before_it_ingests_a_capture(
        self, _name: str, sender_status: int, sender_body: dict | None, expected_status: int, expected_ingestion: bool
    ) -> None:
        with patch(SENDER_STATUS_REQUEST) as mock_sender_status:
            mock_sender_status.return_value = sender_status_response(sender_status, sender_body)
            response = self._post_outbound_email(message_id=f"<ambiguous-{_name}@example.com>")

        assert response.status_code == expected_status
        mock_sender_status.assert_called_once()
        assert EmailThread.objects.for_team(self.team.id).exists() is expected_ingestion

    def test_the_secondary_region_never_asks_itself_about_the_sender(self) -> None:
        # A host other than the primary domain makes this deployment the secondary, which would
        # otherwise ask itself and always find its own channel.
        with self.settings(SITE_URL="https://us.posthog.com"), patch(SENDER_STATUS_REQUEST) as mock_sender_status:
            response = self._post_outbound_email(message_id="<secondary-no-probe@example.com>")

        assert response.status_code == 202
        mock_sender_status.assert_not_called()
        assert EmailThread.objects.for_team(self.team.id).exists()

    def test_the_sender_status_endpoint_answers_only_a_signed_caller(self) -> None:
        unsigned = self.client.post("/api/conversations/v1/email/sender-status", {"sender": self.channel.from_email})
        active = post_mailgun(
            self.client, "/api/conversations/v1/email/sender-status", {"sender": self.channel.from_email}
        )
        absent = post_mailgun(
            self.client, "/api/conversations/v1/email/sender-status", {"sender": "nobody@example.com"}
        )

        assert unsigned.status_code == 403
        assert active.status_code == 204
        assert absent.status_code == 404

    @parameterized.expand(
        [
            ("the sender is active here", "csm@example.com", 204),
            ("no channel here sends as the sender", "nobody@example.com", 404),
        ]
    )
    def test_the_outbound_route_answers_a_legacy_sender_probe_without_ingesting(
        self, _name: str, sender_email: str, expected_status: int
    ) -> None:
        response = self.client.post(
            "/api/conversations/v1/email/outbound?sender_lookup=1",
            {
                **signed_mailgun_fields(),
                "recipient": "sent@mg.posthog.com",
                "from": f"Customer success <{sender_email}>",
                "sender": sender_email,
                "To": "Prospect <prospect@future.example>",
                "Message-Id": f"<legacy-probe-{_name}@example.com>",
                "subject": "Account update",
                "body-plain": "Here is your account update.",
                "message-headers": json.dumps(
                    [
                        ["X-Mailgun-Spf", "Fail"],
                        ["X-Mailgun-Dkim-Check-Result", "Pass"],
                        ["DKIM-Signature", "v=1; a=rsa-sha256; d=example.com; s=mail"],
                    ]
                ),
            },
        )

        assert response.status_code == expected_status
        assert not EmailThread.objects.for_team(self.team.id).exists()

    @parameterized.expand(
        [
            ("pending_confirmation", EmailChannelConnectionStatus.PENDING_CONFIRMATION),
            ("confirmation_expired", EmailChannelConnectionStatus.CONFIRMATION_EXPIRED),
        ]
    )
    def test_outbound_capture_skips_non_active_channels(
        self, _name: str, connection_status: EmailChannelConnectionStatus
    ) -> None:
        self.channel.connection_status = connection_status
        self.channel.save(update_fields=["connection_status"])

        response = self._post_outbound_email(message_id=f"<outbound-{_name}@customer-success.example>")

        assert response.status_code == 202
        assert not EmailThread.objects.for_team(self.team.id).exists()

    def test_outbound_capture_drops_internal_only_messages(self) -> None:
        colleague = User.objects.create(email="colleague@example.com", current_team=self.team)
        OrganizationMembership.objects.create(
            organization=self.organization,
            user=colleague,
            level=OrganizationMembership.Level.MEMBER,
        )

        response = self._post_outbound_email(
            message_id="<internal@example.com>",
            To="Colleague <colleague@example.com>",
        )

        assert response.status_code == 202
        assert not EmailThread.objects.for_team(self.team.id).exists()

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

        assert first_response.status_code == 202
        assert retry_response.status_code == 202
        assert second_owner_response.status_code == 202
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

        assert response.status_code == 202
        assert not EmailThread.objects.for_team(self.team.id).exists()


class TestForwardingChallengeTokens(SimpleTestCase):
    def test_stops_reading_headers_after_reaching_the_token_limit(self) -> None:
        class HeaderValues(list[list[str]]):
            def __iter__(self) -> Iterator[list[str]]:
                for index in range(MAX_FORWARDING_CHALLENGE_TOKENS):
                    yield [FORWARDING_CHALLENGE_HEADER, f"token-{index}"]
                raise AssertionError("challenge extraction read beyond its limit")

        message = MailgunMessage(mailgun_delivery({"message-headers": "[]"}))
        with patch("products.conversations.backend.services.mailgun_events.json.loads", return_value=HeaderValues()):
            tokens = message.forwarding_challenge_tokens()

        assert len(tokens) == MAX_FORWARDING_CHALLENGE_TOKENS


class TestParseAddresses(SimpleTestCase):
    def test_recipient_count_is_capped(self) -> None:
        header = ", ".join(f"user{index}@example.com" for index in range(MAX_RECIPIENTS + 50))

        parsed = _parse_addresses(header)

        assert len(parsed) == MAX_RECIPIENTS


class TestParseSentAt(SimpleTestCase):
    @parameterized.expand(
        [
            # A far-future Date header is rejected and falls back to the authenticated timestamp.
            ("future_date_rejected", "Mon, 1 Jan 2999 00:00:00 +0000", datetime(2025, 6, 10, 14, 30, tzinfo=UTC)),
            # A plausible past Date header is kept as-is, not overridden by the timestamp.
            ("valid_past_date_kept", "Wed, 1 Jan 2025 00:00:00 +0000", datetime(2025, 1, 1, 0, 0, tzinfo=UTC)),
        ]
    )
    def test_parse_sent_at(self, _name: str, date_header: str, expected: datetime) -> None:
        message = MailgunMessage(mailgun_delivery({"Date": date_header, "timestamp": "1749565800"}))

        assert message.sent_at() == expected


class TestOwnershipOfATimedOutChannelLookup(SimpleTestCase):
    STATEMENT_TIMEOUT = OperationalError("canceling statement due to statement timeout")

    def test_an_outbound_lookup_that_times_out_does_not_answer_elsewhere(self) -> None:
        delivery = mailgun_delivery(
            {
                "recipient": "sent@mg.posthog.com",
                "from": "Customer success <csm@example.com>",
                "sender": "csm@example.com",
                "message-headers": json.dumps(
                    [
                        ["X-Mailgun-Spf", "Fail"],
                        ["X-Mailgun-Dkim-Check-Result", "Pass"],
                        ["DKIM-Signature", "v=1; a=rsa-sha256; d=example.com; s=mail"],
                    ]
                ),
            },
            app="outbound",
        )

        with (
            patch(
                "products.conversations.backend.services.mailgun_events._channel_for_outbound_sender",
                side_effect=self.STATEMENT_TIMEOUT,
            ),
            pytest.raises(OperationalError),
        ):
            mailgun_outbound_delivery_ownership(delivery)

    def test_an_inbound_lookup_that_times_out_still_answers_elsewhere(self) -> None:
        delivery = mailgun_delivery({"recipient": "team-abc123@mg.posthog.com"})

        with patch(
            "products.conversations.backend.services.mailgun_events._channel_for_inbound_token",
            side_effect=self.STATEMENT_TIMEOUT,
        ):
            assert mailgun_inbound_delivery_ownership(delivery) is DeliveryOwnership.ELSEWHERE
