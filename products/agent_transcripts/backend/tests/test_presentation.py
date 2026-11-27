from unittest.mock import MagicMock, patch

from django.utils import timezone

from rest_framework import status

from posthog.storage import object_storage

from products.agent_transcripts.backend.facade.contracts import (
    ALLOWED_TRANSCRIPT_EXTENSIONS,
    MAX_TRANSCRIPT_SIZE_BYTES,
    TRANSCRIPT_RETENTION_DAYS,
)
from products.agent_transcripts.backend.facade.enums import SubmissionStatus, TranscriptAgent
from products.agent_transcripts.backend.presentation.views import UploadBurstThrottle
from products.agent_transcripts.backend.tests.base import TRANSCRIPT_BYTES, TranscriptStorageTestCase
from products.agent_transcripts.backend.tests.test_content import FAKE_GITHUB_TOKEN
from products.agent_transcripts.backend.tests.test_submissions import CAPTURE_PATH, MERCH_CODE

REVIEW_NOTE = "Staff-only: looked fine, sent the code."
STORAGE_KEY_SUFFIX = "upload/conversation.jsonl"


class TestAgentTranscriptAPI(TranscriptStorageTestCase):
    def _url(self, action: str) -> str:
        return f"/api/organizations/{self.organization.id}/agent_transcripts/{action}/"

    def test_submission_state_never_exposes_staff_fields(self) -> None:
        storage_key = f"{self.folder}/{self.organization.id}/{STORAGE_KEY_SUFFIX}"
        self.create_submission(
            SubmissionStatus.APPROVED,
            storage_key=storage_key,
            submitted_at=timezone.now(),
            review_note=REVIEW_NOTE,
            merch_code=MERCH_CODE,
        )

        response = self.client.get(self._url("submission"))

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert set(body) == {
            "status",
            "agent",
            "original_filename",
            "submitted_at",
            "review_message",
            "retention_days",
            "max_size_bytes",
            "allowed_extensions",
        }
        assert body["status"] == SubmissionStatus.APPROVED
        assert body["retention_days"] == TRANSCRIPT_RETENTION_DAYS
        assert body["max_size_bytes"] == MAX_TRANSCRIPT_SIZE_BYTES
        assert body["allowed_extensions"] == list(ALLOWED_TRANSCRIPT_EXTENSIONS)
        for staff_only_value in (REVIEW_NOTE, MERCH_CODE, storage_key):
            assert staff_only_value not in response.content.decode()

    def test_submission_state_without_a_submission(self) -> None:
        response = self.client.get(self._url("submission"))

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["status"] is None

    @patch(CAPTURE_PATH)
    def test_upload_flow(self, _capture: MagicMock) -> None:
        start = self.client.post(
            self._url("start_upload"),
            {"filename": "conversation.jsonl", "size_bytes": len(TRANSCRIPT_BYTES), "agent": TranscriptAgent.CURSOR},
        )
        assert start.status_code == status.HTTP_200_OK, start.json()
        object_storage.write(start.json()["form_fields"]["key"], TRANSCRIPT_BYTES)

        complete = self.client.post(self._url("complete_upload"))

        assert complete.status_code == status.HTTP_200_OK, complete.json()
        assert complete.json()["status"] == SubmissionStatus.SUBMITTED
        assert complete.json()["agent"] == TranscriptAgent.CURSOR

    def test_complete_upload_names_the_secret_without_echoing_it(self) -> None:
        start = self.client.post(
            self._url("start_upload"),
            {"filename": "conversation.txt", "size_bytes": len(TRANSCRIPT_BYTES), "agent": TranscriptAgent.CODEX},
        )
        object_storage.write(start.json()["form_fields"]["key"], f"export GH_TOKEN={FAKE_GITHUB_TOKEN}\n".encode())

        response = self.client.post(self._url("complete_upload"))

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["code"] == "contains_secret"
        assert "GitHub token" in response.json()["detail"]
        assert FAKE_GITHUB_TOKEN not in response.content.decode()

    def test_start_upload_refused_while_in_review(self) -> None:
        self.create_submission(SubmissionStatus.SUBMITTED)

        response = self.client.post(
            self._url("start_upload"),
            {"filename": "conversation.md", "size_bytes": len(TRANSCRIPT_BYTES), "agent": TranscriptAgent.OTHER},
        )

        assert response.status_code == status.HTTP_409_CONFLICT
        assert response.json()["code"] == "invalid_state"

    def test_upload_steps_share_one_throttle_per_organization(self) -> None:
        burst_limit, _ = UploadBurstThrottle().parse_rate(UploadBurstThrottle.rate)
        assert burst_limit is not None
        upload = {"filename": "conversation.md", "size_bytes": len(TRANSCRIPT_BYTES), "agent": TranscriptAgent.OTHER}
        for _ in range(burst_limit):
            assert self.client.post(self._url("start_upload"), upload).status_code == status.HTTP_200_OK

        response = self.client.post(self._url("complete_upload"))

        assert response.status_code == status.HTTP_429_TOO_MANY_REQUESTS
