import time
from typing import cast

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db.models import Model
from django.views import View
import posthoganalytics
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.permissions import SAFE_METHODS, BasePermission, IsAdminUser
from rest_framework.request import Request
from rest_framework.views import APIView

from posthog.auth import (
    PersonalAPIKeyAuthentication,
    SessionAuthentication,
    SharingAccessTokenAuthentication,
)
from posthog.cloud_utils import is_cloud
from posthog.exceptions import EnterpriseFeatureException
from posthog.models import Organization, OrganizationMembership, Team, User
from posthog.models.personal_api_key import APIScopeObjectOrNotSupported
from posthog.utils import get_can_create_org

CREATE_METHODS = ["POST", "PUT"]


def extract_organization(object: Model, view: View) -> Organization:
    # This is set as part of the TeamAndOrgViewSetMixin to allow models that are not directly related to an organization
    organization_id_rewrite = getattr(view, "filter_rewrite_rules", {}).get("organization_id")
    if organization_id_rewrite:
        for part in organization_id_rewrite.split("__"):
            if part == "organization_id":
                break
            object = getattr(object, part)

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


class SingleTenancyOrAdmin(BasePermission):
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

    def has_object_permission(self, request: Request, view: View, object: Model) -> bool:
        organization = extract_organization(object, view)
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

    def has_object_permission(self, request: Request, view: View, object: Model) -> bool:
        if request.method in SAFE_METHODS:
            return True

        # TODO: Optimize so that this computation is only done once, on `OrganizationMemberPermissions`
        organization = extract_organization(object, view)

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

        if view.premium_feature not in [
            feature["key"]
            for feature in request.user.organization.available_product_features  # type: ignore
        ]:
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
            try:
                view.team  # noqa: B018
                if request.successful_authenticator.sharing_configuration.team != view.team:
                    return False
            except NotFound:
                return False

            return view.action in view.sharing_enabled_actions

        return False


class TimeSensitiveActionPermission(BasePermission):
    """
    Validates that the authenticated session is not older than the allowed time for the action.
    """

    message = "This action requires you to be recently authenticated."

    def has_permission(self, request, view) -> bool:
        if not isinstance(request.successful_authenticator, SessionAuthentication):
            return True

        allow_safe_methods = getattr(view, "time_sensitive_allow_safe_methods", True)

        if allow_safe_methods and request.method in SAFE_METHODS:
            return True

        session_created_at = request.session.get(settings.SESSION_COOKIE_CREATED_AT_KEY)

        if not session_created_at:
            # This should always be covered by the middleware but just in case
            return False

        session_age_seconds = time.time() - session_created_at

        if session_age_seconds > settings.SESSION_SENSITIVE_ACTIONS_AGE:
            return False

        return True


