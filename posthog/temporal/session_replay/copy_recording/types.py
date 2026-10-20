from typing import Literal

from pydantic import BaseModel, Field

MAX_SESSIONS_PER_COPY = 50

# Mirrors ValidRetentionPeriods in the replay ingestion consumer; recording-api rejects keys under any other prefix.
RETENTION_PERIODS: dict[int, str] = {30: "30d", 90: "90d", 365: "1y", 1825: "5y"}


class CopyRecordingsInput(BaseModel):
    source_team_id: int
    target_team_id: int
    session_ids: list[str] = Field(min_length=1, max_length=MAX_SESSIONS_PER_COPY)
    retention_days: Literal[30, 90, 365, 1825] = 365


class CopySessionInput(BaseModel):
    source_team_id: int
    target_team_id: int
    session_id: str
    retention_days: Literal[30, 90, 365, 1825]


class CopySessionResult(BaseModel):
    session_id: str
    status: Literal["copied", "already_copied", "not_found"]
    block_count: int = 0
    event_count: int = 0
    warnings: list[str] = Field(default_factory=list)


class CopyRecordingsResult(BaseModel):
    sessions: list[CopySessionResult]
