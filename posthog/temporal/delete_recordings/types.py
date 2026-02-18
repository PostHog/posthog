from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field

MAX_BULK_DELETE_BATCH_SIZE = 100


class DeletionProgress(BaseModel):
    """Accumulated state across continue-as-new executions."""

    cursor: str | None = None
    total_found: int = 0
    total_deleted: int = 0
    total_failed: int = 0
    started_at: datetime | None = None


class DeletionConfig(BaseModel):
    dry_run: bool = False
    batch_size: Annotated[int, Field(ge=1, le=MAX_BULK_DELETE_BATCH_SIZE)] = MAX_BULK_DELETE_BATCH_SIZE
    max_deletions_per_second: float = 30
    reason: str = ""


class RecordingsWithPersonInput(BaseModel):
    distinct_ids: list[str]
    team_id: int
    config: DeletionConfig = DeletionConfig()
    cursor: str | None = None
    page_size: int = 10_000
    progress: DeletionProgress | None = None


class RecordingsWithTeamInput(BaseModel):
    team_id: int
    config: DeletionConfig = DeletionConfig()
    cursor: str | None = None
    page_size: int = 10_000
    progress: DeletionProgress | None = None


class RecordingsWithQueryInput(BaseModel):
    query: str
    team_id: int
    config: DeletionConfig = DeletionConfig()
    query_limit: int = 100
    cursor: str | None = None
    progress: DeletionProgress | None = None


class RecordingsWithSessionIdsInput(BaseModel):
    session_ids: list[str]
    team_id: int
    config: DeletionConfig = DeletionConfig()
    source_filename: str | None = None
    progress: DeletionProgress | None = None


class BulkDeleteInput(BaseModel):
    team_id: int
    session_ids: list[str]
    dry_run: bool = False


class BulkDeleteResult(BaseModel):
    deleted: list[str]
    failed_count: int = 0


class LoadRecordingsPage(BaseModel):
    session_ids: list[str]
    next_cursor: str | None = None


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


class LoadRecordingError(Exception):
    pass


class PurgeDeletedMetadataInput(BaseModel):
    """Input for the nightly metadata purge workflow."""

    grace_period_days: int = 10


class PurgeDeletedMetadataResult(BaseModel):
    """Result of the metadata purge operation."""

    started_at: datetime
    completed_at: datetime
