from typing import TYPE_CHECKING

import structlog
import posthoganalytics

if TYPE_CHECKING:
    from posthog.models import Team

logger = structlog.get_logger(__name__)

# Pre-release templates a team can neither see nor use until it has the named feature flag:
# the authenticated template list drops them, and workflow validation rejects them as
# "Template not found". The flag key is shared with FEATURE_FLAGS in
# frontend/src/lib/constants.tsx. Remove an entry when its feature goes GA.
FLAG_GATED_TEMPLATE_IDS = {
    "template-posthog-create-task": "workflow-ai-task-action",
    "template-posthog-classify": "workflow-classify-action",
    "template-posthog-add-to-static-cohort": "workflow-add-to-static-cohort-action",
    "template-posthog-opt-out-of-messages": "workflow-opt-out-of-messages-action",
}


def gated_template_enabled(flag_key: str, team: "Team") -> bool:
    # A flag-eval blip hides the pre-release template rather than exposing it: fail closed.
    try:
        return bool(
            posthoganalytics.feature_enabled(
                flag_key,
                str(team.uuid),
                groups={"organization": str(team.organization_id), "project": str(team.id)},
                group_properties={
                    "organization": {"id": str(team.organization_id)},
                    # A team id repeats across PostHog instances (self-hosted, local dev), so a flag that
                    # must reach one project matches on the uuid.
                    "project": {"id": str(team.id), "uuid": str(team.uuid)},
                },
            )
        )
    except Exception:
        logger.warning(
            "cdp.gated_template_flag_check_failed_defaulting_off",
            team_id=team.id,
            flag=flag_key,
            exc_info=True,
        )
        return False


def hidden_gated_template_ids(team: "Team") -> list[str]:
    """Template ids this team must not see, per the flag map above."""
    return [
        template_id
        for template_id, flag_key in FLAG_GATED_TEMPLATE_IDS.items()
        if not gated_template_enabled(flag_key, team)
    ]
