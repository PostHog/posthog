from datetime import datetime, timedelta
from typing import Optional

from django.utils import timezone

from posthog.constants import AvailableFeature
from posthog.models import Organization

from .constants import ADVANCED_ACTIVITY_LOGS_LOOKBACK_FALLBACK_LIMIT, ADVANCED_ACTIVITY_LOGS_LOOKBACK_FALLBACK_UNIT


def get_activity_log_lookback_restriction(organization: Organization) -> Optional[datetime]:
    """Get the lookback restriction date based on the AUDIT_LOGS feature."""
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
        delta = timedelta(days=limit)
    elif unit_lower in ("month", "months"):
        delta = timedelta(days=limit * 30)
    elif unit_lower in ("year", "years"):
        delta = timedelta(days=limit * 365)
    else:
        raise ValueError(f"Invalid unit: {unit}")

    return timezone.now() - delta
