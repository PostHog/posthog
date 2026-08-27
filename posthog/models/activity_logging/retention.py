from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Optional

from django.utils import timezone

from posthog.constants import AvailableFeature

if TYPE_CHECKING:
    from posthog.models.organization import Organization
    from posthog.models.team.team import Team

# Fallbacks need to be kept in sync with the smallest AUDIT_LOG feature limits in billing
ADVANCED_ACTIVITY_LOGS_LOOKBACK_FALLBACK_LIMIT = 2
ADVANCED_ACTIVITY_LOGS_LOOKBACK_FALLBACK_UNIT = "months"


def get_activity_log_lookback_window(organization: "Organization") -> Optional[timedelta]:
    """How far back the organization may read activity logs, or None when unrestricted.

    Split out from `get_activity_log_lookback_restriction` so callers that must not move with the
    clock — notably the query cache key, which has to change on a downgrade but not on every
    request — can vary on the window itself rather than on a timestamp.
    """
    audit_log_feature = organization.get_available_feature(AvailableFeature.AUDIT_LOGS)

    if not audit_log_feature:
        return None

    limit = audit_log_feature.get("limit")
    unit = audit_log_feature.get("unit")

    if limit is None or unit is None:
        limit = ADVANCED_ACTIVITY_LOGS_LOOKBACK_FALLBACK_LIMIT
        unit = ADVANCED_ACTIVITY_LOGS_LOOKBACK_FALLBACK_UNIT

    unit_lower = unit.lower()
    if unit_lower in ("day", "days"):
        return timedelta(days=limit)
    elif unit_lower in ("month", "months"):
        return timedelta(days=limit * 30)
    elif unit_lower in ("year", "years"):
        return timedelta(days=limit * 365)

    raise ValueError(f"Invalid unit: {unit}")


def get_activity_log_lookback_restriction(organization: "Organization") -> Optional[datetime]:
    """Get the lookback restriction date based on the AUDIT_LOGS feature."""
    window = get_activity_log_lookback_window(organization)
    return None if window is None else timezone.now() - window


def activity_log_retention_start_for_team(team: Optional["Team"], team_id: Optional[int]) -> Optional[datetime]:
    """Oldest `created_at` a team may read activity logs back to, or None if unrestricted.

    Wraps `get_activity_log_lookback_restriction` for callers that hold a team rather than an
    organization, so the SQL surface and the REST viewsets derive the window from one place.
    Resolved lazily by the printer, and only for a query that actually reads a retention-bearing
    table, so ordinary queries never pay the organization load.
    """
    from posthog.models.team.team import Team  # noqa: PLC0415 (avoids a models import cycle)

    if team is None:
        if team_id is None:
            return None
        team = Team.objects.filter(id=team_id).select_related("organization").first()
        if team is None:
            return None

    return get_activity_log_lookback_restriction(team.organization)
