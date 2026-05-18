"""Z-score-based change detection for Pulse candidate metrics."""

import asyncio
import statistics
from typing import Any

import structlog

from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.models import Team
from posthog.sync import database_sync_to_async
from posthog.temporal.ai.pulse.types import CandidateMetric, Finding

logger = structlog.get_logger(__name__)


DETECTION_DATE_FROM = "-42d"  # 6 weeks: 1 current + 5 baseline
DETECTION_CONCURRENCY = 8
MIN_BASELINE_WEEKS = 3
MIN_BASELINE_VALUE = 5.0  # Skip near-zero-volume metrics that produce noisy z-scores


def _build_detection_query(base_query: dict) -> dict:
    query = {**base_query}
    query["dateRange"] = {"date_from": DETECTION_DATE_FROM, "date_to": None}
    query["interval"] = "week"
    # Strip breakdowns for the initial detection scan — we want the headline metric.
    if "breakdownFilter" in query:
        query["breakdownFilter"] = None
    return query


def _extract_weekly_series(result: Any) -> list[float]:
    if not isinstance(result, dict):
        return []
    results = result.get("results") or []
    if not results:
        return []
    first_series = results[0]
    if not isinstance(first_series, dict):
        return []
    data = first_series.get("data") or []
    return [float(v) for v in data if isinstance(v, int | float) and not isinstance(v, bool)]


def _compute_z_score(current: float, baseline: list[float]) -> tuple[float, float]:
    """Return (z_score, baseline_mean). Falls back to 0.0 if baseline has zero variance."""
    if len(baseline) < 2:
        return 0.0, 0.0
    mean = statistics.mean(baseline)
    stddev = statistics.stdev(baseline)
    if stddev == 0:
        return 0.0, mean
    return (current - mean) / stddev, mean


def _evaluate_candidate(
    candidate: CandidateMetric, weekly_values: list[float], z_threshold: float, min_change_pct: float
) -> Finding | None:
    # We need at least the in-progress current week + MIN_BASELINE_WEEKS completed baseline weeks
    if len(weekly_values) < MIN_BASELINE_WEEKS + 2:
        return None

    # Drop the in-progress current week (last bucket) since trend buckets are partial.
    completed = weekly_values[:-1]
    current = completed[-1]
    baseline = completed[:-1][-4:]
    if len(baseline) < MIN_BASELINE_WEEKS:
        return None

    z_score, baseline_mean = _compute_z_score(current, baseline)
    if baseline_mean < MIN_BASELINE_VALUE:
        # Too low-volume — z-scores and percentage changes are unreliable.
        return None

    change_pct = (current - baseline_mean) / baseline_mean
    if abs(z_score) < z_threshold and abs(change_pct) < min_change_pct:
        return None

    return Finding(
        descriptor=candidate.descriptor,
        current_value=current,
        baseline_value=baseline_mean,
        change_pct=change_pct,
        z_score=z_score,
    )


@database_sync_to_async
def _run_query_sync(team: Team, query_json: dict) -> Any:
    from posthog.api.services.query import process_query_dict

    response = process_query_dict(
        team=team,
        query_json=query_json,
        execution_mode=ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE,
    )
    return response.model_dump() if hasattr(response, "model_dump") else response


async def _evaluate_one(
    team: Team,
    candidate: CandidateMetric,
    z_threshold: float,
    min_change_pct: float,
    semaphore: asyncio.Semaphore,
) -> Finding | None:
    async with semaphore:
        try:
            query = _build_detection_query(candidate.descriptor.query)
            result = await _run_query_sync(team, query)
            series = _extract_weekly_series(result)
            return _evaluate_candidate(candidate, series, z_threshold, min_change_pct)
        except Exception as exc:
            logger.exception(
                "pulse_detection_candidate_failed",
                team_id=team.id,
                metric=candidate.descriptor.label,
                error=str(exc),
            )
            return None


async def detect_changes(
    team_id: int, candidates: list[CandidateMetric], z_threshold: float, min_change_pct: float
) -> list[Finding]:
    @database_sync_to_async
    def _get_team() -> Team:
        return Team.objects.get(id=team_id)

    team = await _get_team()
    semaphore = asyncio.Semaphore(DETECTION_CONCURRENCY)
    results = await asyncio.gather(
        *[_evaluate_one(team, c, z_threshold, min_change_pct, semaphore) for c in candidates]
    )
    return [f for f in results if f is not None]
