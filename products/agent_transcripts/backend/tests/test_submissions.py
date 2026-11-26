from datetime import timedelta
from typing import Any

import time_machine
from unittest.mock import MagicMock, patch

from django.db import IntegrityError
from django.utils import timezone

from parameterized import parameterized

from posthog.models.organization import Organization
from posthog.storage import object_storage

from products.agent_transcripts.backend.facade import api
from products.agent_transcripts.backend.facade.contracts import (
    MAX_TRANSCRIPT_SIZE_BYTES,
    TRANSCRIPT_RETENTION_DAYS,
    CompleteUploadInput,
    DuplicateMerchCode,
    InvalidSubmissionState,
    StartUploadInput,
    UploadRejected,
)
from products.agent_transcripts.backend.facade.enums import SubmissionStatus, TranscriptAgent, UploadRejectionReason
from products.agent_transcripts.backend.logic import storage
from products.agent_transcripts.backend.models import AgentTranscriptSubmission
from products.agent_transcripts.backend.tests.base import TRANSCRIPT_BYTES, TranscriptStorageTestCase, stored_bytes
from products.agent_transcripts.backend.tests.test_content import FAKE_GITHUB_TOKEN

CAPTURE_PATH = "products.agent_transcripts.backend.logic.submissions.posthoganalytics.capture"
MERCH_CODE = "HEDGEHOG-0001"


