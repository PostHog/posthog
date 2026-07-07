from posthog.models import PropertyDefinition, Team, User


def restricted_property_names(team: Team, user: User | None, property_type: PropertyDefinition.Type) -> set[str]:
    """Property names the user may not read for this type, per field-level access control.

    Mirrors PropertyDefinitionViewSet._get_restricted_property_names so taxonomy listings and value
    lookups (including the agent's) honor the same access control as the product property picker —
    otherwise restricted property names and values would still be surfaced. Returns an empty set
    when property access control is not enabled for the team, so this is a cheap no-op for the
    common case.

    Lives in posthog/ (not ee/) so callers in ee can reach it without ee depending on
    products.access_control, which the import boundary forbids.
    """
    # Deferred to keep products.access_control off the module import graph, matching
    # PropertyDefinitionViewSet._get_restricted_property_names.
    from products.access_control.backend.property_access_control import get_restricted_property_names  # noqa: PLC0415

    return get_restricted_property_names(team_id=team.id, user=user, property_type=property_type)
