from django.conf import settings
from django.db.models import Model
from rest_framework.permissions import SAFE_METHODS, BasePermission
from rest_framework.request import Request

from posthog.models import Organization, OrganizationMembership
from posthog.models.user import User

CREATE_METHODS = ["POST", "PUT"]


def extract_organization(object: Model) -> Organization:
    if isinstance(object, Organization):
        return object
    try:
        return object.organization  # type: ignore
    except AttributeError:
        try:
            return object.team.organization  # type: ignore
        except AttributeError:
            try:
                return object.project.organization  # type: ignore
            except AttributeError:
                pass
    raise ValueError("Object not compatible with organization-based permissions!")


class UninitiatedOrCloudOnly(BasePermission):
    """Only enable endpoint on uninitiated instances or on PostHog Cloud."""

    message = "This endpoint is unavailable on initiated self-hosted instances of PostHog."

    def has_permission(self, request: Request, view) -> bool:
        return settings.MULTI_TENANCY or not User.objects.exists()


class ProjectMembershipNecessaryPermissions(BasePermission):
    """Require organization and project membership to access endpoint."""

    message = "You don't belong to any organization that has a project."

    def has_object_permission(self, request: Request, view, object) -> bool:
        return request.user.team is not None


class OrganizationMembershipNecessaryPermissions(BasePermission):
    """Require organization membership to access endpoint."""

    message = "You don't belong to any organization."

    def has_object_permission(self, request: Request, view, object) -> bool:
        return request.user.organization is not None


class OrganizationMemberPermissions(BasePermission):
    """Require relevant organization membership to access object."""

    message = "You don't belong to the relevant organization."

    def has_object_permission(self, request: Request, view, object: Model) -> bool:
        organization = extract_organization(object)
        return OrganizationMembership.objects.filter(user=request.user, organization=organization).exists()


class OrganizationAdminWritePermissions(BasePermission):
    """Require organization admin level to change object, allowing everyone read."""

    message = "Your organization access level is insufficient."

    def has_object_permission(self, request: Request, view, object: Model) -> bool:
        if request.method in SAFE_METHODS:
            return True
        organization = extract_organization(object)
        return (
            OrganizationMembership.objects.get(user=request.user, organization=organization).level
            >= OrganizationMembership.Level.ADMIN
        )


class OrganizationAdminAnyPermissions(BasePermission):
    """Require organization admin level to change and also read object."""

    message = "Your organization access level is insufficient."

    def has_object_permission(self, request: Request, view, object: Model) -> bool:
        organization = extract_organization(object)
        return (
            OrganizationMembership.objects.get(user=request.user, organization=organization).level
            >= OrganizationMembership.Level.ADMIN
        )
