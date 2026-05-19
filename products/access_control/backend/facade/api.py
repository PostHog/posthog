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

from uuid import UUID

from django.shortcuts import get_object_or_404

from posthog.models import OrganizationMembership, PropertyDefinition, Team

from ee.models.rbac.role import Role

from ..models.property_access_control import PropertyAccessControl
from . import contracts
from .contracts import PropertyAccessLevel


class PropertyDefinitionNotFoundError(Exception):
    """Raised when the target property definition cannot be found for the team."""


class PropertyAccessControlRuleNotFoundError(Exception):
    """Raised when trying to delete a rule that does not exist."""


class InvalidPropertyAccessControlTargetError(Exception):
    """Raised when the rule target (role or organization member) does not
    belong to the same organization as the team."""


# --- Mappers (model -> DTO) ---


def _to_rule(rule: PropertyAccessControl) -> contracts.PropertyAccessControlRule:
    return contracts.PropertyAccessControlRule(
        id=rule.id,
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
    "upsert_property_access_control",
]
