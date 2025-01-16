from rest_framework import viewsets
from rest_framework.exceptions import ValidationError

from posthog.warehouse.models import DataWarehouseFolder
from rest_framework import serializers
from posthog.api.routing import TeamAndOrgViewSetMixin
from rest_framework.response import Response


class DataWarehouseFolderSerializer(serializers.ModelSerializer):
    created_by = serializers.SerializerMethodField()
    children = serializers.SerializerMethodField()

    class Meta:
        model = DataWarehouseFolder
        fields = [
            "id",
            "name",
            "items",
            "children",
            "parent",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_by", "created_at", "updated_at", "children"]

    def get_created_by(self, obj):
        return obj.created_by.first_name if obj.created_by else None

    def get_children(self, obj):
        include_subfolders = self.context.get("include_subfolders", False)
        if not include_subfolders:
            return []

        # Get all subfolders
        subfolders = DataWarehouseFolder.objects.filter(team_id=obj.team_id, parent=obj.id, deleted=False).order_by(
            "name"
        )

        # Recursively serialize subfolders
        serialized_subfolders = DataWarehouseFolderSerializer(subfolders, many=True, context=self.context).data

        return serialized_subfolders

    def validate(self, attrs):
        # Ensure folder name is unique within the same parent and team
        name = attrs.get("name")
        parent = attrs.get("parent")
        team_id = self.context["team_id"]

        existing_query = DataWarehouseFolder.objects.filter(team_id=team_id, name=name, parent=parent)

        if self.instance:
            existing_query = existing_query.exclude(id=self.instance.id)

        if existing_query.exists():
            raise ValidationError("A folder with this name already exists in this location")

        return attrs


class DataWarehouseFolderViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    """
    Create, Read, Update, and Delete Data Warehouse Folders.
    """

    scope_object = "INTERNAL"
    serializer_class = DataWarehouseFolderSerializer
    queryset = DataWarehouseFolder.objects.all()

    def get_serializer_context(self) -> dict[str, any]:
        context = super().get_serializer_context()
        context["team_id"] = self.team_id
        context["include_subfolders"] = self.request.query_params.get("include_subfolders", "false").lower() == "true"
        return context

    def safely_get_queryset(self, queryset):
        return queryset.exclude(deleted=True).order_by("name")

    def perform_create(self, serializer):
        serializer.save(team_id=self.team_id, created_by=self.request.user)

    def perform_destroy(self, instance):
        instance.deleted = True
        instance.save()

    # by default only return top level folders
    def list(self, request, *args, **kwargs):
        queryset = self.safely_get_queryset(self.get_queryset())
        queryset = queryset.filter(parent__isnull=True)
        page = self.paginate_queryset(queryset)

        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)
