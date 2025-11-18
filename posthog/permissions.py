import time
from typing import Optional, cast

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db.models import Model

import posthoganalytics
from rest_framework.exceptions import AuthenticationFailed, NotFound, PermissionDenied
from rest_framework.permissions import SAFE_METHODS, BasePermission, IsAdminUser
from rest_framework.request import Request
from rest_framework.views import APIView
from rest_framework.viewsets import ViewSet

from posthog.auth import (
    OAuthAccessTokenAuthentication,
    PersonalAPIKeyAuthentication,
    ProjectSecretAPIKeyAuthentication,
    SessionAuthentication,
    SharingAccessTokenAuthentication,
    SharingPasswordProtectedAuthentication,
)
from posthog.cloud_utils import is_cloud
from posthog.constants import AvailableFeature
from posthog.exceptions import Conflict, EnterpriseFeatureException
from posthog.models import Organization, OrganizationMembership, Team, User
from posthog.rbac.user_access_control import AccessControlLevel, UserAccessControl, ordered_access_levels
from posthog.scopes import APIScopeObject, APIScopeObjectOrNotSupported
from posthog.utils import get_can_create_org

CREATE_ACTIONS = ["create", "update"]


def extract_organization(object: Model, view: ViewSet) -> Organization:
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
                try:
                    return object.user.organization  # type: ignore
                except AttributeError:
                    pass
    raise ValueError("Object not compatible with organization-based permissions!")


def get_organization_from_view(view) -> Organization:
    try:
        organization = view.organization
        if isinstance(organization, Organization):
            return organization
    except (KeyError, AttributeError, AssertionError):
        pass

    try:
        organization = view.team.organization
        if isinstance(organization, Organization):
            return organization
    except (KeyError, AttributeError, AssertionError):
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

        # TODO: Optimize this - we can get it from view.user_access_control
        return OrganizationMembership.objects.filter(user=cast(User, request.user), organization=organization).exists()

    def has_object_permission(self, request: Request, view, object: Model) -> bool:
        organization = extract_organization(object, view)

        # TODO: Optimize this - we can get it from view.user_access_control
        return OrganizationMembership.objects.filter(user=cast(User, request.user), organization=organization).exists()


class UserNoOrgMembershipDeletePermission(BasePermission):
    """
    Disallow DELETE on a User if they have any organization memberships.
    """

    message = "Cannot delete user with organization memberships."

    def has_object_permission(self, request, view, obj):
        if request.method == "DELETE" and OrganizationMembership.objects.filter(user=obj).exists():
            raise Conflict(self.message)
        return True


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

        try:
            membership = OrganizationMembership.objects.get(user=cast(User, request.user), organization=organization)
        except OrganizationMembership.DoesNotExist:
            raise NotFound("Organization not found.")

        return membership.level >= OrganizationMembership.Level.ADMIN

    def has_object_permission(self, request: Request, view, object: Model) -> bool:
        if request.method in SAFE_METHODS:
            return True

        # TODO: Optimize so that this computation is only done once, on `OrganizationMemberPermissions`
        organization = extract_organization(object, view)

        try:
            membership = OrganizationMembership.objects.get(user=cast(User, request.user), organization=organization)
        except OrganizationMembership.DoesNotExist:
            raise NotFound("Organization not found.")

        return membership.level >= OrganizationMembership.Level.ADMIN


class TeamMemberAccessPermission(BasePermission):
    """Require effective project membership for any access at all."""

    message = "You don't have access to the project."

    def has_permission(self, request, view) -> bool:
        if is_authenticated_via_project_secret_api_token(request):
            # Ignore the team check for project secret API keys. It's handled by the ProjectSecretAPITokenPermission
            return True

        try:
            view.team  # noqa: B018
        except Team.DoesNotExist:
            return True  # This will be handled as a 404 in the viewset

        # NOTE: The naming here is confusing - "current_team" refers to the team that the user_permissions was initialized with
        # - not the "current_team" property of the user
        requesting_level = view.user_permissions.current_team.effective_membership_level
        return requesting_level is not None


def is_authenticated_via_project_secret_api_token(request: Request) -> bool:
    return isinstance(request.successful_authenticator, ProjectSecretAPIKeyAuthentication)


def _is_request_for_project_secret_api_token_secured_endpoint(request: Request) -> bool:
    return bool(
        request.resolver_match
        and request.resolver_match.view_name
        in {
            "featureflag-local-evaluation",
            "project_feature_flags-remote-config",
            "project_feature_flags-local-evaluation",
            "project_live_debugger_breakpoints-active-breakpoints",
        }
    )


