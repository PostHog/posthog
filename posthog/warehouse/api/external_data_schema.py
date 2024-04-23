from rest_framework import serializers
from posthog.warehouse.models import ExternalDataSchema
from typing import Optional, Dict, Any
from posthog.api.routing import TeamAndOrgViewSetMixin
from rest_framework import viewsets, filters
from posthog.hogql.database.database import create_hogql_database
from posthog.warehouse.data_load.service import (
    external_data_workflow_exists,
    sync_external_data_job_workflow,
    pause_external_data_schedule,
    unpause_external_data_schedule,
)


class ExternalDataSchemaSerializer(serializers.ModelSerializer):
    table = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = ExternalDataSchema

        fields = ["id", "name", "table", "should_sync", "last_synced_at", "latest_error"]

    def get_table(self, schema: ExternalDataSchema) -> Optional[dict]:
        from posthog.warehouse.api.table import SimpleTableSerializer

        hogql_context = self.context.get("database", None)
        if not hogql_context:
            hogql_context = create_hogql_database(team_id=self.context["team_id"])

        return SimpleTableSerializer(schema.table, context={"database": hogql_context}).data or None

    def update(self, instance: ExternalDataSchema, validated_data: Dict[str, Any]) -> ExternalDataSchema:
        should_sync = validated_data.get("should_sync", None)
        schedule_exists = external_data_workflow_exists(str(instance.id))

        if schedule_exists:
            if should_sync is False:
                pause_external_data_schedule(str(instance.id))
            elif should_sync is True:
                unpause_external_data_schedule(str(instance.id))
        else:
            if should_sync is True:
                sync_external_data_job_workflow(instance, create=True)

        return super().update(instance, validated_data)


class SimpleExternalDataSchemaSerializer(serializers.ModelSerializer):
    class Meta:
        model = ExternalDataSchema
        fields = ["id", "name", "should_sync", "last_synced_at"]


class ExternalDataSchemaViewset(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "INTERNAL"
    queryset = ExternalDataSchema.objects.all()
    serializer_class = ExternalDataSchemaSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ["name"]
    ordering = "-created_at"

    def get_serializer_context(self) -> Dict[str, Any]:
        context = super().get_serializer_context()
        context["database"] = create_hogql_database(team_id=self.team_id)
        return context

    def filter_queryset(self, queryset):
        return queryset.prefetch_related("created_by").order_by(self.ordering)
