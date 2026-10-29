from dataclasses import replace
from functools import cache, cached_property
from typing import Any, Literal, cast
from uuid import UUID

from django.db import transaction

from drf_spectacular.utils import OpenApiResponse, PolymorphicProxySerializer, extend_schema, extend_schema_field
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.pagination import PrecountedLimitOffsetPagination
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.event_usage import report_user_action
from posthog.exceptions import Conflict
from posthog.models import Team, User
from posthog.permissions import (
    FEATURE_FLAG_REQUIRED_ERROR_CODE,
    PostHogFeatureFlagPermission,
    get_authenticator_client,
    get_authenticator_scoped_team_ids,
    get_authenticator_scopes,
    posthog_feature_flag_enabled,
)
from posthog.scopes import APIScopeObject, scopes_not_covered

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.alerts_platform.backend.facade import api as platform_api
from products.alerts_platform.backend.facade.contracts import (
    DEFAULT_MAX_INSTANCES,
    MAX_EVALUATION_PERIODS,
    MAX_INSTANCES_CEILING,
    MAX_STORED_INTEGER,
    Grouping,
    GroupingMode,
    InvalidPlatformAlertEdit,
    OnOverflow,
    PlatformAlertConfigurationEdit,
    PlatformAlertConfigurationView,
    PlatformAlertCreateRefused,
    PlatformAlertNotEditable,
    SourceConfigSpec,
    SourceKind,
    UnknownPlatformAlertGroup,
)
from products.alerts_platform.backend.facade.enums import (
    PlatformAlertCheckStatus,
    PlatformAlertConfigurationRecurrenceUnit,
    PlatformAlertConfigurationSourceKind,
    PlatformAlertOwner,
    PlatformAlertState,
)
from products.alerts_platform.backend.facade.source_configs import editable_source_configs
from products.alerts_platform.backend.presentation.views.schedule_restriction import ScheduleRestrictionField

