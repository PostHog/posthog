"""
Contract types for agent_transcripts.

Frozen dataclasses, constants and errors that define what this product exposes.
No Django imports.
"""

from datetime import datetime
from uuid import UUID

from pydantic.dataclasses import dataclass

from .enums import SecretKind, SubmissionAction, SubmissionStatus, TranscriptAgent, UploadRejectionReason

MEGABYTE = 1024 * 1024
MAX_TRANSCRIPT_SIZE_BYTES = 25 * MEGABYTE

# The bucket lifecycle rule that deletes the transcripts prefix after this many days lives in the
# infrastructure repository. Keep the two in sync.
TRANSCRIPT_RETENTION_DAYS = 14

ALLOWED_TRANSCRIPT_EXTENSIONS: tuple[str, ...] = (".jsonl", ".json", ".md", ".txt")

# Staff paste merch codes from a pre-generated list. Each one is a discount of this many dollars in the merch store.
MERCH_CODE_VALUE_USD = 20
MERCH_CODE_MAX_LENGTH = 64


@dataclass(frozen=True)
class AgentTranscriptSubmission:
    """A submission as staff see it. The storage key stays internal: staff download through a presigned URL."""

    id: UUID
    organization_id: UUID
    status: SubmissionStatus
    agent: TranscriptAgent
    original_filename: str
    size_bytes: int | None
    content_type: str | None
    submitted_by_id: int | None
    submitted_at: datetime | None
    reviewed_by_id: int | None
    reviewed_at: datetime | None
    review_note: str | None
    review_message: str | None
    merch_code: str | None
    file_deleted_at: datetime | None
    # False when no upload completed yet, staff deleted the file, or the retention window passed.
    file_available: bool
    # When the bucket lifecycle rule removes the file. None until an upload completes.
    file_expires_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class Submitter:
    user_id: int
    name: str
    email: str


@dataclass(frozen=True)
class SubmissionForReview:
    """A submission with the organization and the person behind it, for the staff review in PostHog Admin."""

    submission: AgentTranscriptSubmission
    organization_name: str
    # None before an upload completes, and after the submitting user is deleted.
    submitter: Submitter | None


@dataclass(frozen=True)
class CustomerSubmissionState:
    """What a customer sees about their organization's submission. Holds no staff-only field."""

    status: SubmissionStatus | None
    agent: TranscriptAgent | None
    original_filename: str | None
    submitted_at: datetime | None
    review_message: str | None
    retention_days: int
    max_size_bytes: int
    allowed_extensions: list[str]


@dataclass(frozen=True)
class StartUploadInput:
    organization_id: UUID
    filename: str
    size_bytes: int
    agent: TranscriptAgent


@dataclass(frozen=True)
class PresignedUpload:
    upload_url: str
    form_fields: dict[str, str]
    expires_in: int


@dataclass(frozen=True)
class CompleteUploadInput:
    organization_id: UUID
    user_id: int
    # The submitting user's analytics distinct ID, for the submitted event.
    distinct_id: str


class AgentTranscriptError(Exception):
    pass


class SubmissionNotFound(AgentTranscriptError):
    pass


class InvalidSubmissionState(AgentTranscriptError):
    def __init__(self, status: SubmissionStatus, action: SubmissionAction) -> None:
        super().__init__(f"Action {action.value} is not allowed for a submission in status {status.value}")
        self.status = status
        self.action = action


class UploadRejected(AgentTranscriptError):
    def __init__(self, reason: UploadRejectionReason, secret_kind: SecretKind | None = None) -> None:
        super().__init__(f"Upload rejected: {reason.value}")
        self.reason = reason
        self.secret_kind = secret_kind


class DuplicateMerchCode(AgentTranscriptError):
    pass


class TranscriptStorageUnavailable(AgentTranscriptError):
    pass
