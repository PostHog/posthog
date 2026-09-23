"""
Facade API for access_control.

This is the module that other apps / the presentation layer should
import from. It accepts plain inputs and returns contract DTOs, never
ORM instances or QuerySets.

Responsibilities:
- Accept DTOs / primitive inputs
- Call domain logic / ORM
- Convert Django models to DTOs before returning
- Remain thin and stable

Do NOT:
- Import DRF / serializers / HTTP concerns here
- Return ORM instances or QuerySets
"""

from __future__ import annotations

from typing import cast
from uuid import UUID

from django.shortcuts import get_object_or_404

from posthog.hogql.property_access_types import RestrictedProperty

from posthog.constants import AvailableFeature
from posthog.models import Organization, OrganizationMembership, PropertyDefinition, Team
from posthog.models.user import User
from posthog.scopes import API_SCOPE_OBJECTS, INTERNAL_API_SCOPE_OBJECTS, APIScopeObject

from products.access_control.backend.models.role import Role

from ..models.access_control import AccessControl
from ..models.property_access_control import PropertyAccessControl
from ..property_access_control import (
    get_restricted_properties_with_group_type_index_for_team as _get_restricted_properties_with_group_type_index_for_team,
    is_property_access_control_enabled,
)
from . import contracts
from .contracts import PropertyAccessLevel
from .user_access_control import (
    RESOURCE_INHERITANCE_MAP,
    RESOURCES_WITHOUT_RESOURCE_LEVEL_CONTROLS,
    AccessControlLevel,
    access_level_satisfied_for_resource,
    default_access_level,
    highest_access_level,
    minimum_access_level,
    ordered_access_levels,
)


class InvalidObjectAccessControlError(Exception):
    """Raised when an object access control rule names an unknown resource, an access level the
    resource does not support, or a subject outside the team's organization."""


class PropertyDefinitionNotFoundError(Exception):
    """Raised when the target property definition cannot be found for the team."""


class PropertyAccessControlRuleNotFoundError(Exception):
    """Raised when trying to delete a rule that does not exist."""


class InvalidPropertyAccessControlTargetError(Exception):
    """Raised when the rule target (role or organization member) does not
    belong to the same organization as the team."""


# --- Mappers (model -> DTO) ---


def _to_rule(rule: PropertyAccessControl) -> contracts.PropertyAccessControlRule:
    # The FK is nullable in the schema, but a rule is always attached to a property: the upsert
    # resolves a concrete definition before writing, and every read path filters null rows out
    assert rule.property_definition_id is not None
    return contracts.PropertyAccessControlRule(
        id=rule.id,
        property_definition_id=rule.property_definition_id,
        access_level=PropertyAccessLevel(rule.access_level),
        organization_member_id=rule.organization_member_id,
        role_id=rule.role_id,
        created_by_id=rule.created_by_id,
        created_at=rule.created_at,
        updated_at=rule.updated_at,
    )


def _get_property_definition(property_definition_id: str, team_id: int) -> PropertyDefinition:
    try:
        return get_object_or_404(PropertyDefinition, id=property_definition_id, team_id=team_id)
    except Exception as exc:
        # Normalize 404 -> domain error so presentation can translate without leaking ORM concerns.
        from django.http import Http404

        if isinstance(exc, Http404):
            raise PropertyDefinitionNotFoundError(property_definition_id) from exc
        raise


# --- Read API ---


def get_restricted_properties_with_group_type_index_for_team(
    *, user: User | None, team_id: int
) -> set[RestrictedProperty]:
    """Return property restrictions for a user and team."""
    return _get_restricted_properties_with_group_type_index_for_team(user=user, team_id=team_id)


def split_restricted_property_names(restrictions: set[RestrictedProperty]) -> contracts.RestrictedPropertyNames:
    """Return restricted event and person property names."""
    return contracts.RestrictedPropertyNames(
        event=frozenset(
            restriction.name
            for restriction in restrictions
            if restriction.property_type == PropertyDefinition.Type.EVENT
        ),
        person=frozenset(
            restriction.name
            for restriction in restrictions
            if restriction.property_type == PropertyDefinition.Type.PERSON
        ),
    )


