from dataclasses import replace
from functools import cache, cached_property
from typing import Any, cast

from drf_spectacular.utils import OpenApiResponse, PolymorphicProxySerializer, extend_schema, extend_schema_field
from rest_framework import serializers, viewsets
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.pagination import PrecountedLimitOffsetPagination
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.exceptions import Conflict
from posthog.models import Team, User
from posthog.permissions import PostHogFeatureFlagPermission, get_authenticator_scopes
from posthog.scopes import APIScopeObject, scopes_not_covered

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.alerts_platform.backend.facade import api as platform_api
from products.alerts_platform.backend.facade.contracts import (
    DEFAULT_MAX_INSTANCES,
    Grouping,
    GroupingMode,
    InvalidPlatformAlertEdit,
    OnOverflow,
    PlatformAlertNotEditable,
    SourceConfigSpec,
    SourceKind,
)
from products.alerts_platform.backend.facade.enums import (
    PlatformAlertCheckStatus,
    PlatformAlertConfigurationRecurrenceUnit,
    PlatformAlertConfigurationSourceKind,
    PlatformAlertOwner,
    PlatformAlertState,
)
from products.alerts_platform.backend.facade.scheduling import validate_and_normalize_schedule_restriction
from products.alerts_platform.backend.facade.source_configs import editable_source_configs
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


