from datetime import timedelta
from typing import Any, Literal

from django.utils import timezone

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field, extend_schema_serializer
from rest_framework import serializers
from rest_framework.fields import empty

from posthog.api.fields import JSONTolerantListField, RepeatedOrCommaSeparatedListField
from posthog.api.shared import UserBasicSerializer
from posthog.models.user import User

from products.annotations.backend.facade import api, contracts
from products.annotations.backend.facade.enums import AnnotationCreationType, AnnotationScope, ChangeKind

DEFAULT_WINDOW = timedelta(hours=24)
DEFAULT_LIMIT = 100
MAX_LIMIT = 500


class ChangeKindsField(RepeatedOrCommaSeparatedListField, JSONTolerantListField):
    """Repeated keys, one comma-joined value (the generated frontend client) or one JSON array (the MCP client).

    The base order matters: JSONTolerantListField reads a JSON array before
    RepeatedOrCommaSeparatedListField splits on commas.
    """


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
    kinds = ChangeKindsField(
        child=serializers.ChoiceField(choices=ChangeKind.choices),
        required=False,
        default=[],
        help_text=(
            "Return only these kinds of change. Omit to return every kind. "
            "Use `feature_flag` and `experiment` to see configuration edits without releases and annotations."
        ),
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


_CONTENT_MAX_LENGTH = 8192
_EMOJI_MAX_LENGTH = 16


@extend_schema_field(OpenApiTypes.INT)
class InsightReferenceField(serializers.Field):
    """An insight id, read and written the way a primary key related field does it.

    The insight resolves through the annotations facade to an `AnnotationParent`, so a soft-deleted
    insight of the project resolves too. `AnnotationSerializer.validate_dashboard_item` decides what
    a deleted one may do.
    """

    default_error_messages = {
        "required": serializers.PrimaryKeyRelatedField.default_error_messages["required"],
        "does_not_exist": serializers.PrimaryKeyRelatedField.default_error_messages["does_not_exist"],
        "incorrect_type": serializers.PrimaryKeyRelatedField.default_error_messages["incorrect_type"],
    }

    def run_validation(self, data: Any = empty) -> Any:
        # Relational fields read an empty string as null.
        if data == "":
            data = None
        return super().run_validation(data)

    def to_internal_value(self, data: Any) -> contracts.AnnotationParent:
        # The cast the ORM applies to a primary key lookup, so the same inputs pass and fail.
        try:
            if isinstance(data, bool):
                raise TypeError
            insight_id = int(data)
        except (TypeError, ValueError):
            self.fail("incorrect_type", data_type=type(data).__name__)
        team_id = self.context.get("team_id")
        parent = api.find_insight_parent(team_id=team_id, insight_id=insight_id) if team_id else None
        if parent is None:
            self.fail("does_not_exist", pk_value=data)
        return parent

    def to_representation(self, value: int) -> int:
        return value


class AnnotationSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True, label="ID", help_text="Unique ID of the annotation.")
    content = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        max_length=_CONTENT_MAX_LENGTH,
        help_text="Annotation text shown on charts to describe the change, release, or incident.",
    )
    date_marker = serializers.DateTimeField(
        required=False,
        allow_null=True,
        help_text="When this annotation happened (ISO 8601 timestamp). Used to position it on charts.",
    )
    creation_type = serializers.ChoiceField(
        choices=AnnotationCreationType.choices,
        required=False,
        help_text="Who created this annotation. Use `USR` for user-created notes and `GIT` for bot/deployment notes.",
    )
    # Soft-deleted parents resolve here because the frontend echoes both parent ids back on every write. A
    # project-scoped annotation whose dashboard was deleted would otherwise be impossible to edit or delete.
    # Only the pointer the annotation already stores may be echoed. Every other deleted parent answers as if
    # it does not exist.
    dashboard_item = InsightReferenceField(
        source="insight_id",
        required=False,
        allow_null=True,
        help_text="Optional insight ID to attach this annotation to. Must belong to the current project.",
    )
    dashboard_id = serializers.IntegerField(
        required=False,
        allow_null=True,
        help_text="Optional dashboard ID to attach this annotation to. Must belong to the current project.",
    )
    dashboard_name = serializers.CharField(
        read_only=True,
        allow_null=True,
        help_text="Name of the dashboard in `dashboard_id`, or null when there is none.",
    )
    insight_short_id = serializers.CharField(
        read_only=True,
        allow_null=True,
        help_text="Short ID of the insight in `dashboard_item`, or null when there is none.",
    )
    insight_name = serializers.CharField(
        read_only=True, allow_null=True, help_text="Name of the insight in `dashboard_item`, or null when it has none."
    )
    insight_derived_name = serializers.CharField(
        read_only=True,
        allow_null=True,
        help_text="Generated name of the insight in `dashboard_item`, shown when the insight has no name.",
    )
    created_by = UserBasicSerializer(read_only=True, help_text="User who created the annotation.")
    created_at = serializers.DateTimeField(
        read_only=True, allow_null=True, help_text="When the annotation was created."
    )
    updated_at = serializers.DateTimeField(read_only=True, help_text="When the annotation was last changed.")
    deleted = serializers.BooleanField(
        required=False,
        help_text="Soft-delete flag. Set to true to hide the annotation, or false to restore it.",
    )
    scope = serializers.ChoiceField(
        choices=AnnotationScope.choices,
        required=False,
        help_text=(
            "Annotation visibility scope: `project`, `organization`, `dashboard`, or `dashboard_item`. "
            "`recording` is deprecated and rejected."
        ),
    )
    emoji = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        max_length=_EMOJI_MAX_LENGTH,
        help_text="Optional emoji shown in place of the default badge when this annotation is surfaced on a chart.",
    )
    hidden_in_user_interface = serializers.BooleanField(
        required=False,
        allow_null=True,
        help_text=(
            "When true, the annotation is hidden from the PostHog UI (charts and the annotations list) "
            "but still readable over the API and MCP. Use for high-frequency markers like deployments "
            "that would otherwise crowd the UI. Null (the default) means the annotation is shown."
        ),
    )

    def validate_emoji(self, value: str | None) -> str | None:
        # Normalise blank strings to None so the DB has a single canonical "no emoji" state.
        return value or None

    def validate_dashboard_item(self, value: contracts.AnnotationParent | None) -> contracts.AnnotationParent | None:
        # A deleted insight answers exactly as an unknown one does unless the annotation already
        # points at it, so a guessed ID cannot report back its name.
        if value is not None and value.deleted and value.id != getattr(self.instance, "insight_id", None):
            self.fields["dashboard_item"].fail("does_not_exist", pk_value=value.id)
        return value

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if attrs.get("scope") == AnnotationScope.RECORDING.value:
            raise serializers.ValidationError("Recording scope is deprecated")

        instance: contracts.Annotation | None = self.instance
        if attrs.get("dashboard_id") is not None:
            dashboard = api.find_dashboard_parent(
                team_id=self.context["get_team"]().id, dashboard_id=attrs["dashboard_id"]
            )
            stored_dashboard_id = instance.dashboard_id if instance is not None else None
            # A deleted dashboard answers exactly as an unknown one does unless the annotation already
            # points at it, so a guessed ID cannot report back its name.
            if dashboard is None or (dashboard.deleted and dashboard.id != stored_dashboard_id):
                raise serializers.ValidationError({"dashboard_id": "Dashboard not found."})
            if dashboard.id != stored_dashboard_id:
                self._require_viewer_access(dashboard, "dashboard_id", "dashboard")

        insight = attrs.get("insight_id")
        if insight is not None and insight.id != (instance.insight_id if instance is not None else None):
            self._require_viewer_access(insight, "dashboard_item", "insight")
        return attrs

    def _require_viewer_access(
        self, parent: contracts.AnnotationParent, field: str, resource: Literal["dashboard", "insight"]
    ) -> None:
        user_access_control = self.context["view"].user_access_control
        if isinstance(self.context["request"].user, User) and user_access_control.denied_object_ids(
            resource, [(str(parent.id), parent.team_id, parent.created_by_id)], "viewer"
        ):
            raise serializers.ValidationError({field: f"You need viewer access to this {resource} to annotate it."})

    def to_write(self) -> contracts.AnnotationWrite:
        data = dict(self.validated_data)
        if "insight_id" in data:
            insight = data["insight_id"]
            data["insight_id"] = insight.id if insight is not None else None
        return contracts.AnnotationWrite(fields_set=frozenset(data), **data)
