from rest_framework.exceptions import PermissionDenied
from rest_framework.request import Request

from posthog.models import Organization, User
from posthog.permissions import can_in_organization
from posthog.utils import posthoganalytics

from products.authorization.backend.facade import api as authorization
from products.authorization.backend.facade.enums import Action


def require_organization_access_management(request: Request, organization: Organization) -> None:
    authorization.invalidate_session()
    if not can_in_organization(request, organization, Action.MANAGE_ACCESS):
        raise PermissionDenied("You do not have permission to manage organization access.")


def organization_role_grants_enabled(request: Request, organization: Organization) -> bool:
    user = request.user
    return isinstance(user, User) and bool(
        posthoganalytics.feature_enabled(
            "organization-role-access",
            str(user.distinct_id),
            groups={"organization": str(organization.id)},
            only_evaluate_locally=False,
            send_feature_flag_events=False,
        )
    )
