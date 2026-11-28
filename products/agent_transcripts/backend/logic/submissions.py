"""Reads and writes of transcript submissions, and the analytics events they emit."""

from typing import Any
from uuid import UUID

from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.utils import timezone

import posthoganalytics

from posthog.paging import Page, PageRequest
from posthog.queryset_paging import select_page

from ..facade.contracts import (
    CompleteUploadInput,
    DuplicateMerchCode,
    InvalidSubmissionState,
    PresignedUpload,
    StartUploadInput,
    SubmissionNotFound,
    TranscriptFile,
    UploadRejected,
)
from ..facade.enums import SubmissionAction, SubmissionStatus, UploadRejectionReason
from ..models import AgentTranscriptSubmission
from . import content, emails, storage, transitions

SUBMITTED_EVENT = "agent transcript submitted"
APPROVED_EVENT = "agent transcript approved"
CHANGES_REQUESTED_EVENT = "agent transcript changes requested"
DECLINED_EVENT = "agent transcript declined"

COMPLETE_UPLOAD_CLAIM_KEY_PREFIX = "agent_transcripts:complete_upload:"
# Long enough to download and scan the largest allowed file. A call that dies without releasing the
# claim blocks that upload only until this expires.
COMPLETE_UPLOAD_CLAIM_SECONDS = 5 * 60


def get_for_organization(organization_id: UUID) -> AgentTranscriptSubmission | None:
    return AgentTranscriptSubmission.objects.filter(organization_id=organization_id).first()


def list_submissions(*, status: SubmissionStatus | None, page: PageRequest) -> Page[AgentTranscriptSubmission]:
    queryset = AgentTranscriptSubmission.objects.order_by("-created_at")
    if status is not None:
        queryset = queryset.filter(status=status)

    return select_page(queryset, page)


def _with_available_file(organization_id: UUID) -> tuple[AgentTranscriptSubmission, str] | None:
    """The submission and its storage key, or None when it has no file staff may still read."""
    submission = get_for_organization(organization_id)
    if submission is None or submission.storage_key is None:
        return None

    file_available = transitions.is_file_available(
        storage_key=submission.storage_key,
        file_deleted_at=submission.file_deleted_at,
        submitted_at=submission.submitted_at,
        now=timezone.now(),
    )
    return (submission, submission.storage_key) if file_available else None


def get_download_url(organization_id: UUID) -> str | None:
    found = _with_available_file(organization_id)
    if found is None:
        return None

    submission, storage_key = found
    return storage.presign_download(storage_key, submission.original_filename)


def read_file(organization_id: UUID) -> TranscriptFile | None:
    found = _with_available_file(organization_id)
    if found is None:
        return None

    submission, storage_key = found
    data = storage.read(storage_key)
    if data is None:
        return None

    return TranscriptFile(
        filename=content.storage_filename(submission.original_filename),
        content_type=content.content_type_for(submission.original_filename),
        content=data,
    )


def start_upload(data: StartUploadInput) -> PresignedUpload:
    filename = content.display_filename(data.filename)
    content.check_extension(filename)
    content.check_size(data.size_bytes)

    staging_key = storage.build_staging_key(data.organization_id)
    presigned_upload = storage.presign_upload(staging_key)

    superseded_staging_key: str | None = None
    with transaction.atomic():
        submission, created = AgentTranscriptSubmission.objects.select_for_update().get_or_create(
            organization_id=data.organization_id,
            defaults={
                "status": SubmissionStatus.PENDING_UPLOAD,
                "agent": data.agent,
                "original_filename": filename,
                "staging_key": staging_key,
            },
        )
        if not created:
            status = SubmissionStatus(submission.status)
            if not transitions.is_allowed(status, SubmissionAction.START_UPLOAD):
                raise InvalidSubmissionState(status, SubmissionAction.START_UPLOAD)

            superseded_staging_key = submission.staging_key
            submission.status = SubmissionStatus.PENDING_UPLOAD
            submission.agent = data.agent
            submission.original_filename = filename
            submission.staging_key = staging_key
            submission.save(update_fields=["status", "agent", "original_filename", "staging_key", "updated_at"])

    if superseded_staging_key is not None:
        storage.delete_quietly(superseded_staging_key)

    return presigned_upload


