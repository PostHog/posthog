from typing import Any

from rest_framework.exceptions import PermissionDenied, ValidationError

from posthog.models.property import Property
from posthog.models.user import User

from products.access_control.backend.facade.api import get_restricted_properties_with_group_type_index_for_team
from products.event_definitions.backend.models.property_definition import PropertyDefinition


def can_access_clustering_filters(team_id: int, user: User, filters: list[dict[str, Any]]) -> bool:
    if not isinstance(filters, list) or any(not isinstance(event_filter, dict) for event_filter in filters):
        return False
    restrictions = get_restricted_properties_with_group_type_index_for_team(user=user, team_id=team_id)
    if not restrictions:
        return True
    property_types = {
        "event": PropertyDefinition.Type.EVENT,
        "person": PropertyDefinition.Type.PERSON,
        "group": PropertyDefinition.Type.GROUP,
    }
    for event_filter in filters:
        if not isinstance(event_filter.get("key"), str):
            return False
        try:
            prop = Property(**event_filter)
        except (TypeError, ValueError, ValidationError):
            return False
        property_type = property_types.get(prop.type)
        # Cohort and HogQL predicates can reference properties indirectly.
        if property_type is None:
            return False
        if any(
            restriction.property_type == property_type
            and (restriction.name == prop.key or prop.key.startswith(f"{restriction.name}."))
            and (
                property_type != PropertyDefinition.Type.GROUP
                or restriction.group_type_index in (None, prop.group_type_index)
            )
            for restriction in restrictions
        ):
            return False
    return True


def validate_clustering_filters(team_id: int, user: User, filters: list[dict[str, Any]]) -> None:
    if not can_access_clustering_filters(team_id, user, filters):
        raise PermissionDenied("These clustering filters require property access you don't have. Choose other filters.")
