from typing import Any

from pydantic import BaseModel


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
    z_score: float


class EnrichedFinding(BaseModel):
    descriptor: MetricDescriptor
    current_value: float
    baseline_value: float
    change_pct: float
    z_score: float
    attribution_breakdown: dict[str, Any] | None = None
    narrative: str


class SelectCandidatesInputs(BaseModel):
    team_id: int
    max_candidates: int = 50


class DetectChangesInputs(BaseModel):
    team_id: int
    candidates: list[CandidateMetric]
    z_threshold: float = 2.0
    min_change_pct: float = 0.25


class EnrichFindingsInputs(BaseModel):
    team_id: int
    findings: list[Finding]
    max_findings: int = 5


class DeliverDigestInputs(BaseModel):
    team_id: int
    digest_id: str
    findings: list[EnrichedFinding]
