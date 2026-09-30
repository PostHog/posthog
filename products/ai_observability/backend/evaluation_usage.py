from collections.abc import Mapping
from datetime import datetime
from uuid import UUID

from django.conf import settings

import structlog
from cachetools.func import ttl_cache

from posthog.models.team import Team
from posthog.ph_client import ph_background_capture

logger = structlog.get_logger(__name__)


def evaluation_output_usage_properties(
    output_type: str, output_config: Mapping[str, object] | None
) -> dict[str, object]:
    config = output_config or {}
    properties: dict[str, object] = {
        "output_type": output_type,
        "allows_na": bool(config.get("allows_na", False)),
        "has_passing_rule": output_type == "boolean" or config.get("passing_rule") is not None,
    }
    if output_type == "categorical":
        options = config.get("options")
        properties["category_count"] = len(options) if isinstance(options, list) else 0
        properties["selection_mode"] = "multiple" if config.get("selection_mode") == "multiple" else "single"
    return properties


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
