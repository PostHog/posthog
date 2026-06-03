from typing import Any

from pydantic import BaseModel, Field

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
    url: str | None = None  # deep-link to the source (e.g. /insights/<short_id>), surfaced as "View insight"


class CandidateMetric(BaseModel):
    descriptor: MetricDescriptor


class Finding(BaseModel):
    descriptor: MetricDescriptor
    current_value: float
    baseline_value: float
    change_pct: float
    impact: float
    robust_z: float
    # Recent completed-week values (oldest→newest, current week last) for the card's trend sparkline.
    series: list[float] | None = None


class EnrichedFinding(BaseModel):
    descriptor: MetricDescriptor
    current_value: float
    baseline_value: float
    change_pct: float
    impact: float
    robust_z: float
    attribution_breakdown: dict[str, Any] | None = None
    # Supporting evidence, e.g. {"session_ids": [...]} for example replays. None when none found.
    evidence: dict[str, Any] | None = None
    narrative: str


class PulseScanConfig(BaseModel):
    """Every tunable knob for one Pulse scan. Defaults mirror the production constants.

    Resolved per-run, never persisted: a staff manual trigger may pass a full override; scheduled
    runs fill the detection thresholds from the team's PulseSubscription and leave selection at
    defaults. Each run is therefore reproducible from the inputs that started it.

    The change_v1 detector and the impact ranking formula are deliberately NOT knobs here — they're
    structural, not tuning levers.
    """

    # --- Selection: which metrics get scanned. A per-source limit of 0 disables that source. ---
    max_candidates: int = 200
    recent_days: int = 30  # window for "recently accessed" dashboards and "recently viewed" insights
    min_viewers_for_recent_insight: int = 3
    dashboard_tile_limit: int = 10
    recent_insight_limit: int = 100  # was max_candidates // 2 (=100 at the default max_candidates)
    saved_insight_limit: int = 15
    top_event_limit: int = 25

    # --- Detection: what counts as a notable change. ---
    min_baseline_value: float = 5.0  # volume floor; skip metrics quieter than this (the top noise lever)
    min_change_pct: float = 0.25  # primary gate
    robust_z_threshold: float = 3.5  # secondary/informational only, never a sole trigger
    baseline_weeks: int = 4
    max_findings: int = 5


class SelectCandidatesInputs(BaseModel):
    team_id: int
    config: PulseScanConfig = Field(default_factory=PulseScanConfig)


class DetectChangesInputs(BaseModel):
    team_id: int
    candidates: list[CandidateMetric]
    config: PulseScanConfig = Field(default_factory=PulseScanConfig)


class EnrichFindingsInputs(BaseModel):
    team_id: int
    user_id: int | None = None
    findings: list[Finding]
    max_findings: int = 5
    # Period bounds (ISO) used to scope the replay-evidence window. Empty disables evidence collection.
    period_start: str = ""
    period_end: str = ""


class DeliverDigestInputs(BaseModel):
    team_id: int
    digest_id: str
    findings: list[EnrichedFinding]


class SynthesizeDigestInputs(BaseModel):
    team_id: int
    digest_id: str
    user_id: int | None = None
    findings: list[EnrichedFinding]
    period_start: str = ""
    period_end: str = ""
