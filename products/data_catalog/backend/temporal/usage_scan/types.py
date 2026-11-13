import uuid

from posthog.dataclasses import frozen

# PostHog's own project on US Cloud, where the run event and the MCP telemetry land for every team.
DEFAULT_TELEMETRY_TEAM_ID = 2


@frozen
class CollectRunsInput:
    team_id: int
    snapshot_id: uuid.UUID
    telemetry_team_id: int = DEFAULT_TELEMETRY_TEAM_ID


@frozen
class DetectAdjustedRunsInput:
    team_id: int
    snapshot_id: uuid.UUID
    telemetry_team_id: int = DEFAULT_TELEMETRY_TEAM_ID


@frozen
class CollectTopicsInput:
    team_id: int
    snapshot_id: uuid.UUID
    telemetry_team_id: int = DEFAULT_TELEMETRY_TEAM_ID


@frozen
class SectionWritten:
    """What a scan step wrote. The section itself stays in the snapshot row, out of the workflow history."""

    rows: int
