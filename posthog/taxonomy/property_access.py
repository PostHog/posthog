from posthog.models import PropertyDefinition, Team, User
from posthog.settings import EE_AVAILABLE


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


def excluded_property_names(team: Team, user: User | None, property_type: PropertyDefinition.Type) -> set[str]:
    """Property names the agent must not surface or sample values from, for this type.

    Two controls, one answer: field-level access control, plus the `hidden` flag a team sets in
    data management. Both read the same way to the agent — the property is absent from the
    taxonomy, so the agent cannot report that the name exists and cannot put its values in the
    model context.

    `hidden` lives only on the enterprise definition, so it adds nothing on OSS builds. That is the
    same condition PropertyDefinitionViewSet applies before it adds its `exclude_hidden` filter for
    the product property picker.

    The hidden set is scoped by type only. A group property hidden under one group type index also
    disappears for the others, which keeps this to one query and errs toward hiding.
    """
    excluded = restricted_property_names(team, user, property_type)
    if not EE_AVAILABLE:
        return excluded

    from ee.models.property_definition import (
        EnterprisePropertyDefinition,  # noqa: PLC0415 — EE-only model, keep off the OSS import path
    )

    return excluded | set(
        EnterprisePropertyDefinition.objects.filter(team=team, type=property_type, hidden=True).values_list(
            "name", flat=True
        )
    )
