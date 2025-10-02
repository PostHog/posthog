from datetime import timedelta
from typing import Optional

from django.utils import timezone

from posthog.constants import AvailableFeature
from posthog.models import Organization


def get_activity_log_lookback_restriction(organization: Organization) -> Optional[timezone.datetime]:
    """Get the lookback restriction date based on the AUDIT_LOGS feature."""
    audit_log_feature = organization.get_available_feature(AvailableFeature.AUDIT_LOGS)

    if not audit_log_feature:
        return None

    limit = audit_log_feature.get("limit")
    unit = audit_log_feature.get("unit")

    if limit is None or unit is None:
        return None

    unit_lower = unit.lower()
    if unit_lower in ("day", "days"):
        delta = timedelta(days=limit)
    elif unit_lower in ("month", "months"):
        delta = timedelta(days=limit * 30)
    elif unit_lower in ("year", "years"):
        delta = timedelta(days=limit * 365)
    else:
        return None

    return timezone.now() - delta
