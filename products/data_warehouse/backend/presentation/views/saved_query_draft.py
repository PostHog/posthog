import uuid

from rest_framework import pagination, serializers, viewsets

from posthog.api.routing import TeamAndOrgViewSetMixin

from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery, DataWarehouseSavedQueryDraft


class DataWarehouseSavedQueryDraftPagination(pagination.LimitOffsetPagination):
    default_limit = 100


class DataWarehouseSavedQueryDraftSerializer(serializers.ModelSerializer):
    saved_query_id = serializers.UUIDField(required=False, allow_null=True)
    name = serializers.CharField(required=False, allow_null=True)

    class Meta:
        model = DataWarehouseSavedQueryDraft
        fields = ["id", "created_at", "updated_at", "query", "saved_query_id", "name", "edited_history_id"]
        read_only_fields = ["id", "created_at", "updated_at", "name"]

    def validate_saved_query_id(self, value: uuid.UUID | None) -> uuid.UUID | None:
        if value is None:
            return None
        if not DataWarehouseSavedQuery.objects.filter(id=value, team_id=self.context["get_team"]().id).exists():
            raise serializers.ValidationError("Saved query not found.")
        return value

    def create(self, validated_data):
        validated_data["team_id"] = self.context["get_team"]().id
        validated_data["created_by"] = self.context["request"].user
        saved_query_id = validated_data.get("saved_query_id")

        name = "Untitled"
        if saved_query_id:
            saved_query = DataWarehouseSavedQuery.objects.get(id=saved_query_id, team_id=validated_data["team_id"])
            count = DataWarehouseSavedQueryDraft.objects.filter(
                saved_query_id=saved_query_id,
                team_id=validated_data["team_id"],
                created_by=validated_data["created_by"],
            ).count()
            name = f"({count + 1}) {saved_query.name}"

        validated_data["name"] = name

        draft = DataWarehouseSavedQueryDraft(**validated_data)
        draft.save()

        return draft


class DataWarehouseSavedQueryDraftViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "INTERNAL"
    queryset = DataWarehouseSavedQueryDraft.objects.all()
    serializer_class = DataWarehouseSavedQueryDraftSerializer
    pagination_class = DataWarehouseSavedQueryDraftPagination

    def safely_get_queryset(self, queryset):
        # API is scoped to user
        return queryset.filter(created_by=self.request.user)