def complete_upload(data: CompleteUploadInput) -> AgentTranscriptSubmission:
    submission = get_for_organization(data.organization_id)
    if submission is None:
        raise SubmissionNotFound(f"No transcript submission for organization {data.organization_id}")

    status = SubmissionStatus(submission.status)
    staging_key = submission.staging_key
    if not transitions.is_allowed(status, SubmissionAction.COMPLETE_UPLOAD) or staging_key is None:
        raise InvalidSubmissionState(status, SubmissionAction.COMPLETE_UPLOAD)

    # Each call downloads and scans the whole file, so a second call for the same upload fails fast
    # instead of repeating that work while the first one runs.
    claim_key = f"{COMPLETE_UPLOAD_CLAIM_KEY_PREFIX}{staging_key}"
    if not cache.add(claim_key, True, timeout=COMPLETE_UPLOAD_CLAIM_SECONDS):
        raise InvalidSubmissionState(status, SubmissionAction.COMPLETE_UPLOAD)

    try:
        return _promote_staged_upload(data, submission, staging_key)
    finally:
        cache.delete(claim_key)


def _promote_staged_upload(
    data: CompleteUploadInput, submission: AgentTranscriptSubmission, staging_key: str
) -> AgentTranscriptSubmission:
    # Check the stored size before downloading, so an oversize object is never read into memory.
    size_bytes = storage.object_size(staging_key)
    if size_bytes is None:
        raise UploadRejected(UploadRejectionReason.NOT_UPLOADED)

    try:
        content.check_size(size_bytes)
        transcript = storage.read(staging_key)
        if transcript is None:
            raise UploadRejected(UploadRejectionReason.NOT_UPLOADED)
        content.check_content(filename=submission.original_filename, content=transcript)
    except UploadRejected as rejection:
        if rejection.reason != UploadRejectionReason.NOT_UPLOADED:
            _discard_staged_upload(submission.organization_id, staging_key)
        raise

    # The upload form for the staging key stays valid until it expires, so the object there can change
    # after the read above. Writing the bytes that passed the checks keeps unchecked bytes out of review.
    content_type = content.content_type_for(submission.original_filename)
    storage_key = storage.build_storage_key(data.organization_id, submission.original_filename)
    storage.write(storage_key, transcript, content_type)

    previous_storage_key: str | None = None
    with transaction.atomic():
        submission = AgentTranscriptSubmission.objects.select_for_update().get(id=submission.id)
        # A start_upload after the read above points the row at a newer staging key. That upload
        # completes on its own call, so this call drops its copy.
        superseded = submission.staging_key != staging_key or submission.status != SubmissionStatus.PENDING_UPLOAD
        if not superseded:
            previous_storage_key = submission.storage_key
            submission.status = SubmissionStatus.SUBMITTED
            submission.storage_key = storage_key
            submission.staging_key = None
            submission.size_bytes = len(transcript)
            submission.content_type = content_type
            submission.submitted_by_id = data.user_id
            submission.submitted_at = timezone.now()
            submission.review_message = None
            submission.file_deleted_at = None
            submission.save()

    if superseded:
        storage.delete_quietly(storage_key)
        raise InvalidSubmissionState(SubmissionStatus(submission.status), SubmissionAction.COMPLETE_UPLOAD)

    storage.delete_quietly(staging_key)
    if previous_storage_key is not None:
        storage.delete_quietly(previous_storage_key)

    _capture(
        SUBMITTED_EVENT,
        organization_id=data.organization_id,
        distinct_id=data.distinct_id,
        properties={"agent": submission.agent, "size_bytes": submission.size_bytes},
    )
    return submission


def approve(
    *, organization_id: UUID, reviewer_id: int, review_note: str | None, merch_code: str | None
) -> AgentTranscriptSubmission:
    normalized_merch_code = _blank_to_none(merch_code)
    submission = _record_decision(
        organization_id=organization_id,
        reviewer_id=reviewer_id,
        status=SubmissionStatus.APPROVED,
        review_note=review_note,
        review_message=None,
        merch_code=normalized_merch_code,
    )

    _capture_decision(
        APPROVED_EVENT, submission, extra_properties={"has_merch_code": normalized_merch_code is not None}
    )
    return submission


