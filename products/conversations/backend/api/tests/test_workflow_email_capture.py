from datetime import timedelta
from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.apps import apps
from django.test import SimpleTestCase
from django.utils import timezone

from parameterized import parameterized
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
from products.customer_analytics.backend.facade.email_matching import recalculate_email_thread_links


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


class TestWorkflowEmailCapture(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.client = APIClient()
        flag = patch(
            "products.conversations.backend.services.workflow_email_ingestion.posthoganalytics.feature_enabled",
            return_value=True,
        )
        self.capture_enabled = flag.start()
        self.addCleanup(flag.stop)
        self.integration = Integration.objects.create(
            team=self.team,
            kind=Integration.IntegrationKind.EMAIL,
            config={"verified": True, "email": "sender@example.com", "domain": "example.com"},
        )
        self.account = self.create_account(known_emails=["customer@example.com"])
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

    def create_account(self, *, known_emails: list[str]) -> Any:
        return (
            apps.get_model("customer_analytics", "Account")
            .objects.for_team(self.team.id)
            .create(team=self.team, name="Example account", _properties={"known_emails": known_emails})
        )

    def post_capture(self, payload: dict | None = None, claims: dict | None = None):
        body = payload if payload is not None else self.payload
        token = CONVERSATIONS_WORKFLOW_EMAILS_PURPOSE.mint(
            claims if claims is not None else {"team_id": self.team.id, "source_id": body["source_id"]}
        )
        return self.client.post(self.url, body, content_type="application/json", HTTP_AUTHORIZATION=f"Bearer {token}")

    @patch("products.customer_analytics.backend.facade.email_matching.current_app.send_task")
    @patch("products.customer_analytics.backend.logic.email_account_matching._match_accounts_by_person_group")
    def test_matched_capture_links_account_without_person_groups_or_recalculation(
        self, person_group_lookup, send_task
    ) -> None:
        person_group_lookup.side_effect = AssertionError("Workflow emails must not look up person groups")
        with self.captureOnCommitCallbacks(execute=True):
            first = self.post_capture()
        retry = self.post_capture({**self.payload, "provider_message_id": "010001-other-000000"})

        assert (first.json(), retry.json()) == ({"status": "created"}, {"status": "existing"})
        send_task.assert_not_called()
        message = EmailThreadMessage.objects.for_team(self.team.id).get(source_type="workflow")
        assert message.message_id == "<010001-fake-000000@email.amazonses.com>"
        assert message.direction == EmailThreadMessageDirection.OUTBOUND
        assert message.comment.content == "Rendered body"
        assert message.cc_recipients == [{"email": "observer@example.net", "name": "Observer"}]
        assert (
            EmailThreadParticipant.objects.for_team(self.team.id)
            .get(thread=message.thread, email="sender@example.com")
            .kind
            == "internal"
        )

        assert recalculate_email_thread_links(self.team.id, thread_ids=[str(message.thread_id)]) == 1
        person_group_lookup.assert_not_called()
        assert list(
            EmailThreadAccountLink.objects.for_team(self.team.id)
            .filter(thread=message.thread)
            .values_list("account_id", flat=True)
        ) == [str(self.account.id)]

    def test_reply_before_capture_joins_thread_and_restores_person_group_matching(self) -> None:
        channel = EmailChannel.objects.create(
            team=self.team,
            kind=EmailChannelKind.CUSTOMER_COMMUNICATION,
            owner=self.user,
            inbound_token="reply-before-send",
            from_email="sender@example.com",
            domain="example.com",
        )
        rfc_id = get_ses_rfc_message_id(str(self.payload["provider_message_id"]))
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
        with patch(
            "products.customer_analytics.backend.logic.email_account_matching._match_accounts_by_person_group",
            return_value=({}, set()),
        ) as person_group_lookup:
            recalculate_email_thread_links(self.team.id, thread_ids=[str(outbound.thread_id)])
        person_group_lookup.assert_called_once()

    @parameterized.expand(
        [
            ("capture_disabled", {}, False, 200, {"status": "skipped_disabled"}),
            (
                "no_account_match",
                {"to": {"email": "nobody@unknown.example.net"}, "cc": []},
                True,
                200,
                {"status": "skipped_unmatched"},
            ),
            ("unverified_sender", {"sender": {"email": "someone@other.example.net"}}, True, 404, None),
            ("wrong_source_claim", {}, True, 403, None),
            ("wrong_team_claim", {}, True, 401, None),
        ]
    )
    def test_rejected_capture_does_not_store_email(
        self, name: str, overrides: dict, enabled: bool, status_code: int, body: dict | None
    ) -> None:
        self.capture_enabled.return_value = enabled
        claims = {
            "wrong_source_claim": {"team_id": self.team.id, "source_id": "other-invocation"},
            "wrong_team_claim": {"team_id": self.team.id + 1, "source_id": self.payload["source_id"]},
        }.get(name)

        response = self.post_capture({**self.payload, **overrides}, claims=claims)

        assert response.status_code == status_code
        if body is not None:
            assert response.json() == body
        assert not EmailThreadMessage.objects.for_team(self.team.id).exists()

    def test_internal_cc_does_not_link_an_unrelated_account(self) -> None:
        User.objects.create_and_join(self.organization, "coworker@example.org", None)
        self.create_account(known_emails=["coworker@example.org"])

        response = self.post_capture(
            {
                **self.payload,
                "to": {"email": "nobody@unknown.example.net"},
                "cc": [{"email": "coworker@example.org", "name": "Coworker"}],
            }
        )

        assert response.json() == {"status": "skipped_unmatched"}
        assert not EmailThreadMessage.objects.for_team(self.team.id).exists()
