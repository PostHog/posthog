"""Answers checks with the current access rules (`UserAccessControl`), so each decision matches today's."""

from collections.abc import Sequence
from typing import Any, cast
from uuid import UUID

from posthog.models import OrganizationMembership, Team, User
from posthog.organization_caching import get_cached_organization_membership
from posthog.scopes import API_SCOPE_OBJECTS, APIScopeObject
from posthog.user_permissions import UserPermissions

from products.access_control.backend.facade import api as access_control_api
from products.access_control.backend.facade.contracts import FallbackParent, ObjectAccessRef
from products.access_control.backend.facade.user_access_control import AccessControlLevelResource, UserAccessControl

from ..facade.contracts import CheckRequest, Context, Resource, Subject
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

_Level = OrganizationMembership.Level
_ADMIN_ACTIONS = dict.fromkeys((Action.EDIT, Action.DELETE, Action.SHARE, Action.MANAGE_ACCESS), _Level.ADMIN)

# JOIN and the staff-only actions have no row, so asking for them raises instead of granting admins.
MEMBERSHIP_LEVELS: dict[ResourceType, dict[Action, OrganizationMembership.Level]] = {
    ResourceType.ORGANIZATION: {
        **_ADMIN_ACTIONS,
        Action.VIEW: _Level.MEMBER,
        Action.CREATE: _Level.ADMIN,
        Action.DELETE: _Level.OWNER,
        Action.MANAGE_OWNERS: _Level.OWNER,
    },
    ResourceType.PROJECT: {**_ADMIN_ACTIONS, Action.VIEW: _Level.MEMBER, Action.CREATE: _Level.ADMIN},
    ResourceType.ROLE: {**_ADMIN_ACTIONS, Action.VIEW: _Level.MEMBER},
}


def check(requests: Sequence[CheckRequest], context: Context | None) -> list[bool]:
    if context is not None and context != Context():
        raise NotImplementedError("The current access rules read no request context.")
    session = current() or Session()
    return [_check(session, request) for request in requests]


def permissions(resource: Resource, subject: Subject | None, context: Context | None) -> frozenset[Action]:
    actions = list(MEMBERSHIP_LEVELS.get(resource.type, RESOURCE_LEVELS))
    results = check([CheckRequest(resource=resource, action=action, subject=subject) for action in actions], context)
    return frozenset(action for action, allowed in zip(actions, results, strict=True) if allowed)


def _check(session: Session, request: CheckRequest) -> bool:
    resource, action = request.resource, request.action
    if resource.type in MEMBERSHIP_LEVELS:
        return _check_membership(session, request)
    level = RESOURCE_LEVELS.get(action)
    if level is None:
        raise ValueError(f"{action} does not apply to {resource.type} resources.")
    # Access rules are scoped to a team, so project_id carries the team id.
    if resource.project_id is None:
        raise ValueError(f"A {resource.type} check needs project_id.")
    scope = _scope(resource.type)

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


def _check_membership(session: Session, request: CheckRequest) -> bool:
    resource, action = request.resource, request.action
    level = MEMBERSHIP_LEVELS[resource.type].get(action)
    if level is None:
        raise ValueError(f"{action} does not apply to {resource.type} resources.")
    if resource.id is None:
        raise ValueError(f"A {resource.type} check needs `id`.")
    if resource.type == ResourceType.ROLE and resource.organization_id is None:
        raise ValueError("A role check needs `organization_id`.")

    principal = _principal(session, request.subject)
    # Only a user holds a membership. The other principals have no organization or project level.
    if not isinstance(principal, User):
        return False

    if resource.type == ResourceType.PROJECT:
        return _check_project(session, principal, int(resource.id), action, level)
    if resource.type == ResourceType.ROLE:
        organization_id = cast(UUID, resource.organization_id)
        if not access_control_api.role_belongs_to_organization(
            role_id=UUID(resource.id), organization_id=organization_id
        ):
            return False
    else:
        organization_id = UUID(resource.id)
    membership = get_cached_organization_membership(organization_id, principal)
    return membership is not None and membership.level >= level


def _check_project(
    session: Session, user: User, project_id: int, action: Action, level: OrganizationMembership.Level
) -> bool:
    access = _access(session, user, project_id)
    if access is None:
        return False
    team = cast(Team, access.team)
    if action == Action.MANAGE_ACCESS:
        return access.check_can_modify_access_levels_for_object(team)
    user_level = _user_permissions(session, user).team(team).effective_membership_level
    return user_level is not None and user_level >= level


def _user_permissions(session: Session, user: User) -> UserPermissions:
    if user.pk in session.permissions:
        return session.permissions[user.pk]
    permissions = UserPermissions(user)
    if session.can_cache():
        session.permissions[user.pk] = permissions
    return permissions


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
