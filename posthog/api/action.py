from typing import Any, Dict, List, cast

from django.db.models import Count, Prefetch
from rest_framework import request, serializers, viewsets
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
from posthog.models import Action, ActionStep

from .forbid_destroy_model import ForbidDestroyModel
from .tagged_item import TaggedItemSerializerMixin, TaggedItemViewSetMixin


class ActionStepSerializer(serializers.HyperlinkedModelSerializer):
    id = serializers.CharField(read_only=False, required=False)

    class Meta:
        model = ActionStep
        fields = [
            "id",
            "event",
            "tag_name",
            "text",
            "text_matching",
            "href",
            "href_matching",
            "selector",
            "url",
            "name",
            "url_matching",
            "properties",
        ]
        extra_kwargs = {
            "event": {"trim_whitespace": False},
            "tag_name": {"trim_whitespace": False},
            "text": {"trim_whitespace": False},
            "href": {"trim_whitespace": False},
            "name": {"trim_whitespace": False},
        }


class ActionSerializer(TaggedItemSerializerMixin, serializers.HyperlinkedModelSerializer):
    steps = ActionStepSerializer(many=True, required=False)
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
        steps = validated_data.pop("steps", [])
        validated_data["created_by"] = self.context["request"].user
        instance = super().create(validated_data)

        for step in steps:
            ActionStep.objects.create(
                action=instance,
                **{key: value for key, value in step.items() if key not in ("isNew", "selection")},
            )

        report_user_action(
            validated_data["created_by"],
            "action created",
            instance.get_analytics_metadata(),
        )

        return instance

    def update(self, instance: Any, validated_data: Dict[str, Any]) -> Any:
        steps = validated_data.pop("steps", None)
        # If there's no steps property at all we just ignore it
        # If there is a step property but it's an empty array [], we'll delete all the steps
        if steps is not None:
            # remove steps not in the request
            step_ids = [step["id"] for step in steps if step.get("id")]
            instance.steps.exclude(pk__in=step_ids).delete()

            for step in steps:
                if step.get("id"):
                    step_instance = ActionStep.objects.get(pk=step["id"])
                    step_serializer = ActionStepSerializer(instance=step_instance)
                    step_serializer.update(step_instance, step)
                else:
                    ActionStep.objects.create(
                        action=instance,
                        **{key: value for key, value in step.items() if key not in ("isNew", "selection")},
                    )

        # bytecode might have been altered in the action steps
        instance.refresh_from_db(fields=["bytecode", "bytecode_error"])
        instance = super().update(instance, validated_data)
        instance.refresh_from_db()
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

    def filter_queryset(self, queryset):
        if self.action == "list":
            queryset = queryset.filter(deleted=False)

        queryset = queryset.annotate(count=Count(TREND_FILTER_TYPE_EVENTS))
        queryset = queryset.prefetch_related(Prefetch("steps", queryset=ActionStep.objects.order_by("id")))
        return queryset.filter(team_id=self.team_id).order_by(*self.ordering)

    def list(self, request: request.Request, *args: Any, **kwargs: Any) -> Response:
        actions = self.get_queryset()
        actions_list: List[Dict[Any, Any]] = self.serializer_class(
            actions, many=True, context={"request": request}
        ).data  # type: ignore
        return Response({"results": actions_list})
