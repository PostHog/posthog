from typing import cast

from django.db.models import Model
from django.core.exceptions import ImproperlyConfigured

from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import SAFE_METHODS, BasePermission, IsAdminUser
from rest_framework.request import Request
from rest_framework.views import APIView
from posthog.auth import PersonalAPIKeyAuthentication, SharingAccessTokenAuthentication

from posthog.cloud_utils import is_cloud
from posthog.exceptions import EnterpriseFeatureException
from posthog.models import Organization, OrganizationMembership, Team, User
from posthog.models.personal_api_key import APIScopeObjectOrNotSupported
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

    def has_permission(self, request, *args, **kwargs) -> bool:
        return get_can_create_org(request.user)


class SingleTenancyOrAdmin(BasePermission, type(BasePermission)):
    """
    Allows access to only staff users on cloud.
    """

    message = "You are not an admin."

    def has_permission(self, request, view):
        return not is_cloud() or request.user.is_staff


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
        if request.method in SAFE_METHODS:
            return True

        # When request is not creating (or listing) an `Organization`, an object exists, delegate to `has_object_permission`
        if view.basename == "organizations" and view.action not in ["create"]:
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


class TeamMemberAccessPermission(BasePermission):
    """Require effective project membership for any access at all."""

    message = "You don't have access to the project."

    def has_permission(self, request, view) -> bool:
        try:
            view.team  # noqa: B018
        except Team.DoesNotExist:
            return True  # This will be handled as a 404 in the viewset

        # NOTE: The naming here is confusing - "current_team" refers to the team that the user_permissions was initialized with
        # - not the "current_team" property of the user
        requesting_level = view.user_permissions.current_team.effective_membership_level
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
        requesting_level = view.user_permissions.team(team).effective_membership_level
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
        requesting_level = view.user_permissions.current_team.effective_membership_level
        if requesting_level is None:
            return False
        minimum_level = (
            OrganizationMembership.Level.MEMBER
            if request.method in SAFE_METHODS
            else OrganizationMembership.Level.ADMIN
        )
        return requesting_level >= minimum_level


class IsStaffUser(IsAdminUser):
    message = "You are not a staff user, contact your instance admin."


class PremiumFeaturePermission(BasePermission):
    """
    Requires the user to have proper permission for the feature.
    `premium_feature` must be defined as a view attribute.
    Permission class requires a user in context, should generally be used in conjunction with IsAuthenticated.
    """

    def has_permission(self, request: Request, view: APIView) -> bool:
        assert hasattr(
            view, "premium_feature"
        ), "this permission class requires the `premium_feature` attribute to be set in the view."

        if not request.user or not request.user.organization:  # type: ignore
            return True

        if view.premium_feature not in request.user.organization.available_features:  # type: ignore
            raise EnterpriseFeatureException()

        return True


class SharingTokenPermission(BasePermission):
    """
    Validates an authenticated SharingToken against the current request.
    """

    def has_object_permission(self, request, view, object) -> bool:
        if not isinstance(request.successful_authenticator, SharingAccessTokenAuthentication):
            raise ValueError("SharingTokenPermission only works if SharingAccessTokenAuthentication succeeded")
        return request.successful_authenticator.sharing_configuration.can_access_object(object)

    def has_permission(self, request, view) -> bool:
        assert hasattr(
            view, "sharing_enabled_actions"
        ), "SharingTokenPermission requires the `sharing_enabled_actions` attribute to be set in the view"

        if isinstance(request.successful_authenticator, SharingAccessTokenAuthentication):
            return view.action in view.sharing_enabled_actions

        return False


class APIScopePermission(BasePermission):
    """
    The request is via an API key and the user has the appropriate scopes.

    This permission requires that the view has a "scope" attribute which is the base scope required for the action.
    E.g. scope="insight" for a view that requires "insight:read" or "insight:write" for the relevant actions.

    Actions can override this default scope by setting the `required_scopes` attribute on the view method.

    """

    write_actions = ["create", "update", "partial_update", "destroy"]
    read_actions = ["list", "retrieve"]

    def has_permission(self, request, view):
        # NOTE: We do this first to error out quickly if the view is missing the required attribute
        # Helps devs remember to add it.
        base_scope = self.get_base_scope(request, view)

        # API Scopes currently only apply to PersonalAPIKeyAuthentication
        if not isinstance(request.successful_authenticator, PersonalAPIKeyAuthentication):
            return True

        requester_scopes = request.successful_authenticator.personal_api_key.scopes_list

        # If scopes is not set then full access is granted
        # TODO: Is this correct?
        if not requester_scopes:
            return True

        # LOGIC:
        # 1. Derive the required scope from the action
        # 2. Check if the required scope is in the requester's scopes
        # - If the scope is :read then either :read or :write is enough

        if base_scope == APIScopeObjectOrNotSupported.NOT_SUPPORTED:
            raise PermissionDenied(f"This action does not support Personal API Key access")

        required_scopes = self.derive_required_scopes(request, view, base_scope)

        # TODO: Abstract this into a method that we can reliably test
        for required_scope in required_scopes:
            valid_scopes = [required_scope]

            # For all valid scopes with :read we also add :write
            for scope in valid_scopes:
                if scope.endswith(":read"):
                    valid_scopes.append(scope.replace(":read", ":write"))

            if not valid_scopes:
                # NOTE: This will happen if an @action does not specify a scope
                raise ImproperlyConfigured(
                    f"Valid scopes could not be properly determined. Please ensure the action has `required_scopes` and that it is specific e.g. insights:read"
                )

            if not any(scope in requester_scopes for scope in valid_scopes):
                raise PermissionDenied(f"API key missing required scope: {valid_scopes[0]}")

        return True

    def derive_required_scopes(self, request, view, base_scope: APIScopeObjectOrNotSupported) -> list[str]:
        # If required_scopes is set on the view method then use that
        # Otherwise use the base_scope and derive the required scope from the action

        if hasattr(view, "required_scopes"):
            return view.required_scopes

        if view.action in self.write_actions:
            return [f"{base_scope.value}:write"]
        elif view.action in self.read_actions or request.method == "OPTIONS":
            return [f"{base_scope.value}:read"]

        # If we get here this typically means an action was called without a required scope
        raise ImproperlyConfigured(
            f"Required scopes could not be properly determined. Please ensure the action has `required_scopes` and that it is specific e.g. insights:read"
        )

    def get_base_scope(self, request, view) -> APIScopeObjectOrNotSupported:
        try:
            return view.base_scope
        except AttributeError:
            raise ImproperlyConfigured("APIScopePermission requires the view to define the base_scope attribute.")
