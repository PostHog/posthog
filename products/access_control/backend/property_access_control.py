from __future__ import annotations

import contextlib
from collections.abc import Callable, Iterator
from contextvars import ContextVar
from typing import TYPE_CHECKING, TypeVar
from uuid import UUID

from django.core.signals import request_finished, request_started
from django.db import DatabaseError, connections
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from celery.signals import task_postrun, task_prerun

from posthog.constants import AvailableFeature
from posthog.models import OrganizationMembership
from posthog.models.team import Team

from products.access_control.backend.facade.contracts import PropertyAccessLevel
from products.access_control.backend.models.property_access_control import PropertyAccessControl

from ee.models.rbac.role import RoleMembership

# Scoped memoization for `get_restricted_properties_for_team`. A single request, Celery task,
# or other unit of work can construct many query runners (e.g. a dashboard with N insights),
# each of which would otherwise issue an identical PropertyAccessControl lookup. We cache the
# computed set keyed by (team_id, user_id) for the lifetime of an explicitly-opened scope and
# discard the cache when the scope closes.
#
# The ContextVar defaults to ``None`` which means "no scope active — do not cache". This is
# critical: a thread-lifetime cache on a Celery worker could serve restricted data to a user
# whose access was revoked between tasks. Scopes are opened explicitly at HTTP request
# boundaries (`request_started` / `request_finished`) and Celery task boundaries
# (`task_prerun` / `task_postrun`); callers running outside those boundaries (management
# commands, ad-hoc scripts, code paths we haven't instrumented) simply pay the query cost
# rather than risk stale authorization data.
_restriction_cache_var: ContextVar[dict[tuple[int, int | None], set[tuple[str, int]]] | None] = ContextVar(
    "property_access_restriction_cache", default=None
)


@contextlib.contextmanager
def restriction_cache_scope() -> Iterator[None]:
    """Open a memoization scope for ``get_restricted_properties_for_team``.

    Use this to bracket any non-HTTP, non-Celery code path that calls
    ``get_restricted_properties_for_team`` more than once for the same user
    (e.g. management commands or tests that want the per-request behavior
    without going through the signal plumbing).
    """
    token = _restriction_cache_var.set({})
    try:
        yield
    finally:
        _restriction_cache_var.reset(token)


@receiver(request_started)
@receiver(task_prerun)
def _open_restriction_cache_scope(**_kwargs: object) -> None:
    _restriction_cache_var.set({})


@receiver(request_finished)
@receiver(task_postrun)
def _close_restriction_cache_scope(**_kwargs: object) -> None:
    _restriction_cache_var.set(None)


@receiver(post_save, sender=PropertyAccessControl)
@receiver(post_delete, sender=PropertyAccessControl)
@receiver(post_save, sender=OrganizationMembership)
@receiver(post_delete, sender=OrganizationMembership)
@receiver(post_save, sender=RoleMembership)
@receiver(post_delete, sender=RoleMembership)
def _invalidate_restriction_cache_on_change(**_kwargs: object) -> None:
    # The cached restrictions depend on PropertyAccessControl rules plus the user's organization
    # membership and role memberships. Any change to those rows invalidates the cache for the
    # current scope so subsequent calls within the same request/task see fresh data.
    cache = _restriction_cache_var.get()
    if cache is not None:
        cache.clear()


if TYPE_CHECKING:
    from posthog.models import User

    from products.event_definitions.backend.models.property_definition import PropertyDefinition


# Re-exported for legacy callers; canonical definition lives in facade.contracts.
__all__ = [
    "PropertyAccessLevel",
    "get_default_access_level",
    "get_non_writable_property_names",
    "get_property_access_level",
    "get_restricted_properties_for_team",
    "get_restricted_property_names",
    "is_property_access_control_enabled",
    "strip_restricted_properties",
]


_T = TypeVar("_T")


def _run_with_stale_connection_retry(operation: Callable[[], _T]) -> _T:
    """Run a read-only DB ``operation``, retrying once if a pooled connection is found dead.

    Long-lived async / Temporal workers keep Postgres connections open across queries (pooled via
    pgbouncer). A connection can be recycled or time out while idle and then, on reuse, raise a
    corrupted-protocol error (``lost synchronization with server``) — for property access control
    this surfaces in the HogQL printer's hot path. Evict any unusable connection and retry once on
    a fresh one. If no connection is actually unusable the error is a genuine query failure, so we
    re-raise. Safe because every ``operation`` passed here is a read and thus idempotent.
    """
    try:
        return operation()
    except DatabaseError:
        dead = [conn for conn in connections.all(initialized_only=True) if not conn.is_usable()]
        if not dead:
            raise
        for conn in dead:
            conn.close()
        return operation()


def get_default_access_level() -> PropertyAccessLevel:
    """
    :returns: The default access level for a property
    """
    return PropertyAccessLevel.READ_WRITE


