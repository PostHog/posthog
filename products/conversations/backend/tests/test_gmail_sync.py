import base64

import pytest
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.constants import AvailableFeature
from posthog.egress.google_workspace.transport import GoogleWorkspaceEgressBudgetExhausted
from posthog.models.integration import Integration
from posthog.models.organization import OrganizationMembership

from products.access_control.backend.models.access_control import AccessControl
from products.conversations.backend.models import (
    EmailThread,
    EmailThreadAccountLink,
    EmailThreadMessage,
    EmailThreadMessageDirection,
)
from products.conversations.backend.services import gmail_sync
from products.customer_analytics.backend.facade.email_matching import recalculate_email_thread_links
from products.customer_analytics.backend.models import Account


def _response(payload: dict, status_code: int = 200) -> MagicMock:
    response = MagicMock(status_code=status_code)
    response.json.return_value = payload
    response.text = ""
    return response


def _gmail_message(*, label: str, sender: str, recipient: str, message_id: str = "gmail-1") -> dict:
    body = base64.urlsafe_b64encode(b"Customer message body").decode().rstrip("=")
    return {
        "id": message_id,
        "threadId": "thread-1",
        "historyId": "101",
        "internalDate": "1785855600000",
        "labelIds": [label],
        "payload": {
            "mimeType": "text/plain",
            "headers": [
                {"name": "Message-ID", "value": f"<{message_id}@example.com>"},
                {"name": "From", "value": sender},
                {"name": "To", "value": recipient},
                {"name": "Subject", "value": "Account follow-up"},
            ],
            "body": {"data": body},
        },
    }


