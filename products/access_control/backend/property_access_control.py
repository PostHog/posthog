from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING
from uuid import UUID

from posthog.models import OrganizationMembership
from posthog.models.team import Team

from products.access_control.backend.models.property_access_control import PropertyAccessControl

from ee.models.rbac.role import RoleMembership

if TYPE_CHECKING:
    from posthog.models import User

    from products.event_definitions.backend.models.property_definition import PropertyDefinition


class PropertyAccessLevel(Enum):
    READ_WRITE = "read_write"
    READ = "read"
    NONE = "none"

    def grants_access(self) -> bool:
        """Returns True if this level allows the property to be read in queries."""
        return self in (PropertyAccessLevel.READ_WRITE, PropertyAccessLevel.READ)


def get_default_access_level() -> PropertyAccessLevel:
    """
    :returns: The default access level for a property
    """
    return PropertyAccessLevel.READ_WRITE


def get_property_access_level(
    *,
    property: PropertyDefinition,
    user: User | None,
) -> PropertyAccessLevel:
    """
    Determines the effective access level for a property. If a user is provided, then the user's membership and role are
    used in the calculation for the access level.

    The hierarchy is:
    1. user-specific rules (access control rule has non-null membership foreign key)
    2. role-specific rules (access control rule has non-null role foreign key)
    3. the default rule for the property definition (access control rule has null membership and role foreign keys)

    :param property: The property which we are checking access for.
    :param user: (optional) The user who is attempting to access the property. When not provided the property's default access level is
    returned.

    :returns: The `PropertyAccessLevel` for the property.
    """
    rules = list(
        PropertyAccessControl.objects.filter(property_definition=property).select_related("organization_member", "role")
    )

    if not rules:
        return get_default_access_level()

    membership = None
    user_role_ids: set[int] = set()
    if user is not None:
        membership = (
            OrganizationMembership.objects.filter(
                user=user,
                organization_id=property.team.organization_id,
            )
            .only("id", "level")
            .first()
        )

        if membership is None:
            raise ValueError("user does not have organization membership")

        user_role_ids = set(
            RoleMembership.objects.filter(organization_member=membership).values_list("role_id", flat=True)
        )

    return _resolve_access_level(rules, membership=membership, user_role_ids=user_role_ids)


def strip_restricted_properties(
    properties: dict,
    restricted_names: set[str],
) -> dict:
    """
    Returns a copy of the properties dict with restricted keys removed.
    """
    if not restricted_names:
        return properties
    return {k: v for k, v in properties.items() if k not in restricted_names}


def get_restricted_property_names(
    *,
    team_id: int,
    user: Optional[User],
    property_type: int,
) -> set[str]:
    """
    Convenience wrapper over get_restricted_properties_for_team that returns just the property names
    restricted for a specific PropertyDefinition.Type (EVENT or PERSON).

    :param team_id: The team whose restrictions to check.
    :param user: The user making the request.
    :param property_type: PropertyDefinition.Type value (e.g., PropertyDefinition.Type.EVENT).
    :returns: Set of restricted property name strings.
    """
    restricted = get_restricted_properties_for_team(team_id=team_id, user=user)
    return {name for name, ptype in restricted if ptype == property_type}


def get_non_writable_property_names(
    *,
    team_id: int,
    user: Optional[User],
    property_type: int,
) -> set[str]:
    """
    Returns property names where the user does not have write access (i.e., the effective
    access level is READ or NONE).

    :param team_id: The team whose restrictions to check.
    :param user: The user making the request.
    :param property_type: PropertyDefinition.Type value (e.g., PropertyDefinition.Type.PERSON).
    :returns: Set of property name strings that the user cannot write to.
    """
    from posthog.models import OrganizationMembership

    from products.platform_features.backend.models.property_access_control import PropertyAccessControl

    rules = (
        PropertyAccessControl.objects.filter(team_id=team_id)
        .select_related("property_definition", "organization_member", "role")
        .exclude(property_definition__isnull=True)
        .filter(property_definition__type=property_type)
    )

    if not rules.exists():
        return set()

    rules_by_property: dict[int, list[PropertyAccessControl]] = {}
    for rule in rules:
        prop_def_id = rule.property_definition_id
        if prop_def_id not in rules_by_property:
            rules_by_property[prop_def_id] = []
        rules_by_property[prop_def_id].append(rule)

    membership = None
    user_role_ids: set[int] = set()
    if user is not None:
        from posthog.models.team import Team

        org_id = Team.objects.values_list("organization_id", flat=True).get(id=team_id)
        membership = OrganizationMembership.objects.filter(user=user, organization_id=org_id).only("id").first()

        from ee.models.rbac.role import RoleMembership

        user_role_ids = set(RoleMembership.objects.filter(user=user).values_list("role_id", flat=True))

    non_writable: set[str] = set()
    for _prop_def_id, prop_rules in rules_by_property.items():
        prop_def = prop_rules[0].property_definition
        level = _resolve_access_level(prop_rules, membership=membership, user_role_ids=user_role_ids)
        if level != PropertyAccessLevel.READ_WRITE:
            non_writable.add(prop_def.name)

    return non_writable


