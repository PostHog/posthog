import re

from django.db import transaction

from rest_framework import mixins, serializers, viewsets

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.models import SchemaPropertyGroup, SchemaPropertyGroupProperty

PROPERTY_NAME_REGEX = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


class SchemaPropertyGroupPropertySerializer(serializers.ModelSerializer):
    class Meta:
        model = SchemaPropertyGroupProperty
        fields = (
            "id",
            "name",
            "property_type",
            "is_required",
            "description",
            "order",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "created_at", "updated_at")

    def validate_name(self, value: str) -> str:
        if not value or not value.strip():
            raise serializers.ValidationError("Property name is required")

        cleaned_value = value.strip()
        if not PROPERTY_NAME_REGEX.match(cleaned_value):
            raise serializers.ValidationError(
                "Property name must start with a letter or underscore and contain only letters, numbers, and underscores"
            )

        return cleaned_value


class SchemaPropertyGroupSerializer(serializers.ModelSerializer):
    properties = SchemaPropertyGroupPropertySerializer(many=True, required=False)
    created_by = UserBasicSerializer(read_only=True)

    class Meta:
        model = SchemaPropertyGroup
        fields = (
            "id",
            "name",
            "description",
            "properties",
            "created_at",
            "updated_at",
            "created_by",
        )
        read_only_fields = ("id", "created_at", "updated_at", "created_by")

    def create(self, validated_data):
        properties_data = validated_data.pop("properties", [])
        request = self.context.get("request")

        property_group = SchemaPropertyGroup.objects.create(
            **validated_data,
            team_id=self.context["team_id"],
            project_id=self.context["project_id"],
            created_by=request.user if request else None,
        )

        for property_data in properties_data:
            SchemaPropertyGroupProperty.objects.create(property_group=property_group, **property_data)

        return property_group

    def update(self, instance, validated_data):
        properties_data = validated_data.pop("properties", None)

        with transaction.atomic():
            instance.name = validated_data.get("name", instance.name)
            instance.description = validated_data.get("description", instance.description)
            instance.save()

            if properties_data is not None:
                instance.properties.all().delete()
                for property_data in properties_data:
                    property_data.pop("id", None)  # Remove id since we're creating new properties
                    SchemaPropertyGroupProperty.objects.create(property_group=instance, **property_data)

        # Query fresh instance with properties to ensure all data is current
        return SchemaPropertyGroup.objects.prefetch_related("properties").get(pk=instance.pk)


class SchemaPropertyGroupViewSet(
    TeamAndOrgViewSetMixin,
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    scope_object = "INTERNAL"
    serializer_class = SchemaPropertyGroupSerializer
    queryset = SchemaPropertyGroup.objects.all()
    lookup_field = "id"

    def safely_get_queryset(self, queryset):
        return queryset.filter(team_id=self.team_id).prefetch_related("properties").order_by("-created_at")
