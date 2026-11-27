from datetime import timedelta
from email.utils import parseaddr
from typing import Any

from django.core import mail
from django.test import Client, override_settings
from django.utils import timezone

from parameterized import parameterized

from posthog.models.instance_setting import override_instance_config
from posthog.models.organization import Organization
from posthog.models.user import User
from posthog.storage import object_storage

from products.agent_transcripts.backend.console import (
    APPROVE_OPERATION,
    DECLINE_OPERATION,
    DELETE_FILE_OPERATION,
    DOWNLOAD_OPERATION,
    HOGLOG_VIEWER,
    OPEN_IN_VIEWER_OPERATION,
    PANEL_KEY,
    QUEUE_TOOL_KEY,
    REQUEST_CHANGES_OPERATION,
    AgentTranscriptPanel,
)
from products.agent_transcripts.backend.facade.contracts import TRANSCRIPT_RETENTION_DAYS
from products.agent_transcripts.backend.facade.enums import SubmissionStatus
from products.agent_transcripts.backend.models import AgentTranscriptSubmission
from products.agent_transcripts.backend.tests.base import (
    TRANSCRIPT_BYTES,
    TRANSCRIPT_FILENAME,
    TranscriptStorageTestCase,
)

SUBMITTER_EMAIL = "submitter@example.com"
MERCH_CODE = "AGENT-0001"
CUSTOMER_MESSAGE = "Upload the whole conversation, from the first prompt to the end."
INTERNAL_NOTE = "Only the last few messages were in the file."
OTHER_ORGANIZATION_NAME = "Other organization"
REVIEW_OPERATIONS = {APPROVE_OPERATION, REQUEST_CHANGES_OPERATION, DECLINE_OPERATION}
FILE_OPERATIONS = {DOWNLOAD_OPERATION, OPEN_IN_VIEWER_OPERATION, DELETE_FILE_OPERATION}

EXPIRED = "expired"
DELETED = "deleted"
AVAILABLE = "available"
RECENT_UPLOAD_AGE_DAYS = 1


