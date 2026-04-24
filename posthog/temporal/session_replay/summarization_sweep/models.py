from dataclasses import dataclass, field


@dataclass
class SummarizeTeamSessionsInputs:
    team_id: int
    dry_run: bool = False


@dataclass
class FindSessionsInput:
    team_id: int
    lookback_minutes: int
    max_sessions: int


@dataclass
class FindSessionsResult:
    team_id: int
    # Distinct from empty session_ids: disabled triggers schedule teardown.
    team_disabled: bool = False
    session_ids: list[str] = field(default_factory=list)
    user_id: int | None = None
    user_distinct_id: str | None = None


@dataclass
class DeleteTeamScheduleInput:
    team_id: int
    dry_run: bool = False


@dataclass
class UpsertTeamScheduleInput:
    team_id: int
    dry_run: bool = False


@dataclass
class ReconcileSchedulesInputs:
    dry_run: bool = False


@dataclass
class ReconcileSchedulesResult:
    upserted_team_ids: list[int] = field(default_factory=list)
    deleted_team_ids: list[int] = field(default_factory=list)
    failed_upsert_team_ids: list[int] = field(default_factory=list)
    failed_delete_team_ids: list[int] = field(default_factory=list)
    dry_run: bool = False
