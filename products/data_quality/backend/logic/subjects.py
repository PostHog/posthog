"""Resolve a check's subject id to something queryable.

The check row carries the subject as a foreign key (``saved_query`` or ``table``); resolution still
goes through the owning product's facade rather than traversing the FK, so model instances never
cross the product boundary. A subject that no longer resolves marks the check orphaned, and the
denormalized name is refreshed on every run so renames self-heal.
"""

from uuid import UUID

from products.data_modeling.backend.facade import api as data_modeling_facade
from products.warehouse_sources.backend.facade import api as warehouse_facade

from ..facade.enums import SubjectType
from .contracts import SubjectRef


def resolve_subject(team_id: int, subject_type: str, subject_uuid: str | UUID) -> SubjectRef:
    """Look the subject up in its owning product. Never raises for a missing subject."""
    kind = SubjectType(subject_type)
    if kind is SubjectType.TABLE:
        return _resolve_table(team_id, subject_uuid)
    return _resolve_view(team_id, subject_uuid)


def _resolve_table(team_id: int, subject_uuid: str | UUID) -> SubjectRef:
    table = warehouse_facade.get_queryable_table(UUID(str(subject_uuid)), team_id)
    if table is None:
        return _missing(SubjectType.TABLE, subject_uuid)
    return SubjectRef(
        subject_type=SubjectType.TABLE,
        subject_uuid=str(subject_uuid),
        name=table.name,
        queryable_name=table.name,
        exists=True,
    )


def _resolve_view(team_id: int, subject_uuid: str | UUID) -> SubjectRef:
    saved_query = data_modeling_facade.get_saved_query_summary(team_id, subject_uuid)
    if saved_query is None:
        return _missing(SubjectType.VIEW, subject_uuid)
    return SubjectRef(
        subject_type=SubjectType.VIEW,
        subject_uuid=str(subject_uuid),
        name=saved_query.name,
        queryable_name=saved_query.name,
        exists=True,
    )


def _missing(kind: SubjectType, subject_uuid: str | UUID) -> SubjectRef:
    return SubjectRef(
        subject_type=kind,
        subject_uuid=str(subject_uuid),
        name="",
        queryable_name="",
        exists=False,
    )