def is_property_access_control_enabled(*, team: Team | None = None, team_id: int | None = None) -> bool:
    if team is None and team_id is not None:
        team = Team.objects.select_related("organization").filter(id=team_id).first()

    if team is None:
        return False

    organization = team.organization
    if organization is None:
        return False  # type: ignore

    return organization.is_feature_available(AvailableFeature.PROPERTY_ACCESS_CONTROL)


def get_property_access_level(
    *,
    property: PropertyDefinition,
    user: User | None,
) -> PropertyAccessLevel:
    """
    Determines the effective access level for a property. If a user is provided, then the user's membership and role are
    used in the calculation for the access level.

    The hierarchy is:
    1. user-specific rules (access control rule has non-null membership foreign key)
    2. role-specific rules (access control rule has non-null role foreign key)
    3. the default rule for the property definition (access control rule has null membership and role foreign keys)

    :param property: The property which we are checking access for.
    :param user: (optional) The user who is attempting to access the property. When not provided the property's default access level is
    returned.

    :returns: The `PropertyAccessLevel` for the property.
    """
    if not is_property_access_control_enabled(team=property.team):
        return get_default_access_level()

    rules = list(
        PropertyAccessControl.objects.filter(property_definition=property).select_related("organization_member", "role")
    )

    if not rules:
        return get_default_access_level()

    membership = None
    user_role_ids: set[int] = set()
    if user is not None:
        membership = (
            OrganizationMembership.objects.filter(
                user=user,
                organization_id=property.team.organization_id,
            )
            .only("id", "level")
            .first()
        )

        if membership is None:
            raise ValueError("user does not have organization membership")

        user_role_ids = set(
            RoleMembership.objects.filter(organization_member=membership).values_list("role_id", flat=True)
        )

    return _resolve_access_level(rules, membership=membership, user_role_ids=user_role_ids)


def strip_restricted_properties(
    properties: dict,
    restricted_names: set[str],
) -> dict:
    """
    Returns a copy of the properties dict with restricted keys removed.
    """
    if not restricted_names:
        return properties
    return {k: v for k, v in properties.items() if k not in restricted_names}


def get_restricted_property_names(
    *,
    team_id: int,
    user: User | None,
    property_type: int,
) -> set[str]:
    """
    Convenience wrapper over get_restricted_properties_for_team that returns just the property names
    restricted for a specific PropertyDefinition.Type (EVENT or PERSON).

    :param team_id: The team whose restrictions to check.
    :param user: The user making the request.
    :param property_type: PropertyDefinition.Type value (e.g., PropertyDefinition.Type.EVENT).
    :returns: Set of restricted property name strings.
    """
    restricted = get_restricted_properties_for_team(team_id=team_id, user=user)
    return {name for name, ptype in restricted if ptype == property_type}


def get_non_writable_property_names(
    *,
    team_id: int,
    user: User | None,
    property_type: int,
) -> set[str]:
    """
    Returns property names where the user does not have write access (i.e., the effective
    access level is READ or NONE).

    :param team_id: The team whose restrictions to check.
    :param user: The user making the request.
    :param property_type: PropertyDefinition.Type value (e.g., PropertyDefinition.Type.PERSON).
    :returns: Set of property name strings that the user cannot write to.
    """
    from posthog.models import OrganizationMembership

    from products.access_control.backend.models.property_access_control import PropertyAccessControl

    # Short-circuit: no PROPERTY_ACCESS_CONTROL means no property access control rules exist
    if not is_property_access_control_enabled(team_id=team_id):
        return set()

    rules = (
        PropertyAccessControl.objects.filter(team_id=team_id)
        .select_related("property_definition", "organization_member", "role")
        .exclude(property_definition__isnull=True)
        .filter(property_definition__type=property_type)
    )

    rules_by_property: dict[UUID, list[PropertyAccessControl]] = {}
    for rule in rules:
        prop_def_id = rule.property_definition_id

        if prop_def_id is None:
            continue

        if prop_def_id not in rules_by_property:
            rules_by_property[prop_def_id] = []
        rules_by_property[prop_def_id].append(rule)

    if len(rules_by_property) == 0:
        return set()

    membership = None
    user_role_ids: set[int] = set()
    if user is not None:
        from posthog.models.team import Team

        org_id = Team.objects.values_list("organization_id", flat=True).get(id=team_id)
        membership = OrganizationMembership.objects.filter(user=user, organization_id=org_id).only("id").first()

        from ee.models.rbac.role import RoleMembership

        user_role_ids = set(RoleMembership.objects.filter(user=user).values_list("role_id", flat=True))

    non_writable: set[str] = set()
    for _prop_def_id, prop_rules in rules_by_property.items():
        prop_def = prop_rules[0].property_definition
        if prop_def is None:
            continue

        level = _resolve_access_level(prop_rules, membership=membership, user_role_ids=user_role_ids)
        if level != PropertyAccessLevel.READ_WRITE:
            non_writable.add(prop_def.name)

    return non_writable


