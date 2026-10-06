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
    request_id: str | None = None


@frozen
class AccountPropertySyncCoordinatorInput:
    team_id: int
    saved_query_id: str


@frozen
class AccountPropertySyncWork:
    team_id: int
    saved_query_id: str
    request_id: str
    job_id: str
    kind: Literal["live", "staged"]
    generation: int
    started_at: str
