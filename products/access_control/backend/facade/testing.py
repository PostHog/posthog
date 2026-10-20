"""Test-support facade for access_control.

Test suites outside the product plant roles, role members and access control rows. They get
them here instead of importing the models.
"""

from uuid import UUID

from products.access_control.backend.models.access_control import AccessControl
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