class APIScopePermission(BasePermission):
    """
    The request is via an API key and the user has the appropriate scopes.

    This permission requires that the view has a "scope" attribute which is the base scope required for the action.
    E.g. scope="insight" for a view that requires "insight:read" or "insight:write" for the relevant actions.

    Actions can override this default scope by setting the `required_scopes` attribute on the view method.

    """

    write_actions: list[str] = ["create", "update", "partial_update", "patch", "destroy"]
    read_actions: list[str] = ["list", "retrieve"]
    scope_object_read_actions: list[str] = []
    scope_object_write_actions: list[str] = []

    def _get_action(self, request, view) -> str:
        # TRICKY: DRF doesn't have an action for non-detail level "patch" calls which we use sometimes

        if not view.action:
            if request.method == "PATCH" and not view.detail:
                return "patch"
        return view.action

    def has_permission(self, request, view) -> bool:
        # NOTE: We do this first to error out quickly if the view is missing the required attribute
        # Helps devs remember to add it.
        self.get_scope_object(request, view)

        # API Scopes currently only apply to PersonalAPIKeyAuthentication
        if not isinstance(request.successful_authenticator, PersonalAPIKeyAuthentication):
            return True

        key_scopes = request.successful_authenticator.personal_api_key.scopes

        # TRICKY: Legacy API keys have no scopes and are allowed to do anything, even if the view is unsupported.
        if not key_scopes:
            return True

        required_scopes = self.get_required_scopes(request, view)
        self.check_team_and_org_permissions(request, view)

        if "*" in key_scopes:
            return True

        for required_scope in required_scopes:
            valid_scopes = [required_scope]

            # For all valid scopes with :read we also add :write
            if required_scope.endswith(":read"):
                valid_scopes.append(required_scope.replace(":read", ":write"))

            if not any(scope in key_scopes for scope in valid_scopes):
                self.message = f"API key missing required scope '{required_scope}'"
                return False

        return True

    def check_team_and_org_permissions(self, request, view) -> None:
        scope_object = self.get_scope_object(request, view)
        if scope_object == "user":
            return  # The /api/users/@me/ endpoint is exempt from team and org scoping

        scoped_organizations = request.successful_authenticator.personal_api_key.scoped_organizations
        scoped_teams = request.successful_authenticator.personal_api_key.scoped_teams

        if scoped_teams:
            try:
                team = view.team
                if team.id not in scoped_teams:
                    raise PermissionDenied(f"API key does not have access to the requested project: ID {team.id}.")
            except (KeyError, AttributeError):
                raise PermissionDenied(f"API keys with scoped projects are only supported on project-based endpoints.")

        if scoped_organizations:
            try:
                organization = get_organization_from_view(view)
                if str(organization.id) not in scoped_organizations:
                    raise PermissionDenied(
                        f"API key does not have access to the requested organization: ID {organization.id}."
                    )
            except ValueError:
                # Indicates this is not an organization scoped view
                pass

    def get_required_scopes(self, request, view) -> list[str]:
        # If required_scopes is set on the view method then use that
        # Otherwise use the scope_object and derive the required scope from the action
        if getattr(view, "required_scopes", None):
            return view.required_scopes

        scope_object = self.get_scope_object(request, view)

        if scope_object == "INTERNAL":
            raise PermissionDenied(f"This action does not support Personal API Key access")

        action = self._get_action(request, view)
        read_actions = getattr(view, "scope_object_read_actions", self.read_actions)
        write_actions = getattr(view, "scope_object_write_actions", self.write_actions)

        if action in write_actions:
            return [f"{scope_object}:write"]
        elif action in read_actions or request.method == "OPTIONS":
            return [f"{scope_object}:read"]

        # If we get here this typically means an action was called without a required scope
        # It is essentially "INTERNAL"
        raise PermissionDenied(f"This action does not support Personal API Key access")

    def get_scope_object(self, request, view) -> APIScopeObjectOrNotSupported:
        if not getattr(view, "scope_object", None):
            raise ImproperlyConfigured("APIScopePermission requires the view to define the scope_object attribute.")

        return view.scope_object


class PostHogFeatureFlagPermission(BasePermission):
    def has_permission(self, request, view) -> bool:
        user = cast(User, request.user)
        organization = get_organization_from_view(view)
        flag = getattr(view, "posthog_feature_flag", None)

        config = {}

        if not flag:
            raise ImproperlyConfigured(
                "PostHogFeatureFlagPermission requires the view to define the posthog_feature_flag attribute."
            )

        if isinstance(flag, str):
            config[flag] = ["*"]
        else:
            config = flag

        for required_flag, actions in config.items():
            if "*" in actions or view.action in actions:
                org_id = str(organization.id)

                enabled = posthoganalytics.feature_enabled(
                    required_flag,
                    user.distinct_id,
                    groups={"organization": org_id},
                    group_properties={"organization": {"id": org_id}},
                    only_evaluate_locally=False,
                    send_feature_flag_events=False,
                )

                return enabled or False

        return True
