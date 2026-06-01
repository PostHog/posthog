from dataclasses import dataclass, field


@dataclass
class SummarizeTeamSessionsInputs:
    team_id: int


@dataclass
class FindSessionsInput:
    team_id: int
    lookback_minutes: int


@dataclass
class FindSessionsResult:
    team_id: int
    session_ids: list[str] = field(default_factory=list)
    user_id: int | None = None
    user_distinct_id: str | None = None


@dataclass
class DeleteTeamScheduleInput:
    team_id: int


@dataclass
class UpsertTeamScheduleInput:
    team_id: int


@dataclass
class ReconcileSchedulesInputs:
    pass


@dataclass
class ReconcileSchedulesResult:
    upserted_team_ids: list[int] = field(default_factory=list)
    deleted_team_ids: list[int] = field(default_factory=list)
    failed_upsert_team_ids: list[int] = field(default_factory=list)
    failed_delete_team_ids: list[int] = field(default_factory=list)
