from datetime import timedelta

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.test import SimpleTestCase
from django.utils import timezone

from rest_framework.test import APIClient

from posthog.models.integration import Integration
from posthog.models.user import User

from products.conversations.backend.api.internal import (
    CONVERSATIONS_WORKFLOW_EMAILS_PURPOSE,
    WorkflowEmailCaptureSerializer,
)
from products.conversations.backend.models import (
    EmailChannel,
    EmailChannelKind,
    EmailThreadAccountLink,
    EmailThreadMessage,
    EmailThreadMessageDirection,
    EmailThreadParticipant,
)
from products.conversations.backend.services.email_thread_ingestion import (
    EmailAddress,
    ParsedEmail,
    ingest_customer_email,
)
from products.conversations.backend.services.workflow_email_ingestion import get_ses_rfc_message_id
from products.customer_analytics.backend.models import Account


class TestWorkflowEmailCaptureValidation(SimpleTestCase):
    def test_rejects_bcc_and_header_injection(self) -> None:
        payload = {
            "source_id": "invocation-1",
            "provider_message_id": "provider-id\r\nBcc: hidden@example.com",
            "email_integration_id": 1,
            "sent_at": timezone.now().isoformat(),
            "sender": {"email": "sender@example.com"},
            "to": {"email": "customer@example.com"},
            "subject": "Hello",
            "body_plain": "Body",
            "bcc": [{"email": "hidden@example.com"}],
        }
        serializer = WorkflowEmailCaptureSerializer(data=payload)
        assert not serializer.is_valid()
        assert "provider_message_id" in serializer.errors

        payload["provider_message_id"] = "provider-id\n"
        serializer = WorkflowEmailCaptureSerializer(data=payload)
        assert not serializer.is_valid()
        assert "provider_message_id" in serializer.errors

        payload["provider_message_id"] = "provider-id"
        serializer = WorkflowEmailCaptureSerializer(data=payload)
        assert not serializer.is_valid()
        assert "bcc" in serializer.errors

        payload.pop("bcc")
        payload["cc"] = [{"email": "copy@example.com"}] * 50
        serializer = WorkflowEmailCaptureSerializer(data=payload)
        assert not serializer.is_valid()
        assert "cc" in serializer.errors

    def test_normalizes_current_ses_provider_id(self) -> None:
        assert get_ses_rfc_message_id("010001-fake-000000") == "<010001-fake-000000@email.amazonses.com>"


