from typing import Any, Dict, Optional

from rest_framework.exceptions import APIException, AuthenticationFailed, NotFound
from rest_framework.pagination import CursorPagination as BaseCursorPagination
from rest_framework_extensions.mixins import NestedViewSetMixin
from rest_framework_extensions.routers import ExtendedDefaultRouter
from rest_framework_extensions.settings import extensions_api_settings

from posthog.models import Organization, Team


class CursorPagination(BaseCursorPagination):
    ordering = "-created_at"
    page_size = 100


class DefaultRouterPlusPlus(ExtendedDefaultRouter):
    """DefaultRouter with optional trailing slash and drf-extensions nesting."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.trailing_slash = r"/?"


class StructuredViewSetMixin(NestedViewSetMixin):
    legacy_team_compatibility: bool = False

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

    def get_parents_query_dict(self) -> Dict[str, Any]:
        if self.legacy_team_compatibility:
            if not self.request.user.is_authenticated:
                raise AuthenticationFailed()
            return {"team_id": self.request.user.team.id}
        result = {}
        for kwarg_name, kwarg_value in self.kwargs.items():
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
                            raise NotFound("Current project not found.")
                        query_value = project.id
                    elif query_lookup == "organization_id":
                        organization = self.request.user.organization
                        if organization is None:
                            raise NotFound("Current organization not found.")
                        query_value = organization.id
                elif query_lookup == "team_id":
                    try:
                        query_value = int(query_value)
                    except ValueError:
                        raise NotFound()
                result[query_lookup] = query_value
        return result

    def get_serializer_context(self) -> Dict[str, Any]:
        return {**super().get_serializer_context(), **self.get_parents_query_dict()}
