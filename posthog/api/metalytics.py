from typing import Any

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import request, response, serializers, viewsets
from rest_framework.serializers import BaseSerializer
from structlog import get_logger

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.kafka_client.routing import get_producer
from posthog.kafka_client.topics import KAFKA_APP_METRICS2
from posthog.models.event.util import format_clickhouse_timestamp
from posthog.utils import cast_timestamp_or_now

from products.cdp.backend.models.plugin import PluginConfig

logger = get_logger(__name__)


class MetalyticsCreateRequestSerializer(serializers.Serializer):
    metric_name = serializers.ChoiceField(
        choices=["viewed"], required=True, help_text="The metric being recorded. Only 'viewed' is currently supported."
    )
    instance_id = serializers.CharField(
        required=True, help_text="Identifier of the viewed item, formatted as '<activity_scope>:<activity_item_id>'."
    )


class MetalyticsViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "INTERNAL"
    queryset = PluginConfig.objects.all()

    def get_serializer_class(self) -> type[BaseSerializer]:
        return MetalyticsCreateRequestSerializer if self.action == "create" else MetalyticsCreateRequestSerializer

    @extend_schema(
        request=MetalyticsCreateRequestSerializer,
        responses={200: OpenApiResponse(description="View recorded (best-effort).")},
    )
    def create(self, request: request.Request, *args: Any, **kwargs: Any) -> response.Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        validated_data = serializer.validated_data

        payload = {
            **validated_data,
            "team_id": self.team_id,
            "app_source_id": self.request.user.pk,
            "app_source": "metalytics",
            "count": 1,
            "timestamp": format_clickhouse_timestamp(cast_timestamp_or_now(None)),
        }

        # Best-effort internal view tracking: a Kafka hiccup here must not surface as a
        # 5xx. produce() only enqueues locally (non-blocking), but producer construction
        # or a misconfigured cluster can still raise — swallow it and report success.
        try:
            get_producer(topic=KAFKA_APP_METRICS2).produce(topic=KAFKA_APP_METRICS2, data=payload)
        except Exception:
            logger.warning("metalytics_produce_failed", team_id=self.team_id, exc_info=True)

        return response.Response({})