def request_changes(
    *, organization_id: UUID, reviewer_id: int, review_note: str | None, review_message: str | None
) -> AgentTranscriptSubmission:
    submission = _record_decision(
        organization_id=organization_id,
        reviewer_id=reviewer_id,
        status=SubmissionStatus.CHANGES_REQUESTED,
        review_note=review_note,
        review_message=review_message,
        merch_code=None,
    )

    _capture_decision(CHANGES_REQUESTED_EVENT, submission)
    return submission


def decline(
    *, organization_id: UUID, reviewer_id: int, review_note: str | None, review_message: str | None
) -> AgentTranscriptSubmission:
    submission = _record_decision(
        organization_id=organization_id,
        reviewer_id=reviewer_id,
        status=SubmissionStatus.DECLINED,
        review_note=review_note,
        review_message=review_message,
        merch_code=None,
    )

    _capture_decision(DECLINED_EVENT, submission)
    return submission


def delete_transcript_file(organization_id: UUID) -> AgentTranscriptSubmission:
    submission = get_for_organization(organization_id)
    if submission is None:
        raise SubmissionNotFound(f"No transcript submission for organization {organization_id}")

    if submission.storage_key is None or submission.file_deleted_at is not None:
        return submission

    deleted_storage_key = submission.storage_key
    storage.delete(deleted_storage_key)

    # A replacement upload can commit while the delete runs. Its file is still stored, so only the
    # row that still points at the deleted key is marked.
    AgentTranscriptSubmission.objects.filter(
        id=submission.id, storage_key=deleted_storage_key, file_deleted_at__isnull=True
    ).update(file_deleted_at=timezone.now(), updated_at=timezone.now())
    submission.refresh_from_db()
    return submission


def _record_decision(
    *,
    organization_id: UUID,
    reviewer_id: int,
    status: SubmissionStatus,
    review_note: str | None,
    review_message: str | None,
    merch_code: str | None,
) -> AgentTranscriptSubmission:
    with transaction.atomic():
        submission = (
            AgentTranscriptSubmission.objects.select_for_update().filter(organization_id=organization_id).first()
        )
        if submission is None:
            raise SubmissionNotFound(f"No transcript submission for organization {organization_id}")

        current_status = SubmissionStatus(submission.status)
        if not transitions.is_allowed(current_status, SubmissionAction.REVIEW):
            raise InvalidSubmissionState(current_status, SubmissionAction.REVIEW)

        submission.status = status
        submission.reviewed_by_id = reviewer_id
        submission.reviewed_at = timezone.now()
        submission.review_note = _blank_to_none(review_note)
        submission.review_message = _blank_to_none(review_message)
        submission.merch_code = merch_code
        try:
            with transaction.atomic():
                submission.save()
        except IntegrityError as error:
            raise DuplicateMerchCode("This merch code is already assigned to another organization") from error

        emails.schedule_decision_email(submission)

    return submission


def _discard_staged_upload(organization_id: UUID, staging_key: str) -> None:
    """Drop a rejected upload, so a later complete_upload cannot pick up the same bytes again."""
    AgentTranscriptSubmission.objects.filter(organization_id=organization_id, staging_key=staging_key).update(
        staging_key=None, updated_at=timezone.now()
    )
    storage.delete_quietly(staging_key)


def _blank_to_none(value: str | None) -> str | None:
    if value is None:
        return None

    stripped = value.strip()
    return stripped or None


def _capture_decision(
    event: str, submission: AgentTranscriptSubmission, extra_properties: dict[str, Any] | None = None
) -> None:
    # Staff make the decision, but the event describes the organization, so it carries the
    # organization as its distinct ID and keeps staff out of the customer's person data.
    _capture(
        event,
        organization_id=submission.organization_id,
        distinct_id=str(submission.organization_id),
        properties={"agent": submission.agent, **(extra_properties or {})},
    )


def _capture(event: str, *, organization_id: UUID, distinct_id: str, properties: dict[str, Any]) -> None:
    posthoganalytics.capture(
        distinct_id=distinct_id,
        event=event,
        properties=properties,
        groups={"organization": str(organization_id)},
    )