def get_restricted_properties_for_team(
    *,
    team_id: int,
    user: User | None,
) -> set[tuple[str, int]]:
    """
    Returns the set of (property_name, property_type) pairs that are restricted for the given user on the team.
    This is designed to be called once per query to batch-load all restrictions rather than checking one property
    at a time.

    The result is memoized per scope (HTTP request, Celery task, or an explicit
    ``restriction_cache_scope()`` block), keyed by ``(team_id, user_id)``, so that rendering a dashboard
    with many insights doesn't trigger one ``PropertyAccessControl`` lookup per insight. Outside of an
    active scope (e.g. ad-hoc scripts) the lookup runs uncached so we never serve stale authorization data.

    :param team_id: The team whose property restrictions we are checking.
    :param user: (optional) The user making the query. When not provided, only the default (property-level) rules apply.

    :returns: A set of (property_name, property_definition_type) tuples that are restricted.
    """
    cache = _restriction_cache_var.get()
    cache_key = (team_id, user.pk if user is not None else None)
    if cache is not None:
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

    # This DB work runs in the HogQL printer's hot path, which executes inside long-lived async /
    # Temporal workers where a pooled Postgres connection can be recycled or time out while idle
    # between queries. Retry once on a fresh connection if the pooled one is found dead — see
    # `_run_with_stale_connection_retry`.
    restricted = _run_with_stale_connection_retry(
        lambda: _compute_restricted_properties_for_team(team_id=team_id, user=user)
    )

    if cache is not None:
        cache[cache_key] = restricted
    return restricted


def _compute_restricted_properties_for_team(*, team_id: int, user: User | None) -> set[tuple[str, int]]:
    # Short-circuit: no PROPERTY_ACCESS_CONTROL means no property access control rules exist
    if not is_property_access_control_enabled(team_id=team_id):
        return set()

    rules = (
        PropertyAccessControl.objects.filter(team_id=team_id)
        .select_related("property_definition", "organization_member", "role")
        .exclude(property_definition__isnull=True)
    )

    if not rules.exists():
        return set()

    # group rules by property definition
    rules_by_property: dict[UUID, list[PropertyAccessControl]] = {}
    for rule in rules:
        if rule.property_definition_id is None:
            continue

        prop_def_id = rule.property_definition_id
        if prop_def_id not in rules_by_property:
            rules_by_property[prop_def_id] = []
        rules_by_property[prop_def_id].append(rule)

    # resolve the user's membership and roles once
    membership = None
    user_role_ids: set[int] = set()
    if user is not None:
        org_id = Team.objects.values_list("organization_id", flat=True).get(id=team_id)
        membership_qs = OrganizationMembership.objects.filter(
            user=user,
            organization_id=org_id,
        ).only("id", "level")
        membership = membership_qs.first()

        if membership is None:
            raise ValueError("user does not have organization membership")

        user_role_ids = set(
            RoleMembership.objects.filter(organization_member=membership).values_list("role_id", flat=True)
        )

    restricted: set[tuple[str, int]] = set()

    for _prop_def_id, prop_rules in rules_by_property.items():
        prop_def = prop_rules[0].property_definition
        level = _resolve_access_level(
            prop_rules,
            membership=membership,
            user_role_ids=user_role_ids,
        )
        if prop_def is not None and not level.grants_access():
            restricted.add((prop_def.name, prop_def.type))

    return restricted


def _resolve_access_level(
    rules: list[PropertyAccessControl],
    *,
    membership: OrganizationMembership | None,
    user_role_ids: set[int],
) -> PropertyAccessLevel:
    """
    Resolves the effective access level from a set of rules for a single property definition,
    following the hierarchy: user-specific > role-specific > default.

    Org admins bypass member- and role-specific overrides and always get the default access level
    for the property, mirroring the admin bypass in `UserAccessControl.access_level_for_object`.
    """
    # Org admins bypass all access control rules and get full access
    if membership is not None and membership.level >= OrganizationMembership.Level.ADMIN:
        return get_default_access_level()

    # 1. user-specific rule
    if membership is not None:
        for rule in rules:
            if rule.organization_member_id == membership.pk:
                return PropertyAccessLevel(rule.access_level)

    # 2. role-specific rules (most permissive wins)
    role_rules = [r for r in rules if r.role_id is not None and r.role_id in user_role_ids]
    if role_rules:
        for rule in role_rules:
            level = PropertyAccessLevel(rule.access_level)
            if level.grants_access():
                return level
        return PropertyAccessLevel.NONE

    # 3. default rule (null membership and null role)
    for rule in rules:
        if rule.organization_member_id is None and rule.role_id is None:
            return PropertyAccessLevel(rule.access_level)

    return get_default_access_level()
