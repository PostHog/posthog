"""
Facade for agent_transcripts.

The only module other products and core may import. Accepts and returns the frozen
dataclasses in contracts.py, and raises the errors defined there.
"""

from __future__ import annotations

from uuid import UUID

from django.utils import timezone

from posthog.paging import Page, PageRequest

from ..logic import review, submissions, transitions
from ..models import AgentTranscriptSubmission as SubmissionModel
from .contracts import (
    ALLOWED_TRANSCRIPT_EXTENSIONS,
    MAX_TRANSCRIPT_SIZE_BYTES,
    TRANSCRIPT_RETENTION_DAYS,
    AgentTranscriptSubmission,
    CompleteUploadInput,
    CustomerSubmissionState,
    PresignedUpload,
    StartUploadInput,
    SubmissionForReview,
    TranscriptFile,
)
from .enums import SubmissionStatus, TranscriptAgent


def _to_submission(submission: SubmissionModel) -> AgentTranscriptSubmission:
    return AgentTranscriptSubmission(
        id=submission.id,
        organization_id=submission.organization_id,
        status=SubmissionStatus(submission.status),
        agent=TranscriptAgent(submission.agent),
        original_filename=submission.original_filename,
        size_bytes=submission.size_bytes,
        content_type=submission.content_type,
        submitted_by_id=submission.submitted_by_id,
        submitted_at=submission.submitted_at,
        reviewed_by_id=submission.reviewed_by_id,
        reviewed_at=submission.reviewed_at,
        review_note=submission.review_note,
        review_message=submission.review_message,
        merch_code=submission.merch_code,
        file_deleted_at=submission.file_deleted_at,
        file_available=transitions.is_file_available(
            storage_key=submission.storage_key,
            file_deleted_at=submission.file_deleted_at,
            submitted_at=submission.submitted_at,
            now=timezone.now(),
        ),
        file_expires_at=transitions.file_expires_at(submission.submitted_at),
        created_at=submission.created_at,
        updated_at=submission.updated_at,
    )


def _to_customer_state(submission: SubmissionModel | None) -> CustomerSubmissionState:
    return CustomerSubmissionState(
        status=SubmissionStatus(submission.status) if submission is not None else None,
        agent=TranscriptAgent(submission.agent) if submission is not None else None,
        original_filename=submission.original_filename if submission is not None else None,
        submitted_at=submission.submitted_at if submission is not None else None,
        review_message=submission.review_message if submission is not None else None,
        retention_days=TRANSCRIPT_RETENTION_DAYS,
        max_size_bytes=MAX_TRANSCRIPT_SIZE_BYTES,
        allowed_extensions=list(ALLOWED_TRANSCRIPT_EXTENSIONS),
    )


def get_customer_state(organization_id: UUID) -> CustomerSubmissionState:
    """The organization's submission as its members see it, with no staff-only field."""
    return _to_customer_state(submissions.get_for_organization(organization_id))


def start_upload(data: StartUploadInput) -> PresignedUpload:
    """
    Reserve an upload and return a presigned POST for the file. Creates the organization's row on
    the first call. Allowed when there is no submission yet, or its status is `pending_upload` or
    `changes_requested`.

    Raises UploadRejected for a wrong extension or size, InvalidSubmissionState for any other
    status, and TranscriptStorageUnavailable when no upload URL can be made.
    """
    return submissions.start_upload(data)


def complete_upload(data: CompleteUploadInput) -> CustomerSubmissionState:
    """
    Validate the uploaded bytes, move them to permanent storage and mark the submission `submitted`.
    A rejected upload is deleted, and the caller starts a new one.

    Raises SubmissionNotFound, InvalidSubmissionState when no upload is pending, UploadRejected
    when the file fails a check, and TranscriptStorageUnavailable when storage cannot be read.
    """
    return _to_customer_state(submissions.complete_upload(data))


