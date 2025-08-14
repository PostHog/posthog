from typing import Optional
import structlog
from posthog.models.cohort.cohort import CohortType
from posthog.models.property import BehavioralPropertyType, Property, PropertyGroup, PropertyOperatorType

logger = structlog.get_logger(__name__)

# Analytical behavioral property types
ANALYTICAL_BEHAVIORAL_TYPES = {
    BehavioralPropertyType.PERFORMED_EVENT_FIRST_TIME,
    BehavioralPropertyType.PERFORMED_EVENT_REGULARLY,
    BehavioralPropertyType.PERFORMED_EVENT_SEQUENCE,
    BehavioralPropertyType.STOPPED_PERFORMING_EVENT,
    BehavioralPropertyType.RESTARTED_PERFORMING_EVENT,
}

# Type hierarchy for determining precedence
TYPE_PRIORITY = {
    CohortType.STATIC: 0,
    CohortType.PERSON_PROPERTY: 1,
    CohortType.BEHAVIORAL: 2,
    CohortType.ANALYTICAL: 3,
}


def _parse_property_group(group: Optional[dict]) -> PropertyGroup:
    """Parse a dictionary into PropertyGroup. Mirrors PropertyMixin._parse_property_group"""
    if group and "type" in group and "values" in group:
        return PropertyGroup(
            PropertyOperatorType(group["type"].upper()),
            _parse_property_group_list(group["values"]),
        )
    return PropertyGroup(PropertyOperatorType.AND, [])


def _parse_property_group_list(prop_list: Optional[list]):
    """Parse a list of properties/property groups. Mirrors PropertyMixin._parse_property_group_list"""
    if not prop_list:
        return []

    # Determine what type of properties we have
    property_group_count = sum(
        1 for prop in prop_list if isinstance(prop, dict) and "type" in prop and "values" in prop
    )
    simple_property_count = sum(1 for prop in prop_list if isinstance(prop, dict) and "key" in prop)

    if property_group_count > 0 and simple_property_count > 0:
        raise ValueError("Property list cannot contain both PropertyGroup and Property objects")

    if property_group_count > 0:
        return [_parse_property_group(group) for group in prop_list if isinstance(group, dict)]
    else:
        return _parse_properties(prop_list)


def _parse_properties(properties: Optional[list]) -> list[Property]:
    """Parse a list of property dictionaries into Property objects"""
    if not properties:
        return []

    return [Property(**prop) for prop in properties if isinstance(prop, dict)]


def _extract_property_group_from_data(data: dict) -> Optional[PropertyGroup]:
    """Extract and parse PropertyGroup from cohort data, returning None if no valid properties"""
    filters = data.get("filters", {})
    if not filters:
        return None

    properties_data = filters.get("properties", {})
    if not properties_data:
        return None

    try:
        return _parse_property_group(properties_data)
    except (ValueError, KeyError, TypeError):
        return None


def _extract_cohort_id(prop_value) -> int:
    """Extract cohort ID from property value, handling both single values and lists"""
    if not prop_value:
        raise ValueError("Cohort filter has no value")

    # Extract cohort ID from value (handle both list and single value)
    if isinstance(prop_value, list):
        if len(prop_value) != 1:
            raise ValueError("Cohort filter must reference exactly one cohort")
        cohort_value = str(prop_value[0])
    else:
        cohort_value = str(prop_value)

    try:
        return int(cohort_value)
    except (ValueError, TypeError):
        raise ValueError(f"Invalid cohort ID '{cohort_value}'")


def validate_cohort_type_against_data(
    provided_cohort_type: str, cohort_data: dict, team_id: int
) -> tuple[bool, Optional[str]]:
    """
    Validate cohort type against raw cohort data without model instantiation.
    Pure function that can be used in serializers or elsewhere.

    Args:
        provided_cohort_type: The cohort type string to validate
        cohort_data: Raw cohort data dict (filters, is_static, query, etc.)
        team_id: Team ID for cohort reference validation

    Returns:
        Tuple of (is_valid, error_message)
    """
    # Validate the provided type string
    try:
        provided_type_enum = CohortType(provided_cohort_type)
    except ValueError:
        return False, f"Invalid cohort type: {provided_cohort_type}"

    # Determine required type from data
    try:
        required_type = determine_cohort_type_from_data(cohort_data, team_id)
    except ValueError as e:
        logger.warning("Cohort validation error", error=str(e))
        return False, "Cohort validation failed due to invalid references or circular dependencies."

    # Check for exact match
    if provided_type_enum != required_type:
        return (
            False,
            f"Cohort type '{provided_cohort_type}' does not match the filters. Expected type: '{required_type}'",
        )

    return True, None


