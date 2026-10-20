from typing import cast

from drf_spectacular.utils import OpenApiResponse
from rest_framework import viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.mixins import validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models import User
from posthog.permissions import get_authenticator_scopes
from posthog.scopes import APIScopeObject, scopes_not_covered

from products.annotations.backend.facade import api
from products.annotations.backend.facade.change_feed import ChangeKind, ChangeWindow, KindVisibility

from .serializers import ChangeFeedQuerySerializer, ChangeFeedSerializer

KIND_RESOURCES: dict[ChangeKind, APIScopeObject] = {
    ChangeKind.FEATURE_FLAG: "feature_flag",
    ChangeKind.EXPERIMENT: "experiment",
    ChangeKind.RELEASE: "error_tracking",
    ChangeKind.ANNOTATION: "annotation",
}


class ChangeFeedViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    """
    One time-ordered list of the production changes in a project: feature flag and experiment edits,
    error tracking releases, and annotations.
    """

    scope_object = "annotation"

    def _visibility(self, request: Request) -> dict[ChangeKind, KindVisibility]:
        access = self.user_access_control
        # The endpoint needs only `annotation:read`, so a scoped token must also hold each source's read scope.
        key_scopes = get_authenticator_scopes(request.successful_authenticator)
        allowlisted = access.allowlisted_resource_ids_by_scope
        blocked = access.blocked_resource_ids_by_scope
        visibility: dict[ChangeKind, KindVisibility] = {}
        for kind, resource in KIND_RESOURCES.items():
            if (
                key_scopes is not None
                and "*" not in key_scopes
                and scopes_not_covered(key_scopes, [f"{resource}:read"])
            ):
                continue
            if kind == ChangeKind.RELEASE:
                # Object-level error tracking rules address issues, not releases.
                if access.check_access_level_for_resource(resource, "viewer"):
                    visibility[kind] = KindVisibility()
            elif resource in allowlisted:
                visibility[kind] = KindVisibility(allowed_ids=allowlisted[resource])
            elif access.check_access_level_for_resource(resource, "viewer"):
                visibility[kind] = KindVisibility(blocked_ids=blocked.get(resource, frozenset()))
        return visibility

    @validated_request(
        query_serializer=ChangeFeedQuerySerializer,
        responses={200: OpenApiResponse(response=ChangeFeedSerializer)},
        summary="List recent production changes",
        description=(
            "Lists the changes that can affect production in a time window, newest first: feature flag and "
            "experiment edits, error tracking releases, and annotations. Use it to find what changed just before "
            "an error spike or a metric drop. Changes the user has no access to are left out."
        ),
    )
    def list(self, request: Request, **kwargs) -> Response:
        query = request.validated_query_data
        visibility = self._visibility(request)
        if query["kinds"]:
            visibility = {kind: rules for kind, rules in visibility.items() if kind in query["kinds"]}
        feed = api.list_changes(
            team_id=self.team_id,
            organization_id=self.team.organization_id,
            user_is_staff=cast(User, request.user).is_staff,
            window=ChangeWindow(start=query["date_from"], end=query["date_to"]),
            visibility=visibility,
            limit=query["limit"],
        )
        return Response(ChangeFeedSerializer(feed).data)
