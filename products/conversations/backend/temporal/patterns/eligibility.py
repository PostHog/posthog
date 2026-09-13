from __future__ import annotations

import structlog
import posthoganalytics

from posthog.models import Team

from products.conversations.backend.temporal.patterns.constants import MASTER_FLAG

logger = structlog.get_logger(__name__)


def is_pattern_detection_enabled(team: Team) -> bool:
    """Cheapest gates first: the two settings are already loaded, the flag is a network call."""
    if not team.conversations_enabled:
        return False
    if not (team.conversations_settings or {}).get("pattern_detection_enabled"):
        return False
    return _is_master_flag_enabled(team)


def _is_master_flag_enabled(team: Team) -> bool:
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
