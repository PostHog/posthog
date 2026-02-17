from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field

MAX_BULK_DELETE_BATCH_SIZE = 100


class RecordingsWithPersonInput(BaseModel):
    distinct_ids: list[str]
    team_id: int
    reason: str = ""
    dry_run: bool = False
    batch_size: Annotated[int, Field(ge=1, le=MAX_BULK_DELETE_BATCH_SIZE)] = MAX_BULK_DELETE_BATCH_SIZE


class RecordingsWithTeamInput(BaseModel):
    team_id: int
    reason: str = ""
    dry_run: bool = False
    batch_size: Annotated[int, Field(ge=1, le=MAX_BULK_DELETE_BATCH_SIZE)] = MAX_BULK_DELETE_BATCH_SIZE


class RecordingsWithQueryInput(BaseModel):
    query: str
    team_id: int
    reason: str = ""
    dry_run: bool = False
    batch_size: Annotated[int, Field(ge=1, le=MAX_BULK_DELETE_BATCH_SIZE)] = MAX_BULK_DELETE_BATCH_SIZE
    query_limit: int = 100


class RecordingsWithSessionIdsInput(BaseModel):
    session_ids: list[str]
    team_id: int
    reason: str = ""
    dry_run: bool = False
    batch_size: Annotated[int, Field(ge=1, le=MAX_BULK_DELETE_BATCH_SIZE)] = MAX_BULK_DELETE_BATCH_SIZE
    source_filename: str | None = None


class BulkDeleteInput(BaseModel):
    team_id: int
    session_ids: list[str]
    dry_run: bool = False


class DeleteFailure(BaseModel):
    session_id: str
    error: str


class BulkDeleteResult(BaseModel):
    deleted: list[str]
    failed: list[DeleteFailure]


class DeleteSuccess(BaseModel):
    session_id: str
    deleted_at: datetime


class DeletionCertificate(BaseModel):
    """Certificate documenting the deletion of a collection of recordings."""

    workflow_type: Literal["person", "team", "query", "session_ids"]
    workflow_id: str
    team_id: int
    started_at: datetime
    completed_at: datetime
    dry_run: bool
    reason: str = ""

    # Request metadata (varies by workflow type)
    distinct_ids: list[str] | None = None
    query: str | None = None
    source_filename: str | None = None

    # Summary statistics
    total_recordings_found: int
    total_deleted: int
    total_failed: int

    # Detailed records
    deleted_recordings: list[DeleteSuccess]
    failed: list[DeleteFailure]


class LoadRecordingError(Exception):
    pass


class PurgeDeletedMetadataInput(BaseModel):
    """Input for the nightly metadata purge workflow."""

    grace_period_days: int = 10


class PurgeDeletedMetadataResult(BaseModel):
    """Result of the metadata purge operation."""

    started_at: datetime
    completed_at: datetime
