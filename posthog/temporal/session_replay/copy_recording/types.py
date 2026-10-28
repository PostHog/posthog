from typing import Literal

from pydantic import BaseModel, Field

from posthog.session_recordings.data_retention import RETENTION_PERIOD_DAYS

MAX_SESSIONS_PER_COPY = 50

RETENTION_PERIOD_BY_DAYS: dict[int, str] = {days: period for period, days in RETENTION_PERIOD_DAYS.items()}

RetentionDays = Literal[30, 90, 365, 1825]


class CopyRecordingsInput(BaseModel):
    source_team_id: int
    target_team_id: int
    session_ids: list[str] = Field(min_length=1, max_length=MAX_SESSIONS_PER_COPY)
    retention_days: RetentionDays = 365


class CopySessionInput(BaseModel):
    source_team_id: int
    target_team_id: int
    session_id: str
    retention_days: RetentionDays


class CopySessionResult(BaseModel):
    session_id: str
    status: Literal["copied", "already_copied", "not_found", "failed"]
    block_count: int = 0
    event_count: int = 0
    warnings: list[str] = Field(default_factory=list)


class CopyRecordingsResult(BaseModel):
    sessions: list[CopySessionResult]
