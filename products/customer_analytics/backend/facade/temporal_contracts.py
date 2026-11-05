from typing import Literal

from posthog.dataclasses import frozen

DEFAULT_ACCOUNT_PROPERTY_SOURCE_CONCURRENCY = 3


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
    # None closes open runs in both segments. Histories recorded before this field existed decode to None.
    segment: str | None = None


@frozen
class AccountPropertySyncInput:
    team_id: int
    saved_query_id: str
    job_id: str
    segment: str
    source_concurrency: int = DEFAULT_ACCOUNT_PROPERTY_SOURCE_CONCURRENCY


@frozen
class AccountPropertySourceSyncInput:
    team_id: int
    saved_query_id: str
    job_id: str
    segment: str
    source_id: str


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
