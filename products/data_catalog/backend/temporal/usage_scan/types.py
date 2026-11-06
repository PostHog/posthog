import uuid
import dataclasses

# PostHog's own project on US Cloud, where the run event and the MCP telemetry land for every team.
DEFAULT_TELEMETRY_TEAM_ID = 2


@dataclasses.dataclass(frozen=True)
class ScanStepInput:
    """Every scan step reads the same three values; the snapshot row holds the window."""

    team_id: int
    snapshot_id: uuid.UUID
    telemetry_team_id: int = DEFAULT_TELEMETRY_TEAM_ID


@dataclasses.dataclass(frozen=True)
class SectionWritten:
    """What a scan step wrote. The section itself stays in the snapshot row, out of the workflow history."""

    rows: int


@dataclasses.dataclass(frozen=True)
class UsageScanInput:
    team_id: int
    snapshot_id: uuid.UUID
    telemetry_team_id: int = DEFAULT_TELEMETRY_TEAM_ID


@dataclasses.dataclass(frozen=True)
class UsageScheduleInput:
    lookback_days: int = 28
    telemetry_team_id: int = DEFAULT_TELEMETRY_TEAM_ID


@dataclasses.dataclass(frozen=True)
class CreateSnapshotInput:
    team_id: int
    lookback_days: int


@dataclasses.dataclass(frozen=True)
class FailedStep:
    section: str
    reason: str


@dataclasses.dataclass(frozen=True)
class FinalizeSnapshotInput:
    team_id: int
    snapshot_id: uuid.UUID
    error: str | None = None
    failed_sections: list[FailedStep] = dataclasses.field(default_factory=list)
