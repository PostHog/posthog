from datetime import UTC, datetime, timedelta

from django.test import SimpleTestCase

from parameterized import parameterized

from products.agent_transcripts.backend.facade.contracts import TRANSCRIPT_RETENTION_DAYS
from products.agent_transcripts.backend.facade.enums import SubmissionAction, SubmissionStatus
from products.agent_transcripts.backend.logic import transitions

SUBMITTED_AT = datetime(2026, 1, 1, tzinfo=UTC)
STORAGE_KEY = "agent_transcripts/org/upload/chat.jsonl"
ONE_SECOND = timedelta(seconds=1)


class TestTransitions(SimpleTestCase):
    @parameterized.expand(
        [
            (SubmissionStatus.PENDING_UPLOAD, SubmissionAction.START_UPLOAD, True),
            (SubmissionStatus.PENDING_UPLOAD, SubmissionAction.COMPLETE_UPLOAD, True),
            (SubmissionStatus.PENDING_UPLOAD, SubmissionAction.REVIEW, False),
            (SubmissionStatus.SUBMITTED, SubmissionAction.START_UPLOAD, False),
            (SubmissionStatus.SUBMITTED, SubmissionAction.COMPLETE_UPLOAD, False),
            (SubmissionStatus.SUBMITTED, SubmissionAction.REVIEW, True),
            (SubmissionStatus.CHANGES_REQUESTED, SubmissionAction.START_UPLOAD, True),
            (SubmissionStatus.CHANGES_REQUESTED, SubmissionAction.COMPLETE_UPLOAD, False),
            (SubmissionStatus.CHANGES_REQUESTED, SubmissionAction.REVIEW, False),
            (SubmissionStatus.APPROVED, SubmissionAction.START_UPLOAD, False),
            (SubmissionStatus.APPROVED, SubmissionAction.COMPLETE_UPLOAD, False),
            (SubmissionStatus.APPROVED, SubmissionAction.REVIEW, False),
            (SubmissionStatus.DECLINED, SubmissionAction.START_UPLOAD, False),
            (SubmissionStatus.DECLINED, SubmissionAction.COMPLETE_UPLOAD, False),
            (SubmissionStatus.DECLINED, SubmissionAction.REVIEW, False),
        ]
    )
    def test_is_allowed(self, status: SubmissionStatus, action: SubmissionAction, expected: bool) -> None:
        assert transitions.is_allowed(status, action) is expected

    @parameterized.expand(
        [
            ("fresh", STORAGE_KEY, None, SUBMITTED_AT, SUBMITTED_AT + ONE_SECOND, True),
            (
                "last_second_of_retention",
                STORAGE_KEY,
                None,
                SUBMITTED_AT,
                SUBMITTED_AT + timedelta(days=TRANSCRIPT_RETENTION_DAYS),
                True,
            ),
            (
                "past_retention",
                STORAGE_KEY,
                None,
                SUBMITTED_AT,
                SUBMITTED_AT + timedelta(days=TRANSCRIPT_RETENTION_DAYS) + ONE_SECOND,
                False,
            ),
            ("deleted_by_staff", STORAGE_KEY, SUBMITTED_AT, SUBMITTED_AT, SUBMITTED_AT + ONE_SECOND, False),
            ("never_uploaded", None, None, None, SUBMITTED_AT, False),
        ]
    )
    def test_is_file_available(
        self,
        _name: str,
        storage_key: str | None,
        file_deleted_at: datetime | None,
        submitted_at: datetime | None,
        now: datetime,
        expected: bool,
    ) -> None:
        available = transitions.is_file_available(
            storage_key=storage_key, file_deleted_at=file_deleted_at, submitted_at=submitted_at, now=now
        )

        assert available is expected
