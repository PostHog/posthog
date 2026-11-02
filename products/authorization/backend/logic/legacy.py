"""Answers checks with the current access rules (`UserAccessControl`), so each decision matches today's."""

from collections.abc import Sequence
from typing import Any, cast

from posthog.models import Team, User
from posthog.scopes import API_SCOPE_OBJECTS, APIScopeObject

from products.access_control.backend.facade.contracts import FallbackParent, ObjectAccessRef
from products.access_control.backend.facade.user_access_control import (
    RESOURCE_FALLBACK_MAP,
    AccessControlLevelResource,
    UserAccessControl,
)

from ..facade.contracts import CheckRequest, Context, Subject
from ..facade.enums import Action, ResourceType
from .session import PrincipalKey, Session, current

# MANAGE_ACCESS reads its level through the "can modify access levels" rule, which also lets
# the creator and project admins in.
RESOURCE_LEVELS: dict[Action, AccessControlLevelResource] = {
    Action.VIEW: "viewer",
    Action.QUERY: "viewer",
    Action.EDIT: "editor",
    Action.DELETE: "editor",
    Action.SHARE: "editor",
    Action.CREATE: "editor",
    Action.MANAGE_ACCESS: "manager",
}

MEMBERSHIP_RESOURCES = frozenset({ResourceType.ORGANIZATION, ResourceType.PROJECT, ResourceType.ROLE})


def check(requests: Sequence[CheckRequest], context: Context | None) -> list[bool]:
    if context is not None and context != Context():
        raise NotImplementedError("The current access rules read no request context.")
    session = current() or Session()
    return [_check(session, request) for request in requests]


def _check(session: Session, request: CheckRequest) -> bool:
    resource, action = request.resource, request.action
    if resource.type in MEMBERSHIP_RESOURCES:
        raise NotImplementedError(f"Checks on {resource.type} resources are not supported yet.")
    level = RESOURCE_LEVELS.get(action)
    if level is None:
        raise ValueError(f"{action} does not apply to {resource.type} resources.")
    # Access rules are scoped to a team, so project_id carries the team id.
    if resource.project_id is None:
        raise ValueError(f"A {resource.type} check needs project_id.")
    scope = _scope(resource.type)
    parent_type = RESOURCE_FALLBACK_MAP.get(scope)
    if resource.id is not None and parent_type and resource.parent is None:
        raise ValueError(
            f"A {resource.type} check needs `parent`, or it skips the parent's rules. "
            f"Use Parent(type=ResourceType.{parent_type.upper()}, id=None) when the object has no parent."
        )
    if resource.parent is not None and resource.parent.type.value != parent_type:
        raise ValueError(f"A {resource.type} falls back to {parent_type}, not {resource.parent.type}.")

    principal = _principal(session, request.subject)
    if principal is None:
        return False
    access = _access(session, principal, resource.project_id)
    if access is None:
        return False

    if resource.id is None:
        if action == Action.MANAGE_ACCESS:
            return access.check_can_modify_access_levels_for_object(cast(Team, access.team))
        return access.check_access_level_for_resource(scope, level)

    ref = ObjectAccessRef(
        resource=scope,
        id=resource.id,
        team_id=resource.project_id,
        created_by_id=resource.created_by_id,
        fallback_parent=(
            FallbackParent(resource=_scope(resource.parent.type), id=resource.parent.id)
            if resource.parent is not None
            else None
        ),
    )
    if action == Action.MANAGE_ACCESS:
        return access.check_can_modify_access_levels_for_ref(ref)
    return access.check_access_level_for_ref(ref, level)


def _scope(resource_type: ResourceType) -> APIScopeObject:
    if resource_type.value not in API_SCOPE_OBJECTS:
        raise ValueError(f"The current access rules have no scope for {resource_type}.")
    return cast(APIScopeObject, resource_type.value)


def _principal(session: Session, subject: Subject | None) -> Any:
    """The user that the current access rules evaluate, or None to deny.

    Without a subject this is the request's user as authentication left it, which can also be a
    share link or a service principal. The rules evaluate it the same way a view does today.
    """
    request_user = session.principal() if session.principal is not None else None
    if subject is None:
        if session.principal is None:
            raise ValueError("Pass a subject. No request is active, so there is no current user.")
        return request_user if getattr(request_user, "is_authenticated", False) else None
    if subject.user_id is None:
        raise NotImplementedError("Only user subjects are supported yet.")
    if isinstance(request_user, User) and request_user.pk == subject.user_id:
        return request_user
    if subject.user_id in session.users:
        return session.users[subject.user_id]
    user = User.objects.filter(pk=subject.user_id).first()
    if session.can_cache():
        session.users[subject.user_id] = user
    return user


def _principal_key(principal: Any) -> PrincipalKey:
    if isinstance(principal, User):
        return ("user", principal.pk)
    return ("object", id(principal))


def _access(session: Session, principal: Any, team_id: int) -> UserAccessControl | None:
    key = _principal_key(principal)
    if key in session.access:
        # v1 keeps one instance per team, sharing the user's membership and roles across them.
        return session.access[key].for_team_ids([team_id]).get(team_id)
    team = Team.objects.filter(pk=team_id).first()
    if team is None:
        return None
    access = UserAccessControl(user=cast(User, principal), team=team)
    if session.can_cache():
        session.access[key] = access
    return access
