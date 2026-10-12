from functools import cached_property
from typing import cast

from drf_spectacular.utils import extend_schema
from rest_framework import serializers, viewsets
from rest_framework.exceptions import NotFound
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.pagination import PrecountedLimitOffsetPagination
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models import Team, User
from posthog.permissions import PostHogFeatureFlagPermission, get_authenticator_scopes
from posthog.scopes import APIScopeObject, scopes_not_covered

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.alerts_platform.backend.facade import api as platform_api
from products.alerts_platform.backend.facade.enums import (
    PlatformAlertConfigurationRecurrenceUnit,
    PlatformAlertConfigurationSourceKind,
    PlatformAlertState,
)
from products.alerts_platform.backend.presentation.views.schedule_restriction import ScheduleRestrictionField


class PlatformAlertSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True, help_text="Unique identifier of this alert instance.")
    grouping_key = serializers.CharField(
        read_only=True,
        help_text="Key of the result group this instance tracks. Empty when the source does not group results.",
    )
    state = serializers.ChoiceField(
        choices=PlatformAlertState.choices,
        read_only=True,
        help_text="Current state of this alert instance.",
    )
    firing_started_at = serializers.DateTimeField(
        read_only=True,
        allow_null=True,
        help_text="When the current firing started. Null when the instance is not firing.",
    )
    last_notified_at = serializers.DateTimeField(
        read_only=True, allow_null=True, help_text="When a notification was last sent for this instance."
    )
    snooze_until = serializers.DateTimeField(
        read_only=True,
        allow_null=True,
        help_text="Time until which notifications are snoozed. Null when not snoozed.",
    )


class PlatformAlertConfigurationSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True, help_text="Unique identifier of the alert configuration.")
    name = serializers.CharField(read_only=True, help_text="Human-readable name of the alert.")
    enabled = serializers.BooleanField(read_only=True, help_text="Whether the alert is evaluated on schedule.")
    source_kind = serializers.ChoiceField(
        choices=PlatformAlertConfigurationSourceKind.choices,
        read_only=True,
        help_text="Product whose data the alert evaluates.",
    )
    source_config = serializers.DictField(
        child=serializers.JSONField(),
        read_only=True,
        help_text=(
            "Source-specific settings. The shape depends on source_kind. The bound the alert is evaluated "
            "against is under the condition key."
        ),
    )
    check_interval_minutes = serializers.IntegerField(
        read_only=True,
        help_text="Minutes between scheduled checks. Applies when recurrence_unit is null.",
    )
    recurrence_unit = serializers.ChoiceField(
        choices=PlatformAlertConfigurationRecurrenceUnit.choices,
        read_only=True,
        allow_null=True,
        help_text="Calendar unit the alert recurs on. Null means it recurs on check_interval_minutes.",
    )
    anchor_time = serializers.CharField(
        read_only=True,
        allow_null=True,
        help_text="Local time (HH:MM in the project timezone) a calendar recurrence lands on. "
        "Null means the default anchor for the unit.",
    )
    evaluation_periods = serializers.IntegerField(
        read_only=True, help_text="Number of recent checks considered when deciding to fire."
    )
    datapoints_to_alarm = serializers.IntegerField(
        read_only=True, help_text="Number of breaching checks within evaluation_periods required to fire."
    )
    cooldown_minutes = serializers.IntegerField(
        read_only=True, help_text="Minimum minutes between notifications for the same alert."
    )
    schedule_restriction = ScheduleRestrictionField(
        read_only=True,
        allow_null=True,
        help_text="Blocked local time windows (HH:MM in the project timezone) when the alert does not run. "
        "Null means no quiet hours.",
    )
    next_check_at = serializers.DateTimeField(
        read_only=True, allow_null=True, help_text="When the next check is due. Null when no check is scheduled."
    )
    consecutive_failures = serializers.IntegerField(
        read_only=True, help_text="Number of checks in a row that failed to evaluate."
    )
    legacy_configuration_id = serializers.UUIDField(
        read_only=True,
        allow_null=True,
        help_text="ID of the legacy source configuration this row was backfilled from. "
        "Null for alerts created on the platform.",
    )
    created_at = serializers.DateTimeField(read_only=True, help_text="When the configuration was created.")
    updated_at = serializers.DateTimeField(read_only=True, help_text="When the configuration was last changed.")
    alerts = PlatformAlertSerializer(
        many=True,
        read_only=True,
        help_text="Runtime state for each result group of this configuration.",
    )


