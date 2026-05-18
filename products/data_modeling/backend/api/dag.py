from django.db.models import Count

from rest_framework import serializers, viewsets

from posthog.api.routing import TeamAndOrgViewSetMixin

from products.data_modeling.backend.models import DAG
from products.data_warehouse.backend.models.external_data_schema import (
    sync_frequency_interval_to_sync_frequency,
    sync_frequency_to_sync_frequency_interval,
)


class DAGSerializer(serializers.ModelSerializer):
    node_count = serializers.IntegerField(read_only=True, default=0)
    sync_frequency = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="Sync frequency string (e.g. '24hour', '7day')",
    )

    class Meta:
        model = DAG
        fields = [
            "id",
            "name",
            "description",
            "sync_frequency",
            "node_count",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "node_count",
            "created_at",
            "updated_at",
        ]
        extra_kwargs = {
            "name": {"help_text": "Human-readable name for this DAG"},
            "description": {"help_text": "Optional description of the DAG's purpose"},
        }

    def to_representation(self, instance: DAG) -> dict:
        data = super().to_representation(instance)
        data["sync_frequency"] = sync_frequency_interval_to_sync_frequency(instance.sync_frequency_interval)
        return data

    def validate_sync_frequency(self, value: str | None) -> str | None:
        if value is not None:
            try:
                sync_frequency_to_sync_frequency_interval(value)
            except ValueError:
                raise serializers.ValidationError(f"Invalid sync frequency: {value}")
        return value

    def create(self, validated_data: dict) -> DAG:
        validated_data["team_id"] = self.context["team_id"]
        sync_frequency = validated_data.pop("sync_frequency", None)
        if sync_frequency:
            validated_data["sync_frequency_interval"] = sync_frequency_to_sync_frequency_interval(sync_frequency)
        return super().create(validated_data)

    def update(self, instance: DAG, validated_data: dict) -> DAG:
        sync_frequency = validated_data.pop("sync_frequency", None)
        if sync_frequency is not None:
            validated_data["sync_frequency_interval"] = sync_frequency_to_sync_frequency_interval(sync_frequency)
        return super().update(instance, validated_data)


class DAGViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "INTERNAL"
    queryset = DAG.objects.all()
    serializer_class = DAGSerializer
    http_method_names = ["get", "post", "patch", "head", "options"]

    def safely_get_queryset(self, queryset):
        return queryset.filter(team_id=self.team_id).annotate(node_count=Count("node")).order_by("name")
