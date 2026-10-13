"""Derive an `AccessFilter` from the legacy access-control rows.

Same inputs and same outcome as `filters.filters`, the OpenFGA engine, so the rollout can
run either one and the enforcement adapters never know which.

The shape mirrors the OpenFGA engine: only objects with a rule of their own can differ from the
resource level, so those are resolved one by one and the rest follow the resource level.
"""

from collections.abc import Sequence
from typing import cast

from posthog.models import Team, User
from posthog.scopes import APIScopeObject

from products.access_control.backend.facade.contracts import ObjectAccessRef
from products.access_control.backend.facade.user_access_control import AccessControlLevel, UserAccessControl

from ..facade.contracts import AccessFilter, Resource, Subject
from ..facade.enums import Action, FilterKind
from . import authorization

# Above this many ids the filter is not worth inlining into a query, so the subject fails closed.
# OpenFGA's ListObjects cap is 1000; the same ceiling keeps both engines interchangeable.
MAX_IDS = 1000

ACTION_LEVEL: dict[Action, AccessControlLevel] = {
    Action.VIEW: "viewer",
    Action.LIST: "viewer",
    Action.QUERY: "viewer",
    Action.EDIT: "editor",
    Action.DELETE: "editor",
    Action.MANAGE_ACCESS: "manager",
}


def filters(
    resources: Sequence[Resource],
    action: Action,
    subject: Subject | None,
    creator_exempt: bool,
    user_access_control: UserAccessControl | None = None,
) -> list[AccessFilter]:
    """One filter per resource, in order. Resources in the same project share one preload of the rules.

    `user_access_control` is the request's preload, when the caller has one. Reusing it costs no query.
    """
    authorization.actor_key(subject)
    assert subject is not None and subject.user_id is not None
    level = ACTION_LEVEL.get(action)
    if level is None:
        raise NotImplementedError(f"The legacy rules have no level for action {action.value}.")
    access_by_team: dict[int, UserAccessControl] = {}
    if user_access_control is not None and user_access_control.team is not None:
        if user_access_control.user.pk != subject.user_id:
            raise ValueError("The preloaded access control belongs to another user")
        access_by_team[user_access_control.team.id] = user_access_control
    user: User | None = None
    results: list[AccessFilter] = []
    for resource in resources:
        team_id = authorization.project_id(resource)
        if team_id is None:
            raise ValueError("A filter is scoped to a project; set resource.project_id.")
        if team_id not in access_by_team:
            user = user or User.objects.get(pk=subject.user_id)
            access_by_team[team_id] = UserAccessControl(user=user, team=Team.objects.get(pk=team_id))
        results.append(_filter(access_by_team[team_id], team_id, resource, action, level, creator_exempt))
    return results


def _filter(
    access: UserAccessControl,
    team_id: int,
    resource: Resource,
    action: Action,
    level: AccessControlLevel,
    creator_exempt: bool,
) -> AccessFilter:
    def build(kind: FilterKind, ids: frozenset[str] = frozenset(), *, complete: bool = True) -> AccessFilter:
        return AccessFilter(
            resource_type=resource.type,
            action=action,
            kind=kind,
            ids=ids,
            creator_exempt=creator_exempt and kind != FilterKind.ALL,
            complete=complete,
        )

    if access.is_organization_admin or not access.access_controls_supported:
        return build(FilterKind.ALL)

    scope = cast(APIScopeObject, resource.type.value)
    with_rule = access.object_ids_with_rules(scope)
    if len(with_rule) > MAX_IDS:
        return build(FilterKind.NONE, complete=False)
    allowed = {
        id: access.check_access_level_for_ref(
            ObjectAccessRef(resource=scope, id=id, team_id=team_id, created_by_id=None), level
        )
        for id in with_rule
    }

    if access.check_access_level_for_resource(scope, level):
        denied = frozenset(id for id, ok in allowed.items() if not ok)
        return build(FilterKind.EXCEPT, denied) if denied else build(FilterKind.ALL)
    granted = frozenset(id for id, ok in allowed.items() if ok)
    return build(FilterKind.ONLY, granted) if granted else build(FilterKind.NONE)
