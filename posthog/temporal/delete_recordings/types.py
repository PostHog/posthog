from dataclasses import dataclass

from posthog.session_recordings.session_recording_v2_service import RecordingBlock


@dataclass(frozen=True)
class DeleteRecordingInput:
    session_id: str
    team_id: int


@dataclass(frozen=True)
class DeleteRecordingsWithPersonInput:
    distinct_ids: list[str]
    team_id: int


@dataclass(frozen=True)
class LoadRecordingBlocksInput:
    session_id: str
    team_id: int


@dataclass(frozen=True)
class DeleteRecordingBlocksInput:
    session_id: str
    team_id: int
    blocks: list[RecordingBlock]


@dataclass(frozen=True)
class LoadRecordingsWithPersonInput:
    distinct_ids: list[str]
    team_id: int


class DeleteRecordingError(Exception):
    pass
