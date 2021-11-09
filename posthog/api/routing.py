from typing import TYPE_CHECKING, Any, Dict, Optional, cast

from rest_framework import serializers
from rest_framework.exceptions import AuthenticationFailed, NotFound, ValidationError
from rest_framework.fields import empty
from rest_framework.request import Request
from rest_framework.viewsets import GenericViewSet
from rest_framework_extensions.routers import ExtendedDefaultRouter
from rest_framework_extensions.settings import extensions_api_settings

from posthog.api.utils import get_token
from posthog.models.organization import Organization
from posthog.models.team import Team
from posthog.models.user import User

if TYPE_CHECKING:
    _GenericViewSet = GenericViewSet
else:
    _GenericViewSet = object


class DefaultRouterPlusPlus(ExtendedDefaultRouter):
    """DefaultRouter with optional trailing slash and drf-extensions nesting."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.trailing_slash = r"/?"


class StructuredViewSetMixin(_GenericViewSet):
    # This flag disables nested routing handling, reverting to the old request.user.team behavior
    # Allows for a smoother transition from the old flat API structure to the newer nested one
    legacy_team_compatibility: bool = False

    # Rewrite filter queries, so that for example foreign keys can be accessed
    # Example: {"team_id": "foo__team_id"} will make the viewset filtered by obj.foo.team_id instead of obj.team_id
    filter_rewrite_rules: Dict[str, str] = {}

    _parents_query_dict: Optional[Dict[str, Any]]

    def get_queryset(self):
        queryset = super().get_queryset()
        return self.filter_queryset_by_parents_lookups(queryset)

    @property
    def team_id(self) -> int:
        team_from_token = self._get_team_from_request()
        if team_from_token:
            return team_from_token.id

        if self.legacy_team_compatibility:
            user = cast(User, self.request.user)
            team = user.team
            assert team is not None
            return team.id
        return self.get_parents_query_dict()["team_id"]

    @property
    def team(self) -> Team:
        team_from_token = self._get_team_from_request()
        if team_from_token:
            return team_from_token

        user = cast(User, self.request.user)
        if self.legacy_team_compatibility:
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
            return self.get_parents_query_dict()["organization_id"]
        except KeyError:
            return str(self.team.organization_id)

    @property
    def organization(self) -> Organization:
        try:
            return Organization.objects.get(id=self.organization_id)
        except Organization.DoesNotExist:
            raise NotFound(detail="Organization not found.")

    def filter_queryset_by_parents_lookups(self, queryset):
        parents_query_dict = self.get_parents_query_dict()

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

    def get_parents_query_dict(self) -> Dict[str, Any]:
        if getattr(self, "_parents_query_dict", None) is not None:
            return cast(Dict[str, Any], self._parents_query_dict)

        # used to override the last visited project if there's a token in the request
        team_from_request = self._get_team_from_request()

        if self.legacy_team_compatibility:
            if not self.request.user.is_authenticated:
                raise AuthenticationFailed()
            project = team_from_request or self.request.user.team
            if project is None:
                raise ValidationError("This endpoint requires a project.")
            return {"team_id": project.id}
        result = {}
        # process URL paremetrs (here called kwargs), such as organization_id in /api/organizations/:organization_id/
        for kwarg_name, kwarg_value in self.kwargs.items():
            # drf-extensions nested parameters are prefixed
            if kwarg_name.startswith(extensions_api_settings.DEFAULT_PARENT_LOOKUP_KWARG_NAME_PREFIX):
                query_lookup = kwarg_name.replace(
                    extensions_api_settings.DEFAULT_PARENT_LOOKUP_KWARG_NAME_PREFIX, "", 1
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
        self._parents_query_dict = result
        return result

    def get_serializer_context(self) -> Dict[str, Any]:
        return {**super().get_serializer_context(), **self.get_parents_query_dict()}

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


class ProjectScopedSerializerMixin(serializers.ModelSerializer):
    team: Team
    request: Request

    def __init__(self, instance=None, data=empty, **kwargs):
        context = kwargs.get("context")

        if context:
            request = context.get("request")
            if request:
                self.request = request
                token = get_token(None, request)

                if token:
                    team = Team.objects.get_team_from_token(token)
                    if team:
                        self.team = team
                print("hereeeee")

            elif context.get("team_id"):
                self.team = Team.objects.get(id=self.context["team_id"])

        super().__init__(instance=instance, data=data, **kwargs)

    # Stdout tracing to see what legacy endpoints (non-project-nested) are still requested by the frontend
    # TODO: Delete below when no legacy endpoints are used anymore

    # def create(self, *args, **kwargs):
    #     super_cls = super()
    #     if self.legacy_team_compatibility:
    #         print(f"Legacy endpoint called – {super_cls.get_view_name()} (create)")
    #     return super_cls.create(*args, **kwargs)

    # def retrieve(self, *args, **kwargs):
    #     super_cls = super()
    #     if self.legacy_team_compatibility:
    #         print(f"Legacy endpoint called – {super_cls.get_view_name()} (retrieve)")
    #     return super_cls.retrieve(*args, **kwargs)

    # def list(self, *args, **kwargs):
    #     super_cls = super()
    #     if self.legacy_team_compatibility:
    #         print(f"Legacy endpoint called – {super_cls.get_view_name()} (list)")
    #     return super_cls.list(*args, **kwargs)

    # def update(self, *args, **kwargs):
    #     super_cls = super()
    #     if self.legacy_team_compatibility:
    #         print(f"Legacy endpoint called – {super_cls.get_view_name()} (update)")
    #     return super_cls.update(*args, **kwargs)

    # def delete(self, *args, **kwargs):
    #     super_cls = super()
    #     if self.legacy_team_compatibility:
    #         print(f"Legacy endpoint called – {super_cls.get_view_name()} (delete)")
    #     return super_cls.delete(*args, **kwargs)
