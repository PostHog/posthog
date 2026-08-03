"""
`/api/projects/:id/presence/` — ephemeral "who is here right now" for any scope + item_id pair.

Generic in the same loose way as comments and activity logs: the API knows nothing about the objects
it reports presence on. A product enables presence for its own scope by registering an access check
(see `posthog/presence/access.py`), and a scene renders `<PresenceIndicator>` against the same
scope + item_id it already uses for discussions.
"""

from collections.abc import Sequence
from typing import Any, cast

import posthoganalytics
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.exceptions import NotFound
from rest_framework.response import Response

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.api.utils import action
from posthog.models import Team, User
from posthog.presence import PresenceAccessContext, PresenceEntry, check_presence_access, service
from posthog.rate_limit import BurstRateThrottle, PresenceRateThrottle, SustainedRateThrottle

PRESENCE_FEATURE_FLAG = "presence-indicator"

# Mirrors `Comment.scope` / `Comment.item_id`. The character class also keeps braces out of the
# values, which matters because they end up inside a Redis cluster hash tag.
_SCOPE_FIELD_KWARGS: dict[str, Any] = {
    "max_length": 79,
    "help_text": (
        "The kind of object presence is being reported on, e.g. `conversations_ticket` or "
        "`FeatureFlag`. Must be a scope that has presence enabled."
    ),
}
_ITEM_ID_FIELD_KWARGS: dict[str, Any] = {
    "max_length": 72,
    "help_text": "Id of the specific object within the scope.",
}
_IDENTIFIER_REGEX = r"^[A-Za-z0-9_\-:.]+$"


class PresenceScopeQuerySerializer(serializers.Serializer):
    scope = serializers.RegexField(_IDENTIFIER_REGEX, **_SCOPE_FIELD_KWARGS)
    item_id = serializers.RegexField(_IDENTIFIER_REGEX, **_ITEM_ID_FIELD_KWARGS)


class PresenceHeartbeatRequestSerializer(PresenceScopeQuerySerializer):
    client_id = serializers.RegexField(
        _IDENTIFIER_REGEX,
        max_length=64,
        help_text=(
            "Stable id for this browser tab. One user can be present from several tabs; the UI "
            "collapses them into a single viewer."
        ),
    )
    activity = serializers.ChoiceField(
        choices=list(service.PRESENCE_ACTIVITIES),
        default="viewing",
        help_text="What this client is doing. `composing` means the user is writing something.",
    )


class PresenceLeaveRequestSerializer(PresenceScopeQuerySerializer):
    client_id = serializers.RegexField(
        _IDENTIFIER_REGEX,
        max_length=64,
        help_text="Id of the tab that is leaving.",
    )


class PresenceViewerSerializer(serializers.Serializer):
    client_id = serializers.CharField(help_text="Id of the browser tab this viewer is present from.")
    # read_only, or the response-validation pass runs UserBasicSerializer's model uniqueness
    # validators against users that already exist and reports every viewer as invalid.
    user = UserBasicSerializer(read_only=True, help_text="The user who is present.")
    activity = serializers.ChoiceField(
        choices=list(service.PRESENCE_ACTIVITIES),
        help_text="What this viewer is doing. `composing` means they are writing something.",
    )
    last_seen_at = serializers.DateTimeField(help_text="When this viewer last sent a heartbeat.")


class PresenceListResponseSerializer(serializers.Serializer):
    results = PresenceViewerSerializer(many=True, help_text="Everyone currently present on the item.")


@extend_schema(extensions={"x-product": "core"})
class PresenceViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "INTERNAL"
    # Presence lives in Redis, not Postgres. The queryset only exists to satisfy DRF's generic
    # machinery, the same way MetalyticsViewSet does it.
    queryset = Team.objects.none()
    serializer_class = PresenceViewerSerializer
    # A single item has at most `MAX_VIEWERS_RETURNED` viewers, so `list` returns them all rather
    # than a page. Without this drf-spectacular describes the response as paginated.
    pagination_class = None
    throttle_classes = [BurstRateThrottle, SustainedRateThrottle, PresenceRateThrottle]
    http_method_names = ["get", "post"]

    @validated_request(
        query_serializer=PresenceScopeQuerySerializer,
        responses={200: OpenApiResponse(response=PresenceListResponseSerializer)},
        summary="List who is currently viewing an item",
    )
    def list(self, request: ValidatedRequest, **kwargs) -> Response:
        scope, item_id = self._authorize(request.validated_query_data)
        return self._respond(service.get_viewers(self.team_id, scope, item_id))

    @validated_request(
        request_serializer=PresenceHeartbeatRequestSerializer,
        responses={200: OpenApiResponse(response=PresenceListResponseSerializer)},
        summary="Record presence on an item and return who else is here",
        description=(
            "Call this on an interval while the item is open. Returns the current viewers so a "
            "client needs one request per tick rather than a write followed by a read."
        ),
    )
    @action(methods=["POST"], detail=False)
    def heartbeat(self, request: ValidatedRequest, **kwargs) -> Response:
        data = request.validated_data
        scope, item_id = self._authorize(data)
        entries = service.heartbeat(
            self.team_id,
            scope,
            item_id,
            client_id=data["client_id"],
            user_id=cast(User, request.user).pk,
            activity=data["activity"],
        )
        return self._respond(entries)

    @validated_request(
        request_serializer=PresenceLeaveRequestSerializer,
        responses={204: OpenApiResponse(description="This client is no longer present.")},
        summary="Stop reporting presence on an item",
        description="Optional: presence also expires on its own once heartbeats stop.",
    )
    @action(methods=["POST"], detail=False)
    def leave(self, request: ValidatedRequest, **kwargs) -> Response:
        data = request.validated_data
        scope, item_id = self._authorize(data)
        service.leave(self.team_id, scope, item_id, client_id=data["client_id"])
        return Response(status=status.HTTP_204_NO_CONTENT)

    def _authorize(self, data: dict[str, Any]) -> tuple[str, str]:
        """Gate on the feature flag, then on the scope's own access check. Returns scope, item_id."""
        self._require_feature_flag()
        scope: str = data["scope"]
        item_id: str = data["item_id"]
        check_presence_access(
            PresenceAccessContext(
                team_id=self.team_id,
                scope=scope,
                item_id=item_id,
                user=cast(User, self.request.user),
                user_access_control=self.user_access_control,
            )
        )
        return scope, item_id

    def _require_feature_flag(self) -> None:
        # Scoped to the team's organization rather than the user's current one, so a user in several
        # orgs can't flip their current org to get presence in a team where it's off.
        user = cast(User, self.request.user)
        enabled = posthoganalytics.feature_enabled(
            PRESENCE_FEATURE_FLAG,
            str(user.distinct_id),
            groups={"organization": str(self.organization_id)},
        )
        if not enabled:
            # 404 rather than 403, so a disabled flag looks like an endpoint that isn't there.
            raise NotFound("Not found")

    # `Sequence`, not `list`: the viewset's own `list` action shadows the builtin in the class body.
    def _respond(self, entries: Sequence[PresenceEntry]) -> Response:
        users_by_id = {user.pk: user for user in User.objects.filter(pk__in={entry.user_id for entry in entries})}
        results = [
            {
                "client_id": entry.client_id,
                "user": users_by_id[entry.user_id],
                "activity": entry.activity,
                "last_seen_at": entry.last_seen_at,
            }
            for entry in entries
            if entry.user_id in users_by_id
        ]
        return Response(PresenceListResponseSerializer({"results": results}).data)