class TestUploadFlow(TranscriptStorageTestCase):
    def _complete(self) -> Any:
        return api.complete_upload(
            CompleteUploadInput(
                organization_id=self.organization.id, user_id=self.user.id, distinct_id=str(self.user.distinct_id)
            )
        )

    @patch(CAPTURE_PATH)
    def test_complete_upload_moves_the_file_and_submits(self, capture: MagicMock) -> None:
        staged = self.stage_upload()

        state = self._complete()

        submission = AgentTranscriptSubmission.objects.get(id=staged.id)
        assert state.status == SubmissionStatus.SUBMITTED
        assert submission.submitted_by_id == self.user.id
        assert submission.size_bytes == len(TRANSCRIPT_BYTES)
        assert submission.content_type == "application/jsonl"
        assert submission.staging_key is None
        assert submission.storage_key is not None
        assert submission.storage_key.startswith(f"{self.folder}/{self.organization.id}/")
        assert stored_bytes(submission.storage_key) == TRANSCRIPT_BYTES
        assert stored_bytes(staged.staging_key) is None
        capture.assert_called_once_with(
            distinct_id=str(self.user.distinct_id),
            event="agent transcript submitted",
            properties={"agent": TranscriptAgent.CLAUDE_CODE.value, "size_bytes": len(TRANSCRIPT_BYTES)},
            groups={"organization": str(self.organization.id)},
        )

    @parameterized.expand(
        [
            ("too_large", b"a" * (MAX_TRANSCRIPT_SIZE_BYTES + 1), UploadRejectionReason.TOO_LARGE),
            ("binary", b"\x89PNG\r\n\x1a\n\xff\xfe\x00\x00", UploadRejectionReason.NOT_TEXT),
            ("secret", f"token {FAKE_GITHUB_TOKEN}\n".encode(), UploadRejectionReason.CONTAINS_SECRET),
        ]
    )
    @patch(CAPTURE_PATH)
    def test_complete_upload_rejects_and_discards_the_file(
        self, _name: str, data: bytes, reason: UploadRejectionReason, capture: MagicMock
    ) -> None:
        staged = self.stage_upload(data=data)

        with self.assertRaises(UploadRejected) as raised:
            self._complete()

        submission = AgentTranscriptSubmission.objects.get(id=staged.id)
        assert raised.exception.reason == reason
        assert submission.status == SubmissionStatus.PENDING_UPLOAD
        assert submission.storage_key is None
        assert submission.staging_key is None
        assert stored_bytes(staged.staging_key) is None
        capture.assert_not_called()

    @patch(CAPTURE_PATH)
    def test_complete_upload_stores_the_bytes_it_checked(self, _capture: MagicMock) -> None:
        staged = self.stage_upload()
        read_stored_object = storage.read

        def read_then_upload_again(key: str) -> bytes | None:
            checked = read_stored_object(key)
            object_storage.write(key, f"token {FAKE_GITHUB_TOKEN}\n".encode())
            return checked

        with patch.object(storage, "read", side_effect=read_then_upload_again):
            self._complete()

        submission = AgentTranscriptSubmission.objects.get(id=staged.id)
        assert stored_bytes(submission.storage_key) == TRANSCRIPT_BYTES
        assert stored_bytes(staged.staging_key) is None

    @patch(CAPTURE_PATH)
    def test_second_complete_upload_fails_fast_while_the_first_runs(self, _capture: MagicMock) -> None:
        self.stage_upload()
        read_stored_object = storage.read
        read_keys: list[str] = []

        def read_and_complete_again(key: str) -> bytes | None:
            read_keys.append(key)
            if len(read_keys) == 1:
                with self.assertRaises(InvalidSubmissionState):
                    self._complete()
            return read_stored_object(key)

        with patch.object(storage, "read", side_effect=read_and_complete_again):
            state = self._complete()

        assert state.status == SubmissionStatus.SUBMITTED
        assert len(read_keys) == 1

    def test_new_upload_discards_the_superseded_staged_file(self) -> None:
        first = self.stage_upload()
        replacement = b'{"role": "assistant", "content": "the whole conversation"}\n'

        second = self.stage_upload(data=replacement)

        assert second.staging_key != first.staging_key
        assert stored_bytes(first.staging_key) is None
        assert stored_bytes(second.staging_key) == replacement

    def test_complete_upload_without_a_file_keeps_the_upload_open(self) -> None:
        api.start_upload(
            StartUploadInput(
                organization_id=self.organization.id,
                filename="conversation.md",
                size_bytes=len(TRANSCRIPT_BYTES),
                agent=TranscriptAgent.CURSOR,
            )
        )

        with self.assertRaises(UploadRejected) as raised:
            self._complete()

        assert raised.exception.reason == UploadRejectionReason.NOT_UPLOADED
        assert AgentTranscriptSubmission.objects.get(organization=self.organization).staging_key is not None

    @parameterized.expand(
        [
            ("too_large", "conversation.jsonl", MAX_TRANSCRIPT_SIZE_BYTES + 1, UploadRejectionReason.TOO_LARGE),
            ("wrong_extension", "conversation.pdf", len(TRANSCRIPT_BYTES), UploadRejectionReason.UNSUPPORTED_EXTENSION),
        ]
    )
    def test_start_upload_rejects_declared_file(
        self, _name: str, filename: str, size_bytes: int, reason: UploadRejectionReason
    ) -> None:
        with self.assertRaises(UploadRejected) as raised:
            api.start_upload(
                StartUploadInput(
                    organization_id=self.organization.id,
                    filename=filename,
                    size_bytes=size_bytes,
                    agent=TranscriptAgent.OTHER,
                )
            )

        assert raised.exception.reason == reason
        assert not AgentTranscriptSubmission.objects.filter(organization=self.organization).exists()

    @parameterized.expand(
        [
            (SubmissionStatus.PENDING_UPLOAD, True),
            (SubmissionStatus.CHANGES_REQUESTED, True),
            (SubmissionStatus.SUBMITTED, False),
            (SubmissionStatus.APPROVED, False),
            (SubmissionStatus.DECLINED, False),
        ]
    )
    def test_start_upload_reuses_the_one_row_per_organization(self, status: SubmissionStatus, allowed: bool) -> None:
        existing = self.create_submission(status)
        upload = StartUploadInput(
            organization_id=self.organization.id,
            filename="conversation.txt",
            size_bytes=len(TRANSCRIPT_BYTES),
            agent=TranscriptAgent.CHATGPT,
        )

        if allowed:
            presigned = api.start_upload(upload)
            assert presigned.form_fields["key"].startswith(f"{self.folder}/{self.organization.id}/staging/")
        else:
            with self.assertRaises(InvalidSubmissionState):
                api.start_upload(upload)

        assert list(AgentTranscriptSubmission.objects.filter(organization=self.organization)) == [existing]
        with self.assertRaises(IntegrityError):
            self.create_submission(SubmissionStatus.PENDING_UPLOAD)

    @patch(CAPTURE_PATH)
    def test_resubmission_after_changes_requested_replaces_the_file(self, _capture: MagicMock) -> None:
        self.stage_upload()
        self._complete()
        first = AgentTranscriptSubmission.objects.get(organization=self.organization)
        api.request_changes(
            organization_id=self.organization.id,
            reviewer_id=self.user.id,
            review_note="only the first prompt",
            review_message="Please include the whole conversation.",
        )
        replacement = b'{"role": "assistant", "content": "the whole conversation"}\n'

        self.stage_upload(data=replacement, filename="whole.jsonl")
        state = self._complete()

        second = AgentTranscriptSubmission.objects.get(organization=self.organization)
        assert second.id == first.id
        assert state.status == SubmissionStatus.SUBMITTED
        assert state.review_message is None
        assert second.original_filename == "whole.jsonl"
        assert second.storage_key is not None
        assert stored_bytes(second.storage_key) == replacement
        assert stored_bytes(first.storage_key) is None


