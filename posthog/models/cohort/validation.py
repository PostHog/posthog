from typing import Any, Optional
import structlog
from rest_framework import serializers
from rest_framework.exceptions import ValidationError

from posthog.models.cohort.cohort import CohortType

logger = structlog.get_logger(__name__)

# Analytical behavioral property types
ANALYTICAL_BEHAVIORAL_TYPES = {
    "performed_event_first_time",
    "performed_event_regularly",
    "performed_event_sequence",
    "stopped_performing_event",
    "restarted_performing_event",
}

# Type hierarchy for determining precedence
TYPE_PRIORITY = {
    CohortType.STATIC: 0,
    CohortType.PERSON_PROPERTY: 1,
    CohortType.BEHAVIORAL: 2,
    CohortType.ANALYTICAL: 3,
}


class PropertySerializer(serializers.Serializer):
    """Serializer for individual property filters"""

    type = serializers.ChoiceField(choices=["person", "behavioral", "cohort"])
    key = serializers.CharField()
    value = serializers.JSONField(required=False, allow_null=True)
    operator = serializers.CharField(required=False, allow_null=True)
    negation = serializers.BooleanField(required=False, default=False)

    # Behavioral-specific fields
    event_type = serializers.CharField(required=False)
    time_value = serializers.IntegerField(required=False, allow_null=True)
    time_interval = serializers.CharField(required=False, allow_null=True)
    operator_value = serializers.IntegerField(required=False, allow_null=True)
    seq_time_interval = serializers.CharField(required=False, allow_null=True)
    seq_time_value = serializers.IntegerField(required=False, allow_null=True)
    seq_event = serializers.CharField(required=False, allow_null=True)
    seq_event_type = serializers.CharField(required=False, allow_null=True)
    total_periods = serializers.IntegerField(required=False, allow_null=True)
    min_periods = serializers.IntegerField(required=False, allow_null=True)
    explicit_datetime = serializers.CharField(required=False, allow_null=True)


class PropertyGroupSerializer(serializers.Serializer):
    """Serializer for property groups (AND/OR logic)"""

    type = serializers.ChoiceField(choices=["AND", "OR"])
    values = serializers.ListField()

    def to_internal_value(self, data):
        """Parse into nested structure with validation"""
        if not isinstance(data, dict):
            raise ValidationError("Property group must be a dictionary")

        if "type" not in data or "values" not in data:
            raise ValidationError("Property group must have 'type' and 'values' fields")

        validated = super().to_internal_value(data)
        validated["values"] = self._parse_values(data["values"])
        return validated

    def _parse_values(self, values_list):
        """Recursively parse property group values"""
        if not values_list:
            return []

        parsed_values = []
        for value in values_list:
            if isinstance(value, dict):
                if "type" in value and "values" in value:
                    # Nested property group
                    group_serializer = PropertyGroupSerializer()
                    parsed_values.append(group_serializer.to_internal_value(value))
                elif "key" in value:
                    # Individual property
                    prop_serializer = PropertySerializer()
                    parsed_values.append(prop_serializer.to_internal_value(value))

        return parsed_values


class CohortFiltersSerializer(serializers.Serializer):
    """Serializer for cohort filters"""

    properties = PropertyGroupSerializer(required=False)


