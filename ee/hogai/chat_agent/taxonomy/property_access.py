from posthog.models import Team, User

from products.access_control.backend.property_access_control import get_restricted_property_names
from products.event_definitions.backend.models.property_definition import PropertyDefinition


def restricted_property_names(team: Team, user: User | None, property_type: PropertyDefinition.Type) -> set[str]:
    """Property names the user may not read for this type, per field-level access control.

    Mirrors PropertyDefinitionViewSet._get_restricted_property_names so the agent's taxonomy
    listings and value lookups honor the same access control as the product property picker —
    otherwise Max would advertise (and return values for) properties the picker hides. Returns
    an empty set when property access control is not enabled for the team, so this is a cheap
    no-op for the common case.
    """
    return get_restricted_property_names(team_id=team.id, user=user, property_type=property_type)
