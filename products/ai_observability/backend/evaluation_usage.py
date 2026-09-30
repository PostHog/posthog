from collections.abc import Mapping
from datetime import datetime
from uuid import UUID

from django.conf import settings

import structlog
from cachetools.func import ttl_cache

from posthog.models.team import Team
from posthog.ph_client import ph_background_capture

logger = structlog.get_logger(__name__)


@ttl_cache(maxsize=10_000, ttl=300)
def _usage_groups(team_id: int) -> dict[str, str]:
    team = Team.objects.values("organization_id", "uuid").get(id=team_id)
    return {
        "organization": str(team["organization_id"]),
        "project": str(team["uuid"]),
        "instance": settings.SITE_URL,
    }


def capture_evaluation_usage(
    team_id: int,
    event: str,
    properties: Mapping[str, object],
    *,
    timestamp: datetime | None = None,
    event_uuid: UUID | None = None,
) -> None:
    try:
        groups = _usage_groups(team_id)
        ph_background_capture()(
            distinct_id=f"org-{groups['organization']}",
            event=event,
            properties={"team_id": team_id, **properties},
            groups=groups,
            timestamp=timestamp,
            uuid=event_uuid,
        )
    except Exception:
        logger.warning("evaluation_usage_capture_failed", team_id=team_id, usage_event=event, exc_info=True)
