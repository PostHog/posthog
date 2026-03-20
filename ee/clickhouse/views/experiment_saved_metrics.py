from django.db.models.functions import Lower

from drf_spectacular.utils import extend_schema
from rest_framework import serializers, viewsets

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.api.tagged_item import TaggedItemSerializerMixin
from posthog.rbac.user_access_control import UserAccessControlSerializerMixin

from products.experiments.backend.experiment_saved_metric_service import ExperimentSavedMetricService
from products.experiments.backend.models.experiment import ExperimentSavedMetric, ExperimentToSavedMetric

from ee.api.rbac.access_control import AccessControlViewSetMixin


class ExperimentToSavedMetricSerializer(serializers.ModelSerializer):
    query = serializers.JSONField(source="saved_metric.query", read_only=True)
    name = serializers.CharField(source="saved_metric.name", read_only=True)

    class Meta:
        model = ExperimentToSavedMetric
        fields = [
            "id",
            "experiment",
            "saved_metric",
            "metadata",
            "created_at",
            "query",
            "name",
        ]
        read_only_fields = [
            "id",
            "created_at",
        ]


class ExperimentSavedMetricSerializer(
    UserAccessControlSerializerMixin, TaggedItemSerializerMixin, serializers.ModelSerializer
):
    created_by = UserBasicSerializer(read_only=True)

    class Meta:
        model = ExperimentSavedMetric
        fields = [
            "id",
            "name",
            "description",
            "query",
            "created_by",
            "created_at",
            "updated_at",
            "tags",
            "user_access_level",
        ]
        read_only_fields = [
            "id",
            "created_by",
            "created_at",
            "updated_at",
            "user_access_level",
        ]

    def create(self, validated_data):
        tags = validated_data.pop("tags", None)
        name = validated_data.pop("name")
        query = validated_data.pop("query")
        description = validated_data.pop("description", None)

        if validated_data:
            raise serializers.ValidationError(
                f"Can't create keys: {', '.join(sorted(validated_data))} on ExperimentSavedMetric"
            )

        service = self._build_service()
        instance = service.create_saved_metric(name=name, query=query, description=description)
        self._attempt_set_tags(tags, instance)
        return instance

    def update(self, instance: ExperimentSavedMetric, validated_data):
        tags = validated_data.pop("tags", None)
        service = self._build_service()
        instance = service.update_saved_metric(instance, validated_data)
        self._attempt_set_tags(tags, instance)
        return instance

    def _build_service(self) -> ExperimentSavedMetricService:
        request = self.context["request"]
        return ExperimentSavedMetricService(team=self.context["get_team"](), user=request.user)


@extend_schema(tags=["experiments"])
class ExperimentSavedMetricViewSet(TeamAndOrgViewSetMixin, AccessControlViewSetMixin, viewsets.ModelViewSet):
    scope_object = "experiment_saved_metric"
    queryset = ExperimentSavedMetric.objects.prefetch_related("created_by").order_by(Lower("name")).all()
    serializer_class = ExperimentSavedMetricSerializer

    def perform_destroy(self, instance: ExperimentSavedMetric) -> None:
        service = ExperimentSavedMetricService(team=self.team, user=self.request.user)
        service.delete_saved_metric(instance)
