"""
Facade for authorization.

The ONLY module other products are allowed to import.
Accept frozen dataclasses, call logic/, return frozen
dataclasses. Never return ORM instances or import DRF.

Each function raises NotImplementedError until its logic lands.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import TYPE_CHECKING, overload
from uuid import UUID

from posthog.hogql.property_access_types import RestrictedProperty

from ..logic import legacy, lists, session
from . import contracts
from .enums import Action, Level, SubjectType

if TYPE_CHECKING:
    from posthog.user_permissions import UserPermissions

    from products.access_control.backend.facade.user_access_control import UserAccessControl


@contextmanager
def authorization_session() -> Iterator[None]:
    """Share user, project and rule lookups between the checks in the block.

    Every request already runs in a session. Open one in a task or a command that checks many
    resources. It does not bind a current user, so checks in it still pass `subject`.
    """
    with session.scope():
        yield


def reuse_current_rules(
    user_access_control: UserAccessControl, user_permissions: UserPermissions | None = None
) -> None:
    """Let the checks in the current session read the rules and memberships that a view already loaded.

    The current access rules answer every check, so the checks then skip a second load of the same
    rules. It has no effect outside a session, or for rules that no project scopes.
    """
    # TODO: remove after the migration to the SDK. Only views that load UserAccessControl themselves need it.
    legacy.reuse(user_access_control, user_permissions)


def synchronize_organization(organization_id: UUID) -> None:
    """Reconcile the organization's authorization graph with committed database state."""
    raise NotImplementedError


def get_openfga_status() -> contracts.OpenFgaStatus:
    """Return whether OpenFGA is reachable, and the store and authorization model the client uses."""
    raise NotImplementedError


@overload
def check(
    *,
    resource: contracts.Resource,
    action: Action,
    subject: contracts.Subject | None = None,
    context: contracts.Context | None = None,
) -> bool: ...


@overload
def check(
    requests: Sequence[contracts.CheckRequest],
    /,
    *,
    context: contracts.Context | None = None,
) -> list[bool]: ...


def check(
    requests: Sequence[contracts.CheckRequest] | None = None,
    /,
    *,
    resource: contracts.Resource | None = None,
    action: Action | None = None,
    subject: contracts.Subject | None = None,
    context: contracts.Context | None = None,
) -> bool | list[bool]:
    """Return whether the subject may take the action on the resource, or one result per request, in order.

    `subject=None` means the user of the current request. Outside a request, pass `subject`.
    """
    if requests is None:
        if resource is None or action is None:
            raise TypeError("Pass `resource` and `action`, or a sequence of check requests.")
        return legacy.check([contracts.CheckRequest(resource=resource, action=action, subject=subject)], context)[0]
    if resource is not None or action is not None or subject is not None:
        raise TypeError("Pass either a sequence of check requests or `resource` and `action`, not both.")
    return legacy.check(requests, context)


def permissions(
    *,
    resource: contracts.Resource,
    subject: contracts.Subject | None = None,
    context: contracts.Context | None = None,
) -> frozenset[Action]:
    """Return every action the subject may take on the resource."""
    return legacy.permissions(resource, subject, context)


def legacy_access_levels(
    resources: Sequence[contracts.Resource], /, *, subject: contracts.Subject | None = None
) -> list[str | None]:
    """Preserve serialized v1 levels until API consumers switch to allowed actions.

    Results follow input order. Objects are grouped by subject, project and type so a page scans
    its rules once, rather than once per object. Enforcement should use `check` or `permissions`.
    """
    return legacy.access_levels(resources, subject)


def restricted_properties(*, project_id: int, user_id: int | None) -> set[RestrictedProperty]:
    """Property restrictions for a query. An explicit `user_id=None` reads only default rules."""
    return legacy.restricted_properties(project_id, user_id)


def non_writable_property_names(*, project_id: int, user_id: int | None, property_type: int) -> set[str]:
    return legacy.non_writable_property_names(project_id, user_id, property_type)


def person_property_names_with_access_rules(*, project_id: int) -> frozenset[str]:
    return legacy.person_property_names_with_access_rules(project_id)


def blocked_object_ids(*, resource: contracts.Resource, subject: contracts.Subject | None = None) -> frozenset[str]:
    """Explicit denials, including deleted objects whose access rules outlive their rows."""
    return lists.blocked_object_ids(resource, subject)


def list_objects(
    *,
    resource: contracts.Resource,
    action: Action,
    subject: contracts.Subject | None = None,
    context: contracts.Context | None = None,
    limit: int | None = None,
    creator_exempt: bool = False,
) -> contracts.ObjectIds:
    """Return project-scoped IDs for the requested action.

    VIEW and QUERY return an inclusion or exclusion filter for rows. A complete result with
    `excluded=True` allows every ID except those returned. Other actions retain inclusion-only IDs.
    An incomplete result allows nothing. `creator_exempt` requests a creator predicate only when
    the rules permit it.

    The current access rules list only VIEW and QUERY. `resource` names a type and its `project_id`,
    or `ResourceType.PROJECT` and an `organization_id`. A project list without an `organization_id`
    lists the projects of every organization the subject belongs to. VIEW gives the rows of today's list filter,
    which applies object rules to org admins too. QUERY gives the rows the query guard reads, so an
    org admin gets every row. To filter a QuerySet, use `presentation.querysets` instead.
    """
    return lists.list_objects(resource, action, subject, context, limit, creator_exempt)


def principal_user_id(*, subject: contracts.Subject | None = None) -> int | None:
    """Return the id of the user that checks evaluate for the subject, or None when the subject is not a user.

    `subject=None` means the user of the current request.
    """
    return lists.principal_user_id(subject)


def list_subjects(
    *,
    resource: contracts.Resource,
    action: Action,
    subject_type: SubjectType,
    context: contracts.Context | None = None,
) -> list[contracts.Subject]:
    """Return the subjects of `subject_type` that may take the action on the resource."""
    raise NotImplementedError


def write(changes: Sequence[contracts.AddRelationshipRequest | contracts.DeleteRelationshipRequest], /) -> None:
    """Apply the relationship adds and deletes."""
    raise NotImplementedError


def dangerous_query_relation(*, subject: contracts.Subject, resource: contracts.Resource, level: Level) -> bool:
    """Return whether the subject holds the relation `level` on the resource, without evaluating actions or context.

    Use it only in access-rule editors and for debugging. Authorization decisions must use `check`.
    """
    raise NotImplementedError


def dangerous_explain(
    request: contracts.CheckRequest,
    /,
    *,
    context: contracts.Context | None = None,
) -> contracts.Explanation:
    """Return the decision for one check and the path of rules that produced it.

    Use it only in access-rule editors and for debugging. Authorization decisions must use `check`.
    """
    raise NotImplementedError
