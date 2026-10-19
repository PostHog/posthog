from typing import Literal

from posthog.dataclasses import frozen


@frozen
class StageAccountPropertySyncInput:
    team_id: int
    saved_query_id: str
    job_id: str
    table_uri: str
    delta_version: int


@frozen
class DispatchAccountPropertySyncInput:
    team_id: int
    saved_query_id: str
    job_id: str


@frozen
class FinalizeAccountPropertySyncRunsInput:
    team_id: int
    saved_query_id: str
    job_id: str
    status: str
    phase: str
    error: str | None = None


@frozen
class AccountPropertySyncInput:
    team_id: int
    saved_query_id: str
    job_id: str
    segment: str


@frozen
class AccountPropertySegmentTelemetryInput:
    team_id: int
    saved_query_id: str
    job_id: str
    segment: str
    path: Literal["legacy", "fanout"]
    status: Literal["completed", "failed", "cancelled"]
    duration_seconds: float
    source_count: int | None = None
    counts: dict[str, int] | None = None
    error_type: str | None = None
