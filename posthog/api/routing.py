from functools import cached_property, lru_cache
from typing import TYPE_CHECKING, Any, Dict, Optional, cast

from rest_framework import authentication
from rest_framework.exceptions import AuthenticationFailed, NotFound, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.viewsets import GenericViewSet
from rest_framework_extensions.routers import ExtendedDefaultRouter
from rest_framework_extensions.settings import extensions_api_settings

from posthog.api.utils import get_token
from posthog.auth import JwtAuthentication, PersonalAPIKeyAuthentication
from posthog.models.organization import Organization
from posthog.models.personal_api_key import APIScopeObjectOrNotSupported
from posthog.models.team import Team
from posthog.models.user import User
from posthog.permissions import APIScopePermission, OrganizationMemberPermissions, TeamMemberAccessPermission
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
class TeamAndOrgViewSetMixin(_GenericViewSet):
    # This flag disables nested routing handling, reverting to the old request.user.team behavior
    # Allows for a smoother transition from the old flat API structure to the newer nested one
    derive_current_team_from_user_only: bool = False

    # Rewrite filter queries, so that for example foreign keys can be accessed
    # Example: {"team_id": "foo__team_id"} will make the viewset filtered by obj.foo.team_id instead of obj.team_id
    filter_rewrite_rules: Dict[str, str] = {}

    authentication_classes = []
    permission_classes = []

    # NOTE: Could we type this? Would be pretty cool as a helper
    base_scope: Optional[APIScopeObjectOrNotSupported] = None
    required_scopes: Optional[list[str]] = None

    # We want to try and ensure that the base permission and authentication are always used
    # so we offer a way to add additional classes
    def get_permissions(self):
        # NOTE: We define these here to make it hard _not_ to use them. If you want to override them, you have to
        # override the entire method.
        permission_classes: list = [IsAuthenticated, APIScopePermission]

        if self.is_team_view:
            permission_classes.append(TeamMemberAccessPermission)
        else:
            permission_classes.append(OrganizationMemberPermissions)

        permission_classes.extend(self.permission_classes)
        return [permission() for permission in permission_classes]

    def get_authenticators(self):
        # NOTE: Custom authentication_classes go first as these typically have extra initial checks
        authentication_classes: list = [
            *self.authentication_classes,
            JwtAuthentication,
            PersonalAPIKeyAuthentication,
            authentication.SessionAuthentication,
        ]

        return [auth() for auth in authentication_classes]

    def get_queryset(self):
        queryset = super().get_queryset()
        return self.filter_queryset_by_parents_lookups(queryset)

    @property
    def is_team_view(self):
        # NOTE: We check the property first as it avoids any potential DB lookups via the parents_query_dict
        return self.derive_current_team_from_user_only or "team_id" in self.parents_query_dict

    @property
    def team_id(self) -> int:
        team_from_token = self._get_team_from_request()
        if team_from_token:
            return team_from_token.id

        if self.derive_current_team_from_user_only:
            user = cast(User, self.request.user)
            team = user.team
            assert team is not None
            return team.id

        return self.parents_query_dict["team_id"]

    @cached_property
    def team(self) -> Team:
        team_from_token = self._get_team_from_request()
        if team_from_token:
            return team_from_token

        if self.derive_current_team_from_user_only:
            user = cast(User, self.request.user)
            team = user.team
            assert team is not None
            return team
        try:
            return Team.objects.get(id=self.team_id)
        except Team.DoesNotExist:
            raise NotFound(detail="Project not found.")

    @property
    def organization_id(self) -> str:
        try:
            return self.parents_query_dict["organization_id"]
        except KeyError:
            user = cast(User, self.request.user)
            current_organization_id = self.team.organization_id if self.is_team_view else user.current_organization_id

            if not current_organization_id:
                raise NotFound("You need to belong to an organization.")
            return str(current_organization_id)

    @cached_property
    def organization(self) -> Organization:
        try:
            return Organization.objects.get(id=self.organization_id)
        except Organization.DoesNotExist:
            raise NotFound(detail="Organization not found.")

    def filter_queryset_by_parents_lookups(self, queryset):
        parents_query_dict = self.parents_query_dict.copy()

        for source, destination in self.filter_rewrite_rules.items():
            parents_query_dict[destination] = parents_query_dict[source]
            del parents_query_dict[source]
        if parents_query_dict:
            try:
                return queryset.filter(**parents_query_dict)
            except ValueError:
                raise NotFound()
        else:
            return queryset

    @cached_property
    def parents_query_dict(self) -> Dict[str, Any]:
        # used to override the last visited project if there's a token in the request
        team_from_request = self._get_team_from_request()

        if self.derive_current_team_from_user_only:
            if not self.request.user.is_authenticated:
                raise AuthenticationFailed()
            project = team_from_request or self.request.user.team
            if project is None:
                raise ValidationError("This endpoint requires a project.")
            return {"team_id": project.id}
        result = {}
        # process URL parameters (here called kwargs), such as organization_id in /api/organizations/:organization_id/
        for kwarg_name, kwarg_value in self.kwargs.items():
            # drf-extensions nested parameters are prefixed
            if kwarg_name.startswith(extensions_api_settings.DEFAULT_PARENT_LOOKUP_KWARG_NAME_PREFIX):
                query_lookup = kwarg_name.replace(
                    extensions_api_settings.DEFAULT_PARENT_LOOKUP_KWARG_NAME_PREFIX,
                    "",
                    1,
                )
                query_value = kwarg_value
                if query_value == "@current":
                    if not self.request.user.is_authenticated:
                        raise AuthenticationFailed()
                    if query_lookup == "team_id":
                        project = self.request.user.team
                        if project is None:
                            raise NotFound("Project not found.")
                        query_value = project.id
                    elif query_lookup == "organization_id":
                        organization = self.request.user.organization
                        if organization is None:
                            raise NotFound("Organization not found.")
                        query_value = organization.id
                elif query_lookup == "team_id":
                    try:
                        query_value = team_from_request.id if team_from_request else int(query_value)
                    except ValueError:
                        raise NotFound()
                result[query_lookup] = query_value
        return result

    def get_serializer_context(self) -> Dict[str, Any]:
        serializer_context = super().get_serializer_context() if hasattr(super(), "get_serializer_context") else {}
        serializer_context.update(self.parents_query_dict)
        # The below are lambdas for lazy evaluation (i.e. we only query Postgres for team/org if actually needed)
        serializer_context["get_team"] = lambda: self.team
        serializer_context["get_organization"] = lambda: self.organization
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

    # Stdout tracing to see what legacy endpoints (non-project-nested) are still requested by the frontend
    # TODO: Delete below when no legacy endpoints are used anymore

    # def create(self, *args, **kwargs):
    #     super_cls = super()
    #     if self.derive_current_team_from_user_only:
    #         print(f"Legacy endpoint called – {super_cls.get_view_name()} (create)")
    #     return super_cls.create(*args, **kwargs)

    # def retrieve(self, *args, **kwargs):
    #     super_cls = super()
    #     if self.derive_current_team_from_user_only:
    #         print(f"Legacy endpoint called – {super_cls.get_view_name()} (retrieve)")
    #     return super_cls.retrieve(*args, **kwargs)

    # def list(self, *args, **kwargs):
    #     super_cls = super()
    #     if self.derive_current_team_from_user_only:
    #         print(f"Legacy endpoint called – {super_cls.get_view_name()} (list)")
    #     return super_cls.list(*args, **kwargs)

    # def update(self, *args, **kwargs):
    #     super_cls = super()
    #     if self.derive_current_team_from_user_only:
    #         print(f"Legacy endpoint called – {super_cls.get_view_name()} (update)")
    #     return super_cls.update(*args, **kwargs)

    # def delete(self, *args, **kwargs):
    #     super_cls = super()
    #     if self.derive_current_team_from_user_only:
    #         print(f"Legacy endpoint called – {super_cls.get_view_name()} (delete)")
    #     return super_cls.delete(*args, **kwargs)
