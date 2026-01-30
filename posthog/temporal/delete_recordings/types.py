from datetime import datetime
from typing import Literal

from pydantic import BaseModel


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


class BulkDeleteInput(BaseModel):
    team_id: int
    session_ids: list[str]


class BulkDeleteResult(BaseModel):
    deleted: list[str]
    not_found: list[str]
    already_deleted: list[str]
    errors: list[dict]


class DeletedRecordingEntry(BaseModel):
    session_id: str
    deleted_at: datetime


class DeletionCertificate(BaseModel):
    """Certificate documenting the deletion of a collection of recordings."""

    workflow_type: Literal["person", "team", "query"]
    workflow_id: str
    team_id: int
    started_at: datetime
    completed_at: datetime
    dry_run: bool

    # Request metadata (varies by workflow type)
    distinct_ids: list[str] | None = None
    query: str | None = None

    # Summary statistics
    total_recordings_found: int
    total_deleted: int
    total_not_found: int
    total_already_deleted: int
    total_errors: int

    # Detailed records
    deleted_recordings: list[DeletedRecordingEntry]
    not_found_session_ids: list[str]
    already_deleted_session_ids: list[str]
    errors: list[dict]


class LoadRecordingError(Exception):
    pass


class PurgeDeletedMetadataInput(BaseModel):
    """Input for the nightly metadata purge workflow."""

    grace_period_days: int = 7


class PurgeDeletedMetadataResult(BaseModel):
    """Result of the metadata purge operation."""

    started_at: datetime
    completed_at: datetime
