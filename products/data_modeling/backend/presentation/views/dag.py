import re
from typing import Any, cast

from django.db.models import Count

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers, status, viewsets
from rest_framework.exceptions import APIException, ValidationError

from posthog.api.routing import TeamAndOrgViewSetMixin

from products.data_modeling.backend.facade.api import delete_dag_schedules, tiered_schedules_enabled
from products.data_modeling.backend.facade.models import DAG, RESERVED_DAG_NAMES
from products.warehouse_sources.backend.facade.models import (
    sync_frequency_interval_to_sync_frequency,
    sync_frequency_to_sync_frequency_interval,
)

# C0 controls, DEL, C1 controls, and the Unicode line/paragraph separators.
CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f-\x9f\u2028\u2029]")


class ScheduleTeardownUnavailable(APIException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = "Couldn't remove this DAG's schedules, so it wasn't deleted. Try again in a few minutes."


class DAGSerializer(serializers.ModelSerializer):
    node_count = serializers.IntegerField(read_only=True, default=0)
    sync_frequency = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="Sync frequency string (e.g. '24hour', '7day')",
    )
    frequency_managed_by_nodes = serializers.SerializerMethodField(
        read_only=True,
        help_text=(
            "True when this team's DAG schedules are driven by per-model freshness targets, so "
            "`sync_frequency` no longer controls scheduling and writes to it are rejected. False "
            "when the DAG-level frequency still applies."
        ),
    )

    class Meta:
        model = DAG
        fields = [
            "id",
            "name",
            "description",
            "sync_frequency",
            "frequency_managed_by_nodes",
            "node_count",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "frequency_managed_by_nodes",
            "node_count",
            "created_at",
            "updated_at",
        ]
        extra_kwargs = {
            "name": {"help_text": "Human-readable name for this DAG"},
            "description": {"help_text": "Optional description of the DAG's purpose"},
        }

    @extend_schema_field(serializers.BooleanField())
    def get_frequency_managed_by_nodes(self, dag: DAG) -> bool:
        # Resolved once per request in DAGViewSet.get_serializer_context — it is team-scoped,
        # so evaluating the flag per DAG row would be redundant.
        return bool(self.context.get("frequency_managed_by_nodes", False))

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
        # DAG names are echoed into management-command output, the confirmation prompt of
        # destructive fleet tooling, and logs. A control character there can erase or rewrite the
        # surrounding text, so reject it at the boundary rather than escaping at each display site.
        if CONTROL_CHARACTERS.search(value):
            raise serializers.ValidationError("Name cannot contain control characters.")
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
            if self.context.get("frequency_managed_by_nodes", False):
                # The frontend spreads the whole DAG into every PATCH, so an unchanged
                # echo of the current frequency must pass; only a real change is rejected.
                current = sync_frequency_interval_to_sync_frequency(instance.sync_frequency_interval)
                if sync_frequency != current:
                    raise serializers.ValidationError(
                        "Sync frequency is managed per model on this team. Edit each model's sync frequency instead."
                    )
            else:
                validated_data["sync_frequency_interval"] = sync_frequency_to_sync_frequency_interval(sync_frequency)
        return super().update(instance, validated_data)


class DAGViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "INTERNAL"
    queryset = DAG.objects.all()
    serializer_class = DAGSerializer
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def safely_get_queryset(self, queryset):
        return queryset.filter(team_id=self.team_id).annotate(node_count=Count("node")).order_by("name")

    def get_serializer_context(self) -> dict[str, Any]:
        context = super().get_serializer_context()
        context["frequency_managed_by_nodes"] = tiered_schedules_enabled(self.team)
        return context

    def perform_destroy(self, instance: DAG) -> None:
        if instance.is_default:
            raise ValidationError("The default DAG cannot be deleted.")
        if instance.is_managed:
            raise ValidationError("System-managed DAGs cannot be deleted.")
        # Keep the DAG row when teardown fails: it is the only handle left for finding the schedules.
        if not delete_dag_schedules(str(instance.id)).ok:
            raise ScheduleTeardownUnavailable()
        instance.delete()