def list_submissions(
    *, status: SubmissionStatus | None = None, limit: int, offset: int = 0
) -> Page[AgentTranscriptSubmission]:
    """Submissions of every organization for staff review, newest first."""
    page = submissions.list_submissions(status=status, page=PageRequest(limit=limit, offset=offset))
    return page.map(_to_submission)


def get_submission(organization_id: UUID) -> AgentTranscriptSubmission | None:
    submission = submissions.get_for_organization(organization_id)
    return _to_submission(submission) if submission is not None else None


def _for_review(models: list[SubmissionModel]) -> list[SubmissionForReview]:
    organization_names = review.organization_names([model.organization_id for model in models])
    submitters = review.submitters([model.submitted_by_id for model in models if model.submitted_by_id is not None])

    return [
        SubmissionForReview(
            submission=_to_submission(model),
            organization_name=organization_names.get(model.organization_id, ""),
            submitter=submitters.get(model.submitted_by_id) if model.submitted_by_id is not None else None,
        )
        for model in models
    ]


def list_submissions_for_review(
    *, status: SubmissionStatus | None = None, limit: int, offset: int = 0
) -> Page[SubmissionForReview]:
    """Submissions of every organization for the staff queue, newest first, with the organization and submitter."""
    page = submissions.list_submissions(status=status, page=PageRequest(limit=limit, offset=offset))
    return Page(results=_for_review(page.results), count=page.count)


def get_submission_for_review(organization_id: UUID) -> SubmissionForReview | None:
    submission = submissions.get_for_organization(organization_id)
    return _for_review([submission])[0] if submission is not None else None


def get_transcript_download_url(organization_id: UUID) -> str | None:
    """A presigned GET that expires after a minute, or None when there is no stored file."""
    return submissions.get_download_url(organization_id)


def get_transcript_file(organization_id: UUID) -> TranscriptFile | None:
    """The stored file, or None when there is none. Raises TranscriptStorageUnavailable when storage fails."""
    return submissions.read_file(organization_id)


def approve_submission(
    *, organization_id: UUID, reviewer_id: int, review_note: str | None, merch_code: str | None = None
) -> AgentTranscriptSubmission:
    """
    Approve a `submitted` transcript. `merch_code` is optional, because some organizations get no reward.
    Emails the submitter once the decision commits.

    Raises SubmissionNotFound, InvalidSubmissionState, and DuplicateMerchCode when another
    organization already holds the code.
    """
    return _to_submission(
        submissions.approve(
            organization_id=organization_id, reviewer_id=reviewer_id, review_note=review_note, merch_code=merch_code
        )
    )


def request_changes(
    *, organization_id: UUID, reviewer_id: int, review_note: str | None, review_message: str | None
) -> AgentTranscriptSubmission:
    """
    Send a `submitted` transcript back to the customer, who sees `review_message` and can upload again.
    Emails the submitter once the decision commits.

    Raises SubmissionNotFound and InvalidSubmissionState.
    """
    return _to_submission(
        submissions.request_changes(
            organization_id=organization_id,
            reviewer_id=reviewer_id,
            review_note=review_note,
            review_message=review_message,
        )
    )


def decline_submission(
    *, organization_id: UUID, reviewer_id: int, review_note: str | None, review_message: str | None
) -> AgentTranscriptSubmission:
    """
    Decline a `submitted` transcript. The decision is final, and the customer sees `review_message`.
    Emails the submitter once the decision commits.

    Raises SubmissionNotFound and InvalidSubmissionState.
    """
    return _to_submission(
        submissions.decline(
            organization_id=organization_id,
            reviewer_id=reviewer_id,
            review_note=review_note,
            review_message=review_message,
        )
    )


def delete_transcript_file(organization_id: UUID) -> AgentTranscriptSubmission:
    """
    Delete the stored transcript and record when. A no-op when the file is already gone.

    Raises SubmissionNotFound, and TranscriptStorageUnavailable when the delete fails.
    """
    return _to_submission(submissions.delete_transcript_file(organization_id))