def get_property_access_state(
    *,
    team_id: int,
    property_definition_id: str,
) -> contracts.PropertyAccessControlState:
    """Return the full access-control state for a single property definition."""
    prop_def = _get_property_definition(property_definition_id, team_id)

    rules_qs = PropertyAccessControl.objects.filter(
        team_id=team_id,
        property_definition=prop_def,
    ).select_related("organization_member", "role", "created_by")
    rules = list(rules_qs)

    # The rule with null membership AND null role acts as the property-level default.
    default_rule = next(
        (r for r in rules if r.organization_member_id is None and r.role_id is None),
        None,
    )
    default_level = PropertyAccessLevel(default_rule.access_level) if default_rule else PropertyAccessLevel.READ_WRITE

    return contracts.PropertyAccessControlState(
        rules=[_to_rule(r) for r in rules],
        available_access_levels=list(PropertyAccessLevel),
        default_access_level=default_level,
    )


def list_property_access_controls(
    *,
    team_id: int,
    organization_member_id: UUID | None = None,
    role_id: UUID | None = None,
) -> list[contracts.PropertyAccessControlRule]:
    """All property rules belonging to one subject: a member, a role, or (both None) the project-wide default."""
    rules = PropertyAccessControl.objects.filter(
        team_id=team_id,
        organization_member_id=organization_member_id,
        role_id=role_id,  # type: ignore
        property_definition__isnull=False,
    )
    return [_to_rule(rule) for rule in rules]


def team_has_property_access_rules(*, team_id: int) -> bool:
    """Whether the team has any property-level access-control rules in effect.

    True only when the feature is available for the org AND at least one rule
    targeting a property definition exists. Callers that share results across
    users (e.g. userless precompute) use this to opt out entirely, since a
    result computed without a user cannot honor per-user property restrictions.
    """
    if not is_property_access_control_enabled(team_id=team_id):
        return False
    return PropertyAccessControl.objects.filter(team_id=team_id, property_definition__isnull=False).exists()


def user_organizations_use_access_controls(*, user_id: int) -> bool:
    """Whether access rules can narrow what the user reaches in one of their organizations.

    True only when an organization the user belongs to has the access-control feature AND
    at least one rule exists in one of its projects.
    """
    entitled = [
        org.id
        for org in Organization.objects.filter(members=user_id)
        if org.is_feature_available(AvailableFeature.ACCESS_CONTROL)
    ]
    if not entitled:
        return False
    return AccessControl.objects.filter(team__organization_id__in=entitled).exists()


def _level_rank(levels: list[AccessControlLevel], level: str) -> int:
    """Position of `level` on the ladder, with an unrecognized level ranked below every real one."""
    return levels.index(cast(AccessControlLevel, level)) if level in levels else -1


def _grants_at_least(resource: APIScopeObject, level: str, required_level: AccessControlLevel) -> bool:
    """Whether `level` satisfies `required_level`, reading an unrecognized level as no grant.

    The access level of a row is an unvalidated string, so a value outside the ladder of the
    resource is possible. Comparing it would raise, so treat it as restricting instead."""
    if level not in ordered_access_levels(resource):
        return False
    return access_level_satisfied_for_resource(resource, cast(AccessControlLevel, level), required_level)


def every_member_has_resource_access(
    *, team_id: int, resource: APIScopeObject, required_level: AccessControlLevel
) -> bool:
    """Whether every member of the team resolves at least `required_level` on `resource`.

    For a caller that builds something without a request user and hands it to many readers at
    once — an AI-drafted ticket note, a userless precompute. Such a caller cannot honor a
    restriction on one member, so it asks whether any restriction exists at all and leaves the
    data out when one does.

    Deliberately conservative, and for that reason the same answer under both resolution orders:
    one restricting rule makes this False, including where highest-wins resolution would let a
    permissive default outrank it. Erring toward withholding keeps the answer stable when an
    organization moves to most-specific resolution.
    """
    team = Team.objects.select_related("organization").filter(id=team_id).first()
    if team is None:
        return False

    # Resolution reads the rows of the parent of an inheriting resource, never the child's own
    # resource-scope rows, so the parent is what to inspect.
    resource = RESOURCE_INHERITANCE_MAP.get(resource, resource)

    # With no rules in effect, every member sits at the built-in default for the resource.
    if resource in RESOURCES_WITHOUT_RESOURCE_LEVEL_CONTROLS or not team.organization.is_feature_available(
        AvailableFeature.ACCESS_CONTROL
    ):
        return _grants_at_least(resource, default_access_level(resource), required_level)

    rows = list(AccessControl.objects.filter(team_id=team_id, resource=resource, resource_id=None))
    everyone_rows = [row for row in rows if row.organization_member_id is None and row.role_id is None]
    subject_rows = [row for row in rows if row.organization_member_id is not None or row.role_id is not None]

    levels = ordered_access_levels(resource)
    floor = (
        max((row.access_level for row in everyone_rows), key=lambda level: _level_rank(levels, level))
        if everyone_rows
        else default_access_level(resource)
    )
    if not _grants_at_least(resource, floor, required_level):
        return False
    return all(_grants_at_least(resource, row.access_level, required_level) for row in subject_rows)


