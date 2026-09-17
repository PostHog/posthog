from posthog.constants import AvailableFeature
from posthog.models import Organization

from products.access_control.backend.models.access_control import AccessControl


def organization_uses_access_controls(organization: Organization) -> bool:
    """Whether access rules can narrow what a member reaches: the organization has the
    access-control feature and at least one rule exists in one of its projects."""
    if not organization.is_feature_available(AvailableFeature.ACCESS_CONTROL):
        return False
    return AccessControl.objects.filter(team__organization=organization).exists()