class TeamMemberLightManagementPermission(BasePermission):
    """
    Require effective project membership for read AND update access,
    and at least admin effective project access level for delete.
    """

    message = "You don't have sufficient permissions in the project."

    def has_permission(self, request, view) -> bool:
        try:
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

        if not request.user.organization.is_feature_available(view.premium_feature):  # type: ignore
            raise EnterpriseFeatureException()

        return True


class SharingTokenPermission(BasePermission):
    """
    Validates an authenticated SharingToken against the current request.
    """

    def has_object_permission(self, request, view, object) -> bool:
        if not isinstance(
            request.successful_authenticator, SharingAccessTokenAuthentication | SharingPasswordProtectedAuthentication
        ):
            raise ValueError(
                "SharingTokenPermission only works if SharingAccessTokenAuthentication or SharingPasswordProtectedAuthentication succeeded"
            )
        return request.successful_authenticator.sharing_configuration.can_access_object(object)

    def has_permission(self, request, view) -> bool:
        assert hasattr(
            view, "sharing_enabled_actions"
        ), "SharingTokenPermission requires the `sharing_enabled_actions` attribute to be set in the view"

        if isinstance(
            request.successful_authenticator, SharingAccessTokenAuthentication | SharingPasswordProtectedAuthentication
        ):
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

        allow_if_only_fields = getattr(view, "time_sensitive_allow_if_only_fields", None)
        if allow_if_only_fields and request.method not in SAFE_METHODS:
            data = getattr(request, "data", None)
            data_keys: set[str] = set()
            if data is not None and hasattr(data, "keys"):
                data_keys = {str(key) for key in data.keys()}

            if data_keys and data_keys.issubset(set(allow_if_only_fields)):
                return True

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


class ScopeBasePermission(BasePermission):
    """
    Base class for shared functionality between APIScopePermission and AccessControlPermission
    """

    write_actions: list[str] = ["create", "update", "partial_update", "patch", "destroy"]
    read_actions: list[str] = ["list", "retrieve"]
    scope_object_read_actions: list[str] = []
    scope_object_write_actions: list[str] = []

    def _get_scope_object(self, request, view) -> APIScopeObjectOrNotSupported:
        if not getattr(view, "scope_object", None):
            raise ImproperlyConfigured("APIScopePermission requires the view to define the scope_object attribute.")

        return view.scope_object

    def _get_action(self, request, view) -> str:
        # TRICKY: DRF doesn't have an action for non-detail level "patch" calls which we use sometimes
        if not view.action:
            if request.method == "PATCH" and not view.detail:
                return "patch"
        return view.action

    def _get_required_scopes(self, request, view) -> Optional[list[str]]:
        # If required_scopes is set on the view method then use that
        # Otherwise use the scope_object and derive the required scope from the action
        if getattr(view, "required_scopes", None):
            return view.required_scopes

        # If the view has a dangerously_get_required_scopes method then use that
        # If it returns None then we will use the default behavior
        if hasattr(view, "dangerously_get_required_scopes"):
            required_scopes = view.dangerously_get_required_scopes(request, view)
            if required_scopes:
                return required_scopes

        scope_object = self._get_scope_object(request, view)

        if scope_object == "INTERNAL":
            return None

        action = self._get_action(request, view)
        read_actions = getattr(view, "scope_object_read_actions", self.read_actions)
        write_actions = getattr(view, "scope_object_write_actions", self.write_actions)

        if action in write_actions:
            return [f"{scope_object}:write"]
        elif action in read_actions or request.method == "OPTIONS":
            return [f"{scope_object}:read"]

        return None


