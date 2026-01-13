"""Priority calculation for video segment clustering.

Priority is calculated based on:
- Number of unique users affected
- Average impact score (failure, confusion, abandonment)
- Recency of occurrences
"""

import math
from datetime import UTC, datetime

from posthog.temporal.ai.video_segment_clustering import constants
from posthog.temporal.ai.video_segment_clustering.models import ImpactFlags, SegmentWithImpact, VideoSegmentMetadata


def calculate_impact_score(impact_flags: ImpactFlags) -> float:
    """Calculate impact score from impact flags.

    Args:
        impact_flags: Dictionary with failure, confusion, abandonment flags

    Returns:
        Impact score between 0 and 1
    """
    score = 0.0

    if impact_flags.get("failure_detected", False):
        score += 0.4  # Highest weight for failures/errors

    if impact_flags.get("confusion_detected", False):
        score += 0.3  # Medium weight for user confusion

    if impact_flags.get("abandonment_detected", False):
        score += 0.2  # Weight for user abandonment

    return min(score, 1.0)


def derive_impact_from_content(content: str) -> ImpactFlags:
    """Derive impact flags from segment content text.

    This is a simple heuristic approach that looks for keywords
    indicating failures, confusion, or abandonment.

    Args:
        content: The segment description text

    Returns:
        ImpactFlags with detected indicators
    """
    content_lower = content.lower()

    # Failure indicators
    failure_keywords = [
        "error",
        "failed",
        "failure",
        "exception",
        "crash",
        "not found",
        "404",
        "500",
        "timeout",
        "broken",
        "bug",
        "issue",
        "problem",
        "unexpected",
    ]
    failure_detected = any(kw in content_lower for kw in failure_keywords)

    # Confusion indicators
    confusion_keywords = [
        "confus",
        "struggled",
        "repeatedly",
        "back and forth",
        "multiple attempts",
        "unclear",
        "couldn't find",
        "searched for",
        "looked for",
        "tried to",
    ]
    confusion_detected = any(kw in content_lower for kw in confusion_keywords)

    # Abandonment indicators
    abandonment_keywords = [
        "abandon",
        "gave up",
        "left",
        "exited",
        "closed",
        "navigated away",
        "didn't complete",
        "incomplete",
    ]
    abandonment_detected = any(kw in content_lower for kw in abandonment_keywords)

    return ImpactFlags(
        failure_detected=failure_detected,
        confusion_detected=confusion_detected,
        abandonment_detected=abandonment_detected,
    )


def enrich_segments_with_impact(segments: list[VideoSegmentMetadata]) -> list[SegmentWithImpact]:
    """Add impact scores to segments by deriving from content.

    Args:
        segments: List of video segment metadata

    Returns:
        List of segments with impact data
    """
    result: list[SegmentWithImpact] = []

    for segment in segments:
        impact_flags = derive_impact_from_content(segment.content)
        impact_score = calculate_impact_score(impact_flags)

        result.append(
            SegmentWithImpact(
                segment=segment,
                impact_score=impact_score,
                impact_flags=impact_flags,
            )
        )

    return result


def calculate_recency_factor(
    last_occurrence: datetime | None,
    half_life_days: int = constants.RECENCY_HALF_LIFE_DAYS,
) -> float:
    """Calculate recency factor using exponential decay.

    More recent occurrences get higher weight.

    Args:
        last_occurrence: Timestamp of most recent occurrence
        half_life_days: Number of days for the score to decay by half

    Returns:
        Recency factor between 0 and 1
    """
    if last_occurrence is None:
        return 0.0

    now = datetime.now(UTC)
    if last_occurrence.tzinfo is None:
        last_occurrence = last_occurrence.replace(tzinfo=UTC)

    days_ago = (now - last_occurrence).total_seconds() / (24 * 3600)

    # Exponential decay: score = 0.5^(days_ago / half_life)
    return math.pow(0.5, days_ago / half_life_days)


def calculate_priority_score(
    distinct_user_count: int,
    avg_impact_score: float,
    last_occurrence: datetime | None,
    users_weight: float = constants.USERS_AFFECTED_WEIGHT,
    impact_weight: float = constants.IMPACT_WEIGHT,
    recency_weight: float = constants.RECENCY_WEIGHT,
) -> float:
    """Calculate overall priority score for a task.

    Formula:
        priority = (users_weight * log(1 + user_count))
                 + (impact_weight * avg_impact)
                 + (recency_weight * recency_factor)

    We use log for user count to avoid outliers dominating.

    Args:
        distinct_user_count: Number of unique users affected
        avg_impact_score: Average impact score (0-1)
        last_occurrence: Timestamp of most recent occurrence
        users_weight: Weight for user count component
        impact_weight: Weight for impact component
        recency_weight: Weight for recency component

    Returns:
        Priority score (higher = more urgent)
    """
    # Log scale for user count to prevent outliers
    users_component = users_weight * math.log(1 + distinct_user_count)

    # Impact component (already 0-1)
    impact_component = impact_weight * avg_impact_score

    # Recency component
    recency_factor = calculate_recency_factor(last_occurrence)
    recency_component = recency_weight * recency_factor

    return users_component + impact_component + recency_component


def calculate_task_metrics(
    segments_with_impact: list[SegmentWithImpact],
) -> dict:
    """Calculate aggregate metrics for a task from its segments.

    Args:
        segments_with_impact: List of segments with impact data

    Returns:
        Dictionary with distinct_user_count, avg_impact_score, etc.
    """
    if not segments_with_impact:
        return {
            "distinct_user_count": 0,
            "occurrence_count": 0,
            "avg_impact_score": 0.0,
            "last_occurrence_at": None,
        }

    # Count unique users
    distinct_ids = {swi.segment.distinct_id for swi in segments_with_impact}
    distinct_user_count = len(distinct_ids)

    # Calculate average impact
    total_impact = sum(swi.impact_score for swi in segments_with_impact)
    avg_impact_score = total_impact / len(segments_with_impact)

    # Find most recent occurrence
    timestamps = []
    for swi in segments_with_impact:
        if swi.segment.timestamp:
            try:
                ts = datetime.fromisoformat(swi.segment.timestamp.replace("Z", "+00:00"))
                timestamps.append(ts)
            except ValueError:
                pass

    last_occurrence_at = max(timestamps) if timestamps else None

    return {
        "distinct_user_count": distinct_user_count,
        "occurrence_count": len(segments_with_impact),
        "avg_impact_score": avg_impact_score,
        "last_occurrence_at": last_occurrence_at,
    }
