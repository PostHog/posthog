from datetime import timedelta

from django.utils import timezone

from posthog.models.team import Team
from posthog.models.team.extensions import get_or_create_team_extension

from .models import TeamBusinessKnowledgeConfig
from .temporal.learning.constants import LEARNING_MAX_LOOKBACK_DAYS


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
        update_fields.append("learning_backfill_since")
    config.save(update_fields=update_fields)
    return config


def start_learning_backfill(team: Team) -> TeamBusinessKnowledgeConfig:
    config = get_team_business_knowledge_config(team)
    config.learning_backfill_since = timezone.now() - timedelta(days=LEARNING_MAX_LOOKBACK_DAYS)
    config.learning_backfill_cursor = {}
    config.save(update_fields=["learning_backfill_since", "learning_backfill_cursor"])
    return config
