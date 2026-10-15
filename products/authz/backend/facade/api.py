"""
Facade for authz.

The ONLY module other products are allowed to import.
Accept frozen dataclasses, call logic/, return frozen
dataclasses. Never return ORM instances or import DRF.
"""

from __future__ import annotations

from collections.abc import Sequence
from contextlib import AbstractContextManager
from typing import overload
from uuid import UUID

from ..logic import authorization, openfga_status, request_context, rollout, synchronization
from . import (
    contracts,
    synchronization as sync_scheduling,
)
from .enums import Action, Level, SubjectType


def authorization_session() -> AbstractContextManager[None]:
    """Reuse legacy lookups within one request without caching OpenFGA decisions."""
    return request_context.authorization_session()


def synchronize_organization(organization_id: UUID) -> None:
    """Reconcile the organization's dashboard authorization graph with committed database state."""
    synchronization.synchronize_organization(organization_id)


def guest_mode_active(organization_id: UUID) -> bool:
    """Return whether guest rules apply in the organization. Guests act as members when they do not."""
    return rollout.organization_variant(organization_id) == "v2"


def schedule_organization_sync(organization_id: UUID) -> None:
    """Queue a sync of the organization's authorization graph after the current transaction commits.

    Call it after a write that skips model signals, such as a queryset update.
    """
    sync_scheduling.schedule_organization_sync(organization_id)


def get_openfga_status() -> contracts.OpenFgaStatus:
    """Return whether OpenFGA is reachable, and the store and authorization model the client uses."""
    return openfga_status.get_openfga_status()


# Request-context binding is not wired yet, so checks require an explicit user subject.


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
    """Return whether the subject may take the action on the resource, or one result per request, in order."""
    if requests is not None:
        if resource is not None or action is not None or subject is not None:
            raise ValueError("Pass either a batch or a single resource, action, and subject")
        return rollout.check(requests, context)
    if resource is None or action is None:
        raise ValueError("Provide a resource and action")
    return rollout.check([contracts.CheckRequest(resource=resource, action=action, subject=subject)], context)[0]


def permissions(
    *,
    resource: contracts.Resource,
    subject: contracts.Subject | None = None,
    context: contracts.Context | None = None,
) -> frozenset[Action]:
    """Return every action the subject may take on the resource."""
    return rollout.permissions(resource, subject, context)


def list_resources(
    *,
    resource: contracts.Resource,
    action: Action,
    subject: contracts.Subject | None = None,
    context: contracts.Context | None = None,
    limit: int | None = None,
) -> contracts.ResourceIds:
    """Return the ids of `resource.type` resources in its project or organization that the subject may take the action on.

    Apply the ids to your own query, for example `qs.filter(pk__in=result.ids)`. When `complete` is False the set
    was capped, so fail closed and return nothing.
    """
    return rollout.list_resources(resource, action, subject, context, limit)


def list_subjects(
    *,
    resource: contracts.Resource,
    action: Action,
    subject_type: SubjectType,
    context: contracts.Context | None = None,
) -> list[contracts.Subject]:
    """Return the subjects of `subject_type` that may take the action on the resource."""
    # TODO: implement
    raise NotImplementedError


def write(changes: Sequence[contracts.AddRelationshipRequest | contracts.DeleteRelationshipRequest], /) -> None:
    """Apply the relationship adds and deletes."""
    # TODO: implement
    raise NotImplementedError


def dangerous_query_relation(*, subject: contracts.Subject, resource: contracts.Resource, level: Level) -> bool:
    """Return whether the subject holds the relation `level` on the resource, without evaluating actions or context.

    Use it only in access-rule editors and for debugging. Authorization decisions must use `check`.
    """
    return authorization.query_relation(resource, subject, level)


def dangerous_explain(
    request: contracts.CheckRequest,
    /,
    *,
    context: contracts.Context | None = None,
) -> contracts.Explanation:
    """Return the decision for one check and the path of rules that produced it.

    Use it only in access-rule editors and for debugging. Authorization decisions must use `check`.
    """
    # TODO: implement
    raise NotImplementedError
