from typing import Any

from pydantic import BaseModel

from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.models import Team
from posthog.sync import database_sync_to_async


@database_sync_to_async
def run_trends_query_sync(team: Team, query_json: dict) -> Any:
    """Execute an opaque TrendsQuery against ClickHouse and return the result dict.

    Shared by detection (headline metric) and narrative (breakdown attribution).
    """
    from posthog.api.services.query import process_query_dict

    response = process_query_dict(
        team=team,
        query_json=query_json,
        execution_mode=ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE,
    )
    return response.model_dump() if hasattr(response, "model_dump") else response


class MetricDescriptor(BaseModel):
    """Opaque descriptor of a metric Pulse can re-evaluate.

    `source` traces where the candidate came from (for debugging).
    `query` is a TrendsQuery-shaped dict, executable against the existing query runner.
    """

    source: str  # "dashboard_tile" | "recent_insight" | "top_event"
    source_id: str | int | None = None
    label: str
    query: dict[str, Any]


class CandidateMetric(BaseModel):
    descriptor: MetricDescriptor


class Finding(BaseModel):
    descriptor: MetricDescriptor
    current_value: float
    baseline_value: float
    change_pct: float
    impact: float
    robust_z: float


class EnrichedFinding(BaseModel):
    descriptor: MetricDescriptor
    current_value: float
    baseline_value: float
    change_pct: float
    impact: float
    robust_z: float
    attribution_breakdown: dict[str, Any] | None = None
    narrative: str


class SelectCandidatesInputs(BaseModel):
    team_id: int
    max_candidates: int = 50


class DetectChangesInputs(BaseModel):
    team_id: int
    candidates: list[CandidateMetric]
    robust_z_threshold: float = 3.5
    min_change_pct: float = 0.25


class EnrichFindingsInputs(BaseModel):
    team_id: int
    findings: list[Finding]
    max_findings: int = 5


class DeliverDigestInputs(BaseModel):
    team_id: int
    digest_id: str
    findings: list[EnrichedFinding]
