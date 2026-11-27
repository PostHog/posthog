import dataclasses
from datetime import datetime

from ..usage_scan.types import DEFAULT_TELEMETRY_TEAM_ID

DEFAULT_WINDOW_DAYS = 7


@dataclasses.dataclass(frozen=True)
class EffectivenessInput:
    """Without team ids, the run measures every team with metrics and the effectiveness flag on."""

    team_ids: list[int] | None = None
    window_days: int = DEFAULT_WINDOW_DAYS
    telemetry_team_id: int = DEFAULT_TELEMETRY_TEAM_ID


@dataclasses.dataclass(frozen=True)
class MeasureTeamInput:
    team_id: int
    window_start: datetime
    window_end: datetime
    telemetry_team_id: int = DEFAULT_TELEMETRY_TEAM_ID


@dataclasses.dataclass(frozen=True)
class TeamMeasured:
    """Counts only, because session rows would grow the workflow history."""

    skipped: bool
    analysis_sessions: int = 0
    rows: int = 0
