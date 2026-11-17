"""Answers lists with the current access rules (`UserAccessControl`), so each list matches today's list filter."""

from typing import Any, cast

from posthog.models import Organization, User

from products.access_control.backend.facade.user_access_control import (
    RESOURCE_FALLBACK_MAP,
    UserAccessControl,
    visible_teams_for_user,
)

from ..facade.contracts import Context, ObjectIds, Resource, Subject
from ..facade.enums import Action, ResourceType
from .legacy import (
    MEMBERSHIP_LEVELS,
    _access,
    _check_project,
    _Level,
    _principal,
    _principal_key,
    _scope,
    _user_permissions,
)
from .session import Session, current

READ_ACTIONS = frozenset({Action.VIEW, Action.QUERY})

_NOTHING = ObjectIds(ids=frozenset(), complete=True)
_EVERYTHING = ObjectIds(ids=frozenset(), complete=True, excluded=True)


def list_objects(
    resource: Resource,
    action: Action,
    subject: Subject | None,
    context: Context | None,
    limit: int | None,
    creator_exempt: bool,
) -> ObjectIds:
    if context is not None and context != Context():
        raise NotImplementedError("The current access rules read no request context.")
    if limit is not None and limit < 1:
        raise ValueError("`limit` must be positive.")
    if action not in READ_ACTIONS:
        raise NotImplementedError("The current access rules list objects only for VIEW and QUERY.")
    # TODO: list types whose objects fall back to a parent, such as a warehouse table to its source.
    # A list reads only each object's own rules, so it would miss a denial on the parent.
    if resource.type.value in RESOURCE_FALLBACK_MAP:
        raise NotImplementedError(
            f"The SDK cannot list {resource.type} yet, because its objects fall back to a parent."
        )
    session = current() or Session()
    if resource.type == ResourceType.PROJECT:
        result = _list_projects(session, resource, action, subject)
    else:
        result = _list_project_objects(session, resource, action, subject, creator_exempt)
    if limit is not None and len(result.ids) > limit:
        return ObjectIds(ids=frozenset(), complete=False)
    return result


def principal_user_id(subject: Subject | None) -> int | None:
    principal = _principal(current() or Session(), subject)
    return principal.pk if isinstance(principal, User) else None


def _list_project_objects(
    session: Session, resource: Resource, action: Action, subject: Subject | None, creator_exempt: bool
) -> ObjectIds:
    principal = _principal(session, subject)
    access = _list_access(session, resource, principal)
    if access is None:
        return _NOTHING
    # Only a project member lists its objects, as `check` and a view's permission class require.
    if not isinstance(principal, User) or not _check_project(
        session, principal, cast(int, resource.project_id), Action.VIEW, _Level.MEMBER
    ):
        return _NOTHING
    # The query guard reads every object for an org admin. Lists apply the object rules to them,
    # unless the call site asks for every row with `include_all_if_admin`.
    access_filter = access.list_access_filter(_scope(resource.type), include_all_if_admin=action == Action.QUERY)
    if access_filter is None:
        return _EVERYTHING
    if access_filter.only_allowed:
        ids, excluded = access_filter.allowed_ids, False
    else:
        ids, excluded = access_filter.blocked_ids, True
    exempt = creator_exempt and (bool(ids) or not excluded)
    return ObjectIds(
        ids=ids,
        complete=True,
        excluded=excluded,
        creator_exempt=exempt,
        creator_user_id=principal.pk if exempt else None,
    )


def _list_projects(session: Session, resource: Resource, action: Action, subject: Subject | None) -> ObjectIds:
    if action != Action.VIEW:
        raise NotImplementedError("The current access rules list projects only for VIEW.")
    principal = _principal(session, subject)
    access = _list_access(session, resource, principal)
    if access is None:
        return _NOTHING
    organization = Organization.objects.filter(pk=resource.organization_id).first()
    if organization is None:
        return _NOTHING
    teams = visible_teams_for_user(organization, access, _user_permissions(session, cast(User, principal)))
    return ObjectIds(ids=frozenset(str(team_id) for team_id in teams.values_list("pk", flat=True)), complete=True)


def _list_access(session: Session, resource: Resource, principal: Any) -> UserAccessControl | None:
    """The rules a list of `resource` reads: its project's rules, or its organization's for a project list."""
    if resource.id is not None:
        raise ValueError("A list takes a resource type, so `resource` has no `id`.")
    if resource.type == ResourceType.PROJECT:
        if resource.organization_id is None:
            raise ValueError("A project list needs organization_id.")
        # Only a user holds a membership, so the other principals see no project.
        if not isinstance(principal, User):
            return None
        return _organization_access(session, principal, str(resource.organization_id))
    if resource.type in MEMBERSHIP_LEVELS:
        raise ValueError(f"The current access rules do not list {resource.type} resources.")
    if resource.project_id is None:
        raise ValueError(f"A {resource.type} list needs project_id.")
    if principal is None:
        return None
    return _access(session, principal, resource.project_id)


def _organization_access(session: Session, user: User, organization_id: str) -> UserAccessControl:
    access = session.access.get(_principal_key(user))
    # A project list reads the organization's rules, which an instance for any of its teams already holds.
    if access is not None and access.team is not None and str(access.team.organization_id) == organization_id:
        return access
    return UserAccessControl(user=user, organization_id=organization_id)
