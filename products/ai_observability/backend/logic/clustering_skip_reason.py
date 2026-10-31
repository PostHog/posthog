from django.db import models

from posthog.dataclasses import frozen
from posthog.models.team import Team
from posthog.temporal.ai_observability.clustering_skip_status import ClusteringLevel, get_skip_status

from products.ai_observability.backend.models.clustering_job import ClusteringJob


class ClusteringAnalysisLevel(models.TextChoices):
    TRACE = "trace", "Trace"
    GENERATION = "generation", "Generation"
    EVALUATION = "evaluation", "Evaluation"


class ClusteringSkipReason(models.TextChoices):
    AI_DATA_PROCESSING_NOT_APPROVED = "ai_data_processing_not_approved", "AI data processing not approved"
    NO_ENABLED_JOB = "no_enabled_job", "No enabled job for this level"
    NOT_ENOUGH_ITEMS = "not_enough_items", "Not enough items"
    NOT_SCHEDULED = "not_scheduled", "Not in a recent scheduled run"


@frozen
class ClusteringSkipExplanation:
    reason: ClusteringSkipReason
    item_count: int | None = None
    min_required: int | None = None
    checked_at: str | None = None


def explain_clustering_skip(team: Team, analysis_level: ClusteringLevel) -> ClusteringSkipExplanation:
    """Explain why scheduled clustering has no run for this team and level.

    The checks follow the order of the scheduled pipeline: team discovery drops teams without
    AI data processing consent, the coordinator drops levels without a job, and the compute
    activity drops teams below the item minimum.
    """
    if not team.organization.is_ai_data_processing_approved:
        return ClusteringSkipExplanation(reason=ClusteringSkipReason.AI_DATA_PROCESSING_NOT_APPROVED)

    enabled_levels = set(
        ClusteringJob.objects.filter(team_id=team.id, enabled=True).values_list("analysis_level", flat=True)
    )
    # Trace and generation runs fall back to a legacy job when a team has no enabled job at all.
    has_job = analysis_level in enabled_levels or (analysis_level != "evaluation" and not enabled_levels)
    if not has_job:
        return ClusteringSkipExplanation(reason=ClusteringSkipReason.NO_ENABLED_JOB)

    status = get_skip_status(team.id, analysis_level)
    if status is not None:
        return ClusteringSkipExplanation(
            reason=ClusteringSkipReason.NOT_ENOUGH_ITEMS,
            item_count=status.item_count,
            min_required=status.min_required,
            checked_at=status.checked_at,
        )

    return ClusteringSkipExplanation(reason=ClusteringSkipReason.NOT_SCHEDULED)