class TestAgentTranscriptConsole(TranscriptStorageTestCase):
    def setUp(self) -> None:
        super().setUp()

        self.user.is_staff = True
        self.user.save()
        # The console takes HTML form posts, which APIClient would send as JSON.
        self.browser = Client()
        self.browser.force_login(self.user)
        self.submitter = User.objects.create_and_join(self.organization, SUBMITTER_EMAIL, None, first_name="Ada")
        self.enterContext(override_instance_config("EMAIL_HOST", "localhost"))

    def _submission(
        self,
        status: SubmissionStatus,
        file: str = AVAILABLE,
        organization: Organization | None = None,
        **fields: Any,
    ) -> AgentTranscriptSubmission:
        organization = organization or self.organization
        storage_key = f"{self.folder}/{organization.id}/{TRANSCRIPT_FILENAME}"
        object_storage.write(storage_key, TRANSCRIPT_BYTES)
        age_days = TRANSCRIPT_RETENTION_DAYS + 1 if file == EXPIRED else RECENT_UPLOAD_AGE_DAYS
        submitted_at = timezone.now() - timedelta(days=age_days)

        return self.create_submission(
            status,
            organization=organization,
            storage_key=storage_key,
            size_bytes=len(TRANSCRIPT_BYTES),
            submitted_by=self.submitter,
            submitted_at=submitted_at,
            file_deleted_at=timezone.now() if file == DELETED else None,
            **fields,
        )

    def _post(self, operation_key: str, data: dict[str, Any] | None = None) -> Any:
        with self.captureOnCommitCallbacks(execute=True):
            return self.browser.post(
                f"/admin/console/organizations/{self.organization.pk}/{PANEL_KEY}/{operation_key}/", data or {}
            )

    def _offered(self) -> set[str]:
        return {operation.key for operation in AgentTranscriptPanel().operations(self.organization)}

    def _status(self) -> SubmissionStatus:
        return SubmissionStatus(AgentTranscriptSubmission.objects.get(organization=self.organization).status)

    @parameterized.expand(
        [
            ("submitted_with_file", SubmissionStatus.SUBMITTED, AVAILABLE, REVIEW_OPERATIONS | FILE_OPERATIONS),
            ("submitted_file_deleted", SubmissionStatus.SUBMITTED, DELETED, REVIEW_OPERATIONS),
            ("submitted_file_expired", SubmissionStatus.SUBMITTED, EXPIRED, REVIEW_OPERATIONS),
            ("changes_requested", SubmissionStatus.CHANGES_REQUESTED, AVAILABLE, FILE_OPERATIONS),
            ("approved", SubmissionStatus.APPROVED, AVAILABLE, FILE_OPERATIONS),
            ("declined_file_deleted", SubmissionStatus.DECLINED, DELETED, set()),
        ]
    )
    def test_offers_only_the_operations_the_state_allows(
        self, _name: str, status: SubmissionStatus, file: str, expected: set[str]
    ) -> None:
        self._submission(status, file=file)

        assert self._offered() == expected

    def test_organization_without_a_submission_offers_nothing(self) -> None:
        assert self._offered() == set()

    @parameterized.expand(
        [
            (
                "approve_with_code",
                APPROVE_OPERATION,
                {"merch_code": f" {MERCH_CODE} ", "reason": INTERNAL_NOTE},
                SubmissionStatus.APPROVED,
                MERCH_CODE,
                None,
            ),
            (
                "approve_without_code",
                APPROVE_OPERATION,
                {"merch_code": "", "reason": ""},
                SubmissionStatus.APPROVED,
                None,
                None,
            ),
            (
                "request_changes",
                REQUEST_CHANGES_OPERATION,
                {"review_message": CUSTOMER_MESSAGE, "reason": INTERNAL_NOTE},
                SubmissionStatus.CHANGES_REQUESTED,
                None,
                CUSTOMER_MESSAGE,
            ),
            (
                "decline",
                DECLINE_OPERATION,
                {"review_message": CUSTOMER_MESSAGE, "reason": INTERNAL_NOTE},
                SubmissionStatus.DECLINED,
                None,
                CUSTOMER_MESSAGE,
            ),
        ]
    )
    def test_decision_records_the_review_and_emails_the_submitter_once(
        self,
        _name: str,
        operation_key: str,
        data: dict[str, str],
        expected_status: SubmissionStatus,
        expected_merch_code: str | None,
        expected_message: str | None,
    ) -> None:
        self._submission(SubmissionStatus.SUBMITTED)

        response = self._post(operation_key, data)

        assert response.status_code == 302
        submission = AgentTranscriptSubmission.objects.get(organization=self.organization)
        assert submission.status == expected_status
        assert submission.reviewed_by_id == self.user.id
        assert submission.merch_code == expected_merch_code
        assert submission.review_message == expected_message
        assert submission.review_note == (data["reason"] or None)
        assert [parseaddr(address)[1] for message in mail.outbox for address in message.to] == [SUBMITTER_EMAIL]

    def test_duplicate_merch_code_shows_a_form_error_and_changes_nothing(self) -> None:
        other_organization = Organization.objects.create(name=OTHER_ORGANIZATION_NAME)
        self._submission(SubmissionStatus.APPROVED, organization=other_organization, merch_code=MERCH_CODE)
        self._submission(SubmissionStatus.SUBMITTED)

        response = self._post(APPROVE_OPERATION, {"merch_code": MERCH_CODE, "reason": ""})

        assert response.status_code == 409
        assert "Another organization already has this code" in response.content.decode()
        submission = AgentTranscriptSubmission.objects.get(organization=self.organization)
        assert submission.status == SubmissionStatus.SUBMITTED
        assert submission.merch_code is None
        assert mail.outbox == []

    @parameterized.expand(
        [
            ("request_changes", REQUEST_CHANGES_OPERATION, {"reason": INTERNAL_NOTE}),
            ("decline", DECLINE_OPERATION, {"reason": INTERNAL_NOTE}),
            ("decline_without_internal_note", DECLINE_OPERATION, {"review_message": CUSTOMER_MESSAGE}),
        ]
    )
    def test_decision_refuses_a_missing_required_field(
        self, _name: str, operation_key: str, data: dict[str, str]
    ) -> None:
        self._submission(SubmissionStatus.SUBMITTED)

        response = self._post(operation_key, data)

        assert response.status_code == 400
        assert self._status() == SubmissionStatus.SUBMITTED
        assert mail.outbox == []

    def test_decision_on_a_reviewed_transcript_is_not_found(self) -> None:
        self._submission(SubmissionStatus.APPROVED)

        response = self._post(DECLINE_OPERATION, {"review_message": CUSTOMER_MESSAGE, "reason": INTERNAL_NOTE})

        assert response.status_code == 404
        assert self._status() == SubmissionStatus.APPROVED
        assert mail.outbox == []

    def test_download_redirects_to_a_short_lived_link_to_the_file(self) -> None:
        submission = self._submission(SubmissionStatus.SUBMITTED)

        response = self._post(DOWNLOAD_OPERATION)

        assert response.status_code == 302
        assert submission.storage_key is not None
        assert submission.storage_key in response["Location"]

    @parameterized.expand(
        [
            (operation, file)
            for operation in (DOWNLOAD_OPERATION, OPEN_IN_VIEWER_OPERATION)
            for file in (DELETED, EXPIRED)
        ]
    )
    def test_file_operations_are_unavailable_when_the_file_is_gone(self, operation: str, file: str) -> None:
        self._submission(SubmissionStatus.SUBMITTED, file=file)

        response = self._post(operation)

        assert response.status_code == 404

    def test_open_in_viewer_returns_the_file_for_the_page_to_hand_over(self) -> None:
        self._submission(SubmissionStatus.SUBMITTED)

        response = self._post(OPEN_IN_VIEWER_OPERATION)

        assert response.status_code == 200
        assert response.content == TRANSCRIPT_BYTES
        assert response["Content-Disposition"] == f'attachment; filename="{TRANSCRIPT_FILENAME}"'
        assert "no-store" in response["Cache-Control"]

    @parameterized.expand(
        [("posthog_cloud", "https://eu.posthog.com", True), ("self_hosted", "https://ph.example.com", False)]
    )
    def test_offers_the_viewer_only_on_sites_the_viewer_accepts(self, _name: str, site_url: str, offered: bool) -> None:
        self._submission(SubmissionStatus.SUBMITTED)

        with override_settings(SITE_URL=site_url):
            assert (OPEN_IN_VIEWER_OPERATION in self._offered()) is offered

    @parameterized.expand([(AVAILABLE, True, "same-origin-allow-popups"), (DELETED, False, "same-origin")])
    def test_record_page_offers_the_viewer_handoff_only_with_a_file(
        self, file: str, offered: bool, expected_policy: str
    ) -> None:
        self._submission(SubmissionStatus.SUBMITTED, file=file)

        response = self.browser.get(f"/admin/console/organizations/{self.organization.pk}/")

        assert response.status_code == 200
        assert (f'data-console-handoff="{HOGLOG_VIEWER.url}"' in response.content.decode()) is offered
        assert response["Cross-Origin-Opener-Policy"] == expected_policy

    def test_delete_file_removes_the_stored_transcript(self) -> None:
        submission = self._submission(SubmissionStatus.APPROVED)

        response = self._post(DELETE_FILE_OPERATION, {"reason": "The customer asked us to delete it."})

        assert response.status_code == 302
        submission.refresh_from_db()
        assert submission.file_deleted_at is not None
        assert submission.storage_key is not None
        assert object_storage.read_bytes(submission.storage_key, missing_ok=True) is None
        assert self._offered() == set()

    @parameterized.expand(
        [
            ("defaults_to_submitted", "", {"Submitted organization"}),
            ("any_status", "?status=any", {"Submitted organization", "Approved organization"}),
            ("approved", "?status=approved", {"Approved organization"}),
        ]
    )
    def test_queue_filters_by_status(self, _name: str, query: str, expected_names: set[str]) -> None:
        organizations = {
            SubmissionStatus.SUBMITTED: Organization.objects.create(name="Submitted organization"),
            SubmissionStatus.APPROVED: Organization.objects.create(name="Approved organization"),
        }
        for status, organization in organizations.items():
            self._submission(status, organization=organization)

        response = self.browser.get(f"/admin/console/tools/{QUEUE_TOOL_KEY}/{query}")

        assert response.status_code == 200
        content = response.content.decode()
        shown = {organization.name for organization in organizations.values() if organization.name in content}
        assert shown == expected_names
        for organization in organizations.values():
            if organization.name in expected_names:
                assert f"/admin/console/organizations/{organization.id}/" in content
