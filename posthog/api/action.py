from datetime import UTC, datetime
from typing import Any, cast

from django.db.models import Count
from django.dispatch import receiver

from rest_framework import request, serializers, viewsets
from rest_framework.response import Response
from rest_framework.settings import api_settings
from rest_framework_csv import renderers as csvrenderers

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.auth import TemporaryTokenAuthentication
from posthog.constants import TREND_FILTER_TYPE_EVENTS
from posthog.event_usage import report_user_action
from posthog.models import Action
from posthog.models.action.action import ACTION_STEP_MATCHING_OPTIONS
from posthog.models.activity_logging.activity_log import Detail, changes_between, log_activity
from posthog.models.signals import model_activity_signal

from .forbid_destroy_model import ForbidDestroyModel
from .tagged_item import TaggedItemSerializerMixin, TaggedItemViewSetMixin


class ActionStepJSONSerializer(serializers.Serializer):
    event = serializers.CharField(required=False, allow_null=True, trim_whitespace=False)
    properties = serializers.ListField(child=serializers.DictField(), required=False, allow_null=True)
    selector = serializers.CharField(required=False, allow_null=True)
    tag_name = serializers.CharField(required=False, allow_null=True, trim_whitespace=False)
    text = serializers.CharField(required=False, allow_null=True, trim_whitespace=False)
    text_matching = serializers.ChoiceField(choices=ACTION_STEP_MATCHING_OPTIONS, required=False, allow_null=True)
    href = serializers.CharField(required=False, allow_null=True, trim_whitespace=False)
    href_matching = serializers.ChoiceField(choices=ACTION_STEP_MATCHING_OPTIONS, required=False, allow_null=True)
    url = serializers.CharField(required=False, allow_null=True)
    url_matching = serializers.ChoiceField(choices=ACTION_STEP_MATCHING_OPTIONS, required=False, allow_null=True)


class ActionSerializer(TaggedItemSerializerMixin, serializers.HyperlinkedModelSerializer):
    steps = ActionStepJSONSerializer(many=True, required=False)
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
        ]
        read_only_fields = [
            "team_id",
            "bytecode_error",
        ]
        extra_kwargs = {"team_id": {"read_only": True}}

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
        )
        return instance


class ActionViewSet(
    TeamAndOrgViewSetMixin,
    TaggedItemViewSetMixin,
    ForbidDestroyModel,
    viewsets.ModelViewSet,
):
    scope_object = "action"
    renderer_classes = (*tuple(api_settings.DEFAULT_RENDERER_CLASSES), csvrenderers.PaginatedCSVRenderer)
    queryset = Action.objects.select_related("created_by").all()
    serializer_class = ActionSerializer
    authentication_classes = [TemporaryTokenAuthentication]
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
            actions, many=True, context={"request": request}
        ).data  # type: ignore
        return Response({"results": actions_list})


@receiver(model_activity_signal, sender=Action)
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
