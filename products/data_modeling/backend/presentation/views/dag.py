from typing import cast

from django.db.models import Count

from rest_framework import serializers, viewsets
from rest_framework.exceptions import ValidationError

from posthog.api.routing import TeamAndOrgViewSetMixin

from products.data_modeling.backend.facade.models import DAG, RESERVED_DAG_NAMES
from products.warehouse_sources.backend.facade.models import (
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

    def validate_name(self, value: str) -> str:
        is_rename = self.instance is not None and value != self.instance.name
        if is_rename:
            instance = cast(DAG, self.instance)
            if instance.is_default:
                raise serializers.ValidationError("The default DAG cannot be renamed.")
            if instance.is_managed:
                raise serializers.ValidationError("System-managed DAGs cannot be renamed.")
        # Block users from claiming a reserved system name via create or rename.
        if value in RESERVED_DAG_NAMES and (self.instance is None or is_rename):
            raise serializers.ValidationError("This name is reserved for system-managed DAGs.")
        return value

    def create(self, validated_data: dict) -> DAG:
        validated_data["team_id"] = self.context["team_id"]
        sync_frequency = validated_data.pop("sync_frequency", None)
        if sync_frequency:
            validated_data["sync_frequency_interval"] = sync_frequency_to_sync_frequency_interval(sync_frequency)
        return super().create(validated_data)

    def update(self, instance: DAG, validated_data: dict) -> DAG:
        if instance.is_managed:
            raise serializers.ValidationError("System-managed DAGs cannot be edited.")
        sync_frequency = validated_data.pop("sync_frequency", None)
        if sync_frequency is not None:
            validated_data["sync_frequency_interval"] = sync_frequency_to_sync_frequency_interval(sync_frequency)
        return super().update(instance, validated_data)


class DAGViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "INTERNAL"
    queryset = DAG.objects.all()
    serializer_class = DAGSerializer
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def safely_get_queryset(self, queryset):
        return queryset.filter(team_id=self.team_id).annotate(node_count=Count("node")).order_by("name")

    def perform_destroy(self, instance: DAG) -> None:
        if instance.is_default:
            raise ValidationError("The default DAG cannot be deleted.")
        if instance.is_managed:
            raise ValidationError("System-managed DAGs cannot be deleted.")
        instance.delete()