class APIScopePermission(ScopeBasePermission):
    """
    The request is via an API key or OAuth token and the user has the appropriate scopes.

    This permission requires that the view has a "scope" attribute which is the base scope required for the action.
    E.g. scope="insight" for a view that requires "insight:read" or "insight:write" for the relevant actions.

    Actions can override this default scope by setting the `required_scopes` attribute on the view method.

    """

    def has_permission(self, request, view) -> bool:
        # NOTE: We do this first to error out quickly if the view is missing the required attribute
        # Helps devs remember to add it.
        self._get_scope_object(request, view)

        # API Scopes apply to PersonalAPIKeyAuthentication and OAuthAccessTokenAuthentication

        if isinstance(request.successful_authenticator, PersonalAPIKeyAuthentication):
            key_scopes = request.successful_authenticator.personal_api_key.scopes
            # TRICKY: Legacy Personal API keys have no scopes and are allowed to do anything
            if not key_scopes:
                return True
        elif isinstance(request.successful_authenticator, OAuthAccessTokenAuthentication):
            # OAuth tokens store scopes as space-separated string
            token_scope_string = request.successful_authenticator.access_token.scope
            key_scopes = token_scope_string.split() if token_scope_string else []
            # OAuth tokens with no scopes should not have access
            if not key_scopes:
                self.message = "OAuth token has no scopes and cannot access this resource"
                return False
        else:
            return True

        required_scopes = self._get_required_scopes(request, view)

        if not required_scopes:
            self.message = f"This action does not support Personal API Key access"
            return False

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
        scope_object = self._get_scope_object(request, view)
        if scope_object == "user":
            return  # The /api/users/@me/ endpoint is exempt from team and org scoping

        self._check_organization_personal_api_key_restrictions(request, view)

        if isinstance(request.successful_authenticator, OAuthAccessTokenAuthentication):
            scoped_organizations = request.successful_authenticator.access_token.scoped_organizations
            scoped_teams = request.successful_authenticator.access_token.scoped_teams
        elif isinstance(request.successful_authenticator, PersonalAPIKeyAuthentication):
            scoped_organizations = request.successful_authenticator.personal_api_key.scoped_organizations
            scoped_teams = request.successful_authenticator.personal_api_key.scoped_teams
        else:
            raise ValueError("Unexpected authentication type")

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

    def _check_organization_personal_api_key_restrictions(self, request, view) -> None:
        """
        Check if the organization being accessed allows personal API keys.
        Admins can always use personal API keys regardless of the organization setting.
        """
        try:
            org = get_organization_from_view(view)
        except ValueError:
            # Indicates this is not an organization scoped view
            return

        if not org.is_feature_available(AvailableFeature.ORGANIZATION_SECURITY_SETTINGS):
            return

        try:
            membership = OrganizationMembership.objects.get(user=cast(User, request.user), organization=org)

            if not org.members_can_use_personal_api_keys and membership.level < OrganizationMembership.Level.ADMIN:
                raise PermissionDenied(
                    f"Organization '{org.name}' does not allow using personal API keys. "
                    f"Contact an admin to enable personal API keys for this organization."
                )
        except OrganizationMembership.DoesNotExist:
            return