RULE_LABELS_HELP = (
    'Labels that say who owns the alert and how urgent it is, such as {"team": "checkout", "severity": "critical"}. '
    "Names use letters, digits and underscores. alertname and names that start with posthog_ are reserved. "
    "Values cannot use templates."
)
RULE_ANNOTATIONS_HELP = (
    'Context for whoever responds, such as {"runbook_url": "https://..."}. Values can use '
    "{{ $labels.<name> }} for a grouping key or label of the alert, and {{ $value }}. An annotation "
    "whose name ends in _url must start with https://."
)


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
    labels = serializers.DictField(
        child=serializers.CharField(),
        read_only=True,
        help_text="Result labels and their values for the group this instance tracks, such as "
        '{"service_name": "checkout"}. Empty when the source does not group results.',
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
        max_value=MAX_INSTANCES_CEILING,
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
        # A partial update makes every nested field optional, but a grouping is replaced whole.
        if "mode" not in attrs:
            raise ValidationError({"mode": "This field is required."})
        try:
            return Grouping.from_stored(attrs)
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
    overflowed_groups = serializers.IntegerField(
        read_only=True,
        help_text="New groups the last successful check could not track because the alert already held "
        "grouping.max_instances instances. 0 when every group fit.",
    )
    overflow_is_lower_bound = serializers.BooleanField(
        read_only=True,
        help_text="Whether the last successful check cut its results before counting overflowed_groups. "
        "When true, more groups than overflowed_groups may be untracked.",
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
    labels = serializers.DictField(
        child=serializers.CharField(),
        read_only=True,
        help_text=RULE_LABELS_HELP,
    )
    annotations = serializers.DictField(
        child=serializers.CharField(),
        read_only=True,
        help_text=RULE_ANNOTATIONS_HELP,
    )


class PlatformAlertConfigurationListQuerySerializer(serializers.Serializer):
    legacy_configuration_id = serializers.UUIDField(
        required=False,
        help_text="Only the alert copied from, or created with, this source configuration, such as a logs alert's id.",
    )


# A configuration shows the source product's data (its filters and firing state), so a reader
# also needs read access to that product. `alert:read` alone must not reveal it.
SOURCE_KIND_RESOURCE: dict[str, APIScopeObject] = {
    PlatformAlertConfigurationSourceKind.LOGS.value: "logs",
    PlatformAlertConfigurationSourceKind.WAREHOUSE_SOURCE.value: "external_data_source",
    PlatformAlertConfigurationSourceKind.WAREHOUSE_DESTINATION.value: "external_data_source",
    PlatformAlertConfigurationSourceKind.METRICS.value: "metrics",
}

# Kinds the read API does not serve. An insight copy shows its insight's bound and firing state,
# and a reader can hold access to insights in general but not to that insight. This product
# cannot check access to one insight, so the copies stay out of the API until it can.
UNSERVED_SOURCE_KINDS: frozenset[str] = frozenset({PlatformAlertConfigurationSourceKind.INSIGHT.value})


class PlatformAlertConfigurationEditSerializer(serializers.Serializer):
    """The settings an edit can change. Each source kind subclasses it with a typed `source_config`."""

    # A plain string: each subclass serves one kind, and the request schema's discriminator lists them.
    source_kind = serializers.CharField(
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
        min_value=1,
        max_value=MAX_EVALUATION_PERIODS,
        help_text="Number of recent checks considered when deciding to fire.",
    )
    datapoints_to_alarm = serializers.IntegerField(
        min_value=1,
        max_value=MAX_EVALUATION_PERIODS,
        help_text="Number of breaching checks within evaluation_periods required to fire. "
        "Cannot exceed evaluation_periods.",
    )
    cooldown_minutes = serializers.IntegerField(
        min_value=0,
        max_value=MAX_STORED_INTEGER,
        help_text="Minimum minutes between notifications for the same alert.",
    )
    # Optional, so a full update that leaves them out keeps what is stored.
    labels = serializers.DictField(
        child=serializers.CharField(),
        required=False,
        help_text=RULE_LABELS_HELP,
    )
    annotations = serializers.DictField(
        child=serializers.CharField(trim_whitespace=False),
        required=False,
        help_text=RULE_ANNOTATIONS_HELP,
    )


def _typed_edit_serializer(
    source: SourceKind, spec: SourceConfigSpec
) -> type[PlatformAlertConfigurationEditSerializer]:
    """The edit serializer for one source kind, whose `source_config` is described by the source's model."""
    # Pascal case, so a kind like `warehouse_source` names its schema component `WarehouseSource...`.
    prefix = "".join(part.capitalize() for part in source.value.split("_"))
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


DEFAULT_ALERT_NAME = "Untitled alert"


# The default of each setting a create may leave out, with the help text that names it.
CREATE_DEFAULTS: dict[str, tuple[Any, str]] = {
    "name": (DEFAULT_ALERT_NAME, f"Defaults to '{DEFAULT_ALERT_NAME}'."),
    "enabled": (True, "Defaults to true."),
    "grouping": (Grouping, "Defaults to mode single."),
    "schedule_restriction": (None, "Defaults to null."),
    "evaluation_periods": (1, "Defaults to 1."),
    "datapoints_to_alarm": (1, "Defaults to 1."),
    "cooldown_minutes": (0, "Defaults to 0."),
}


def _with_default(field: serializers.Field, default: Any, note: str) -> serializers.Field:
    # Built again from the edit field's own arguments, so a create validates every setting as an edit does.
    # DRF records every field's constructor arguments on `_args` and `_kwargs`, which its stubs leave out.
    original: dict[str, Any] = field._kwargs  # type: ignore[attr-defined]
    args: tuple[Any, ...] = field._args  # type: ignore[attr-defined]
    return type(field)(*args, **{**original, "default": default, "help_text": f"{original['help_text']} {note}"})


def _typed_create_serializer(
    edit_serializer: type[PlatformAlertConfigurationEditSerializer],
) -> type[PlatformAlertConfigurationEditSerializer]:
    """The create serializer for one source kind: its edit serializer, with a default for every
    setting but `source_config`, so a create stores each default and a read returns it."""
    declared = edit_serializer._declared_fields
    return type(
        edit_serializer.__name__.replace("Edit", "Create"),
        (edit_serializer,),
        {
            "__doc__": "The settings of a new alert. Every one but source_config has a default, which is stored.",
            "source_kind": serializers.CharField(
                help_text="Product whose data the alert evaluates. It cannot change after the create.",
            ),
            **{name: _with_default(declared[name], default, note) for name, (default, note) in CREATE_DEFAULTS.items()},
        },
    )


@cache
def create_serializers() -> dict[str, type[PlatformAlertConfigurationEditSerializer]]:
    """One create serializer per kind the API can create."""
    creatable = {source.value for source, spec in editable_source_configs().items() if spec.creatable}
    return {
        source_kind: _typed_create_serializer(serializer)
        for source_kind, serializer in edit_serializers().items()
        if source_kind in creatable
    }


PLATFORM_ALERT_CONFIGURATION_CREATE = PolymorphicProxySerializer(
    component_name="PlatformAlertConfigurationCreate",
    serializers=lambda: dict[str, serializers.Serializer | type[serializers.Serializer]](create_serializers()),
    resource_type_field_name="source_kind",
)

CREATE_RESPONSES = {
    201: PlatformAlertConfigurationSerializer,
    400: OpenApiResponse(description="The settings are invalid, or the source refused the create."),
    403: OpenApiResponse(description="The caller cannot write alerts of this source kind."),
    409: OpenApiResponse(description="The URL names an environment, whose alerts are created on its own page."),
}

PLATFORM_ALERT_CONFIGURATION_EDIT = PolymorphicProxySerializer(
    component_name="PlatformAlertConfigurationEdit",
    serializers=lambda: dict[str, serializers.Serializer | type[serializers.Serializer]](edit_serializers()),
    resource_type_field_name="source_kind",
)


class PlatformAlertGroupSnoozeSerializer(serializers.Serializer):
    grouping_key = serializers.CharField(
        max_length=255,
        help_text="Key of the group to snooze, as the grouping_key of one of the alert's instances.",
    )
    snooze_until = serializers.DateTimeField(
        allow_null=True,
        help_text="Time until which this group's notifications are muted. Must be in the future and at most "
        "30 days away. Null clears the group's snooze. The group keeps being checked, and its firing stays open.",
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
        # The scope check before the view ran saw only the URL's team, so a key confined to some
        # projects must reach the parent as well.
        scoped_teams = get_authenticator_scoped_team_ids(getattr(self.request, "successful_authenticator", None))
        if scoped_teams is not None and parent_team.id not in scoped_teams:
            raise PermissionDenied(f"API key does not have access to the requested project: ID {parent_team.id}.")
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

    def _source_kinds_with(
        self, access_level: Literal["viewer", "editor"], scope_action: Literal["read", "write"]
    ) -> list[str]:
        # Session auth carries no scopes, so only the access-control check applies to it.
        token_scopes = get_authenticator_scopes(getattr(self.request, "successful_authenticator", None))
        permitted: list[str] = []
        for source_kind, resource in SOURCE_KIND_RESOURCE.items():
            if not self.user_access_control.check_access_level_for_resource(resource, access_level):
                continue
            if (
                token_scopes is not None
                and "*" not in token_scopes
                and scopes_not_covered(token_scopes, [f"{resource}:{scope_action}"])
            ):
                continue
            permitted.append(source_kind)
        return permitted

    def _readable_source_kinds(self) -> list[str]:
        return self._source_kinds_with("viewer", "read")

    @cached_property
    def _writable_source_kinds(self) -> list[str]:
        return self._source_kinds_with("editor", "write")

    def _writable_configuration(
        self, team_id: int, configuration_id: UUID, verb: str
    ) -> PlatformAlertConfigurationView:
        current = platform_api.get_configuration(
            team_id=team_id, source_kinds=self._readable_source_kinds(), configuration_id=configuration_id
        )
        if current is None:
            raise NotFound()
        if current.source_kind not in self._writable_source_kinds:
            raise PermissionDenied(f"You cannot {verb} {current.source_kind} alerts.")
        return current

    def _edit(self, request: Request, pk: str, *, partial: bool) -> Response:
        configuration_id = serializers.UUIDField().run_validation(pk)
        team_id = self._canonical_team_id()
        current = self._writable_configuration(team_id, configuration_id, "edit")
        # Checked again under the row lock. Here it answers before the body is validated, so a caller
        # never fixes a body for an alert it can never write.
        if current.owner != PlatformAlertOwner.PLATFORM:
            raise Conflict(f"This alert is managed by the {current.source_kind} product. Edit it there.")
        edit_serializer = edit_serializers().get(current.source_kind)
        if edit_serializer is None:
            raise Conflict(f"{current.source_kind} alerts cannot be edited through this API.")

        serializer = edit_serializer(data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        fields = dict(serializer.validated_data)
        if fields.pop("source_kind", current.source_kind) != current.source_kind:
            raise ValidationError({"source_kind": "The source kind of an alert cannot change."})

        try:
            updated = platform_api.update_configuration(
                team_id=team_id,
                source_kinds=self._writable_source_kinds,
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

    @extend_schema(request=PLATFORM_ALERT_CONFIGURATION_CREATE, responses=CREATE_RESPONSES)
    def create(self, request: Request, **kwargs) -> Response:
        # The rows live on the project, so an alert made here would count the project's data rather
        # than the environment's that the URL names.
        if self.team.parent_team_id is not None:
            raise Conflict("This URL names an environment. Create its alerts on that environment's logs alerts page.")
        source_kind = request.data.get("source_kind") if isinstance(request.data, dict) else None
        create_serializer = create_serializers().get(source_kind) if isinstance(source_kind, str) else None
        if create_serializer is None:
            raise ValidationError(
                {"source_kind": f"Must be one of: {', '.join(sorted(create_serializers()))}."}, code="invalid_choice"
            )
        # The kind comes from the body, so the source product's scope and access are checked here
        # rather than through `required_scopes`.
        if source_kind not in self._source_kinds_with("editor", "write"):
            raise PermissionDenied(f"You cannot create {source_kind} alerts.")
        self._check_rollout_flag(SourceKind(source_kind))

        serializer = create_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        fields = dict(serializer.validated_data)
        fields.pop("source_kind")
        try:
            created = platform_api.create_configuration(
                team_id=self._canonical_team_id(),
                source_kind=SourceKind(source_kind),
                edit=PlatformAlertConfigurationEdit(**fields),
                created_by_id=cast(User, request.user).id,
            )
        except PlatformAlertNotEditable as error:
            raise Conflict(str(error)) from error
        except InvalidPlatformAlertEdit as error:
            raise ValidationError({error.field_name: str(error)}) from error
        except PlatformAlertCreateRefused as error:
            raise ValidationError(str(error)) from error
        # Robust, so an analytics failure, such as a malformed Referer, cannot fail a create that committed.
        transaction.on_commit(lambda: self._track("created", created), robust=True)
        return Response(PlatformAlertConfigurationSerializer(created).data, status=status.HTTP_201_CREATED)

    def _check_rollout_flag(self, source_kind: SourceKind) -> None:
        spec = editable_source_configs().get(source_kind)
        if spec is None or spec.rollout_flag is None:
            return
        if not posthog_feature_flag_enabled(
            spec.rollout_flag,
            str(cast(User, self.request.user).distinct_id),
            organization_id=self.team.organization_id,
            team_id=self.team.id,
            caller_properties=get_authenticator_client(getattr(self.request, "successful_authenticator", None)),
        ):
            raise PermissionDenied(
                f"{source_kind.value.capitalize()} alerts are not available for this project yet.",
                code=FEATURE_FLAG_REQUIRED_ERROR_CODE,
            )

    def _track(self, action: Literal["created", "deleted"], configuration: PlatformAlertConfigurationView) -> None:
        report_user_action(
            cast(User, self.request.user),
            f"alert {action}",
            {
                "alert_id": str(configuration.id),
                "alert_name": configuration.name,
                "config_type": "PlatformAlertConfiguration",
                "source_kind": configuration.source_kind,
                "legacy_configuration_id": str(configuration.legacy_configuration_id),
                "enabled": configuration.enabled,
            },
            team=self.team,
            request=self.request,
        )

    @extend_schema(request=PLATFORM_ALERT_CONFIGURATION_EDIT, responses=EDIT_RESPONSES)
    def update(self, request: Request, pk: str, **kwargs) -> Response:
        return self._edit(request, pk, partial=False)

    @extend_schema(request=PLATFORM_ALERT_CONFIGURATION_EDIT, responses=EDIT_RESPONSES)
    def partial_update(self, request: Request, pk: str, **kwargs) -> Response:
        return self._edit(request, pk, partial=True)

    @extend_schema(
        responses={
            204: OpenApiResponse(description="The alert, its source's own row and its destinations are deleted."),
            403: OpenApiResponse(description="The caller cannot write alerts of this source kind."),
            404: OpenApiResponse(description="No alert with this id that the caller can read."),
            409: OpenApiResponse(description="The source product owns this alert, so only its own API deletes it."),
        }
    )
    def destroy(self, request: Request, pk: str, **kwargs) -> Response:
        configuration_id = serializers.UUIDField().run_validation(pk)
        team_id = self._canonical_team_id()
        current = self._writable_configuration(team_id, configuration_id, "delete")
        # Checked again by the delete, under the source row's lock.
        if current.owner != PlatformAlertOwner.PLATFORM:
            raise Conflict(f"This alert is managed by the {current.source_kind} product. Delete it there.")
        try:
            deleted = platform_api.delete_configuration(
                team_id=team_id, source_kinds=self._writable_source_kinds, configuration_id=configuration_id
            )
        except PlatformAlertNotEditable as error:
            raise Conflict(str(error)) from error
        if not deleted:
            raise NotFound()
        transaction.on_commit(lambda: self._track("deleted", current), robust=True)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @validated_request(
        PlatformAlertGroupSnoozeSerializer,
        responses={
            200: PlatformAlertSerializer,
            400: OpenApiResponse(description="The time is not in the future, or the alert is not grouped."),
            403: OpenApiResponse(description="The caller cannot write alerts of this source kind."),
            404: OpenApiResponse(
                description="No alert with this id that the caller can read, or no group with this key."
            ),
            409: OpenApiResponse(description="The source product owns this alert, so only its own API changes it."),
        },
        summary="Snooze one group of a grouped alert",
    )
    @action(detail=True, methods=["post"], required_scopes=["alert:write"])
    def snooze_group(self, request: ValidatedRequest, pk: str, **kwargs) -> Response:
        configuration_id = serializers.UUIDField().run_validation(pk)
        team_id = self._canonical_team_id()
        self._writable_configuration(team_id, configuration_id, "snooze")
        try:
            group = platform_api.snooze_group(
                team_id=team_id,
                source_kinds=self._writable_source_kinds,
                configuration_id=configuration_id,
                grouping_key=request.validated_data["grouping_key"],
                snooze_until=request.validated_data["snooze_until"],
            )
        except PlatformAlertNotEditable as error:
            raise Conflict(str(error)) from error
        except UnknownPlatformAlertGroup as error:
            raise NotFound(
                "This alert has no group with that key. A group that stays quiet is removed, so refresh the "
                "alert to see its current groups."
            ) from error
        except InvalidPlatformAlertEdit as error:
            raise ValidationError({error.field_name: str(error)}) from error
        if group is None:
            raise NotFound()
        return Response(PlatformAlertSerializer(group).data)

    @extend_schema(parameters=[PlatformAlertConfigurationListQuerySerializer])
    def list(self, request: Request, **kwargs) -> Response:
        query = PlatformAlertConfigurationListQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        paginator = cast(PrecountedLimitOffsetPagination, self.paginator)
        limit = paginator.get_limit(request)
        assert limit is not None
        page = platform_api.list_configurations(
            team_id=self._canonical_team_id(),
            source_kinds=self._readable_source_kinds(),
            limit=limit,
            offset=paginator.get_offset(request),
            legacy_configuration_id=query.validated_data.get("legacy_configuration_id"),
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
