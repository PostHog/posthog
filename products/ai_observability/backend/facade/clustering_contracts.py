from datetime import datetime
from typing import Any

from posthog.dataclasses import frozen


@frozen
class ClusteringRunRef:
    team_id: int
    run_id: str


@frozen
class ClusteringRunContext:
    active: bool
    job_id: str
    job_name: str
    analysis_level: str
    event_filters: list[dict[str, Any]]
    minimum: int
    lookback_days: int
    user_id: int | None = None


@frozen
class ClusteringRunUpdate:
    ref: ClusteringRunRef
    status: str
    eligible_count: int | None = None
    prepared_count: int | None = None
    cluster_count: int | None = None
    failure_reason: str = ""
    result_run_id: str = ""


@frozen
class ClusteringJobProgress:
    job_id: str
    name: str
    analysis_level: str
    has_filters: bool
    minimum: int
    lookback_days: int
    status: str | None
    eligible_count: int | None
    prepared_count: int
    cluster_count: int | None
    failure_reason: str
    updated_at: datetime | None
    result_run_id: str = ""