class AccessControlPermission(ScopeBasePermission):
    """
    Unified permissions access - controls access to any object based on the user's access controls
    """

    def _get_user_access_control(self, request, view) -> UserAccessControl:
        return view.user_access_control

    def _get_required_access_level(self, request, view) -> Optional[AccessControlLevel]:
        resource = self._get_scope_object(request, view)
        required_scopes = self._get_required_scopes(request, view)

        if resource == "INTERNAL":
            return None

        ordered_access_levels_list = ordered_access_levels(resource)
        # For project and organization, the last two levels are the read and write levels
        # For other resources, since we have the manager level, the last three levels are the read, write, and manager levels
        if resource in ["project", "organization"]:
            READ_LEVEL = ordered_access_levels_list[-2]
            WRITE_LEVEL = ordered_access_levels_list[-1]
        else:
            READ_LEVEL = ordered_access_levels_list[-3]
            WRITE_LEVEL = ordered_access_levels_list[-2]

        if not required_scopes:
            return READ_LEVEL if request.method in SAFE_METHODS else WRITE_LEVEL

        # TODO: This is definitely not right - we need to more safely map the scopes to access levels relevant to the object
        for scope in required_scopes:
            if scope.endswith(":write"):
                return WRITE_LEVEL

        return READ_LEVEL

    def has_object_permission(self, request, view, object) -> bool:
        # At this level we are checking an individual resource - this could be a project or a lower level item like a Dashboard
        # NOTE: If the object is a Team then we shortcircuit here and create a UAC
        # Reason being that there is a loop from view.user_access_control -> view.team -> view.user_access_control
        if isinstance(object, Team):
            uac = UserAccessControl(user=request.user, team=object)
        else:
            uac = self._get_user_access_control(request, view)

        if not uac:
            # If the view doesn't have a user_access_control then it is not supported by this permission scheme
            return True

        required_level = self._get_required_access_level(request, view)

        if not required_level:
            return True

        has_access = uac.check_access_level_for_object(object, required_level=required_level)

        if not has_access:
            self.message = f"You do not have {required_level} access to this resource."
            return False

        return True

    def has_permission(self, request, view) -> bool:
        # At this level we are checking that the user can generically access the resource kind.
        # Primarily we are checking the user's access to the parent resource type (i.e. project, organization)
        # as well as enforcing any global restrictions (e.g. generically only editing of a flag is allowed)

        if is_authenticated_via_project_secret_api_token(request):
            # Ignore the team check for project secret API keys. It's handled by the ProjectSecretAPITokenPermission
            return True

        # Check if the endpoint requires a current team to be set on the user
        if hasattr(view, "param_derived_from_user_current_team"):
            if view.param_derived_from_user_current_team in ("team_id", "project_id"):
                if request.user.current_team_id is None:
                    raise AuthenticationFailed("This endpoint requires a current project to be set on your account.")

        uac = self._get_user_access_control(request, view)
        scope_object = self._get_scope_object(request, view)
        required_level = self._get_required_access_level(request, view)

        team: Team

        try:
            team = view.team
        except (ValueError, KeyError):
            # TODO: Change this to a super specific exception...
            # TODO: Does this means its okay because there is no team level thing?
            return True

        # NOTE: This isn't perfect as it will only optimize for endpoints where the pk matches the obj.id
        # We can't load the actual object as get_object in turn calls the permissions check
        pk = view.kwargs.get("pk")
        uac.preload_access_levels(team=team, resource=cast(APIScopeObject, scope_object), resource_id=pk)

        is_member = uac.check_access_level_for_object(team, required_level="member")

        if not is_member:
            self.message = f"You don't have access to the project."
            return False

        # If the API doesn't have a scope object or a required level for accessing then we can simply allow access
        # as it isn't under access control
        if scope_object == "INTERNAL" or not required_level:
            return True

        # TODO: Scope object should probably be applied against the `required_scopes` attribute
        has_access = uac.check_access_level_for_resource(scope_object, required_level=required_level)
        if has_access:
            return True
        elif view.action == "create":
            # If the user has no access to the resource level, but is trying to create a new object, we should block it
            # Specific object access isn't relevant here as we are trying to create a new object
            self.message = f"You do not have {required_level} access to this resource."
            return False

        # Check if they have specific access to any objects of this resource type
        # This handles the case where a user has "none" access to the resource level
        # but has been granted access to specific objects within that resource type
        has_specific_access = uac.has_any_specific_access_for_resource(scope_object, required_level=required_level)
        if has_specific_access:
            return True

        self.message = f"You do not have {required_level} access to this resource."
        return False


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


class ProjectSecretAPITokenPermission(BasePermission):
    """
    Controls access to the local_evaluation and remote_config endpoints when authenticated via a project secret API token.
    Also validates that the authenticated team matches the resolved team (analogous to TeamMemberAccessPermission for personal keys).
    """

    def has_permission(self, request, view) -> bool:
        if not isinstance(request.successful_authenticator, ProjectSecretAPIKeyAuthentication):
            return True

        # Check that the endpoint is allowed for secret API keys
        if not _is_request_for_project_secret_api_token_secured_endpoint(request):
            return False

        # Check team consistency: authenticated team must match resolved team
        # This prevents cross-team access when project_api_key is provided in request body
        authenticated_team = request.user.team  # From ProjectSecretAPIKeyUser
        try:
            resolved_team = view.team  # From routing logic (may use project_api_key override)
        except (AttributeError, Team.DoesNotExist):
            # If team resolution fails, let it be handled as a 404 in the viewset
            return True

        return authenticated_team.id == resolved_team.id


class UserCanInvitePermission(BasePermission):
    """
    Only allows Admins+, and Members if members_can_invite flag is True
    """

    def has_permission(self, request: Request, view) -> bool:
        user = cast(User, request.user)
        org_invite_settings_available = user.organization and user.organization.is_feature_available(
            AvailableFeature.ORGANIZATION_INVITE_SETTINGS
        )

        if not org_invite_settings_available:
            return True

        try:
            membership = OrganizationMembership.objects.get(user=cast(User, user), organization=user.organization)
        except OrganizationMembership.DoesNotExist:
            raise NotFound("Organization not found.")

        members_can_invite = bool(user.organization and user.organization.members_can_invite)
        user_is_admin = membership.level >= OrganizationMembership.Level.ADMIN

        if user_is_admin:
            return True

        return members_can_invite


class OrganizationInviteSettingsPermission(BasePermission):
    """
    Only Admins+ can update org invite settings
    """

    def has_permission(self, request: Request, view) -> bool:
        user = cast(User, request.user)
        membership = user.organization_memberships.get(organization=user.organization)

        return membership.level >= OrganizationMembership.Level.ADMIN
