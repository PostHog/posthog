import logging

from django.db import IntegrityError, transaction
from django.utils import timezone

from drf_spectacular.utils import extend_schema_field
from rest_framework import mixins, serializers, viewsets
from rest_framework.permissions import SAFE_METHODS
from rest_framework.request import Request

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.models import SchemaPropertyGroup, SchemaPropertyGroupProperty
from posthog.permissions import is_scout_sandbox_request
from posthog.taxonomy.scout_writes import refuse_scout_taxonomy_write

MAX_PROPERTY_NAME_LENGTH = 200
# Bounds the per-request write cost of the nested `properties` list
MAX_PROPERTIES_PER_GROUP = 1000


class SchemaPropertyGroupPropertySerializer(serializers.ModelSerializer):
    class Meta:
        model = SchemaPropertyGroupProperty
        fields = (
            "id",
            "name",
            "property_type",
            "is_required",
            "is_optional_in_types",
            "description",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "created_at", "updated_at")

    def validate_name(self, value: str) -> str:
        if not value or not value.strip():
            raise serializers.ValidationError("Property name is required")

        cleaned_value = value.strip()
        if len(cleaned_value) > MAX_PROPERTY_NAME_LENGTH:
            raise serializers.ValidationError(f"Property name must be {MAX_PROPERTY_NAME_LENGTH} characters or less")

        return cleaned_value


class EventDefinitionBasicSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()


class SchemaPropertyGroupSerializer(serializers.ModelSerializer):
    properties = SchemaPropertyGroupPropertySerializer(
        many=True,
        required=False,
        max_length=MAX_PROPERTIES_PER_GROUP,
        help_text=f"Properties in this group, up to {MAX_PROPERTIES_PER_GROUP}. On update, the list replaces the group's existing properties.",
    )
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

    @extend_schema_field(EventDefinitionBasicSerializer(many=True))
    def get_events(self, obj):
        event_schemas = obj.event_schemas.select_related("event_definition").all()
        event_definitions = sorted([es.event_definition for es in event_schemas], key=lambda e: e.name.lower())
        return EventDefinitionBasicSerializer(event_definitions, many=True).data

    def create(self, validated_data):
        properties_data = validated_data.pop("properties", [])
        request = self.context.get("request")

        try:
            with transaction.atomic():
                property_group = SchemaPropertyGroup.objects.create(
                    **validated_data,
                    team_id=self.context["team_id"],
                    project_id=self.context["project_id"],
                    created_by=request.user if request else None,
                )

                SchemaPropertyGroupProperty.objects.bulk_create(
                    [
                        SchemaPropertyGroupProperty(property_group=property_group, **property_data)
                        for property_data in properties_data
                    ]
                )

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
                    properties_to_update: list[SchemaPropertyGroupProperty] = []
                    update_fields: set[str] = set()
                    properties_to_create: list[SchemaPropertyGroupProperty] = []
                    for property_data in properties_data:
                        property_id = property_data.pop("id", None)
                        if property_id and property_id in existing_properties:
                            existing_prop = existing_properties[property_id]
                            for key, value in property_data.items():
                                setattr(existing_prop, key, value)
                            update_fields.update(property_data.keys())
                            properties_to_update.append(existing_prop)
                        else:
                            properties_to_create.append(
                                SchemaPropertyGroupProperty(property_group=instance, **property_data)
                            )

                    if properties_to_update:
                        # bulk_update skips auto_now, so set updated_at explicitly
                        now = timezone.now()
                        for prop in properties_to_update:
                            prop.updated_at = now
                        SchemaPropertyGroupProperty.objects.bulk_update(
                            properties_to_update, [*sorted(update_fields), "updated_at"]
                        )
                    if properties_to_create:
                        SchemaPropertyGroupProperty.objects.bulk_create(properties_to_create)

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
    scope_object = "event_definition"
    serializer_class = SchemaPropertyGroupSerializer
    queryset = SchemaPropertyGroup.objects.all()
    lookup_field = "id"

    def check_permissions(self, request: Request) -> None:
        super().check_permissions(request)
        if request.method not in SAFE_METHODS:
            refuse_scout_taxonomy_write(is_scout_sandbox_request(request))

    def safely_get_queryset(self, queryset):
        return (
            queryset.filter(team_id=self.team_id)
            .prefetch_related("properties", "event_schemas__event_definition")
            .order_by("name")
        )
