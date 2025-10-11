import re
import logging

from django.db import IntegrityError, transaction

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


class EventDefinitionBasicSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()


class SchemaPropertyGroupSerializer(serializers.ModelSerializer):
    properties = SchemaPropertyGroupPropertySerializer(many=True, required=False)
    created_by = UserBasicSerializer(read_only=True)
    events = serializers.SerializerMethodField()

    class Meta:
        model = SchemaPropertyGroup
        fields = (
            "id",
            "name",
            "description",
            "properties",
            "events",
            "created_at",
            "updated_at",
            "created_by",
        )
        read_only_fields = ("id", "created_at", "updated_at", "created_by")

    def get_events(self, obj):
        event_schemas = obj.event_schemas.select_related("event_definition").all()
        event_definitions = sorted([es.event_definition for es in event_schemas], key=lambda e: e.name.lower())
        return EventDefinitionBasicSerializer(event_definitions, many=True).data

    def create(self, validated_data):
        properties_data = validated_data.pop("properties", [])
        request = self.context.get("request")

        try:
            property_group = SchemaPropertyGroup.objects.create(
                **validated_data,
                team_id=self.context["team_id"],
                project_id=self.context["project_id"],
                created_by=request.user if request else None,
            )

            for property_data in properties_data:
                SchemaPropertyGroupProperty.objects.create(property_group=property_group, **property_data)

            return property_group
        except IntegrityError as e:
            if "unique_schema_property_group_team_name" in str(e):
                raise serializers.ValidationError(
                    {"name": "A property group with this name already exists for this team"}
                )
            logging.error(f"Database integrity error while creating property group: {e}", exc_info=True)
            raise serializers.ValidationError("Could not create property group due to a database error.")

    def update(self, instance, validated_data):
        properties_data = validated_data.pop("properties", None)

        try:
            with transaction.atomic():
                instance.name = validated_data.get("name", instance.name)
                instance.description = validated_data.get("description", instance.description)
                instance.save()

                if properties_data is not None:
                    existing_properties = {prop.id: prop for prop in instance.properties.all()}
                    incoming_property_ids = {prop.get("id") for prop in properties_data if prop.get("id")}

                    # Delete properties that are no longer present
                    properties_to_delete = set(existing_properties.keys()) - incoming_property_ids
                    if properties_to_delete:
                        SchemaPropertyGroupProperty.objects.filter(id__in=properties_to_delete).delete()

                    # Update existing properties and create new ones
                    for property_data in properties_data:
                        property_id = property_data.pop("id", None)
                        if property_id and property_id in existing_properties:
                            # Update existing property
                            existing_prop = existing_properties[property_id]
                            for key, value in property_data.items():
                                setattr(existing_prop, key, value)
                            existing_prop.save()
                        else:
                            # Create new property
                            SchemaPropertyGroupProperty.objects.create(property_group=instance, **property_data)

            # Query fresh instance with properties to ensure all data is current
            return SchemaPropertyGroup.objects.prefetch_related("properties").get(pk=instance.pk)
        except IntegrityError as e:
            error_str = str(e)

            # Handle duplicate property name within group
            if "unique_property_group_property_name" in error_str:
                # Extract the property name from the error message
                import re

                match = re.search(r"\(property_group_id, name\)=\([^,]+, ([^)]+)\)", error_str)
                if match:
                    property_name = match.group(1)
                    raise serializers.ValidationError(
                        {"properties": f"A property named '{property_name}' already exists in this group"}
                    )
                raise serializers.ValidationError(
                    {"properties": "A property with this name already exists in this group"}
                )

            # Handle duplicate property group name
            if "unique_schema_property_group_team_name" in error_str:
                raise serializers.ValidationError({"name": "A property group with this name already exists"})

            logging.error(f"Database integrity error while updating property group: {e}", exc_info=True)
            raise serializers.ValidationError("Could not update property group due to a database error.")


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
        return (
            queryset.filter(team_id=self.team_id)
            .prefetch_related("properties", "event_schemas__event_definition")
            .order_by("name")
        )
