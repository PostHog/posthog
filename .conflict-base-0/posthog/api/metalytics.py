from typing import Any

from rest_framework import request, response, serializers, viewsets
from rest_framework.serializers import BaseSerializer

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.kafka_client.client import KafkaProducer
from posthog.kafka_client.topics import KAFKA_APP_METRICS2
from posthog.models.event.util import format_clickhouse_timestamp
from posthog.models.plugin import PluginConfig
from posthog.utils import cast_timestamp_or_now


class MetalyticsCreateRequestSerializer(serializers.Serializer):
    metric_name = serializers.ChoiceField(choices=["viewed"], required=True)
    instance_id = serializers.CharField(required=True)


class MetalyticsViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "INTERNAL"
    queryset = PluginConfig.objects.all()

    def get_serializer_class(self) -> type[BaseSerializer]:
        return MetalyticsCreateRequestSerializer if self.action == "create" else MetalyticsCreateRequestSerializer

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

        KafkaProducer().produce(topic=KAFKA_APP_METRICS2, data=payload)

        return response.Response({})
