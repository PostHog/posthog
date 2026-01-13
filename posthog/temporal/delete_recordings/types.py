from pydantic import BaseModel

from posthog.session_recordings.session_recording_v2_service import RecordingBlock


class Recording(BaseModel):
    session_id: str
    team_id: int


class RecordingWithBlocks(BaseModel):
    recording: Recording
    blocks: list[RecordingBlock]


class RecordingsWithPersonInput(BaseModel):
    distinct_ids: list[str]
    team_id: int
    batch_size: int = 100


class RecordingsWithTeamInput(BaseModel):
    team_id: int
    dry_run: bool = False
    batch_size: int = 100


class RecordingsWithQueryInput(BaseModel):
    query: str
    team_id: int
    dry_run: bool = False
    batch_size: int = 100
    query_limit: int = 100


class RecordingBlockGroup(BaseModel):
    recording: Recording
    path: str
    ranges: list[tuple[int, int]]


class DeleteRecordingMetadataInput(BaseModel):
    dry_run: bool = False


class DeleteRecordingError(Exception):
    pass


class LoadRecordingError(Exception):
    pass


class GroupRecordingError(Exception):
    pass