class CohortTypeValidationSerializer(serializers.Serializer):
    """Main serializer for cohort type validation"""

    cohort_type = serializers.ChoiceField(choices=[t.value for t in CohortType], required=False, allow_null=True)
    filters = CohortFiltersSerializer(required=False, allow_null=True)
    query = serializers.JSONField(required=False, allow_null=True)
    is_static = serializers.BooleanField(required=False, default=False)

    def __init__(self, *args, **kwargs):
        self.team_id = kwargs.pop("team_id", None)
        super().__init__(*args, **kwargs)

    def validate(self, attrs):
        """Validate that cohort type matches the filters"""
        provided_type = attrs.get("cohort_type")

        if not provided_type:
            # If no type provided, determine it from filters
            determined_type = self._determine_type_from_data(attrs)
            attrs["cohort_type"] = determined_type.value
            return attrs

        # Validate provided type matches data
        required_type = self._determine_type_from_data(attrs)

        if provided_type != required_type.value:
            raise ValidationError(
                {
                    "cohort_type": f"Cohort type '{provided_type}' does not match the filters. "
                    f"Expected type: '{required_type.value}'"
                }
            )

        return attrs

    def _determine_type_from_data(self, data: dict) -> CohortType:
        """Determine cohort type from data"""
        visited_cohorts = set()
        return self._determine_type_recursive(data, visited_cohorts)

    def _determine_type_recursive(self, data: dict, visited: set[int]) -> CohortType:
        """Recursively determine cohort type with circular reference detection"""

        # Static cohorts are always STATIC
        if data.get("is_static"):
            return CohortType.STATIC

        # Query-based cohorts are always ANALYTICAL
        if data.get("query"):
            return CohortType.ANALYTICAL

        # Check filters
        filters = data.get("filters", {})
        if not filters:
            raise ValidationError("Cannot determine type: no valid filters found")

        properties = filters.get("properties")
        if not properties:
            raise ValidationError("Cannot determine type: no valid filters found")

        # Check if any properties are analytical
        if self._has_analytical_properties(properties):
            return CohortType.ANALYTICAL

        # Analyze properties to determine type
        max_type = self._analyze_property_group_type(properties, visited)

        if max_type is None:
            raise ValidationError("Cannot determine type: no valid filters found")

        return max_type

    def _has_analytical_properties(self, properties: dict) -> bool:
        """Check if property group contains analytical behavioral filters"""
        if not properties:
            return False

        return self._check_analytical_in_group(properties)

    def _check_analytical_in_group(self, group: dict) -> bool:
        """Recursively check for analytical properties in a group"""
        values = group.get("values", [])

        for value in values:
            if isinstance(value, dict):
                if value.get("type") == "behavioral" and value.get("value") in ANALYTICAL_BEHAVIORAL_TYPES:
                    return True
                elif "type" in value and "values" in value:
                    # Nested group
                    if self._check_analytical_in_group(value):
                        return True

        return False

    def _analyze_property_group_type(self, properties: dict, visited: set[int]) -> Optional[CohortType]:
        """Analyze a property group to determine its cohort type"""

        if not properties:
            return None

        max_type = None
        values = properties.get("values", [])

        for value in values:
            if isinstance(value, dict):
                if "type" in value and "values" in value:
                    # Nested group
                    nested_type = self._analyze_property_group_type(value, visited)
                    max_type = self._highest_priority_cohort_type(max_type, nested_type)
                else:
                    # Individual property
                    prop_type = self._get_property_type(value, visited)
                    max_type = self._highest_priority_cohort_type(max_type, prop_type)

        return max_type

    def _get_property_type(self, prop: dict, visited: set[int]) -> CohortType:
        """Get the cohort type for a single property"""

        prop_type = prop.get("type")

        if prop_type == "behavioral":
            if prop.get("value") in ANALYTICAL_BEHAVIORAL_TYPES:
                return CohortType.ANALYTICAL
            return CohortType.BEHAVIORAL

        elif prop_type == "person":
            return CohortType.PERSON_PROPERTY

        elif prop_type == "cohort":
            # Handle cohort references
            return self._get_referenced_cohort_type(prop.get("value"), visited)

        else:
            raise ValidationError(f"Unknown property type: {prop_type}")

    def _get_referenced_cohort_type(self, cohort_value: Any, visited: set[int]) -> CohortType:
        """Get the type of a referenced cohort"""

        if not cohort_value:
            raise ValidationError("Cohort filter has no value")

        # Extract cohort ID
        if isinstance(cohort_value, list):
            if len(cohort_value) != 1:
                raise ValidationError("Cohort filter must reference exactly one cohort")
            cohort_id = int(cohort_value[0])
        else:
            cohort_id = int(cohort_value)

        # Check for circular references
        if cohort_id in visited:
            raise ValidationError("Circular cohort reference detected")

        # Get the referenced cohort
        from posthog.models.cohort.cohort import Cohort

        try:
            referenced_cohort = Cohort.objects.get(id=cohort_id, team_id=self.team_id)
        except Cohort.DoesNotExist:
            raise ValidationError(f"Referenced cohort {cohort_id} not found")

        # Build data for the referenced cohort
        referenced_data = {
            "is_static": referenced_cohort.is_static,
            "query": referenced_cohort.query,
            "filters": referenced_cohort.filters,
        }

        # Recursively determine type
        return self._determine_type_recursive(referenced_data, visited | {cohort_id})

    def _highest_priority_cohort_type(
        self, current: Optional[CohortType], new: Optional[CohortType]
    ) -> Optional[CohortType]:
        """Return the higher priority cohort type based on complexity hierarchy"""
        if current is None:
            return new
        if new is None:
            return current
        return current if TYPE_PRIORITY[current] > TYPE_PRIORITY[new] else new


def validate_cohort_type_against_data(
    provided_cohort_type: CohortType, cohort_data: dict, team_id: int
) -> tuple[bool, Optional[str]]:
    """
    Validate cohort type against raw cohort data using DRF serializers.

    Args:
        provided_cohort_type: The cohort type string to validate
        cohort_data: Raw cohort data dict (filters, is_static, query, etc.)
        team_id: Team ID for cohort reference validation

    Returns:
        Tuple of (is_valid, error_message)
    """
    # Add the provided type to the data for validation
    data = {**cohort_data, "cohort_type": provided_cohort_type}

    serializer = CohortTypeValidationSerializer(data=data, team_id=team_id)

    try:
        serializer.is_valid(raise_exception=True)
        return True, None
    except ValidationError as e:
        # Extract error message
        if "cohort_type" in e.detail:
            error_msg = e.detail["cohort_type"]
            if isinstance(error_msg, list):
                error_msg = error_msg[0]
            return False, str(error_msg)
        elif "non_field_errors" in e.detail:
            error_msg = e.detail["non_field_errors"]
            if isinstance(error_msg, list):
                error_msg = error_msg[0]
            return False, str(error_msg)
        return False, "Cohort validation failed due to invalid references or circular dependencies."


def determine_cohort_type_from_data(data: dict, team_id: int) -> CohortType:
    """
    Determine cohort type from raw data using DRF serializers.

    Args:
        data: Raw cohort data dict
        team_id: Team ID for cohort reference validation

    Returns:
        The determined CohortType
    """
    serializer = CohortTypeValidationSerializer(data=data, team_id=team_id)

    try:
        serializer.is_valid(raise_exception=True)
        return serializer._determine_type_from_data(serializer.validated_data)
    except ValidationError as e:
        logger.warning("Cohort type determination failed", error=str(e))
        raise ValueError(f"Cannot determine cohort type: {str(e)}")