class TestReview(TranscriptStorageTestCase):
    def _submitted(self, organization: Organization | None = None) -> AgentTranscriptSubmission:
        organization = organization or self.organization
        storage_key = f"{self.folder}/{organization.id}/upload/conversation.jsonl"
        object_storage.write(storage_key, TRANSCRIPT_BYTES)

        return self.create_submission(
            SubmissionStatus.SUBMITTED,
            organization=organization,
            storage_key=storage_key,
            submitted_at=timezone.now(),
            submitted_by=self.user,
        )

    @parameterized.expand(
        [
            ("approve", "agent transcript approved", SubmissionStatus.APPROVED, {"has_merch_code": True}),
            ("request_changes", "agent transcript changes requested", SubmissionStatus.CHANGES_REQUESTED, {}),
            ("decline", "agent transcript declined", SubmissionStatus.DECLINED, {}),
        ]
    )
    @patch(CAPTURE_PATH)
    def test_decision_records_the_review_and_captures_an_event(
        self,
        decision: str,
        event: str,
        expected_status: SubmissionStatus,
        extra_properties: dict[str, Any],
        capture: MagicMock,
    ) -> None:
        self._submitted()

        if decision == "approve":
            result = api.approve_submission(
                organization_id=self.organization.id,
                reviewer_id=self.user.id,
                review_note="good",
                merch_code=MERCH_CODE,
            )
        elif decision == "request_changes":
            result = api.request_changes(
                organization_id=self.organization.id,
                reviewer_id=self.user.id,
                review_note="partial",
                review_message="Please upload the full file.",
            )
        else:
            result = api.decline_submission(
                organization_id=self.organization.id,
                reviewer_id=self.user.id,
                review_note="not an agent",
                review_message="This isn't an agent conversation.",
            )

        assert result.status == expected_status
        assert result.reviewed_by_id == self.user.id
        assert result.reviewed_at is not None
        capture.assert_called_once_with(
            distinct_id=str(self.organization.id),
            event=event,
            properties={"agent": TranscriptAgent.CODEX.value, **extra_properties},
            groups={"organization": str(self.organization.id)},
        )

    @parameterized.expand(
        [(SubmissionStatus.PENDING_UPLOAD,), (SubmissionStatus.APPROVED,), (SubmissionStatus.DECLINED,)]
    )
    def test_decision_needs_a_submitted_transcript(self, status: SubmissionStatus) -> None:
        self.create_submission(status)

        with self.assertRaises(InvalidSubmissionState):
            api.approve_submission(organization_id=self.organization.id, reviewer_id=self.user.id, review_note=None)

        assert AgentTranscriptSubmission.objects.get(organization=self.organization).status == status

    @patch(CAPTURE_PATH)
    def test_merch_code_is_unique_but_optional(self, capture: MagicMock) -> None:
        other_organizations = [Organization.objects.create(name=f"Other {index}") for index in range(3)]
        for organization in [self.organization, *other_organizations]:
            self._submitted(organization)
        api.approve_submission(
            organization_id=self.organization.id, reviewer_id=self.user.id, review_note=None, merch_code=MERCH_CODE
        )

        with self.assertRaises(DuplicateMerchCode):
            api.approve_submission(
                organization_id=other_organizations[0].id,
                reviewer_id=self.user.id,
                review_note=None,
                merch_code=f"  {MERCH_CODE} ",
            )
        for organization in other_organizations[1:]:
            api.approve_submission(organization_id=organization.id, reviewer_id=self.user.id, review_note=None)

        assert AgentTranscriptSubmission.objects.get(organization=other_organizations[0]).status == (
            SubmissionStatus.SUBMITTED
        )
        assert list(
            AgentTranscriptSubmission.objects.filter(status=SubmissionStatus.APPROVED)
            .order_by("merch_code")
            .values_list("merch_code", flat=True)
        ) == [MERCH_CODE, None, None]
        assert capture.call_args.kwargs["properties"]["has_merch_code"] is False

    def test_download_url_until_the_file_is_gone(self) -> None:
        submission = self._submitted()

        assert api.get_transcript_download_url(self.organization.id) is not None
        with time_machine.travel(timezone.now() + timedelta(days=TRANSCRIPT_RETENTION_DAYS, hours=1), tick=False):
            assert api.get_transcript_download_url(self.organization.id) is None
            assert api.get_submission(self.organization.id).file_available is False  # type: ignore[union-attr]

        deleted = api.delete_transcript_file(self.organization.id)

        assert deleted.file_deleted_at is not None
        assert deleted.file_available is False
        assert api.get_transcript_download_url(self.organization.id) is None
        assert stored_bytes(submission.storage_key) is None

    def test_file_delete_leaves_a_replacement_upload_unmarked(self) -> None:
        submission = self._submitted()
        replacement_key = f"{self.folder}/{self.organization.id}/replacement/conversation.jsonl"
        delete_stored_object = storage.delete

        def delete_while_a_replacement_commits(key: str) -> None:
            delete_stored_object(key)
            AgentTranscriptSubmission.objects.filter(id=submission.id).update(storage_key=replacement_key)

        with patch.object(storage, "delete", side_effect=delete_while_a_replacement_commits):
            result = api.delete_transcript_file(self.organization.id)

        assert result.file_deleted_at is None
        assert AgentTranscriptSubmission.objects.get(id=submission.id).storage_key == replacement_key

    def test_list_submissions_filters_by_status(self) -> None:
        self._submitted()
        self.create_submission(SubmissionStatus.APPROVED, organization=Organization.objects.create(name="Approved"))

        page = api.list_submissions(status=SubmissionStatus.SUBMITTED, limit=10)

        assert page.count == 1
        assert [submission.organization_id for submission in page.results] == [self.organization.id]
