from functools import cached_property, lru_cache
from typing import TYPE_CHECKING, Any, Literal, Optional, cast
from uuid import UUID

from django.db.models.query import QuerySet

from rest_framework.exceptions import AuthenticationFailed, NotFound, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.viewsets import GenericViewSet
from rest_framework_extensions.routers import ExtendedDefaultRouter
from rest_framework_extensions.settings import extensions_api_settings

from posthog.api.utils import get_token
from posthog.auth import (
    JwtAuthentication,
    OAuthAccessTokenAuthentication,
    PersonalAPIKeyAuthentication,
    SessionAuthentication,
    SharingAccessTokenAuthentication,
    SharingPasswordProtectedAuthentication,
)
from posthog.clickhouse.query_tagging import tag_queries
from posthog.models.organization import Organization
from posthog.models.project import Project
from posthog.models.team import Team
from posthog.models.user import User
from posthog.permissions import (
    AccessControlPermission,
    APIScopePermission,
    OrganizationMemberPermissions,
    SharingTokenPermission,
    TeamMemberAccessPermission,
)
from posthog.rbac.user_access_control import UserAccessControl
from posthog.scopes import APIScopeObjectOrNotSupported
from posthog.user_permissions import UserPermissions

if TYPE_CHECKING:
    _GenericViewSet = GenericViewSet
else:
    _GenericViewSet = object


