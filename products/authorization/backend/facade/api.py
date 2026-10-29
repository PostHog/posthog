"""
Facade for authorization.

The ONLY module other products are allowed to import.
Accept frozen dataclasses, call logic/, return frozen
dataclasses. Never return ORM instances or import DRF.

Each function raises NotImplementedError until its logic lands.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import overload
from uuid import UUID

from . import contracts
from .enums import Action, Level, SubjectType


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
    """Return whether the subject may take the action on the resource, or one result per request, in order."""
    raise NotImplementedError


def permissions(
    *,
    resource: contracts.Resource,
    subject: contracts.Subject | None = None,
    context: contracts.Context | None = None,
) -> frozenset[Action]:
    """Return every action the subject may take on the resource."""
    raise NotImplementedError


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
    """
    raise NotImplementedError


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
