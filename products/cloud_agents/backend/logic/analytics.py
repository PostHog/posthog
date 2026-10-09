"""Product analytics for cloud_agents, for code that runs in a web request."""

from __future__ import annotations

from typing import Any

import structlog
import posthoganalytics

from posthog.event_usage import groups, report_user_action
from posthog.models import Team, User

from ..facade.contracts import CallerIdentity

logger = structlog.get_logger(__name__)


def capture_event(event: str, caller: CallerIdentity, team_id: int, properties: dict[str, Any]) -> None:
    """Capture one event for the caller. An analytics failure never fails the operation."""
    try:
        team = Team.objects.select_related("organization").filter(id=team_id).first()
        if team is None:
            return
        event_properties = {
            **properties,
            "caller_kind": caller.kind.value,
            "caller_product": caller.product,
        }
        user = User.objects.filter(id=caller.user_id).first() if caller.user_id is not None else None
        if user is not None:
            report_user_action(user, event, event_properties, team=team, organization=team.organization)
            return
        # A caller without a user, for example another product, still has an event to attribute.
        posthoganalytics.capture(
            distinct_id=caller.distinct_id or str(team.uuid),
            event=event,
            properties=event_properties,
            groups=groups(team.organization, team),
        )
    except Exception:
        logger.exception("cloud_agents_analytics_capture_failed", event=event, team_id=team_id)