def determine_cohort_type_from_data(data: dict, team_id: int) -> CohortType:
    """
    Determine cohort type from raw data without creating a model instance.
    Mirrors Cohort.determine_cohort_type_based_on_filters()
    """
    return _determine_cohort_type_from_data_recursive(data, team_id, set())


def _determine_cohort_type_from_data_recursive(data: dict, team_id: int, visited: set[int]) -> CohortType:
    """
    Recursively determine cohort type with circular reference detection.
    """
    # Static cohorts are always STATIC
    if data.get("is_static"):
        return CohortType.STATIC

    # Query-based cohorts are always ANALYTICAL
    if data.get("query"):
        return CohortType.ANALYTICAL

    # Check for analytical filters
    if _has_analytical_filters_in_data(data):
        return CohortType.ANALYTICAL

    # Analyze filters to determine type hierarchy
    max_type = _analyze_filters_for_type_from_data(data, team_id, visited)

    if max_type is None:
        raise ValueError("Cannot determine type: no valid filters found")

    return max_type


def _has_analytical_filters_in_data(data: dict) -> bool:
    """Check if data contains analytical filters without model instantiation"""
    property_group = _extract_property_group_from_data(data)
    if not property_group:
        return False

    return any(prop.type == "behavioral" and prop.value in ANALYTICAL_BEHAVIORAL_TYPES for prop in property_group.flat)


def _analyze_filters_for_type_from_data(data: dict, team_id: int, visited: set[int]) -> Optional[CohortType]:
    """Analyze filters from raw data to determine max complexity type"""
    property_group = _extract_property_group_from_data(data)
    if not property_group:
        return None

    max_type = None
    has_any_filters = False

    try:
        for prop in property_group.flat:
            has_any_filters = True

            if prop.type == "behavioral":
                max_type = _max_cohort_type(max_type, CohortType.BEHAVIORAL)
            elif prop.type == "person":
                max_type = _max_cohort_type(max_type, CohortType.PERSON_PROPERTY)
            elif prop.type == "cohort":
                cohort_type = _get_referenced_cohort_type(prop.value, team_id, visited)
                max_type = _max_cohort_type(max_type, cohort_type)
            else:
                raise ValueError(f"Unknown property type '{prop.type}'")

    except (ValueError, KeyError, TypeError) as e:
        raise ValueError(f"Error parsing filters: {e}")

    if not has_any_filters:
        return None

    return max_type or CohortType.PERSON_PROPERTY


def _get_referenced_cohort_type(prop_value, team_id: int, visited: set[int]) -> CohortType:
    """Get the cohort type of a referenced cohort"""
    referenced_cohort_id = _extract_cohort_id(prop_value)

    # Prevent circular references
    if referenced_cohort_id in visited:
        raise ValueError("Circular cohort reference detected")

    # Get referenced cohort and determine its type
    try:
        from posthog.models.cohort.cohort import Cohort

        referenced_cohort = Cohort.objects.get(id=referenced_cohort_id, team_id=team_id)

        # Build cohort data for the referenced cohort
        referenced_data = {
            "is_static": referenced_cohort.is_static,
            "query": referenced_cohort.query,
            "filters": referenced_cohort.filters,
        }

        # Recursively determine type
        return _determine_cohort_type_from_data_recursive(referenced_data, team_id, visited | {referenced_cohort_id})
    except Cohort.DoesNotExist:
        raise ValueError(f"Referenced cohort {referenced_cohort_id} not found")


def _max_cohort_type(current: Optional[CohortType], new: CohortType) -> CohortType:
    """Return the higher priority cohort type based on complexity hierarchy"""
    if current is None:
        return new

    return current if TYPE_PRIORITY[current] > TYPE_PRIORITY[new] else new