# A configuration shows the source product's data (its filters and firing state), so a reader
# also needs read access to that product. `alert:read` alone must not reveal it.
SOURCE_KIND_RESOURCE: dict[str, APIScopeObject] = {
    PlatformAlertConfigurationSourceKind.LOGS.value: "logs",
}

# Kinds the read API does not serve. An insight copy shows its insight's bound and firing state,
# and a reader can hold access to insights in general but not to that insight. This product
# cannot check access to one insight, so the copies stay out of the API until it can.
UNSERVED_SOURCE_KINDS: frozenset[str] = frozenset({PlatformAlertConfigurationSourceKind.INSIGHT.value})


class PlatformAlertConfigurationViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "alert"
    posthog_feature_flag = "platform-alerts"
    permission_classes = [PostHogFeatureFlagPermission]
    serializer_class = PlatformAlertConfigurationSerializer
    pagination_class = PrecountedLimitOffsetPagination

    @cached_property
    def canonical_team(self) -> Team:
        # The rows live on the parent team, so a child environment reads its parent's.
        if self.team.parent_team_id is None:
            return self.team
        parent_team = self.team.parent_team
        assert parent_team is not None
        return parent_team

    @cached_property
    def user_access_control(self) -> UserAccessControl:
        # Anchored on the team the rows come from, not on the one the URL named. The mixin builds
        # this from `self.team`, which filters access control rows by that team's id, so a deny
        # written on the project would not be seen by a request naming one of its environments
        # while the read still returned the project's rows.
        return UserAccessControl(
            user=cast(User, self.request.user),
            team=self.canonical_team,
            organization_id=self.organization_id,
        )

    def _canonical_team_id(self) -> int:
        return self.canonical_team.id

    def _readable_source_kinds(self) -> list[str]:
        # Session auth carries no scopes, so only the access-control check applies to it.
        token_scopes = get_authenticator_scopes(getattr(self.request, "successful_authenticator", None))
        readable: list[str] = []
        for source_kind, resource in SOURCE_KIND_RESOURCE.items():
            if not self.user_access_control.check_access_level_for_resource(resource, "viewer"):
                continue
            if (
                token_scopes is not None
                and "*" not in token_scopes
                and scopes_not_covered(token_scopes, [f"{resource}:read"])
            ):
                continue
            readable.append(source_kind)
        return readable

    def list(self, request: Request, **kwargs) -> Response:
        paginator = cast(PrecountedLimitOffsetPagination, self.paginator)
        limit = paginator.get_limit(request)
        assert limit is not None
        page = platform_api.list_configurations(
            team_id=self._canonical_team_id(),
            source_kinds=self._readable_source_kinds(),
            limit=limit,
            offset=paginator.get_offset(request),
        )
        paginator.set_count(page.total)
        return self.get_paginated_response(
            PlatformAlertConfigurationSerializer(self.paginate_queryset(page.configurations), many=True).data
        )

    @extend_schema(responses=PlatformAlertConfigurationSerializer)
    def retrieve(self, request: Request, pk: str, **kwargs) -> Response:
        # The route accepts any non-slash value, and an unparseable one reaching the UUID filter
        # raises rather than missing, which would answer a bad id with a 500.
        configuration = platform_api.get_configuration(
            team_id=self._canonical_team_id(),
            source_kinds=self._readable_source_kinds(),
            configuration_id=serializers.UUIDField().run_validation(pk),
        )
        if configuration is None:
            raise NotFound()
        return Response(PlatformAlertConfigurationSerializer(configuration).data)
