from datetime import UTC, datetime
from typing import Any, cast

from django.db.models import Count

from drf_spectacular.utils import PolymorphicProxySerializer, extend_schema, extend_schema_field
from rest_framework import request, serializers, viewsets
from rest_framework.response import Response
from rest_framework.settings import api_settings
from rest_framework_csv import renderers as csvrenderers

from posthog.schema import ProductKey

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.constants import TREND_FILTER_TYPE_EVENTS
from posthog.event_usage import report_user_action
from posthog.models import Action
from posthog.models.action.action import ACTION_STEP_MATCHING_OPTIONS
from posthog.models.activity_logging.activity_log import Detail, changes_between, log_activity
from posthog.models.event.event import Selector
from posthog.models.property.util import build_selector_regex
from posthog.models.signals import model_activity_signal, mutable_receiver
from posthog.rbac.access_control_api_mixin import AccessControlViewSetMixin
from posthog.rbac.user_access_control import UserAccessControlSerializerMixin

from .documentation import (
    ArrayPropertyFilterSerializer,
    DatePropertyFilterSerializer,
    ExistencePropertyFilterSerializer,
    NumericPropertyFilterSerializer,
    StringPropertyFilterSerializer,
)
from .forbid_destroy_model import ForbidDestroyModel
from .tagged_item import TaggedItemSerializerMixin, TaggedItemViewSetMixin

_PropertyFilterUnion = PolymorphicProxySerializer(
    component_name="ActionStepPropertyFilter",
    serializers=[
        StringPropertyFilterSerializer,
        NumericPropertyFilterSerializer,
        ArrayPropertyFilterSerializer,
        DatePropertyFilterSerializer,
        ExistencePropertyFilterSerializer,
    ],
    resource_type_field_name=None,
)


@extend_schema_field(serializers.ListSerializer(child=_PropertyFilterUnion))
class _ActionStepPropertiesField(serializers.ListField):
    """ListField annotated with a typed OpenAPI schema via a oneOf property filter union.

    Runtime validation remains a simple ListField(child=DictField()) — the
    @extend_schema_field decorator only affects the generated OpenAPI spec.
    """

    pass


class ActionStepJSONSerializer(serializers.Serializer):
    event = serializers.CharField(
        required=False,
        allow_null=True,
        trim_whitespace=False,
        help_text="Event name to match (e.g. '$pageview', '$autocapture', or a custom event name).",
    )
    properties = _ActionStepPropertiesField(
        child=serializers.DictField(),
        required=False,
        allow_null=True,
        help_text="Event or person property filters. Each item should have 'key' (string), 'value' (string, number, boolean, or array), optional 'operator' (exact, is_not, is_set, is_not_set, icontains, not_icontains, regex, not_regex, gt, gte, lt, lte), and optional 'type' (event, person).",
    )
    selector = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="CSS selector to match the target element (e.g. 'div > button.cta').",
    )
    selector_regex = serializers.SerializerMethodField()
    tag_name = serializers.CharField(
        required=False,
        allow_null=True,
        trim_whitespace=False,
        help_text='HTML tag name to match (e.g. "button", "a", "input").',
    )
    text = serializers.CharField(
        required=False,
        allow_null=True,
        trim_whitespace=False,
        help_text="Element text content to match.",
    )
    text_matching = serializers.ChoiceField(
        choices=ACTION_STEP_MATCHING_OPTIONS,
        required=False,
        allow_null=True,
        help_text="How to match the text value. Defaults to exact.",
    )
    href = serializers.CharField(
        required=False,
        allow_null=True,
        trim_whitespace=False,
        help_text="Link href attribute to match.",
    )
    href_matching = serializers.ChoiceField(
        choices=ACTION_STEP_MATCHING_OPTIONS,
        required=False,
        allow_null=True,
        help_text="How to match the href value. Defaults to exact.",
    )
    url = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="Page URL to match.",
    )
    url_matching = serializers.ChoiceField(
        choices=ACTION_STEP_MATCHING_OPTIONS,
        required=False,
        allow_null=True,
        help_text="How to match the URL value. Defaults to contains.",
    )

    def get_selector_regex(self, obj) -> str | None:
        selector_str = obj.get("selector") if isinstance(obj, dict) else getattr(obj, "selector", None)
        if not selector_str:
            return None
        try:
            selector = Selector(selector_str, escape_slashes=False)
            return build_selector_regex(selector)
        except Exception:
            return None


