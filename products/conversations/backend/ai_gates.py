"""Which Support AI path a project is on.

Two flags, both keyed on the organization. The first turns Support's AI features on at all. The
second hands the project's tickets to a Self-driving agent, which then replaces Support's own AI
reply workflow for that project.
"""

from __future__ import annotations

import structlog
import posthoganalytics

from posthog.models import Team

logger = structlog.get_logger(__name__)

MASTER_FLAG = "product-support-ai-suggestion-orgs"
SELF_DRIVING_ESCALATION_FLAG = "product-support-self-driving-escalation"


def organization_flag_enabled(team: Team, flag: str) -> bool:
    """Evaluate a flag that is targeted by organization group. A failed evaluation reads as off."""
    # The headless worker only sends the group properties listed here (unlike posthog-js, which
    # auto-attaches full group properties), so a release condition on any other organization property never matches.
    try:
        return bool(
            posthoganalytics.feature_enabled(
                flag,
                str(team.organization_id),
                groups={"organization": str(team.organization_id)},
                group_properties={"organization": {"id": str(team.organization_id)}},
                only_evaluate_locally=False,
                send_feature_flag_events=False,
            )
        )
    except Exception:
        logger.warning("support flag evaluation failed", flag=flag, team_id=team.id, exc_info=True)
        return False


def is_main_environment(team: Team) -> bool:
    return team.parent_team_id is None or team.parent_team_id == team.id


def escalates_directly(team: Team) -> bool:
    """Whether every settled ticket of this project goes to a Self-driving agent.

    True only when Support's own AI gates pass and the escalation flag is on. A child environment
    never escalates directly, because a Self-driving agent runs for a project's main environment only.
    `team.organization` must be loaded.
    """
    settings = team.conversations_settings or {}
    return (
        is_main_environment(team)
        and bool(settings.get("ai_suggestions_enabled", False))
        and bool(team.organization.is_ai_data_processing_approved)
        and organization_flag_enabled(team, MASTER_FLAG)
        and organization_flag_enabled(team, SELF_DRIVING_ESCALATION_FLAG)
    )
