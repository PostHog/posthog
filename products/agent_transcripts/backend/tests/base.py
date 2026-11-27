from typing import Any
from uuid import uuid4

from posthog.test.base import APIBaseTest

from django.test import override_settings

from posthog.storage import object_storage

from products.agent_transcripts.backend.facade import api
from products.agent_transcripts.backend.facade.contracts import StartUploadInput
from products.agent_transcripts.backend.facade.enums import SubmissionStatus, TranscriptAgent
from products.agent_transcripts.backend.models import AgentTranscriptSubmission

TRANSCRIPT_FILENAME = "conversation.jsonl"
TRANSCRIPT_BYTES = b'{"role": "user", "content": "set up PostHog in my Next.js app"}\n'


def stored_bytes(key: str | None) -> bytes | None:
    assert key is not None
    return object_storage.read_bytes(key, missing_ok=True)


# Runs against the real object storage, under a folder of its own that cleanup empties.
class TranscriptStorageTestCase(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()

        self.folder = f"test_agent_transcripts_{uuid4().hex}"
        storage_settings = override_settings(
            OBJECT_STORAGE_ENABLED=True, OBJECT_STORAGE_AGENT_TRANSCRIPTS_FOLDER=self.folder
        )
        storage_settings.enable()
        self.addCleanup(storage_settings.disable)
        self.addCleanup(self._delete_stored_objects)

    def _delete_stored_objects(self) -> None:
        keys = object_storage.list_objects(self.folder) or []
        if keys:
            object_storage.delete_objects(keys)

    def stage_upload(
        self, data: bytes = TRANSCRIPT_BYTES, filename: str = TRANSCRIPT_FILENAME, organization_id: Any = None
    ) -> AgentTranscriptSubmission:
        # Writes the bytes where the browser's presigned POST would. The declared size stays that of a
        # valid transcript, so a test can store bytes that differ from what the client claimed.
        organization_id = organization_id or self.organization.id
        api.start_upload(
            StartUploadInput(
                organization_id=organization_id,
                filename=filename,
                size_bytes=len(TRANSCRIPT_BYTES),
                agent=TranscriptAgent.CLAUDE_CODE,
            )
        )

        submission = AgentTranscriptSubmission.objects.get(organization_id=organization_id)
        assert submission.staging_key is not None
        object_storage.write(submission.staging_key, data)
        return submission

    def create_submission(self, status: SubmissionStatus, **fields: Any) -> AgentTranscriptSubmission:
        return AgentTranscriptSubmission.objects.create(
            organization=fields.pop("organization", self.organization),
            status=status,
            agent=TranscriptAgent.CODEX,
            original_filename=TRANSCRIPT_FILENAME,
            **fields,
        )
