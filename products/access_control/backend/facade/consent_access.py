from collections.abc import Iterable

from posthog.constants import AvailableFeature
from posthog.models import Organization

from products.access_control.backend.models.access_control import AccessControl


def any_organization_uses_access_controls(organizations: Iterable[Organization]) -> bool:
    """Whether access rules can narrow what a member of one of these organizations reaches.

    An organization qualifies when it has the access-control feature and at least one rule
    exists in one of its projects."""
    entitled = [org.id for org in organizations if org.is_feature_available(AvailableFeature.ACCESS_CONTROL)]
    if not entitled:
        return False
    return AccessControl.objects.filter(team__organization_id__in=entitled).exists()
