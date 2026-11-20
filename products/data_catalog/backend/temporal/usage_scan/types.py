import uuid
from dataclasses import field

from posthog.dataclasses import frozen

from ...facade.enums import UsageSection
from ...logic.usage_scan import DEFAULT_LOOKBACK_DAYS

# PostHog's own project on US Cloud, where the run event and the MCP telemetry land for every team.
DEFAULT_TELEMETRY_TEAM_ID = 2


@frozen
class ScanStepInput:
    """Every scan step reads the same three values; the snapshot row holds the window."""

    team_id: int
    snapshot_id: uuid.UUID
    telemetry_team_id: int = DEFAULT_TELEMETRY_TEAM_ID


@frozen
class SectionWritten:
    """What a scan step wrote. The section itself stays in the snapshot row, out of the workflow history."""

    rows: int


@frozen
class UsageScanInput:
    team_id: int
    snapshot_id: uuid.UUID
    telemetry_team_id: int = DEFAULT_TELEMETRY_TEAM_ID


@frozen
class UsageScheduleInput:
    lookback_days: int = DEFAULT_LOOKBACK_DAYS
    telemetry_team_id: int = DEFAULT_TELEMETRY_TEAM_ID


@frozen
class CreateSnapshotInput:
    team_id: int
    lookback_days: int
    # Chosen by the workflow, so a retried activity finds the row an earlier attempt committed.
    snapshot_id: uuid.UUID


@frozen
class FailedStep:
    section: UsageSection
    reason: str


@frozen
class FinalizeSnapshotInput:
    team_id: int
    snapshot_id: uuid.UUID
    error: str | None = None
    failed_sections: list[FailedStep] = field(default_factory=list)
