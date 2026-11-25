"""Access checks for a caller that data quality holds as a `UserAccessControl`.

The caller keeps the `UserAccessControl` because the warehouse facades take it. The checks here go
through the authorization SDK, for the user and the team of that instance.
"""

from typing import TYPE_CHECKING

from posthog.models import User

from products.authorization.backend.facade import api as authorization
from products.authorization.backend.facade.contracts import Resource, Subject
from products.authorization.backend.facade.enums import Action, ResourceType

if TYPE_CHECKING:
    from posthog.models import Team

    from products.access_control.backend.facade.user_access_control import UserAccessControl


def can_access(access: "UserAccessControl", resource_type: ResourceType, action: Action) -> bool:
    """Whether the user of `access` may take `action` on the `resource_type` resources of its team."""
    with authorization.authorization_session():
        # Outside a request, the check then reads the rules that `access` loaded instead of loading them again.
        authorization.reuse_current_rules(access)
        return authorization.check(
            resource=Resource(type=resource_type, project_id=_team(access).pk), action=action, subject=_subject(access)
        )


def can_edit_organization(access: "UserAccessControl") -> bool:
    return authorization.check(
        resource=Resource.organization(_team(access).organization_id), action=Action.EDIT, subject=_subject(access)
    )


def _team(access: "UserAccessControl") -> "Team":
    if access.team is None:
        raise ValueError("A data quality access check needs a UserAccessControl scoped to a team.")
    return access.team


def _subject(access: "UserAccessControl") -> Subject | None:
    # A synthetic principal has no user id. Only a request builds one, and the SDK reads that request's principal.
    user = access.user
    return Subject(user_id=user.pk) if isinstance(user, User) and user.pk is not None else None
