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

    class Meta:
        model = HogFlowBatchJob
        fields = [
            "id",
            "status",
            "hog_flow",
            "variables",
            "created_at",
            "created_by",
            "updated_at",
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
