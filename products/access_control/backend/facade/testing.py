"""Test-support facade for access_control.

Test suites outside the product plant roles, role members, access control rows and property
access control rows. They get
them here instead of importing the models.
"""

from uuid import UUID

from products.access_control.backend.models.access_control import AccessControl
from products.access_control.backend.models.property_access_control import PropertyAccessControl
from products.access_control.backend.models.role import Role, RoleMembership


def create_role(*, organization_id: UUID, name: str) -> UUID:
    return Role.objects.create(organization_id=organization_id, name=name).id


def add_role_member(*, role_id: UUID, user_id: int) -> UUID:
    """Put one user in the role.

    The row carries no organization member, which is the shape `valid_for_authorization`
    always keeps. A test that needs the other shape names the membership.
    """
    return RoleMembership.objects.create(role_id=role_id, user_id=user_id).id


def create_access_control(
    *,
    team_id: int,
    resource: str,
    access_level: str,
    resource_id: str | None = None,
    organization_member_id: UUID | None = None,
    role_id: UUID | None = None,
) -> UUID:
    """One access control row, as stored.

    `set_object_access_control` is the production door, and it always needs a subject. A row
    with no member and no role sets the level everyone starts from, which only a fixture writes
    directly.
    """
    return AccessControl.objects.create(
        team_id=team_id,
        resource=resource,
        resource_id=resource_id,
        access_level=access_level,
        organization_member_id=organization_member_id,
        role_id=role_id,
    ).id


def delete_access_control(*, team_id: int, access_control_id: UUID) -> None:
    """Delete one access control row, signals and all, as the production delete does."""
    AccessControl.objects.get(id=access_control_id, team_id=team_id).delete()


def remove_role_member(*, organization_id: UUID, role_membership_id: UUID) -> None:
    RoleMembership.objects.get(id=role_membership_id, role__organization_id=organization_id).delete()


def create_property_access_control(
    *,
    team_id: int,
    property_definition_id: UUID,
    access_level: str,
    organization_member_id: UUID | None = None,
    role_id: UUID | None = None,
) -> UUID:
    return PropertyAccessControl.objects.create(
        team_id=team_id,
        property_definition_id=property_definition_id,
        access_level=access_level,
        organization_member_id=organization_member_id,
        role_id=role_id,
    ).id


def delete_property_access_control_rule(*, team_id: int, property_access_control_id: UUID) -> None:
    PropertyAccessControl.objects.get(id=property_access_control_id, team_id=team_id).delete()
