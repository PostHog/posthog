from posthog.models.team import Team
from posthog.models.team.extensions import get_or_create_team_extension

from .models import TeamBusinessKnowledgeConfig


def canonical_team_for_config(team: Team) -> Team:
    if not team.parent_team_id:
        return team
    return Team.objects.get(pk=team.parent_team_id)


def get_team_business_knowledge_config(team: Team) -> TeamBusinessKnowledgeConfig:
    return get_or_create_team_extension(canonical_team_for_config(team), TeamBusinessKnowledgeConfig)


def set_learn_from_support_enabled(team: Team, enabled: bool) -> TeamBusinessKnowledgeConfig:
    config = get_team_business_knowledge_config(team)
    config.learn_from_support_enabled = enabled
    config.save(update_fields=["learn_from_support_enabled"])
    return config
