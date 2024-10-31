from rest_framework import serializers, viewsets
from rest_framework.exceptions import ValidationError


from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.models.experiment import ExperimentSavedMetric, ExperimentToSavedMetric


class ExperimentToSavedMetricSerializer(serializers.ModelSerializer):
    class Meta:
        model = ExperimentToSavedMetric
        fields = [
            "id",
            "experiment",
            "saved_metric",
            "metadata",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "created_at",
        ]


class ExperimentSavedMetricSerializer(serializers.ModelSerializer):
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
        ]
        read_only_fields = [
            "id",
            "created_by",
            "created_at",
            "updated_at",
        ]

    def validate_query(self, value):
        if not value:
            raise ValidationError("Query is required to create a saved metric")
        return value

    def create(self, validated_data):
        request = self.context["request"]
        validated_data["created_by"] = request.user
        validated_data["team_id"] = self.context["team_id"]
        return super().create(validated_data)


class ExperimentSavedMetricViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "experiment"
    queryset = ExperimentSavedMetric.objects.prefetch_related("created_by").all()
    serializer_class = ExperimentSavedMetricSerializer
    ordering = "-created_at"
