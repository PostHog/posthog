from typing import cast

from django.conf import settings
from django.db.models import Model
from rest_framework.permissions import SAFE_METHODS, BasePermission
from rest_framework.request import Request

from posthog.constants import AvailableFeature
from posthog.models import Organization, OrganizationMembership, Team, User
from posthog.utils import get_can_create_org

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


def get_organization_from_view(view) -> Organization:
    try:
        organization = view.organization
        if isinstance(organization, Organization):
            return organization
    except (KeyError, AttributeError):
        pass

    try:
        organization = view.team.organization
        if isinstance(organization, Organization):
            return organization
    except (KeyError, AttributeError):
        pass

    raise ValueError("View not compatible with organization-based permissions!")


class CanCreateOrg(BasePermission):
    """Whether new organizations can be created in this instances."""

    message = "New organizations cannot be created in this instance. Contact your administrator if you think this is a mistake."

    def has_permission(self, *args, **kwargs) -> bool:
        return get_can_create_org()


class SingleTenancyOrAdmin(BasePermission):
    """
    Allows access to only staff users on cloud.
    """

    message = "You are not an admin."

    def has_permission(self, request, view):
        return not settings.MULTI_TENANCY or request.user.is_staff


class ProjectMembershipNecessaryPermissions(BasePermission):
    """Require organization and project membership to access endpoint."""

    message = "You don't belong to any organization that has a project."

    # TODO: Remove this permission class once legacy_team_compatibility setting is removed
    def has_object_permission(self, request: Request, view, object) -> bool:
        return request.user.is_authenticated and request.user.team is not None


class OrganizationMembershipNecessaryPermissions(BasePermission):
    """Require organization membership to access endpoint."""

    message = "You don't belong to any organization."

    # TODO: Remove this permission class once legacy_team_compatibility setting is removed
    def has_object_permission(self, request: Request, view, object) -> bool:
        return request.user.is_authenticated and request.user.organization is not None


class OrganizationMemberPermissions(BasePermission):
    """
    Require relevant organization membership to access object.
    Returns a generic permission denied response.
    Note: For POST requests, it will **only** work with nested routers that derive from an Organization or Project (Team).
    """

    def has_permission(self, request: Request, view) -> bool:
        # When request is not creating or listing an `Organization`, an object exists, delegate to `has_object_permission`
        if view.basename == "organizations" and view.action not in ["list", "create"]:
            return True

        organization = get_organization_from_view(view)

        return OrganizationMembership.objects.filter(user=cast(User, request.user), organization=organization).exists()

    def has_object_permission(self, request: Request, view, object: Model) -> bool:
        organization = extract_organization(object)
        return OrganizationMembership.objects.filter(user=cast(User, request.user), organization=organization).exists()


class OrganizationAdminWritePermissions(BasePermission):
    """
    Require organization admin or owner level to change object, allowing everyone read.
    Must always be used **after** `OrganizationMemberPermissions` (which is always required).
    Note: For POST requests, it will **only** work with nested routers that derive from an Organization or Project (Team).
    """

    message = "Your organization access level is insufficient."

    def has_permission(self, request: Request, view) -> bool:

        # When request is not creating or listing an `Organization`, an object exists, delegate to `has_object_permission`
        if view.basename == "organizations" and view.action not in ["list", "create"]:
            return True

        # TODO: Optimize so that this computation is only done once, on `OrganizationMemberPermissions`
        organization = get_organization_from_view(view)

        return (
            OrganizationMembership.objects.get(user=cast(User, request.user), organization=organization).level
            >= OrganizationMembership.Level.ADMIN
        )

    def has_object_permission(self, request: Request, view, object: Model) -> bool:

        if request.method in SAFE_METHODS:
            return True

        # TODO: Optimize so that this computation is only done once, on `OrganizationMemberPermissions`
        organization = extract_organization(object)

        return (
            OrganizationMembership.objects.get(user=cast(User, request.user), organization=organization).level
            >= OrganizationMembership.Level.ADMIN
        )


class OrganizationAdminAnyPermissions(BasePermission):
    """Require organization admin level to change and also read object."""

    message = "Your organization access level is insufficient."

    def has_object_permission(self, request: Request, view, object: Model) -> bool:
        organization = extract_organization(object)
        return (
            OrganizationMembership.objects.get(user=cast(User, request.user), organization=organization).level
            >= OrganizationMembership.Level.ADMIN
        )


class TeamMemberAccessPermission(BasePermission):
    """Require effective project membership for any access at all."""

    message = "You don't have access to the project."

    def has_permission(self, request, view) -> bool:
        try:
            team = view.team
        except Team.DoesNotExist:
            return True  # This will be handled as a 404 in the viewset
        requesting_level = team.get_effective_membership_level(cast(User, request.user))
        return requesting_level is not None


class TeamMemberLightManagementPermission(BasePermission):
    """
    Require effective project membership for read AND update access,
    and at least admin effective project access level for delete.
    """

    message = "You don't have sufficient permissions in the project."

    def has_permission(self, request, view) -> bool:
        try:
            if request.resolver_match.url_name.startswith("team-"):
                # /projects/ endpoint handling
                team = view.get_object()
            else:
                team = view.team
        except Team.DoesNotExist:
            return True  # This will be handled as a 404 in the viewset
        requesting_level = team.get_effective_membership_level(cast(User, request.user))
        if requesting_level is None:
            return False
        minimum_level = (
            OrganizationMembership.Level.MEMBER if request.method != "DELETE" else OrganizationMembership.Level.ADMIN
        )
        return requesting_level >= minimum_level


class TeamMemberStrictManagementPermission(BasePermission):
    """
    Require effective project membership for read access,
    and at least admin effective project access level for delete AND update.
    """

    message = "You don't have sufficient permissions in the project."

    def has_permission(self, request, view) -> bool:
        team = view.team
        requesting_level = team.get_effective_membership_level(cast(User, request.user))
        if requesting_level is None:
            return False
        minimum_level = (
            OrganizationMembership.Level.MEMBER
            if request.method in SAFE_METHODS
            else OrganizationMembership.Level.ADMIN
        )
        return requesting_level >= minimum_level
