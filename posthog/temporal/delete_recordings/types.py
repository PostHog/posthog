from dataclasses import dataclass

from posthog.session_recordings.session_recording_v2_service import RecordingBlock


@dataclass(frozen=True)
class Recording:
    session_id: str
    team_id: int


@dataclass(frozen=True)
class RecordingWithBlocks:
    recording: Recording
    blocks: list[RecordingBlock]


@dataclass(frozen=True)
class RecordingsWithPersonInput:
    distinct_ids: list[str]
    team_id: int
    batch_size: int = 100


@dataclass(frozen=True)
class RecordingBlockGroup:
    recording: Recording
    path: str
    ranges: list[tuple[int, int]]


class DeleteRecordingError(Exception):
    pass


class LoadRecordingError(Exception):
    pass


class GroupRecordingError(Exception):
    pass