class GroupingSerializer(serializers.Serializer):
    mode = serializers.ChoiceField(
        choices=GroupingMode.choices,
        help_text="single keeps one instance for the whole alert. by_result_labels keeps one instance per "
        "distinct value of the labels in keys, so each group fires and resolves on its own.",
    )
    keys = serializers.ListField(
        child=serializers.CharField(),
        default=list,
        help_text="Result labels whose values make a group, such as service_name. Empty for mode single, "
        "required for by_result_labels. Changing them deletes the existing instances and closes their "
        "notification threads without a message.",
    )
    max_instances = serializers.IntegerField(
        min_value=1,
        max_value=DEFAULT_MAX_INSTANCES,
        default=DEFAULT_MAX_INSTANCES,
        help_text="Most instances the alert keeps at once. Groups past it are not tracked, and the last "
        "message says how many were left out.",
    )
    on_overflow = serializers.ChoiceField(
        choices=OnOverflow.choices,
        default=OnOverflow.DEGRADE_VISIBLE.value,
        help_text="What happens to groups past max_instances. degrade_visible names how many were left out.",
    )

    def validate(self, attrs: dict[str, Any]) -> Grouping:
        try:
            # A grouping is replaced whole, so a partial update that sends one gets the defaults too.
            return Grouping(
                mode=GroupingMode(attrs["mode"]),
                keys=tuple(attrs.get("keys", ())),
                max_instances=attrs.get("max_instances", DEFAULT_MAX_INSTANCES),
                on_overflow=OnOverflow(attrs.get("on_overflow", OnOverflow.DEGRADE_VISIBLE)),
            )
        except ValueError as error:
            raise ValidationError(str(error)) from error


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
    grouping = GroupingSerializer(read_only=True, help_text="How the alert splits its results into instances.")
    snooze_until = serializers.DateTimeField(
        read_only=True,
        allow_null=True,
        help_text="Time until which every instance's notifications are muted. Null when not muted. "
        "An instance's own snooze_until mutes one group, and the later of the two holds.",
    )
    check_status = serializers.ChoiceField(
        choices=PlatformAlertCheckStatus.choices,
        read_only=True,
        help_text="Whether the alert's checks succeed. Holds for every instance, because a failed check "
        "names no group.",
    )
    owner = serializers.ChoiceField(
        choices=PlatformAlertOwner.choices,
        read_only=True,
        help_text="Which stack evaluates and delivers the alert. Only an alert the platform owns can be "
        "edited here. The source product's own API edits the rest.",
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


class PlatformAlertConfigurationEditSerializer(serializers.Serializer):
    """The settings an edit can change. Each source kind subclasses it with a typed `source_config`."""

    source_kind = serializers.ChoiceField(
        choices=PlatformAlertConfigurationSourceKind.choices,
        help_text="Product whose data the alert evaluates. It cannot change, so it must match the stored value.",
    )
    name = serializers.CharField(max_length=255, help_text="Human-readable name of the alert.")
    enabled = serializers.BooleanField(help_text="Whether the alert is evaluated on schedule.")
    source_config = serializers.JSONField(help_text="Source-specific settings. The shape depends on source_kind.")
    grouping = GroupingSerializer(help_text="How the alert splits its results into instances.")
    schedule_restriction = ScheduleRestrictionField(
        allow_null=True,
        help_text="Blocked local time windows (HH:MM in the project timezone) when the alert does not notify. "
        "Null means no quiet hours.",
    )
    evaluation_periods = serializers.IntegerField(
        min_value=1, max_value=10, help_text="Number of recent checks considered when deciding to fire."
    )
    datapoints_to_alarm = serializers.IntegerField(
        min_value=1,
        max_value=10,
        help_text="Number of breaching checks within evaluation_periods required to fire. "
        "Cannot exceed evaluation_periods.",
    )
    cooldown_minutes = serializers.IntegerField(
        min_value=0, help_text="Minimum minutes between notifications for the same alert."
    )

    def validate_schedule_restriction(self, value: Any) -> dict[str, Any] | None:
        try:
            return validate_and_normalize_schedule_restriction(value)
        except ValueError as error:
            raise ValidationError(str(error)) from error


def _typed_edit_serializer(
    source: SourceKind, spec: SourceConfigSpec
) -> type[PlatformAlertConfigurationEditSerializer]:
    """The edit serializer for one source kind, whose `source_config` is described by the source's model."""
    prefix = source.value.capitalize()
    source_config_field = extend_schema_field(spec.model)(  # type: ignore[arg-type]
        type(f"{prefix}PlatformAlertSourceConfigField", (serializers.JSONField,), {})
    )
    return type(
        f"{prefix}PlatformAlertConfigurationEditSerializer",
        (PlatformAlertConfigurationEditSerializer,),
        {
            "source_config": source_config_field(
                help_text=f"Settings for a {source.value} alert. The bound the alert is evaluated against "
                "is under condition."
            )
        },
    )


@cache
def edit_serializers() -> dict[str, type[PlatformAlertConfigurationEditSerializer]]:
    """One edit serializer per kind a source registered. Built on first use, because each source's
    schema loads only then."""
    return {source.value: _typed_edit_serializer(source, spec) for source, spec in editable_source_configs().items()}


PLATFORM_ALERT_CONFIGURATION_EDIT = PolymorphicProxySerializer(
    component_name="PlatformAlertConfigurationEdit",
    serializers=lambda: dict[str, serializers.Serializer | type[serializers.Serializer]](edit_serializers()),
    resource_type_field_name="source_kind",
)

EDIT_RESPONSES = {
    200: PlatformAlertConfigurationSerializer,
    403: OpenApiResponse(description="The caller cannot write alerts of this source kind."),
    404: OpenApiResponse(description="No alert with this id that the caller can read."),
    409: OpenApiResponse(description="The source product owns this alert, so only its own API edits it."),
}


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

    def _writable_source_kinds(self) -> list[str]:
        token_scopes = get_authenticator_scopes(getattr(self.request, "successful_authenticator", None))
        writable: list[str] = []
        for source_kind in self._readable_source_kinds():
            resource = SOURCE_KIND_RESOURCE[source_kind]
            if source_kind not in edit_serializers():
                continue
            if not self.user_access_control.check_access_level_for_resource(resource, "editor"):
                continue
            if (
                token_scopes is not None
                and "*" not in token_scopes
                and scopes_not_covered(token_scopes, [f"{resource}:write"])
            ):
                continue
            writable.append(source_kind)
        return writable

    def _edit(self, request: Request, pk: str, *, partial: bool) -> Response:
        configuration_id = serializers.UUIDField().run_validation(pk)
        team_id = self._canonical_team_id()
        current = platform_api.get_configuration(
            team_id=team_id, source_kinds=self._readable_source_kinds(), configuration_id=configuration_id
        )
        if current is None:
            raise NotFound()
        writable = self._writable_source_kinds()
        if current.source_kind not in writable:
            raise PermissionDenied(f"You cannot edit {current.source_kind} alerts.")

        serializer = edit_serializers()[current.source_kind](data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        fields = dict(serializer.validated_data)
        if fields.pop("source_kind", current.source_kind) != current.source_kind:
            raise ValidationError({"source_kind": "The source kind of an alert cannot change."})

        try:
            updated = platform_api.update_configuration(
                team_id=team_id,
                source_kinds=writable,
                configuration_id=configuration_id,
                # A partial update names only the fields it changes. The rest keep what is stored.
                change=lambda stored: replace(stored, **fields),
            )
        except PlatformAlertNotEditable as error:
            raise Conflict(str(error)) from error
        except InvalidPlatformAlertEdit as error:
            raise ValidationError({error.field_name: str(error)}) from error
        if updated is None:
            raise NotFound()
        return Response(PlatformAlertConfigurationSerializer(updated).data)

    @extend_schema(request=PLATFORM_ALERT_CONFIGURATION_EDIT, responses=EDIT_RESPONSES)
    def update(self, request: Request, pk: str, **kwargs) -> Response:
        return self._edit(request, pk, partial=False)

    @extend_schema(request=PLATFORM_ALERT_CONFIGURATION_EDIT, responses=EDIT_RESPONSES)
    def partial_update(self, request: Request, pk: str, **kwargs) -> Response:
        return self._edit(request, pk, partial=True)

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
