"""The gates a team must clear before its ticket text may go to an LLM.

Shared so the coordinator and the detection activity apply the same set. An activity can retry
minutes after the coordinator collected it, and turning the master flag off is how a rollout is
rolled back, so the retry has to see the same answer a fresh tick would.
"""

from __future__ import annotations

import structlog
import posthoganalytics

from posthog.models import Team

from products.conversations.backend.temporal.ticket_patterns.constants import MASTER_FLAG

logger = structlog.get_logger(__name__)


def is_master_flag_enabled(team: Team) -> bool:
    # The flag is targeted by project group; release conditions can match on the project's `uuid`,
    # so it must be in group_properties — the headless worker only sends what's listed here (unlike
    # posthog-js, which auto-attaches full group properties). Without it a uuid filter never matches.
    try:
        return bool(
            posthoganalytics.feature_enabled(
                MASTER_FLAG,
                str(team.uuid),
                groups={"organization": str(team.organization_id), "project": str(team.id)},
                group_properties={
                    "organization": {"id": str(team.organization_id)},
                    "project": {"id": str(team.id), "uuid": str(team.uuid)},
                },
                only_evaluate_locally=False,
                send_feature_flag_events=False,
            )
        )
    except Exception:
        # A flag-service blip must skip the team, not fail the whole tick. Fail closed.
        logger.warning("ticket_patterns: master flag eval failed", team_id=team.id, exc_info=True)
        return False


def is_team_eligible(team: Team) -> bool:
    if not team.conversations_enabled:
        return False
    if not (team.conversations_settings or {}).get("ticket_patterns_enabled"):
        return False
    if not team.organization.is_ai_data_processing_approved:
        return False
    return is_master_flag_enabled(team)
