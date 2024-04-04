from rest_framework import serializers
from posthog.warehouse.models import ExternalDataSchema
from typing import Optional, Dict, Any
from posthog.api.routing import TeamAndOrgViewSetMixin
from rest_framework import viewsets, filters
from rest_framework.exceptions import NotAuthenticated
from posthog.models import User
from posthog.hogql.database.database import create_hogql_database


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

    def get_queryset(self):
        if not isinstance(self.request.user, User) or self.request.user.current_team is None:
            raise NotAuthenticated()

        if self.action == "list":
            return self.queryset.filter(team_id=self.team_id).prefetch_related("created_by").order_by(self.ordering)

        return self.queryset.filter(team_id=self.team_id).prefetch_related("created_by").order_by(self.ordering)
