"""What each submission status allows. Pure, so every case is one table row in the tests."""

from datetime import datetime, timedelta

from ..facade.contracts import TRANSCRIPT_RETENTION_DAYS
from ..facade.enums import SubmissionAction, SubmissionStatus

ALLOWED_ACTIONS: dict[SubmissionStatus, frozenset[SubmissionAction]] = {
    SubmissionStatus.PENDING_UPLOAD: frozenset({SubmissionAction.START_UPLOAD, SubmissionAction.COMPLETE_UPLOAD}),
    SubmissionStatus.SUBMITTED: frozenset({SubmissionAction.REVIEW}),
    SubmissionStatus.CHANGES_REQUESTED: frozenset({SubmissionAction.START_UPLOAD}),
    SubmissionStatus.APPROVED: frozenset(),
    SubmissionStatus.DECLINED: frozenset(),
}


def is_allowed(status: SubmissionStatus, action: SubmissionAction) -> bool:
    return action in ALLOWED_ACTIONS[status]


def file_expires_at(submitted_at: datetime | None) -> datetime | None:
    if submitted_at is None:
        return None

    return submitted_at + timedelta(days=TRANSCRIPT_RETENTION_DAYS)


def is_file_available(
    *, storage_key: str | None, file_deleted_at: datetime | None, submitted_at: datetime | None, now: datetime
) -> bool:
    if storage_key is None or file_deleted_at is not None:
        return False

    expires_at = file_expires_at(submitted_at)
    return expires_at is not None and expires_at >= now
