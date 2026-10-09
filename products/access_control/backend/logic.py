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


def terraform_account_for_team(team_id: int) -> "User | None":
    """The user whose personal API key Terraform uses to manage this project's access rules, or None
    when Terraform does not manage them. A filter rather than get_or_create_team_extension, so that
    a read on the hot path never inserts a row."""
    config = (
        TeamAccessControlConfig.objects.filter(team_id=team_id, managed_by__isnull=False)
        .select_related("managed_by__user")
        .first()
    )
    return config.managed_by.user if config and config.managed_by else None


def can_write_access_rules(team_id: int, user: "User") -> bool:
    """When Terraform manages the project, only its account may change the rules. The check is on
    the user behind the request, never on a client header, because any client can send any header."""
    terraform_account = terraform_account_for_team(team_id)
    return terraform_account is None or terraform_account.id == user.id


def terraform_managed_team_with_role_rules(role: Role, user: "User") -> "Team | None":
    """A Terraform-managed team where the role has rules and `user` is not the Terraform account,
    else None. AccessControl.role cascades, so deleting the role would remove those rules without
    any rule endpoint running."""
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