def object_ids_restricted_from_any_member(
    *, team_id: int, resource: APIScopeObject, required_level: AccessControlLevel
) -> set[str]:
    """Ids of `resource` objects carrying a rule that gives somebody less than `required_level`.

    The object-level counterpart of `every_member_has_resource_access`, for the same kind of
    caller: one that builds something without a request user and hands it to many readers at
    once. It cannot tell those readers apart, so it leaves out every object that any rule
    withholds from any of them.

    Conservative in the same way. One restricting rule on an object is enough to name it, even
    where resolution would let a permissive rule outrank that one, so the answer does not change
    when an organization moves to most-specific resolution.
    """
    team = Team.objects.select_related("organization").filter(id=team_id).first()
    if team is None or not team.organization.is_feature_available(AvailableFeature.ACCESS_CONTROL):
        return set()

    # Object rows are written against the resource itself, never its parent, so an inheriting
    # resource is not mapped here the way a resource-scope lookup maps it.
    satisfying = [
        level for level in ordered_access_levels(resource) if _grants_at_least(resource, level, required_level)
    ]
    restricted = (
        AccessControl.objects.filter(team_id=team_id, resource=resource, resource_id__isnull=False)
        .exclude(access_level__in=satisfying)
        .values_list("resource_id", flat=True)
    )
    return {resource_id for resource_id in restricted if resource_id}


# --- Write API ---


def _validate_target_org(
    *,
    team_id: int,
    organization_member_id: UUID | None,
    role_id: UUID | None,
) -> None:
    """Ensure the rule target (role / organization member) belongs to the
    team's organization.

    Without this check, an org admin who is also a member of another
    organization could inject role or membership UUIDs from that other org
    into rules here — which would then either be silently inert or, worse,
    collide with intra-org IDs in audits and downstream logic.
    """
    if organization_member_id is None and role_id is None:
        return

    organization_id = Team.objects.filter(id=team_id).values_list("organization_id", flat=True).first()
    if organization_id is None:
        # Team doesn't exist — the upstream get_object lookup would have failed already,
        # but be defensive.
        raise InvalidPropertyAccessControlTargetError("Team not found.")

    if organization_member_id is not None:
        if not OrganizationMembership.objects.filter(
            id=organization_member_id, organization_id=organization_id
        ).exists():
            raise InvalidPropertyAccessControlTargetError(
                "organization_member does not belong to this team's organization."
            )

    if role_id is not None:
        if not Role.objects.filter(id=role_id, organization_id=organization_id).exists():
            raise InvalidPropertyAccessControlTargetError("role does not belong to this team's organization.")


def upsert_property_access_control(
    *,
    team_id: int,
    created_by_id: int | None,
    input: contracts.UpsertPropertyAccessControlInput,
) -> contracts.PropertyAccessControlRule:
    """Create or update a single access control rule."""
    prop_def = _get_property_definition(input.property_definition_id, team_id)
    _validate_target_org(
        team_id=team_id,
        organization_member_id=input.organization_member_id,
        role_id=input.role_id,
    )

    # `created_by_id` must only be set on creation — using `defaults` would
    # overwrite the original creator on every update. `create_defaults`
    # (Django 4.2+) is applied only when a new row is inserted.
    rule, _created = PropertyAccessControl.objects.update_or_create(
        team_id=team_id,
        property_definition=prop_def,
        organization_member_id=input.organization_member_id,
        role_id=input.role_id,
        defaults={
            "access_level": input.access_level.value,
        },
        create_defaults={
            "access_level": input.access_level.value,
            "created_by_id": created_by_id,
        },
    )
    return _to_rule(rule)


def delete_property_access_control(
    *,
    team_id: int,
    input: contracts.DeletePropertyAccessControlInput,
) -> None:
    """Delete an override rule. Raises PropertyAccessControlRuleNotFoundError if nothing matched."""
    prop_def = _get_property_definition(input.property_definition_id, team_id)
    _validate_target_org(
        team_id=team_id,
        organization_member_id=input.organization_member_id,
        role_id=input.role_id,
    )

    deleted, _ = PropertyAccessControl.objects.filter(
        team_id=team_id,
        property_definition=prop_def,
        organization_member_id=input.organization_member_id,
        role_id=input.role_id,  # type: ignore
    ).delete()
    if not deleted:
        raise PropertyAccessControlRuleNotFoundError