class TestWorkflowEmailCapture(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.client = APIClient()
        self.team.conversations_enabled = True
        self.team.save(update_fields=["conversations_enabled"])
        self.integration = Integration.objects.create(
            team=self.team,
            kind=Integration.IntegrationKind.EMAIL,
            config={"verified": True, "email": "sender@example.com", "domain": "example.com"},
        )
        self.account = Account.objects.for_team(self.team.id).create(
            team=self.team,
            name="Example account",
            _properties={"known_emails": ["customer@example.com"], "email_domains": []},
        )
        self.url = f"/api/projects/{self.team.id}/internal/conversations/workflow-emails"
        self.payload = {
            "source_id": "invocation-1",
            "provider_message_id": "010001-fake-000000",
            "email_integration_id": self.integration.id,
            "sent_at": timezone.now().isoformat(),
            "sender": {"email": "sender@example.com", "name": "Sender"},
            "to": {"email": "customer@example.com", "name": "Customer"},
            "cc": [{"email": "observer@example.net", "name": "Observer"}],
            "subject": "Hello",
            "body_plain": "Rendered body",
        }

    def post_capture(self, payload: dict | None = None, claims: dict | None = None):
        body = payload if payload is not None else self.payload
        token = CONVERSATIONS_WORKFLOW_EMAILS_PURPOSE.mint(
            claims if claims is not None else {"team_id": self.team.id, "source_id": body["source_id"]}
        )
        return self.client.post(self.url, body, content_type="application/json", HTTP_AUTHORIZATION=f"Bearer {token}")

    @patch(
        "products.conversations.backend.services.workflow_email_ingestion.posthoganalytics.feature_enabled",
        return_value=True,
    )
    def test_capture_is_visible_to_matched_account_and_retry_dedupes(self, _flag) -> None:
        first = self.post_capture()
        assert first.status_code == 200
        assert first.json() == {"status": "created"}
        retry = self.post_capture({**self.payload, "provider_message_id": "010001-other-000000"})
        assert retry.json() == {"status": "existing"}
        message = EmailThreadMessage.objects.for_team(self.team.id).get(source_type="workflow")
        assert message.source_id == "invocation-1"
        assert message.message_id == "<010001-fake-000000@email.amazonses.com>"
        assert message.direction == EmailThreadMessageDirection.OUTBOUND
        assert message.comment.content == "Rendered body"
        assert message.to_recipients == [{"email": "customer@example.com", "name": "Customer"}]
        assert message.cc_recipients == [{"email": "observer@example.net", "name": "Observer"}]
        assert (
            EmailThreadAccountLink.objects.for_team(self.team.id)
            .filter(thread=message.thread, account_id=str(self.account.id))
            .exists()
        )
        assert (
            not EmailThreadParticipant.objects.for_team(self.team.id)
            .filter(thread=message.thread, email="hidden@example.com")
            .exists()
        )
        assert (
            EmailThreadParticipant.objects.for_team(self.team.id)
            .get(thread=message.thread, email="sender@example.com")
            .kind
            == "internal"
        )
        assert EmailThreadMessage.objects.for_team(self.team.id).count() == 1

    @patch(
        "products.conversations.backend.services.workflow_email_ingestion.posthoganalytics.feature_enabled",
        return_value=True,
    )
    def test_reply_before_capture_joins_existing_thread(self, _flag) -> None:
        channel = EmailChannel.objects.create(
            team=self.team,
            kind=EmailChannelKind.CUSTOMER_COMMUNICATION,
            owner=self.user,
            inbound_token="reply-before-send",
            from_email="sender@example.com",
            domain="example.com",
        )
        rfc_id = get_ses_rfc_message_id(self.payload["provider_message_id"])
        reply = ParsedEmail(
            message_id="<reply@mail.gmail.com>",
            in_reply_to=rfc_id,
            references=(rfc_id,),
            sent_at=timezone.now() + timedelta(minutes=1),
            sender=EmailAddress(name="Customer", email="customer@example.com"),
            to_recipients=(EmailAddress(name="Sender", email="sender@example.com"),),
            cc_recipients=(),
            subject="Re: Hello",
            body_plain="Thanks",
            stripped_text="Thanks",
            sender_authenticated=True,
            dkim_passed=True,
            dkim_signing_domains=("example.com",),
            capture_address="inbox@example.com",
            attachments=(),
        )
        with self.captureOnCommitCallbacks(execute=False):
            first = ingest_customer_email(
                team_id=self.team.id, channel=channel, email=reply, direction=EmailThreadMessageDirection.INBOUND
            )
            result = self.post_capture()
        assert result.json() == {"status": "created"}
        outbound = EmailThreadMessage.objects.for_team(self.team.id).get(source_type="workflow")
        assert outbound.thread_id == first.thread_id
        assert list(
            EmailThreadMessage.objects.for_team(self.team.id)
            .filter(thread=outbound.thread)
            .values_list("id", flat=True)
        ) == [outbound.id, first.message_id]

    @patch(
        "products.conversations.backend.services.workflow_email_ingestion.posthoganalytics.feature_enabled",
        return_value=True,
    )
    def test_eligibility_only_matches_accounts_without_persisting_content(self, _flag) -> None:
        token = CONVERSATIONS_WORKFLOW_EMAILS_PURPOSE.mint(
            {"team_id": self.team.id, "source_id": self.payload["source_id"]}
        )
        response = self.client.post(
            f"{self.url}/eligible",
            {key: self.payload[key] for key in ("source_id", "email_integration_id", "sender", "to", "cc")},
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        assert response.status_code == 200
        assert response.json() == {"eligible": True}
        assert not EmailThreadMessage.objects.for_team(self.team.id).exists()

    @patch(
        "products.conversations.backend.services.workflow_email_ingestion.posthoganalytics.feature_enabled",
        return_value=True,
    )
    def test_internal_cc_does_not_link_an_unrelated_account(self, _flag) -> None:
        User.objects.create_and_join(self.organization, "coworker@example.org", None)
        Account.objects.for_team(self.team.id).create(
            team=self.team,
            name="Internal account",
            _properties={"known_emails": ["coworker@example.org"], "email_domains": []},
        )
        payload = {
            **self.payload,
            "to": {"email": "nobody@unknown.example.net"},
            "cc": [{"email": "coworker@example.org", "name": "Coworker"}],
        }
        response = self.post_capture(payload)
        assert response.json() == {"status": "skipped_unmatched"}
        assert not EmailThreadMessage.objects.for_team(self.team.id).exists()

    @patch(
        "products.conversations.backend.services.workflow_email_ingestion.posthoganalytics.feature_enabled",
        return_value=False,
    )
    def test_disabled_team_does_not_store_email(self, _flag) -> None:
        response = self.post_capture()
        assert response.json() == {"status": "skipped_disabled"}
        assert not EmailThreadMessage.objects.for_team(self.team.id).exists()

    @patch(
        "products.conversations.backend.services.workflow_email_ingestion.posthoganalytics.feature_enabled",
        return_value=True,
    )
    def test_unmatched_and_unverified_sender_do_not_store_email(self, _flag) -> None:
        unmatched = self.post_capture({**self.payload, "to": {"email": "nobody@unknown.example.net"}, "cc": []})
        assert unmatched.json() == {"status": "skipped_unmatched"}
        unverified = self.post_capture({**self.payload, "sender": {"email": "someone@other.example.net"}})
        assert unverified.status_code == 404
        assert not EmailThreadMessage.objects.for_team(self.team.id).exists()

    @patch(
        "products.conversations.backend.services.workflow_email_ingestion.posthoganalytics.feature_enabled",
        return_value=True,
    )
    def test_ambiguous_account_does_not_capture_email(self, _flag) -> None:
        Account.objects.for_team(self.team.id).create(
            team=self.team,
            name="Another example account",
            _properties={"known_emails": ["customer@example.com"], "email_domains": []},
        )
        response = self.post_capture({**self.payload, "cc": []})
        assert response.json() == {"status": "skipped_unmatched"}
        assert not EmailThreadMessage.objects.for_team(self.team.id).exists()

    def test_wrong_source_or_team_claim_is_rejected(self) -> None:
        wrong_source = self.post_capture(claims={"team_id": self.team.id, "source_id": "other-invocation"})
        wrong_team = self.post_capture(claims={"team_id": self.team.id + 1, "source_id": self.payload["source_id"]})
        assert wrong_source.status_code == 403
        assert wrong_team.status_code == 401
        assert not EmailThreadMessage.objects.for_team(self.team.id).exists()
