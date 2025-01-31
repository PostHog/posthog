import pydantic
from rest_framework import serializers, viewsets
from rest_framework.exceptions import ValidationError


from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.api.tagged_item import TaggedItemSerializerMixin
from posthog.models.experiment import ExperimentSavedMetric, ExperimentToSavedMetric
from posthog.schema import ExperimentFunnelsQuery, ExperimentTrendsQuery


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


class ExperimentSavedMetricSerializer(TaggedItemSerializerMixin, serializers.ModelSerializer):
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

        metric_query = value

        if metric_query.get("kind") not in ["ExperimentTrendsQuery", "ExperimentFunnelsQuery"]:
            raise ValidationError("Metric query kind must be 'ExperimentTrendsQuery' or 'ExperimentFunnelsQuery'")

        # pydantic models are used to validate the query
        try:
            if metric_query["kind"] == "ExperimentTrendsQuery":
                ExperimentTrendsQuery(**metric_query)
            else:
                ExperimentFunnelsQuery(**metric_query)
        except pydantic.ValidationError as e:
            raise ValidationError(str(e.errors())) from e

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
