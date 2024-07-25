from typing import Any, cast

from rest_framework import serializers, viewsets
from django.db.models import Count
from rest_framework import request
from rest_framework.response import Response
from rest_framework.settings import api_settings
from rest_framework_csv import renderers as csvrenderers

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.auth import (
    TemporaryTokenAuthentication,
)
from posthog.constants import TREND_FILTER_TYPE_EVENTS
from posthog.event_usage import report_user_action
from posthog.models import Action
from posthog.models.action.action import ACTION_STEP_MATCHING_OPTIONS

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
        ]
        read_only_fields = [
            "team_id",
            "bytecode_error",
        ]
        extra_kwargs = {"team_id": {"read_only": True}}

    def get_is_calculating(self, action: Action) -> bool:
        return False

    def validate(self, attrs):
        instance = cast(Action, self.instance)
        exclude_args = {}
        if instance:
            include_args = {"team": instance.team}
            exclude_args = {"id": instance.pk}
        else:
            attrs["team_id"] = self.context["view"].team_id
            include_args = {"team_id": attrs["team_id"]}

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
        validated_data["created_by"] = self.context["request"].user
        instance = super().create(validated_data)

        report_user_action(
            validated_data["created_by"],
            "action created",
            instance.get_analytics_metadata(),
        )

        return instance

    def update(self, instance: Any, validated_data: dict[str, Any]) -> Any:
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
