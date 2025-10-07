from dataclasses import dataclass

from posthog.session_recordings.session_recording_v2_service import RecordingBlock


@dataclass(frozen=True)
class RecordingInput:
    session_id: str
    team_id: int


@dataclass(frozen=True)
class DeleteRecordingBlocksInput:
    recording: RecordingInput
    blocks: list[RecordingBlock]


@dataclass(frozen=True)
class RecordingsWithPersonInput:
    distinct_ids: list[str]
    team_id: int
    batch_size: int = 100


class DeleteRecordingError(Exception):
    pass


class LoadRecordingError(Exception):
    pass
