from typing import Any, Dict, List, Optional, Tuple

from rest_framework.exceptions import AuthenticationFailed, NotFound
from rest_framework_extensions.mixins import NestedViewSetMixin
from rest_framework_extensions.routers import ExtendedDefaultRouter
from rest_framework_extensions.settings import extensions_api_settings

from posthog.models.organization import Organization
from posthog.models.team import Team


class DefaultRouterPlusPlus(ExtendedDefaultRouter):
    """DefaultRouter with optional trailing slash and drf-extensions nesting."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.trailing_slash = r"/?"


class StructuredViewSetMixin(NestedViewSetMixin):
    # This flag disables nested routing handling, reverting to the old request.user.team behavior
    # Allows for a smoother transition from the old flat API structure to the newer nested one
    legacy_team_compatibility: bool = False

    # Rewrite filter queries, so that for example foreign keys can be accessed
    # Example: {"team_id": "foo__team_id"} will make the viewset filtered by obj.foo.team_id instead of obj.team_id
    filter_rewrite_rules: Dict[str, str] = {}

    @property
    def team_id(self) -> int:
        if self.legacy_team_compatibility:
            team = self.request.user.team
            assert team is not None
            return team.id
        return self.get_parents_query_dict()["team_id"]

    @property
    def team(self) -> Team:
        if self.legacy_team_compatibility:
            team = self.request.user.team
            assert team is not None
            return team
        return Team.objects.get(id=self.get_parents_query_dict()["team_id"])

    @property
    def organization_id(self) -> str:
        return self.get_parents_query_dict()["organization_id"]

    @property
    def organization(self) -> Organization:
        return Organization.objects.get(id=self.get_parents_query_dict()["organization_id"])

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

    # if not self.request.user.is_authenticated:
    #    raise AuthenticationFailed()

    def _get_and_validate_query_lookup(self, query_lookup: str, unsanitized_query_value: str) -> Any:
        query_value = None

        if unsanitized_query_value == "@current":
            if query_lookup == "team_id":
                project = self.request.user.team
                if project is None:
                    raise NotFound("Current project not found.")
                query_value = project.id
            elif query_lookup == "organization_id":
                organization = self.request.user.organization
                if organization is None:
                    raise NotFound("Current organization not found.")
                query_value = organization.id

        else:
            if query_lookup == "team_id":
                try:
                    project = Team.objects.get(id=int(query_value))
                    if not project.organization.members.filter(user=self.request.user):
                        raise NotFound()
                    query_value = project.id
                except (ValueError, Team.DoesNotExist):
                    raise NotFound()
            elif query_lookup == "organization_id":
                try:
                    organization = Organization.objects.get(id=query_value)
                    if not organization.members.filter(user=self.request.user):
                        raise NotFound()
                    query_value = organization.id
                except Organization.DoesNotExist:
                    raise NotFound()

        return query_value

    def get_parents_query_dict(self) -> Dict[str, Any]:
        if self.legacy_team_compatibility:
            if not self.request.user.is_authenticated:
                raise AuthenticationFailed()
            return {"team_id": self.request.user.team.id}
        result = {}
        # process URL paremetrs (here called kwargs), such as organization_id in /api/organizations/:organization_id/
        for kwarg_name, kwarg_value in self.kwargs.items():
            # drf-extensions nested parameters are prefixed
            if kwarg_name.startswith(extensions_api_settings.DEFAULT_PARENT_LOOKUP_KWARG_NAME_PREFIX):
                query_lookup = kwarg_name.replace(
                    extensions_api_settings.DEFAULT_PARENT_LOOKUP_KWARG_NAME_PREFIX, "", 1
                )

                result[query_lookup] = self._get_and_validate_query_lookup(query_lookup, kwarg_value)
        return result

    def get_serializer_context(self) -> Dict[str, Any]:
        return {**super().get_serializer_context(), **self.get_parents_query_dict()}
