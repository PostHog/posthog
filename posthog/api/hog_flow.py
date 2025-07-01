import json
import structlog
from django_filters.rest_framework import DjangoFilterBackend
from django_filters import BaseInFilter, CharFilter, FilterSet
from django.db.models import QuerySet
from loginas.utils import is_impersonated_session


from rest_framework import serializers, viewsets, exceptions
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.serializers import BaseSerializer

from posthog.api.app_metrics2 import AppMetricsMixin
from posthog.api.log_entries import LogEntryMixin
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.cdp.validation import HogFunctionFiltersSerializer

from posthog.models.activity_logging.activity_log import log_activity, changes_between, Detail
from posthog.models.hog_flow.hog_flow import HogFlow
from posthog.plugins.plugin_server_api import create_hog_flow_invocation_test


logger = structlog.get_logger(__name__)


class HogFlowTriggerSerializer(serializers.Serializer):
    filters = HogFunctionFiltersSerializer()


class HogFlowMinimalSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)

    class Meta:
        model = HogFlow
        fields = [
            "id",
            "name",
            "description",
            "version",
            "status",
            "created_at",
            "created_by",
            "trigger",
            "trigger_masking",
            "conversion",
            "exit_condition",
            "edges",
            "actions",
            "abort_action",
        ]
        read_only_fields = fields


class HogFlowSerializer(HogFlowMinimalSerializer):
    trigger = HogFlowTriggerSerializer()

    class Meta:
        model = HogFlow
        fields = [
            "id",
            "name",
            "description",
            "version",
            "status",
            "created_at",
            "created_by",
            "trigger",
            "trigger_masking",
            "conversion",
            "exit_condition",
            "edges",
            "actions",
            "abort_action",
        ]
        read_only_fields = [
            "id",
            "version",
            "created_at",
            "created_by",
            "trigger_masking",
            "abort_action",
        ]

    def create(self, validated_data: dict, *args, **kwargs) -> HogFlow:
        request = self.context["request"]
        team_id = self.context["team_id"]
        validated_data["created_by"] = request.user
        validated_data["team_id"] = team_id

        return super().create(validated_data=validated_data)

    # TODO: Validation perhaps via the nodejs api?


class CommaSeparatedListFilter(BaseInFilter, CharFilter):
    pass


class HogFlowFilterSet(FilterSet):
    class Meta:
        model = HogFlow
        fields = ["id", "created_by", "created_at", "updated_at"]


class HogFlowViewSet(TeamAndOrgViewSetMixin, LogEntryMixin, AppMetricsMixin, viewsets.ModelViewSet):
    scope_object = "INTERNAL"
    queryset = HogFlow.objects.all()
    filter_backends = [DjangoFilterBackend]
    filterset_class = HogFlowFilterSet
    log_source = "hog_flow"
    app_source = "hog_flow"

    def get_serializer_class(self) -> type[BaseSerializer]:
        return HogFlowMinimalSerializer if self.action == "list" else HogFlowSerializer

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        if self.action == "list":
            queryset = queryset.order_by("-updated_at")

        if self.request.GET.get("trigger"):
            try:
                trigger = json.loads(self.request.GET["trigger"])

                if trigger:
                    queryset = queryset.filter(trigger__contains=trigger)
            except (ValueError, KeyError, TypeError):
                raise exceptions.ValidationError({"trigger": f"Invalid trigger"})

        return queryset

    def safely_get_object(self, queryset):
        # TODO(team-messaging): Somehow implement version lookups
        return super().safely_get_object(queryset)

    def perform_create(self, serializer):
        serializer.save()
        log_activity(
            organization_id=self.organization.id,
            team_id=self.team_id,
            user=serializer.context["request"].user,
            was_impersonated=is_impersonated_session(serializer.context["request"]),
            item_id=serializer.instance.id,
            scope="HogFlow",
            activity="created",
            detail=Detail(name=serializer.instance.name, type="standard"),
        )

    def perform_update(self, serializer):
        # TODO(team-messaging): Atomically increment version, insert new object instead of default update behavior
        instance_id = serializer.instance.id

        try:
            before_update = HogFlow.objects.get(pk=instance_id)
        except HogFlow.DoesNotExist:
            before_update = None

        serializer.save()

        changes = changes_between("HogFlow", previous=before_update, current=serializer.instance)

        log_activity(
            organization_id=self.organization.id,
            team_id=self.team_id,
            user=serializer.context["request"].user,
            was_impersonated=is_impersonated_session(serializer.context["request"]),
            item_id=instance_id,
            scope="HogFlow",
            activity="updated",
            detail=Detail(changes=changes, name=serializer.instance.name),
        )

    @action(detail=True, methods=["POST"])
    def invocations(self, request: Request, *args, **kwargs):
        try:
            hog_flow = self.get_object()
        except Exception:
            hog_flow = None

        res = create_hog_flow_invocation_test(
            team_id=self.team_id,
            hog_flow_id=str(hog_flow.id) if hog_flow else "new",
            payload=request.data,
        )

        if res.status_code != 200:
            return Response({"status": "error", "message": res.json()["error"]}, status=res.status_code)

        return Response(res.json())