class ActionSerializer(
    TaggedItemSerializerMixin, UserAccessControlSerializerMixin, serializers.HyperlinkedModelSerializer
):
    steps = ActionStepJSONSerializer(
        many=True,
        required=False,
        help_text="Action steps defining trigger conditions. Each step matches events by name, properties, URL, or element attributes. Multiple steps are OR-ed together.",
    )
    created_by = UserBasicSerializer(read_only=True)
    is_calculating = serializers.SerializerMethodField()
    is_action = serializers.BooleanField(read_only=True, default=True)
    creation_context = serializers.SerializerMethodField()
    _create_in_folder = serializers.CharField(required=False, allow_blank=True, write_only=True)

    class Meta:
        model = Action
        fields = [
            "id",
            "name",
            "description",
            "tags",
            "post_to_slack",
            "slack_message_format",
            "steps",
            "created_at",
            "created_by",
            "deleted",
            "is_calculating",
            "last_calculated_at",
            "team_id",
            "is_action",
            "bytecode_error",
            "pinned_at",
            "creation_context",
            "_create_in_folder",
            "user_access_level",
        ]
        read_only_fields = [
            "team_id",
            "bytecode_error",
        ]
        extra_kwargs = {
            "team_id": {"read_only": True},
            "name": {"help_text": "Name of the action (must be unique within the project)."},
            "description": {"help_text": "Human-readable description of what this action represents."},
            "tags": {"help_text": "Tags for organizing and filtering actions."},
            "post_to_slack": {"help_text": "Whether to post a notification to Slack when this action is triggered."},
            "slack_message_format": {
                "help_text": "Custom Slack message format. Supports templates with event properties."
            },
            "pinned_at": {
                "help_text": "ISO 8601 timestamp when the action was pinned, or null if not pinned. Set any value to pin, null to unpin."
            },
        }

    def get_is_calculating(self, action: Action) -> bool:
        return False

    def get_creation_context(self, obj):
        return None

    def validate(self, attrs):
        instance = cast(Action, self.instance)
        exclude_args = {}
        if instance:
            include_args = {"team": instance.team}
            exclude_args = {"id": instance.pk}
        else:
            attrs["team_id"] = self.context["view"].team_id
            include_args = {"team_id": attrs["team_id"]}
        if attrs.get("pinned_at") == "":
            attrs["pinned_at"] = None

        if "name" in attrs:
            colliding_action_ids = list(
                Action.objects.filter(name=attrs["name"], deleted=False, **include_args)
                .exclude(**exclude_args)[:1]
                .values_list("id", flat=True)
            )
            if colliding_action_ids:
                raise serializers.ValidationError(
                    {"name": f"This project already has an action with this name, ID {colliding_action_ids[0]}"},
                    code="unique",
                )

        return attrs

    def create(self, validated_data: Any) -> Any:
        creation_context = self.context["request"].data.get("creation_context")
        validated_data["created_by"] = self.context["request"].user
        instance = super().create(validated_data)

        report_user_action(
            validated_data["created_by"],
            "action created",
            {**instance.get_analytics_metadata(), "creation_context": creation_context},
            team=instance.team,
            request=self.context["request"],
        )

        return instance

    def update(self, instance: Any, validated_data: dict[str, Any]) -> Any:
        if validated_data.get("pinned_at"):
            if instance.pinned_at:
                # drop it from the update
                del validated_data["pinned_at"]
            else:
                # ignore the user-provided timestamp, generate our own
                validated_data["pinned_at"] = datetime.now(UTC).isoformat()

        instance = super().update(instance, validated_data)

        report_user_action(
            self.context["request"].user,
            "action updated",
            {
                **instance.get_analytics_metadata(),
                "updated_by_creator": self.context["request"].user == instance.created_by,
            },
            team=instance.team,
            request=self.context["request"],
        )
        return instance


@extend_schema(tags=[ProductKey.ACTIONS])
class ActionViewSet(
    TeamAndOrgViewSetMixin,
    AccessControlViewSetMixin,
    TaggedItemViewSetMixin,
    ForbidDestroyModel,
    viewsets.ModelViewSet,
):
    scope_object = "action"
    renderer_classes = (*tuple(api_settings.DEFAULT_RENDERER_CLASSES), csvrenderers.PaginatedCSVRenderer)
    queryset = Action.objects.select_related("created_by").all()
    serializer_class = ActionSerializer
    ordering = ["-last_calculated_at", "name"]

    def safely_get_queryset(self, queryset):
        if self.action == "list":
            queryset = queryset.filter(deleted=False)

        queryset = queryset.annotate(count=Count(TREND_FILTER_TYPE_EVENTS))
        return queryset.filter(team_id=self.team_id).order_by(*self.ordering)

    def list(self, request: request.Request, *args: Any, **kwargs: Any) -> Response:
        # :HACKY: we need to override this viewset method until actions support
        # better pagination in the taxonomic filter and on the actions page
        actions = self.filter_queryset(self.get_queryset())
        actions_list: list[dict[Any, Any]] = self.serializer_class(
            actions, many=True, context={"request": request, "view": self}
        ).data  # type: ignore
        return Response({"results": actions_list})


@mutable_receiver(model_activity_signal, sender=Action)
def handle_action_change(sender, scope, before_update, after_update, activity, was_impersonated=False, **kwargs):
    # Detect soft delete/restore by checking the deleted field
    if before_update and after_update:
        if not before_update.deleted and after_update.deleted:
            # Soft deleted
            activity = "deleted"
        elif before_update.deleted and not after_update.deleted:
            # Restored from soft delete
            activity = "updated"

    log_activity(
        organization_id=after_update.team.organization_id,
        team_id=after_update.team_id,
        user=after_update.created_by,
        was_impersonated=was_impersonated,
        item_id=after_update.id,
        scope=scope,
        activity=activity,
        detail=Detail(
            changes=changes_between(scope, previous=before_update, current=after_update),
            name=after_update.name,
        ),
    )