class DefaultRouterPlusPlus(ExtendedDefaultRouter):
    """DefaultRouter with optional trailing slash and drf-extensions nesting."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.trailing_slash = r"/?"


# NOTE: Previously known as the StructuredViewSetMixin
# IMPORTANT: Almost all viewsets should inherit from this mixin. It should be the first thing it inherits from to ensure
# that typing works as expected
class TeamAndOrgViewSetMixin(_GenericViewSet):  # TODO: Rename to include "Env" in name
    # This flag disables nested routing handling, reverting to the old request.user.team behavior
    # Allows for a smoother transition from the old flat API structure to the newer nested one
    param_derived_from_user_current_team: Optional[Literal["team_id", "project_id"]] = None

    # Rewrite filter queries, so that for example foreign keys can be accessed
    # Example: {"team_id": "foo__team_id"} will make the viewset filtered by obj.foo.team_id instead of obj.team_id
    filter_rewrite_rules: dict[str, str] = {}

    authentication_classes = []
    permission_classes = []

    # NOTE: Could we type this? Would be pretty cool as a helper
    scope_object: Optional[APIScopeObjectOrNotSupported] = None
    required_scopes: Optional[list[str]] = None
    sharing_enabled_actions: list[str] = []

    def __init_subclass__(cls, **kwargs):
        """
        This class plays a crucial role in ensuring common permissions, authentication and filtering.
        As such, we use this clever little trick to ensure that the user of it doesn't accidentally override the important methods.
        """
        super().__init_subclass__(**kwargs)
        protected_methods = {
            "get_queryset": "Use safely_get_queryset instead",
            "get_object": "Use safely_get_object instead",
            "get_permissions": "Add additional 'permission_classes' via the class attribute instead. Or in exceptional use cases use dangerously_get_permissions instead",
            "get_authenticators": "Add additional 'authentication_classes' via the class attribute instead",
        }

        for method, message in protected_methods.items():
            if method in cls.__dict__:
                raise Exception(f"Method {method} is protected and should not be overridden. {message}")

    def dangerously_get_permissions(self):
        """
        WARNING: This should be used very carefully. It is only for endpoints with very specific permission needs.
        If you want to add to the defaults simply set `permission_classes` instead.
        """
        raise NotImplementedError()

    # We want to try and ensure that the base permission and authentication are always used
    # so we offer a way to add additional classes
    def get_permissions(self):
        try:
            return self.dangerously_get_permissions()
        except NotImplementedError:
            pass

        if isinstance(
            self.request.successful_authenticator,
            SharingAccessTokenAuthentication | SharingPasswordProtectedAuthentication,
        ):
            return [SharingTokenPermission()]

        # NOTE: We define these here to make it hard _not_ to use them. If you want to override them, you have to
        # override the entire method.
        permission_classes: list = [IsAuthenticated, APIScopePermission, AccessControlPermission]

        if self._is_team_view or self._is_project_view:
            permission_classes.append(TeamMemberAccessPermission)
        else:
            permission_classes.append(OrganizationMemberPermissions)

        permission_classes.extend(self.permission_classes)
        return [permission() for permission in permission_classes]

    def get_authenticators(self):
        # NOTE: Custom authentication_classes go first as these typically have extra initial checks
        authentication_classes: list = [
            *self.authentication_classes,
        ]

        if self.sharing_enabled_actions:
            authentication_classes.append(SharingPasswordProtectedAuthentication)
            authentication_classes.append(SharingAccessTokenAuthentication)

        authentication_classes.extend(
            [JwtAuthentication, OAuthAccessTokenAuthentication, PersonalAPIKeyAuthentication, SessionAuthentication]
        )

        return [auth() for auth in authentication_classes]

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        """
        We don't want to ever allow overriding the get_queryset as the filtering is an important security aspect.
        Instead we provide this method to override and provide additional queryset filtering.
        """
        raise NotImplementedError()

    def dangerously_get_queryset(self) -> QuerySet:
        """
        WARNING: This should be used very carefully. It bypasses all common filtering logic such as team and org filtering.
        It is so named to make it clear that this should be checked whenever changes to access control logic changes.
        """
        raise NotImplementedError()

    def get_queryset(self) -> QuerySet:
        # Add a recursion guard
        if getattr(self, "_in_get_queryset", False):
            return super().get_queryset()

        try:
            self._in_get_queryset = True

            try:
                return self.dangerously_get_queryset()
            except NotImplementedError:
                pass

            queryset = super().get_queryset()
            # First of all make sure we do the custom filters before applying our own
            try:
                queryset = self.safely_get_queryset(queryset)
            except NotImplementedError:
                pass

            queryset = self._filter_queryset_by_parents_lookups(queryset)

            queryset = self._filter_queryset_by_access_level(queryset)

            return queryset
        finally:
            self._in_get_queryset = False

    def _filter_queryset_by_access_level(self, queryset: QuerySet) -> QuerySet:
        if self.action != "list":
            # NOTE: If we are getting an individual object then we don't filter it out here - this is handled by the permission logic
            # The reason being, that if we filter out here already, we can't load the object which is required for checking access controls for it
            return queryset

        # NOTE: Half implemented - for admins, they may want to include listing of results that are not accessible (like private resources)
        include_all_if_admin = self.request.GET.get("admin_include_all") == "true"

        # Additionally "projects" is a special one where we always want to include all projects if you're an org admin
        if self.scope_object == "project":
            include_all_if_admin = True

        # "insights" are a special case where we want to use include_all_if_admin if listing with short_id because
        # individual insights are retrieved
        if self.scope_object == "insight" and self.request.GET.get("short_id") is not None:
            include_all_if_admin = True

        return self.user_access_control.filter_queryset_by_access_level(
            queryset, include_all_if_admin=include_all_if_admin
        )

    def dangerously_get_object(self) -> Any:
        """
        WARNING: This should be used very carefully. It bypasses common security access control checks.
        """
        raise NotImplementedError()

    def safely_get_object(self, queryset: QuerySet) -> Any:
        raise NotImplementedError()

    def get_object(self):
        """
        We don't want to allow generic overriding of get_object as under the hood it does
        check_object_permissions which if not called is a security issue
        """

        try:
            return self.dangerously_get_object()
        except NotImplementedError:
            pass

        queryset = self.filter_queryset(self.get_queryset())

        try:
            obj = self.safely_get_object(queryset)
            if not obj:
                raise NotFound()
        except NotImplementedError:
            return super().get_object()

        # Ensure we always check permissions
        self.check_object_permissions(self.request, obj)

        return obj

    @property
    def _is_team_view(self):
        return self.param_derived_from_user_current_team == "team_id" or "team_id" in self.parent_query_kwargs

    @property
    def _is_project_view(self):
        return self.param_derived_from_user_current_team == "project_id" or "project_id" in self.parent_query_kwargs

    @cached_property
    def team_id(self) -> int:
        if self._is_project_view:
            team_id = self.project_id  # KLUDGE: This is just for the period of transition to project environments
        elif team_from_token := self._get_team_from_request():
            team_id = team_from_token.id
        elif self.param_derived_from_user_current_team == "team_id":
            user = cast(User, self.request.user)
            team = user.team
            assert team is not None
            team_id = team.id
        else:
            team_id = self.parents_query_dict["team_id"]
        tag_queries(team_id=team_id)
        return team_id

    @cached_property
    def team(self) -> Team:
        if team_from_token := self._get_team_from_request():
            team = team_from_token
        elif self._is_project_view:
            team = Team.objects.get(
                id=self.project_id  # KLUDGE: This is just for the period of transition to project environments
            )
        elif self.param_derived_from_user_current_team == "team_id":
            user = cast(User, self.request.user)
            assert user.team is not None
            team = user.team
        else:
            try:
                team = Team.objects.get(id=self.team_id)
            except Team.DoesNotExist:
                raise NotFound(
                    detail="Project not found."  # TODO: "Environment" instead of "Project" when project environments are rolled out
                )

        tag_queries(team_id=team.pk)
        return team

    @cached_property
    def project_id(self) -> int:
        if team_from_token := self._get_team_from_request():
            project_id = team_from_token.project_id

        elif self.param_derived_from_user_current_team == "project_id":
            user = cast(User, self.request.user)
            team = user.team
            assert team is not None
            project_id = team.project_id
        else:
            project_id = self.parents_query_dict["project_id"]

        tag_queries(team_id=project_id)
        return project_id

    @cached_property
    def project(self) -> Project:
        if self.param_derived_from_user_current_team == "project_id":
            user = cast(User, self.request.user)
            team = user.team
            assert team is not None
            assert team.project is not None
            return team.project
        try:
            return Project.objects.get(id=self.project_id)
        except Project.DoesNotExist:
            raise NotFound(detail="Project not found.")

    @cached_property
    def organization_id(self) -> str:
        try:
            return self.parents_query_dict["organization_id"]
        except KeyError:
            user = cast(User, self.request.user)
            current_organization_id: Optional[UUID]
            if self._is_team_view:
                # TODO: self.team.project.organization_id when project environments are rolled out
                current_organization_id = self.team.organization_id
            if self._is_project_view:
                current_organization_id = self.project.organization_id
            elif user:
                current_organization_id = user.current_organization_id

            if not current_organization_id:
                raise NotFound("You need to belong to an organization.")
            return str(current_organization_id)

    @cached_property
    def organization(self) -> Organization:
        try:
            return Organization.objects.get(id=self.organization_id)
        except Organization.DoesNotExist:
            raise NotFound(detail="Organization not found.")

    def _filter_queryset_by_parents_lookups(self, queryset):
        if hasattr(self, "_should_skip_parents_filter") and callable(self._should_skip_parents_filter):
            if self._should_skip_parents_filter():
                return queryset

        parents_query_dict = self.parents_query_dict.copy()

        for source, destination in self.filter_rewrite_rules.items():
            parents_query_dict[destination] = parents_query_dict[source]
            del parents_query_dict[source]

        if "project_id" in parents_query_dict:
            # KLUDGE: This rewrite can be removed once the relevant models get that field directly
            parents_query_dict["team__project_id"] = self.team.project_id
            del parents_query_dict["project_id"]

        if parents_query_dict:
            try:
                return queryset.filter(**parents_query_dict)
            except ValueError:
                raise NotFound()
        else:
            return queryset

    @cached_property
    def parent_query_kwargs(self) -> dict[str, Any]:
        parent_query_kwargs: dict[str, str] = {}
        for kwarg_name, kwarg_value in self.kwargs.items():
            # drf-extensions nested parameters are prefixed
            if kwarg_name.startswith(extensions_api_settings.DEFAULT_PARENT_LOOKUP_KWARG_NAME_PREFIX):
                query_lookup = kwarg_name.replace(
                    extensions_api_settings.DEFAULT_PARENT_LOOKUP_KWARG_NAME_PREFIX,
                    "",
                    1,
                )
                parent_query_kwargs[query_lookup] = kwarg_value
        return parent_query_kwargs

    @cached_property
    def parents_query_dict(self) -> dict[str, Any]:
        # used to override the last visited project if there's a token in the request
        team_from_request = self._get_team_from_request()

        if self.param_derived_from_user_current_team:
            if not self.request.user.is_authenticated:
                raise AuthenticationFailed()
            current_team = team_from_request or self.request.user.team
            if current_team is None:
                raise ValidationError("This endpoint requires the current project to be set on your account.")
            if self.param_derived_from_user_current_team == "project_id":
                return {"project_id": current_team.project_id}
            else:
                return {"team_id": current_team.id}

        result = {}
        # process URL parameters (here called kwargs), such as organization_id in /api/organizations/:organization_id/
        for query_lookup, query_value in self.parent_query_kwargs.items():
            if query_value == "@current":
                if not self.request.user.is_authenticated:
                    raise AuthenticationFailed()
                if query_lookup == "team_id":
                    current_team = self.request.user.team
                    if current_team is None:
                        raise NotFound(
                            "Project not found."  # TODO: "Environment" instead of "Project" when project environments are rolled out
                        )
                    query_value = current_team.id
                elif query_lookup == "project_id":
                    current_team = self.request.user.team
                    if current_team is None:
                        raise NotFound("Project not found.")
                    query_value = current_team.project_id
                elif query_lookup == "organization_id":
                    current_organization = self.request.user.organization
                    if current_organization is None:
                        raise NotFound("Organization not found.")
                    query_value = current_organization.id
            elif query_lookup == "team_id":
                try:
                    query_value = team_from_request.id if team_from_request else int(query_value)
                except ValueError:
                    raise NotFound("Project not found.")  # TODO: "Environment"
            elif query_lookup == "project_id":
                try:
                    query_value = team_from_request.project_id if team_from_request else int(query_value)
                except ValueError:
                    raise NotFound("Project not found.")

            result[query_lookup] = query_value

        return result

    def get_serializer_context(self) -> dict[str, Any]:
        serializer_context = super().get_serializer_context() if hasattr(super(), "get_serializer_context") else {}
        serializer_context.update(self.parents_query_dict)
        # The below are lambdas for lazy evaluation (i.e. we only query Postgres for team/org if actually needed)
        serializer_context["get_team"] = lambda: self.team
        serializer_context["get_project"] = lambda: self.project
        serializer_context["get_organization"] = lambda: self.organization
        if "project_id" in serializer_context:
            # KLUDGE: This alias can be removed once the relevant models get that field directly
            serializer_context["team_id"] = serializer_context["project_id"]
        return serializer_context

    @lru_cache(maxsize=1)
    def _get_team_from_request(self) -> Optional["Team"]:
        team_found = None
        token = get_token(None, self.request)

        if token:
            team = Team.objects.get_team_from_token(token)
            if team:
                team_found = team
            else:
                raise AuthenticationFailed()

        return team_found

    @cached_property
    def user_permissions(self) -> "UserPermissions":
        return UserPermissions(user=cast(User, self.request.user), team=self.team)

    @cached_property
    def user_access_control(self) -> "UserAccessControl":
        team: Optional[Team] = None
        try:
            team = self.team
        except (Team.DoesNotExist, KeyError):
            pass

        return UserAccessControl(user=cast(User, self.request.user), team=team, organization_id=self.organization_id)