class TestGmailSync(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.integration = Integration.objects.create(
            team=self.team,
            kind="google-calendar",
            integration_id="google-sub-1",
            created_by=self.user,
            config={
                "email": self.user.email,
                "scope": f"https://www.googleapis.com/auth/calendar.readonly {gmail_sync.GMAIL_READONLY_SCOPE}",
                "refreshed_at": 9_999_999_999,
                "expires_in": 3600,
            },
            sensitive_config={"access_token": "ACCESS", "refresh_token": "REFRESH"},
        )

    @parameterized.expand(
        [
            ("inbox", "INBOX", "customer@example.com", "test@posthog.com", EmailThreadMessageDirection.INBOUND),
            ("sent", "SENT", "test@posthog.com", "customer@example.com", EmailThreadMessageDirection.OUTBOUND),
        ]
    )
    def test_google_connection_imports_account_email(
        self,
        _name: str,
        label: str,
        sender: str,
        recipient: str,
        expected_direction: EmailThreadMessageDirection,
    ) -> None:
        self.user.email = "test@posthog.com"
        self.user.save(update_fields=["email"])
        self.integration.config["email"] = self.user.email
        self.integration.save(update_fields=["config"])
        account = Account.objects.for_team(self.team.id).create(team=self.team, name="Example", external_id="example")
        account.properties = {"email_domains": ["example.com"]}
        account.save()

        with patch.object(
            gmail_sync,
            "google_workspace_request",
            side_effect=[
                _response({"emailAddress": self.user.email, "historyId": "100"}),
                _response({"messages": [{"id": "gmail-1"}]}),
                _response(_gmail_message(label=label, sender=sender, recipient=recipient)),
            ],
        ):
            gmail_sync.sync_gmail_integration(self.integration.id, self.team.id)

        recalculate_email_thread_links(self.team.id)

        message = EmailThreadMessage.objects.for_team(self.team.id).select_related("comment").get()
        assert message.direction == expected_direction
        assert message.source_type == "gmail"
        assert message.comment.content == "Customer message body"
        assert EmailThreadAccountLink.objects.for_team(self.team.id).get().account_id == str(account.id)
        self.integration.refresh_from_db()
        assert self.integration.config[gmail_sync.GMAIL_HISTORY_ID_CONFIG_KEY] == "100"

    def test_attachment_backed_body_is_imported(self) -> None:
        message = _gmail_message(label="INBOX", sender="customer@example.com", recipient=self.user.email)
        message["payload"]["body"] = {"attachmentId": "body-attachment"}
        attachment_body = base64.urlsafe_b64encode(b"Attachment-backed message body").decode().rstrip("=")

        with patch.object(
            gmail_sync,
            "google_workspace_request",
            side_effect=[
                _response({"emailAddress": self.user.email, "historyId": "100"}),
                _response({"messages": [{"id": "gmail-1"}]}),
                _response(message),
                _response({"data": attachment_body}),
            ],
        ):
            gmail_sync.sync_gmail_integration(self.integration.id, self.team.id)

        imported = EmailThreadMessage.objects.for_team(self.team.id).select_related("comment").get()
        assert imported.comment.content == "Attachment-backed message body"

    def test_message_with_too_many_attachment_backed_bodies_is_skipped(self) -> None:
        message = _gmail_message(label="INBOX", sender="customer@example.com", recipient=self.user.email)
        message["payload"]["mimeType"] = "multipart/alternative"
        message["payload"]["body"] = {}
        message["payload"]["parts"] = [
            {"mimeType": "text/plain", "body": {"attachmentId": f"body-{index}"}}
            for index in range(gmail_sync.MAX_ATTACHMENT_BACKED_BODY_PARTS + 1)
        ]
        attachment_body = base64.urlsafe_b64encode(b"Body part").decode().rstrip("=")

        with patch.object(
            gmail_sync,
            "google_workspace_request",
            side_effect=[
                _response({"emailAddress": self.user.email, "historyId": "100"}),
                _response({"messages": [{"id": "gmail-1"}]}),
                _response(message),
                *[_response({"data": attachment_body}) for _ in range(gmail_sync.MAX_ATTACHMENT_BACKED_BODY_PARTS)],
            ],
        ) as mock_request:
            gmail_sync.sync_gmail_integration(self.integration.id, self.team.id)

        assert mock_request.call_count == 3 + gmail_sync.MAX_ATTACHMENT_BACKED_BODY_PARTS
        assert not EmailThread.objects.for_team(self.team.id).exists()
        self.integration.refresh_from_db()
        assert self.integration.config[gmail_sync.GMAIL_HISTORY_ID_CONFIG_KEY] == "100"

    def test_incremental_sync_checkpoints_each_imported_message(self) -> None:
        self.integration.config[gmail_sync.GMAIL_HISTORY_ID_CONFIG_KEY] = "100"
        self.integration.save(update_fields=["config"])
        history = {
            "history": [
                {
                    "id": "101",
                    "messagesAdded": [
                        {"message": {"id": "gmail-1"}},
                        {"message": {"id": "gmail-2"}},
                    ],
                }
            ],
            "historyId": "101",
        }
        first_message = _gmail_message(
            label="INBOX", sender="first@example.com", recipient=self.user.email, message_id="gmail-1"
        )
        second_message = _gmail_message(
            label="INBOX", sender="second@example.com", recipient=self.user.email, message_id="gmail-2"
        )

        with (
            patch.object(
                gmail_sync,
                "google_workspace_request",
                side_effect=[
                    _response(history),
                    _response(first_message),
                    GoogleWorkspaceEgressBudgetExhausted("budget exhausted"),
                ],
            ),
            pytest.raises(GoogleWorkspaceEgressBudgetExhausted),
        ):
            gmail_sync.sync_gmail_integration(self.integration.id, self.team.id)

        self.integration.refresh_from_db()
        assert self.integration.config[gmail_sync.GMAIL_PENDING_MESSAGE_IDS_CONFIG_KEY] == ["gmail-2"]
        assert EmailThreadMessage.objects.for_team(self.team.id).count() == 1

        with patch.object(gmail_sync, "google_workspace_request", return_value=_response(second_message)):
            gmail_sync.sync_gmail_integration(self.integration.id, self.team.id)

        self.integration.refresh_from_db()
        assert self.integration.config[gmail_sync.GMAIL_HISTORY_ID_CONFIG_KEY] == "101"
        assert gmail_sync.GMAIL_PENDING_MESSAGE_IDS_CONFIG_KEY not in self.integration.config
        assert EmailThreadMessage.objects.for_team(self.team.id).count() == 2

    def test_deleted_message_is_skipped_and_cursor_advances(self) -> None:
        self.integration.config[gmail_sync.GMAIL_HISTORY_ID_CONFIG_KEY] = "100"
        self.integration.save(update_fields=["config"])
        history = {
            "history": [
                {
                    "id": "101",
                    "messagesAdded": [
                        {"message": {"id": "deleted-1"}},
                        {"message": {"id": "gmail-2"}},
                    ],
                }
            ],
            "historyId": "101",
        }
        second_message = _gmail_message(
            label="INBOX", sender="second@example.com", recipient=self.user.email, message_id="gmail-2"
        )

        with patch.object(
            gmail_sync,
            "google_workspace_request",
            side_effect=[
                _response(history),
                _response({"error": {"message": "Requested entity was not found."}}, status_code=404),
                _response(second_message),
            ],
        ):
            gmail_sync.sync_gmail_integration(self.integration.id, self.team.id)

        self.integration.refresh_from_db()
        assert self.integration.config[gmail_sync.GMAIL_HISTORY_ID_CONFIG_KEY] == "101"
        assert gmail_sync.GMAIL_PENDING_MESSAGE_IDS_CONFIG_KEY not in self.integration.config
        message = EmailThreadMessage.objects.for_team(self.team.id).select_related("comment").get()
        assert message.comment.content == "Customer message body"

    def test_deleted_attachment_is_skipped(self) -> None:
        message = _gmail_message(label="INBOX", sender="customer@example.com", recipient=self.user.email)
        message["payload"]["body"] = {"attachmentId": "body-attachment"}

        with patch.object(
            gmail_sync,
            "google_workspace_request",
            side_effect=[
                _response({"emailAddress": self.user.email, "historyId": "100"}),
                _response({"messages": [{"id": "gmail-1"}]}),
                _response(message),
                _response({"error": {"message": "Requested entity was not found."}}, status_code=404),
            ],
        ):
            gmail_sync.sync_gmail_integration(self.integration.id, self.team.id)

        imported = EmailThreadMessage.objects.for_team(self.team.id).select_related("comment").get()
        assert imported.comment.content == ""
        self.integration.refresh_from_db()
        assert self.integration.config[gmail_sync.GMAIL_HISTORY_ID_CONFIG_KEY] == "100"

    def test_incremental_sync_is_idempotent(self) -> None:
        self.integration.config[gmail_sync.GMAIL_HISTORY_ID_CONFIG_KEY] = "100"
        self.integration.save(update_fields=["config"])
        history = {
            "history": [
                {
                    "id": "101",
                    "messagesAdded": [
                        {"message": {"id": "gmail-1"}},
                        {"message": {"id": "gmail-1"}},
                    ],
                }
            ],
            "historyId": "101",
        }
        responses = [
            _response(history),
            _response(_gmail_message(label="INBOX", sender="customer@example.com", recipient=self.user.email)),
            _response(history),
            _response(_gmail_message(label="INBOX", sender="customer@example.com", recipient=self.user.email)),
        ]

        with patch.object(gmail_sync, "google_workspace_request", side_effect=responses):
            gmail_sync.sync_gmail_integration(self.integration.id, self.team.id)
            gmail_sync.sync_gmail_integration(self.integration.id, self.team.id)

        assert EmailThread.objects.for_team(self.team.id).count() == 1
        assert EmailThreadMessage.objects.for_team(self.team.id).count() == 1

    def test_existing_calendar_only_connection_does_not_call_gmail(self) -> None:
        self.integration.config["scope"] = "https://www.googleapis.com/auth/calendar.readonly"
        self.integration.save(update_fields=["config"])

        with patch.object(gmail_sync, "google_workspace_request") as mock_request:
            gmail_sync.sync_gmail_integration(self.integration.id, self.team.id)

        mock_request.assert_not_called()
        assert not EmailThread.objects.for_team(self.team.id).exists()

    def test_removed_organization_member_is_not_synced(self) -> None:
        OrganizationMembership.objects.filter(
            organization=self.team.organization,
            user=self.user,
        ).delete()

        with patch.object(gmail_sync, "google_workspace_request") as mock_request:
            gmail_sync.sync_gmail_integration(self.integration.id, self.team.id)

        mock_request.assert_not_called()
        assert not EmailThread.objects.for_team(self.team.id).exists()

    def test_owner_without_project_access_is_not_synced(self) -> None:
        self.team.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": "Access control"}
        ]
        self.team.organization.save(update_fields=["available_product_features"])
        OrganizationMembership.objects.filter(
            organization=self.team.organization,
            user=self.user,
        ).update(level=OrganizationMembership.Level.MEMBER)
        AccessControl.objects.create(
            team=self.team,
            resource="project",
            resource_id=str(self.team.id),
            access_level="none",
        )

        with patch.object(gmail_sync, "google_workspace_request") as mock_request:
            gmail_sync.sync_gmail_integration(self.integration.id, self.team.id)

        mock_request.assert_not_called()
        assert not EmailThread.objects.for_team(self.team.id).exists()

    def test_internal_only_email_is_not_stored(self) -> None:
        with patch.object(
            gmail_sync,
            "google_workspace_request",
            side_effect=[
                _response({"emailAddress": self.user.email, "historyId": "100"}),
                _response({"messages": [{"id": "gmail-1"}]}),
                _response(_gmail_message(label="INBOX", sender=self.user.email, recipient=self.user.email)),
            ],
        ):
            gmail_sync.sync_gmail_integration(self.integration.id, self.team.id)

        assert not EmailThread.objects.for_team(self.team.id).exists()
