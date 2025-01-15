from rest_framework import viewsets
from rest_framework.exceptions import ValidationError

from posthog.warehouse.models import DataWarehouseFolder
from rest_framework import serializers


class DataWarehouseFolderSerializer(serializers.ModelSerializer):
    created_by = serializers.SerializerMethodField()

    class Meta:
        model = DataWarehouseFolder
        fields = [
            "id",
            "name",
            "items",
            "parent",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_by", "created_at", "updated_at"]

    def get_created_by(self, obj):
        return obj.created_by.first_name if obj.created_by else None

    def validate(self, attrs):
        # Ensure folder name is unique within the same parent and team
        name = attrs.get("name")
        parent = attrs.get("parent")
        team = self.context["team"]

        existing_query = DataWarehouseFolder.objects.filter(team=team, name=name, parent=parent)

        if self.instance:
            existing_query = existing_query.exclude(id=self.instance.id)

        if existing_query.exists():
            raise ValidationError("A folder with this name already exists in this location")

        return attrs


class DataWarehouseFolderViewSet(viewsets.ModelViewSet):
    """
    Create, Read, Update, and Delete Data Warehouse Folders.
    """

    serializer_class = DataWarehouseFolderSerializer
    queryset = DataWarehouseFolder.objects.all()

    def get_queryset(self):
        return self.queryset.filter(team_id=self.team_id, deleted=False)

    def perform_create(self, serializer):
        serializer.save(team_id=self.team_id, created_by=self.request.user)

    def perform_destroy(self, instance):
        instance.deleted = True
        instance.save()
