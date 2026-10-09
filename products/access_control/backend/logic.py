"""
Business logic for access_control.

Validation, calculations, business rules, ORM queries.
Called by facade/api.py.
"""

from typing import TYPE_CHECKING

from products.access_control.backend.models.access_control import AccessControl
from products.access_control.backend.models.role import Role
from products.access_control.backend.models.team_access_control_config import TeamAccessControlConfig

if TYPE_CHECKING:
    from posthog.models.team.team import Team
    from posthog.models.user import User


def managed_access_config(team_id: int) -> TeamAccessControlConfig | None:
    """The team's config while an account manages its access rules, else None. A filter rather than
    get_or_create_team_extension, so that a read on the hot path never inserts a row."""
    return (
        TeamAccessControlConfig.objects.filter(team_id=team_id, managed_by__isnull=False)
        .select_related("managed_by__user")
        .first()
    )


def can_write_access_rules(config: TeamAccessControlConfig | None, user: "User") -> bool:
    """Only the managing account may change the rules of a managed team. The check is on the user
    behind the request, never on a client header, because any client can send any header."""
    return config is None or config.managed_by is None or config.managed_by.user_id == user.id


def managed_team_blocking_role_delete(role: Role, user: "User") -> "Team | None":
    """A managed team where the role has rules and `user` is not its managing account, else None.
    AccessControl.role cascades, so deleting the role would remove those rules without any rule
    endpoint running."""
    config = (
        TeamAccessControlConfig.objects.filter(
            managed_by__isnull=False,
            team_id__in=AccessControl.objects.filter(role=role).values("team_id"),
        )
        .exclude(managed_by__user_id=user.id)
        .select_related("team")
        .first()
    )
    return config.team if config else None
