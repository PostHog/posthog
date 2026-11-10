from datetime import datetime, timedelta

from django.db.models import Count, Q
from django.utils import timezone

from posthog.dataclasses import frozen
from posthog.models.team import Team
from posthog.models.team.extensions import get_or_create_team_extension

from .models import (
    KnowledgeLearningRun,
    LearningBackfillStatus,
    LearningRunResult,
    LearningRunStatus,
    TeamBusinessKnowledgeConfig,
)
from .temporal.learning.constants import ANALYSIS_VERSION, LEARNING_MAX_LOOKBACK_DAYS


@frozen
class LearningBackfillProgress:
    status: LearningBackfillStatus
    started_at: datetime
    finished_at: datetime | None
    tickets_read: int
    tickets_in_progress: int
    knowledge_created: int


def canonical_team_for_config(team: Team) -> Team:
    if not team.parent_team_id:
        return team
    return Team.objects.get(pk=team.parent_team_id)


def get_team_business_knowledge_config(team: Team) -> TeamBusinessKnowledgeConfig:
    return get_or_create_team_extension(canonical_team_for_config(team), TeamBusinessKnowledgeConfig)


def get_environment_business_knowledge_config(team: Team) -> TeamBusinessKnowledgeConfig:
    """This environment's row. GitHub settings stay here; learning stays on the parent project."""
    return get_or_create_team_extension(team, TeamBusinessKnowledgeConfig)


def set_learn_from_support_enabled(team: Team, enabled: bool) -> TeamBusinessKnowledgeConfig:
    config = get_team_business_knowledge_config(team)
    config.learn_from_support_enabled = enabled
    update_fields = ["learn_from_support_enabled"]
    if not enabled:
        # A paused backfill must not restart by surprise when someone turns learning back on.
        config.learning_backfill_since = None
        config.learning_backfill_started_at = None
        config.learning_backfill_finished_at = None
        config.learning_backfill_cursor = {}
        update_fields += [
            "learning_backfill_since",
            "learning_backfill_started_at",
            "learning_backfill_finished_at",
            "learning_backfill_cursor",
        ]
    config.save(update_fields=update_fields)
    return config


def start_learning_backfill(team: Team) -> TeamBusinessKnowledgeConfig:
    config = get_team_business_knowledge_config(team)
    now = timezone.now()
    config.learning_backfill_since = now - timedelta(days=LEARNING_MAX_LOOKBACK_DAYS)
    config.learning_backfill_started_at = now
    config.learning_backfill_finished_at = None
    config.learning_backfill_cursor = {}
    config.save(
        update_fields=[
            "learning_backfill_since",
            "learning_backfill_started_at",
            "learning_backfill_finished_at",
            "learning_backfill_cursor",
        ]
    )
    return config


def get_learning_backfill_progress(config: TeamBusinessKnowledgeConfig) -> LearningBackfillProgress | None:
    started_at = config.learning_backfill_started_at
    if started_at is None:
        return None
    finished_at = None if config.learning_backfill_since is not None else config.learning_backfill_finished_at
    # Runs carry no origin, so ticket analyses from the regular 7-day pass in this time range count too.
    runs = KnowledgeLearningRun.objects.for_team(config.team_id).filter(
        analysis_version=ANALYSIS_VERSION, created_at__gte=started_at
    )
    if finished_at is not None:
        runs = runs.filter(created_at__lte=finished_at)
    counts = runs.aggregate(
        tickets_read=Count("id", filter=Q(status=LearningRunStatus.COMPLETED)),
        tickets_in_progress=Count("id", filter=Q(status__in=[LearningRunStatus.PENDING, LearningRunStatus.RUNNING])),
        knowledge_created=Count("id", filter=Q(result=LearningRunResult.KNOWLEDGE_CREATED)),
    )
    return LearningBackfillProgress(
        status=LearningBackfillStatus.COMPLETED if finished_at is not None else LearningBackfillStatus.RUNNING,
        started_at=started_at,
        finished_at=finished_at,
        tickets_read=counts["tickets_read"],
        tickets_in_progress=counts["tickets_in_progress"],
        knowledge_created=counts["knowledge_created"],
    )
