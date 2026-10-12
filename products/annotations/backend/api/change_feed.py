from datetime import timedelta
from typing import cast

from django.utils import timezone

from drf_spectacular.utils import OpenApiResponse, extend_schema_serializer
from rest_framework import serializers, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.mixins import validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models import User
from posthog.permissions import get_authenticator_scopes
from posthog.scopes import APIScopeObject, scopes_not_covered

from products.annotations.backend.change_feed import ChangeKind, ChangeWindow, KindVisibility, list_changes

DEFAULT_WINDOW = timedelta(hours=24)
DEFAULT_LIMIT = 100
MAX_LIMIT = 500

KIND_RESOURCES: dict[ChangeKind, APIScopeObject] = {
    ChangeKind.FEATURE_FLAG: "feature_flag",
    ChangeKind.EXPERIMENT: "experiment",
    ChangeKind.RELEASE: "error_tracking",
    ChangeKind.ANNOTATION: "annotation",
}


class ChangeFeedQuerySerializer(serializers.Serializer):
    date_from = serializers.DateTimeField(
        required=False,
        help_text="Start of the time window (inclusive), ISO 8601. Defaults to 24 hours before `date_to`.",
    )
    date_to = serializers.DateTimeField(
        required=False,
        help_text="End of the time window (inclusive), ISO 8601. Defaults to now.",
    )
    limit = serializers.IntegerField(
        required=False,
        default=DEFAULT_LIMIT,
        min_value=1,
        max_value=MAX_LIMIT,
        help_text=f"Maximum number of changes to return, newest first. Defaults to {DEFAULT_LIMIT}, at most {MAX_LIMIT}.",
    )

    def validate(self, attrs: dict) -> dict:
        date_to = attrs.get("date_to") or timezone.now()
        date_from = attrs.get("date_from") or date_to - DEFAULT_WINDOW
        if date_from > date_to:
            raise serializers.ValidationError("date_from must be before date_to.")
        return {**attrs, "date_from": date_from, "date_to": date_to}


class ChangeFeedItemSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=ChangeKind.choices, help_text="The source of the change.")
    timestamp = serializers.DateTimeField(
        help_text="When the change happened. For annotations, this is the time the annotation marks."
    )
    item_id = serializers.CharField(
        help_text="ID of the changed object: the feature flag, experiment, release, or annotation ID."
    )
    name = serializers.CharField(
        allow_null=True,
        help_text="Display name: the flag key, experiment name, release version, or annotation text.",
    )
    activity = serializers.CharField(
        help_text="What happened, for example `created`, `updated`, `deleted`, `released`, or `annotated`."
    )
    changed_fields = serializers.ListField(
        child=serializers.CharField(),
        help_text="For flag and experiment updates, the names of the fields that changed. Empty for other kinds.",
    )
    service = serializers.CharField(
        allow_null=True, help_text="For releases, the project or service the release belongs to. Null for other kinds."
    )
    actor_name = serializers.CharField(
        allow_null=True, help_text="Name or email of the person who made the change. Null for automated changes."
    )


# The `list` action returns one feed object, not an array of feeds.
@extend_schema_serializer(many=False)
class ChangeFeedSerializer(serializers.Serializer):
    results = ChangeFeedItemSerializer(many=True, help_text="Changes in the time window, newest first.")
    has_more = serializers.BooleanField(
        help_text="True when the window holds more changes than `limit`. Narrow the window to see the rest."
    )


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
        feed = list_changes(
            team_id=self.team_id,
            organization_id=self.team.organization_id,
            user=cast(User, request.user),
            window=ChangeWindow(start=query["date_from"], end=query["date_to"]),
            visibility=self._visibility(request),
            limit=query["limit"],
        )
        return Response(ChangeFeedSerializer(feed).data)
