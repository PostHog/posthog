from django.db.models import QuerySet

import structlog
from loginas.utils import is_impersonated_session
from rest_framework import mixins, serializers, viewsets

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.cdp.validation import HogFunctionFiltersSerializer
from posthog.models.activity_logging.activity_log import Detail, log_activity
from posthog.models.hog_flow_batch_job.hog_flow_batch_job import HogFlowBatchJob

logger = structlog.get_logger(__name__)


class HogFlowBatchJobSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)
    filters = HogFunctionFiltersSerializer(required=True)

    class Meta:
        model = HogFlowBatchJob
        fields = [
            "id",
            "status",
            "created_at",
            "created_by",
            "updated_at",
            "filters",
        ]
        read_only_fields = [
            "id",
            "status",
            "created_at",
            "created_by",
            "updated_at",
        ]

    def create(self, validated_data: dict, *args, **kwargs) -> HogFlowBatchJob:
        request = self.context["request"]
        team_id = self.context["team_id"]
        validated_data["created_by"] = request.user
        validated_data["team_id"] = team_id

        return super().create(validated_data=validated_data)


class HogFlowBatchJobViewSet(TeamAndOrgViewSetMixin, mixins.CreateModelMixin, viewsets.GenericViewSet):
    scope_object = "INTERNAL"
    queryset = HogFlowBatchJob.objects.all()
    serializer_class = HogFlowBatchJobSerializer

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        return queryset

    def perform_create(self, serializer):
        serializer.save()
        log_activity(
            organization_id=self.organization.id,
            team_id=self.team_id,
            user=serializer.context["request"].user,
            was_impersonated=is_impersonated_session(serializer.context["request"]),
            item_id=serializer.instance.id,
            scope="HogFlowBatchJob",
            activity="created",
            detail=Detail(name=f"Batch job {serializer.instance.id}", type="standard"),
        )