# --- Object access controls ---


def _to_object_rule(rule: AccessControl) -> contracts.ObjectAccessControlRule:
    assert rule.resource_id is not None
    return contracts.ObjectAccessControlRule(
        id=rule.id,
        resource=rule.resource,
        resource_id=rule.resource_id,
        access_level=rule.access_level,
        organization_member_id=rule.organization_member_id,
        role_id=rule.role_id,
    )


def _validate_object_access_control(
    *, organization_id: UUID, input: contracts.SetObjectAccessControlInput
) -> APIScopeObject:
    resource = input.resource
    if resource not in API_SCOPE_OBJECTS or resource in INTERNAL_API_SCOPE_OBJECTS:
        raise InvalidObjectAccessControlError(f"{resource} is not an access controlled resource.")
    scoped_resource = cast(APIScopeObject, resource)

    if input.access_level is not None:
        levels = ordered_access_levels(scoped_resource)
        if input.access_level not in levels:
            raise InvalidObjectAccessControlError(
                f"Invalid access level for {resource}. Must be one of: {', '.join(levels)}."
            )
        # `ordered_access_levels` can include levels the settings UI never offers for a resource
        # (for example "none" on a project), so the bounds apply here as well as in the API.
        level_index = levels.index(input.access_level)
        if level_index < levels.index(minimum_access_level(scoped_resource)):
            raise InvalidObjectAccessControlError(f"Access level is below the minimum for {resource}.")
        if level_index > levels.index(highest_access_level(scoped_resource)):
            raise InvalidObjectAccessControlError(f"Access level is above the maximum for {resource}.")

    if (
        input.organization_member_id is not None
        and not OrganizationMembership.objects.filter(
            id=input.organization_member_id, organization_id=organization_id
        ).exists()
    ):
        raise InvalidObjectAccessControlError("organization_member does not belong to this team's organization.")
    if (
        input.role_id is not None
        and not Role.objects.filter(id=input.role_id, organization_id=organization_id).exists()
    ):
        raise InvalidObjectAccessControlError("role does not belong to this team's organization.")
    return scoped_resource


def set_object_access_control(
    *,
    team_id: int,
    input: contracts.SetObjectAccessControlInput,
) -> contracts.ObjectAccessControlRule | None:
    """Grant, change, or remove one subject's access to one object.

    This is the programmatic counterpart of the `PUT .../access_controls` endpoint, for product code
    that must keep a rule in step with its own state (for example, the assignee of a work item).
    It writes the rule only. The caller decides whether the actor may change access, and the
    caller owns the reverse write when its state changes again.

    A `UserAccessControl` built before this call still holds its preloaded rows. Build a new one
    or clear its cache before checking the object again in the same request.

    Returns the stored rule, or None when `access_level` is None and the rule was removed.
    """
    team = Team.objects.only("id", "organization_id").get(id=team_id)
    resource = _validate_object_access_control(organization_id=team.organization_id, input=input)
    if input.access_level is None:
        AccessControl.objects.filter(
            team_id=team_id,
            resource=resource,
            resource_id=input.resource_id,
            organization_member_id=input.organization_member_id,
            role_id=cast(UUID | str, input.role_id),
        ).delete()
        return None

    rule, _created = AccessControl.objects.update_or_create(
        team_id=team_id,
        resource=resource,
        resource_id=input.resource_id,
        organization_member_id=input.organization_member_id,
        role_id=cast(UUID | str, input.role_id),
        defaults={"access_level": input.access_level},
        create_defaults={"access_level": input.access_level, "created_by_id": input.created_by_id},
    )
    return _to_object_rule(rule)


# --- Convenience for external callers (avoids importing UUID type at call sites) ---


def available_access_levels() -> list[PropertyAccessLevel]:
    return list(PropertyAccessLevel)


__all__ = [
    "InvalidPropertyAccessControlTargetError",
    "PropertyAccessControlRuleNotFoundError",
    "PropertyAccessLevel",
    "PropertyDefinitionNotFoundError",
    "available_access_levels",
    "delete_property_access_control",
    "get_property_access_state",
    "list_property_access_controls",
    "upsert_property_access_control",
]
