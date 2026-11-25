"""Activity-log receiver for access control rules.

``ModelActivityMixin`` emits ``model_activity_signal`` when a rule is saved or deleted. This
persists who granted, changed, or removed access. Registered from ``apps.ready()``.
"""

import dataclasses
from collections import defaultdict
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Optional, cast
from uuid import UUID

from posthog.dataclasses import frozen
from posthog.models import Team, User
from posthog.models.activity_logging.activity_log import (
    ActivityContextBase,
    Change,
    Detail,
    LogActivityEntry,
    changes_between,
    log_activity,
)
from posthog.models.signals import model_activity_signal, mutable_receiver
from posthog.scopes.catalog import APIScopeObject

from products.access_control.backend.facade.object_names import has_own_object_visibility, resolve_object_names
from products.access_control.backend.facade.user_access_control import resource_to_display_name
from products.access_control.backend.models.access_control import AccessControl
from products.access_control.backend.models.role import Role


@dataclasses.dataclass(frozen=True)
class AccessControlContext(ActivityContextBase):
    resource: str
    resource_id: str | None
    resource_name: str | None
    access_level: str
    role_id: str | None
    role_name: str | None
    organization_member_id: str | None


@frozen
class AccessRuleObject:
    resource: str
    resource_id: str


@frozen
class AccessRuleNames:
    objects: dict[AccessRuleObject, str]
    roles: dict[UUID, str]


def _resolve_object_names(*, team: Team, object_ids: dict[str, set[str]]) -> dict[AccessRuleObject, str]:
    objects: dict[AccessRuleObject, str] = {}
    for resource, ids in object_ids.items():
        if resource == "project":
            # A project rule points at the team that owns the rule
            if str(team.pk) in ids:
                objects[AccessRuleObject(resource=resource, resource_id=str(team.pk))] = team.name
            continue
        if has_own_object_visibility(resource):
            # Every reader of the activity log sees access rule rows, so a name the product hides from some
            # members stays out of them
            continue
        for resource_id, resolved in resolve_object_names(resource, sorted(ids), team.pk).items():
            if resolved.name:
                objects[AccessRuleObject(resource=resource, resource_id=resource_id)] = str(resolved.name)
    return objects


def resolve_target_names(
    *, team: Team, objects: Iterable[AccessRuleObject], role_ids: Iterable[UUID]
) -> AccessRuleNames:
    """Look up display names with one query per resource type and one for roles.

    A name that is not found is left out, and the entry shows the id instead. Members are never named:
    every reader of the activity log sees these rows, and an organization can hide its members from
    each other.
    """
    object_ids: dict[str, set[str]] = defaultdict(set)
    for target in objects:
        object_ids[target.resource].add(target.resource_id)
    wanted_role_ids = set(role_ids)
    roles: dict[UUID, str] = {}
    if wanted_role_ids:
        roles = dict(
            Role.objects.filter(organization_id=team.organization_id, id__in=wanted_role_ids).values_list("id", "name")
        )
    return AccessRuleNames(objects=_resolve_object_names(team=team, object_ids=object_ids), roles=roles)


def resolve_access_rule_names(*, team: Team, rules: Iterable[AccessControl]) -> AccessRuleNames:
    rules = list(rules)
    return resolve_target_names(
        team=team,
        objects=[
            AccessRuleObject(resource=rule.resource, resource_id=rule.resource_id) for rule in rules if rule.resource_id
        ],
        role_ids=[rule.role_id for rule in rules if rule.role_id],
    )


_batch_names: ContextVar[AccessRuleNames | None] = ContextVar("access_rule_batch_names", default=None)


@contextmanager
def access_rule_names_for_batch(
    *, team: Team, objects: Iterable[AccessRuleObject], role_ids: Iterable[UUID]
) -> Iterator[None]:
    """Resolve names once for rules that are saved or deleted one at a time inside the block.

    Each save sends its own activity signal, so without this every rule looks up its names again.
    Pass the objects and roles of every rule the block writes: a rule that is missing gets ids in its entry.
    """
    token = _batch_names.set(resolve_target_names(team=team, objects=objects, role_ids=role_ids))
    try:
        yield
    finally:
        _batch_names.reset(token)


def access_rule_display_name(rule: AccessControl, names: AccessRuleNames) -> str:
    resource_label = rule.resource.replace("_", " ")
    if rule.resource_id is None:
        target = f"all {resource_to_display_name(cast(APIScopeObject, rule.resource))}"
    elif resource_name := names.objects.get(AccessRuleObject(resource=rule.resource, resource_id=rule.resource_id)):
        target = f'{resource_label} "{resource_name}"'
    else:
        target = f"{resource_label} {rule.resource_id}"

    if rule.role_id:
        role_name = names.roles.get(rule.role_id)
        role = f'role "{role_name}"' if role_name else f"role {rule.role_id}"
        return f"access rule for {role} on {target}"
    if rule.organization_member_id:
        return f"access rule for a member on {target}"
    return f"default access rule on {target}"


def get_access_control_log_entry(
    *,
    before_update: Optional[AccessControl],
    after_update: Optional[AccessControl],
    activity: str,
    user: Optional[User],
    was_impersonated: bool = False,
    names: AccessRuleNames | None = None,
) -> LogActivityEntry | None:
    rule = after_update or before_update
    if rule is None:
        return None
    if names is None:
        names = _batch_names.get()
    if names is None:
        names = resolve_access_rule_names(team=rule.team, rules=[rule])

    if activity == "created":
        changes = [Change(type="AccessControl", field="access_level", action="created", after=rule.access_level)]
    elif activity == "deleted":
        changes = [Change(type="AccessControl", field="access_level", action="deleted", before=rule.access_level)]
    else:
        changes = changes_between("AccessControl", previous=before_update, current=after_update)

    return LogActivityEntry(
        organization_id=rule.team.organization_id,
        team_id=rule.team_id,
        user=user,
        was_impersonated=was_impersonated,
        item_id=rule.id,
        scope="AccessControl",
        activity=activity,
        detail=Detail(
            name=access_rule_display_name(rule, names),
            changes=changes,
            context=AccessControlContext(
                resource=rule.resource,
                resource_id=rule.resource_id,
                resource_name=(
                    names.objects.get(AccessRuleObject(resource=rule.resource, resource_id=rule.resource_id))
                    if rule.resource_id
                    else None
                ),
                access_level=rule.access_level,
                role_id=str(rule.role_id) if rule.role_id else None,
                role_name=names.roles.get(rule.role_id) if rule.role_id else None,
                organization_member_id=str(rule.organization_member_id) if rule.organization_member_id else None,
            ),
        ),
    )


@mutable_receiver(model_activity_signal, sender=AccessControl)
def handle_access_control_change(
    sender: type,
    scope: str,
    before_update: Optional[AccessControl],
    after_update: Optional[AccessControl],
    activity: str,
    user: Optional[User],
    was_impersonated: bool = False,
    **kwargs: Any,
) -> None:
    entry = get_access_control_log_entry(
        before_update=before_update,
        after_update=after_update,
        activity=activity,
        user=user,
        was_impersonated=was_impersonated,
    )
    if entry is not None:
        log_activity(**entry)
