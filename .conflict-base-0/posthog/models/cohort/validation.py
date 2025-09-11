from typing import Any, Optional

import structlog
from rest_framework import serializers
from rest_framework.exceptions import ValidationError

from posthog.models.cohort.cohort import CohortType

logger = structlog.get_logger(__name__)

# Analytical behavioral property types that make a cohort analytical
ANALYTICAL_BEHAVIORAL_TYPES = {
    "performed_event_first_time",
    "performed_event_regularly",
    "performed_event_sequence",
    "stopped_performing_event",
    "restarted_performing_event",
}

# Type hierarchy for determining precedence (higher number = higher complexity)
TYPE_PRIORITY = {
    CohortType.STATIC: 0,
    CohortType.PERSON_PROPERTY: 1,
    CohortType.BEHAVIORAL: 2,
    CohortType.ANALYTICAL: 3,
}


class CohortTypeValidationSerializer(serializers.Serializer):
    """
    Internal serializer that validates cohort type matches the filters.
    Uses DRF's validation framework for clean, idiomatic Django validation.
    """

    cohort_type = serializers.ChoiceField(choices=[t.value for t in CohortType], required=False, allow_null=True)
    filters = serializers.DictField(required=False, allow_null=True)
    query = serializers.JSONField(required=False, allow_null=True)
    is_static = serializers.BooleanField(required=False, default=False)

    def __init__(self, *args, **kwargs):
        self.team_id = kwargs.pop("team_id", None)
        super().__init__(*args, **kwargs)

    def validate(self, attrs):
        """Validate that cohort type matches the filters"""
        provided_type = attrs.get("cohort_type")

        # Always validate the data structure for consistency, even without cohort_type
        try:
            required_type = self._determine_type_from_data(attrs)
        except ValidationError:
            # Re-raise validation errors (missing cohorts, circular refs, etc.)
            raise

        if provided_type:
            # If type is provided, validate it matches
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
        visited_cohorts: set[int] = set()
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
