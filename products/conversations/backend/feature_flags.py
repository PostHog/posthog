"""Feature-flag checks for the conversations backend.

One module per flag check so rollouts are easy to find and audit. All gates
share the same evaluation settings:

- **Remote evaluation** (``only_evaluate_locally=False``) — no deployment needs a
  local-evaluation personal API key; evaluation goes through PostHog's flags
  endpoint with the project token.
- **Project-group targeting** — the project ``id`` and ``uuid`` ride along in
  ``group_properties`` so a release condition can match on either. The headless
  worker only sends what's listed here (unlike posthog-js, which auto-attaches
  full group properties), so without it a uuid filter never matches.
- ``send_feature_flag_events=False`` — these are control checks, not analytics.
- **Fail-closed** — any error returns ``False`` so a flaky flag call never
  silently enables a feature for everyone.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog
import posthoganalytics

if TYPE_CHECKING:
    from posthog.models.team import Team

logger = structlog.get_logger(__name__)

AI_SUBJECT_GENERATION_FLAG = "conversations-ai-subject-generation"


def is_ai_subject_generation_enabled(team: Team) -> bool:
    """Gate for the AI ticket-subject generator. Keyed on the project group so a
    release condition can target a project by ``id`` or ``uuid``."""
    try:
        return bool(
            posthoganalytics.feature_enabled(
                AI_SUBJECT_GENERATION_FLAG,
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
        logger.warning("conversations ai_subject_generation flag eval failed", team_id=team.id, exc_info=True)
        return False