def get_restricted_properties_for_team(
    *,
    team_id: int,
    user: User | None,
) -> set[tuple[str, int]]:
    """
    Returns the set of (property_name, property_type) pairs that are restricted for the given user on the team.
    This is designed to be called once per query to batch-load all restrictions rather than checking one property
    at a time.

    :param team_id: The team whose property restrictions we are checking.
    :param user: (optional) The user making the query. When not provided, only the default (property-level) rules apply.

    :returns: A set of (property_name, property_definition_type) tuples that are restricted.
    """
    rules = (
        PropertyAccessControl.objects.filter(team_id=team_id)
        .select_related("property_definition", "organization_member", "role")
        .exclude(property_definition__isnull=True)
    )

    if not rules.exists():
        return set()

    # group rules by property definition
    rules_by_property: dict[UUID, list[PropertyAccessControl]] = {}
    for rule in rules:
        if rule.property_definition_id is None:
            continue

        prop_def_id = rule.property_definition_id
        if prop_def_id not in rules_by_property:
            rules_by_property[prop_def_id] = []
        rules_by_property[prop_def_id].append(rule)

    # resolve the user's membership and roles once
    membership = None
    user_role_ids: set[int] = set()
    if user is not None:
        org_id = Team.objects.values_list("organization_id", flat=True).get(id=team_id)
        membership_qs = OrganizationMembership.objects.filter(
            user=user,
            organization_id=org_id,
        ).only("id", "level")
        membership = membership_qs.first()

        if membership is None:
            raise ValueError("user does not have organization membership")

        user_role_ids = set(
            RoleMembership.objects.filter(organization_member=membership).values_list("role_id", flat=True)
        )

    restricted: set[tuple[str, int]] = set()

    for _prop_def_id, prop_rules in rules_by_property.items():
        prop_def = prop_rules[0].property_definition
        level = _resolve_access_level(
            prop_rules,
            membership=membership,
            user_role_ids=user_role_ids,
        )
        if prop_def is not None and not level.grants_access():
            restricted.add((prop_def.name, prop_def.type))

    return restricted


def _resolve_access_level(
    rules: list[PropertyAccessControl],
    *,
    membership: OrganizationMembership | None,
    user_role_ids: set[int],
) -> PropertyAccessLevel:
    """
    Resolves the effective access level from a set of rules for a single property definition,
    following the hierarchy: user-specific > role-specific > default.

    Org admins bypass member- and role-specific overrides and always get the default access level
    for the property, mirroring the admin bypass in `UserAccessControl.access_level_for_object`.
    """
    # Org admins bypass all access control rules and get full access
    if membership is not None and membership.level >= OrganizationMembership.Level.ADMIN:
        return get_default_access_level()

    # 1. user-specific rule
    if membership is not None:
        for rule in rules:
            if rule.organization_member_id == membership.pk:
                return PropertyAccessLevel(rule.access_level)

    # 2. role-specific rules (most permissive wins)
    role_rules = [r for r in rules if r.role_id is not None and r.role_id in user_role_ids]
    if role_rules:
        for rule in role_rules:
            level = PropertyAccessLevel(rule.access_level)
            if level.grants_access():
                return level
        return PropertyAccessLevel.NONE

    # 3. default rule (null membership and null role)
    for rule in rules:
        if rule.organization_member_id is None and rule.role_id is None:
            return PropertyAccessLevel(rule.access_level)

    return get_default_access_level()
