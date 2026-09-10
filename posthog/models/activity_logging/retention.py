from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Optional

from django.utils import timezone

import structlog

from posthog.constants import AvailableFeature

logger = structlog.get_logger(__name__)

if TYPE_CHECKING:
    from posthog.models.organization import Organization
    from posthog.models.team.team import Team

# Smallest window billing sells: Boost gets 7 days, Scale 2 months, Enterprise 60 months. Only those
# packages carry the feature at all, so this fallback is reached by an entitled organization whose
# entitlement is malformed, never by one that bought no activity logs. Falling back to the smallest
# window keeps such an organization inside what any plan grants rather than above it.
ADVANCED_ACTIVITY_LOGS_LOOKBACK_FALLBACK_LIMIT = 7
ADVANCED_ACTIVITY_LOGS_LOOKBACK_FALLBACK_UNIT = "days"


def _lookback_window(organization: "Organization") -> Optional[timedelta]:
    """How far back the organization may read activity logs, or None when unrestricted."""
    audit_log_feature = organization.get_available_feature(AvailableFeature.AUDIT_LOGS)

    if not audit_log_feature:
        return None

    limit = audit_log_feature.get("limit")
    unit = audit_log_feature.get("unit")

    if limit is None or unit is None:
        logger.warning(
            "activity_log_retention.entitlement_missing_window",
            organization_id=str(organization.id),
            limit=limit,
            unit=unit,
        )
        limit = ADVANCED_ACTIVITY_LOGS_LOOKBACK_FALLBACK_LIMIT
        unit = ADVANCED_ACTIVITY_LOGS_LOOKBACK_FALLBACK_UNIT

    unit_lower = unit.lower()
    if unit_lower in ("day", "days"):
        return timedelta(days=limit)
    elif unit_lower in ("month", "months"):
        return timedelta(days=limit * 30)
    elif unit_lower in ("year", "years"):
        return timedelta(days=limit * 365)

    # Both surfaces that read this run outside HogQL's error handling — the printer and
    # `HogQLQueryRunner.get_cache_payload` — so raising here would 500 every query naming
    # system.activity_logs rather than surface a query error. Fall back to the smallest window
    # instead: a unit billing has not used before must not widen what anyone can read.
    logger.warning(
        "activity_log_retention.entitlement_unknown_unit",
        organization_id=str(organization.id),
        limit=limit,
        unit=unit,
    )
    return timedelta(days=ADVANCED_ACTIVITY_LOGS_LOOKBACK_FALLBACK_LIMIT)


def get_activity_log_lookback_restriction(organization: "Organization") -> Optional[datetime]:
    """Get the lookback restriction date based on the AUDIT_LOGS feature."""
    window = _lookback_window(organization)
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
