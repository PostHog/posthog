import logging
from typing import Any

from django.db import IntegrityError, transaction

from rest_framework import mixins, serializers, viewsets

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.models import SchemaPropertyGroup, SchemaPropertyGroupProperty

MAX_PROPERTY_NAME_LENGTH = 200
MAX_ENUM_VALUES = 1000

NUMERIC_RANGE_KEYWORDS = {"minimum", "exclusiveMinimum", "maximum", "exclusiveMaximum"}
LOWER_BOUND_KEYWORDS = {"minimum", "exclusiveMinimum"}
UPPER_BOUND_KEYWORDS = {"maximum", "exclusiveMaximum"}


def validate_validation_rules(property_type: str, rules: dict | None) -> None:
    """Validate that validation_rules are consistent with the property type.

    Raises serializers.ValidationError on invalid input.
    """
    if rules is None or rules == {}:
        return

    if property_type in ("DateTime", "Boolean", "Object"):
        raise serializers.ValidationError(
            {"validation_rules": f"Validation rules are not supported for {property_type} properties"}
        )

    if property_type == "String":
        _validate_string_rules(rules)
    elif property_type == "Numeric":
        _validate_numeric_rules(rules)
    else:
        raise serializers.ValidationError(
            {"validation_rules": f"Validation rules are not supported for {property_type} properties"}
        )


def _validate_string_rules(rules: dict[str, Any]) -> None:
    allowed_keys = {"enum", "not"}
    extra_keys = set(rules.keys()) - allowed_keys
    if extra_keys:
        raise serializers.ValidationError(
            {"validation_rules": f"Unrecognized keys for String validation: {', '.join(sorted(extra_keys))}"}
        )

    has_enum = "enum" in rules
    has_not = "not" in rules

    if has_enum and has_not:
        raise serializers.ValidationError(
            {"validation_rules": "Cannot specify both 'enum' and 'not' — use one or the other"}
        )

    if not has_enum and not has_not:
        raise serializers.ValidationError({"validation_rules": "String validation requires either 'enum' or 'not' key"})

    if has_enum:
        _validate_enum_values(rules["enum"])
    else:
        not_value = rules["not"]
        if not isinstance(not_value, dict) or set(not_value.keys()) != {"enum"}:
            raise serializers.ValidationError({"validation_rules": "'not' must contain exactly one key: 'enum'"})
        _validate_enum_values(not_value["enum"])


def _validate_enum_values(values: Any) -> None:
    if not isinstance(values, list):
        raise serializers.ValidationError({"validation_rules": "'enum' must be a list"})
    if len(values) == 0:
        raise serializers.ValidationError({"validation_rules": "'enum' list must not be empty"})
    if len(values) > MAX_ENUM_VALUES:
        raise serializers.ValidationError({"validation_rules": f"'enum' list must not exceed {MAX_ENUM_VALUES} items"})
    if not all(isinstance(v, str) for v in values):
        raise serializers.ValidationError({"validation_rules": "All 'enum' values must be strings"})


def _validate_numeric_rules(rules: dict[str, Any]) -> None:
    extra_keys = set(rules.keys()) - NUMERIC_RANGE_KEYWORDS
    if extra_keys:
        raise serializers.ValidationError(
            {"validation_rules": f"Unrecognized keys for Numeric validation: {', '.join(sorted(extra_keys))}"}
        )

    if len(set(rules.keys()) & LOWER_BOUND_KEYWORDS) > 1:
        raise serializers.ValidationError({"validation_rules": "Cannot specify both 'minimum' and 'exclusiveMinimum'"})

    if len(set(rules.keys()) & UPPER_BOUND_KEYWORDS) > 1:
        raise serializers.ValidationError({"validation_rules": "Cannot specify both 'maximum' and 'exclusiveMaximum'"})

    for key in rules:
        val = rules[key]
        if not isinstance(val, (int, float)):
            raise serializers.ValidationError({"validation_rules": f"'{key}' must be a number"})

    lower_key = next((k for k in LOWER_BOUND_KEYWORDS if k in rules), None)
    upper_key = next((k for k in UPPER_BOUND_KEYWORDS if k in rules), None)

    if lower_key and upper_key:
        lower_val = rules[lower_key]
        upper_val = rules[upper_key]
        if lower_val >= upper_val:
            raise serializers.ValidationError(
                {
                    "validation_rules": f"Lower bound ({lower_key}={lower_val}) must be less than upper bound ({upper_key}={upper_val})"
                }
            )


class SchemaPropertyGroupPropertySerializer(serializers.ModelSerializer):
    class Meta:
        model = SchemaPropertyGroupProperty
        fields = (
            "id",
            "name",
            "property_type",
            "is_required",
            "is_optional_in_types",
            "validation_rules",
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
                validate_validation_rules(property_data.get("property_type", ""), property_data.get("validation_rules"))
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
                        validate_validation_rules(
                            property_data.get("property_type", ""),
                            property_data.get("validation_rules"),
                        )
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
    scope_object = "event_definition"
    serializer_class = SchemaPropertyGroupSerializer
    queryset = SchemaPropertyGroup.objects.all()
    lookup_field = "id"

    def safely_get_queryset(self, queryset):
        return (
            queryset.filter(team_id=self.team_id)
            .prefetch_related("properties", "event_schemas__event_definition")
            .order_by("name")
        )
