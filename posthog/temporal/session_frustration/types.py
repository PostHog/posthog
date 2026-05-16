"""Data types for session frustration detection workflows."""

import dataclasses
from datetime import datetime


@dataclasses.dataclass
class CoordinatorInputs:
    lookback_hours: int = 2


@dataclasses.dataclass
class TeamWorkflowInputs:
    team_id: int
    api_token: str
    lookback_hours: int = 2


@dataclasses.dataclass
class FrustratedSession:
    session_id: str
    distinct_id: str
    frustration_score: int
    rage_click_count: int
    exception_count: int
    console_error_count: int
    duration_seconds: int
    first_url: str
    session_start: datetime


@dataclasses.dataclass
class TeamWorkflowResult:
    events_emitted: int = 0
    sessions_queried: int = 0
    sessions_deduped: int = 0
