"""
Facade for authz.

The ONLY module other products are allowed to import.
Accept frozen dataclasses, call logic/, return frozen
dataclasses. Never return ORM instances or import DRF.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import overload

from ..logic import spline_reticulators
from ..models import SplineReticulator
from . import contracts
from .enums import Action, Level, SplineStatus, SubjectType


def _to_dto(obj: SplineReticulator) -> contracts.SplineReticulatorDTO:
    return contracts.SplineReticulatorDTO(
        id=obj.id,
        name=obj.name,
        status=SplineStatus(obj.status),
        created_at=obj.created_at,
    )


def create(input: contracts.CreateSplineReticulatorInput) -> contracts.SplineReticulatorDTO:
    obj = spline_reticulators.create_spline_reticulator(team_id=input.team_id, name=input.name)
    return _to_dto(obj)


def list_all() -> list[contracts.SplineReticulatorDTO]:
    return [_to_dto(obj) for obj in spline_reticulators.list_spline_reticulators()]


# In every function below, `subject=None` and `context=None` mean the current request's subject and
# context. Outside a request, such as in a background job, pass both explicitly.


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
    # TODO: implement
    raise NotImplementedError


def permissions(
    *,
    resource: contracts.Resource,
    subject: contracts.Subject | None = None,
    context: contracts.Context | None = None,
) -> frozenset[Action]:
    """Return every action the subject may take on the resource."""
    # TODO: implement
    raise NotImplementedError


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
    # TODO: implement
    raise NotImplementedError


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
    # TODO: implement
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
    # TODO: implement
    raise NotImplementedError
