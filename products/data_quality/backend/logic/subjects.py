"""Resolve a check's subject id to something queryable.

The check row carries the subject as a foreign key (``saved_query`` or ``table``); resolution still
goes through the owning product's facade rather than traversing the FK, so model instances never
cross the product boundary. A subject that no longer resolves marks the check orphaned, and the
denormalized name is refreshed on every run so renames self-heal.
"""

from collections.abc import Iterable
from uuid import UUID

from products.data_modeling.backend.facade import api as data_modeling_facade
from products.warehouse_sources.backend.facade import api as warehouse_facade
from products.warehouse_sources.backend.facade.contracts import WAREHOUSE_OBJECT_TABLE, WAREHOUSE_OBJECT_VIEW

from ..facade.enums import SubjectType
from .contracts import SubjectIdentity, SubjectRef

_WAREHOUSE_OBJECT_SUBJECT_TYPES = {
    WAREHOUSE_OBJECT_TABLE: SubjectType.TABLE,
    WAREHOUSE_OBJECT_VIEW: SubjectType.VIEW,
}


def resolve_subject(team_id: int, subject_type: str, subject_uuid: str | UUID) -> SubjectRef:
    """Look the subject up in its owning product. Never raises for a missing subject."""
    kind = SubjectType(subject_type)
    if kind is SubjectType.TABLE:
        return _resolve_table(team_id, subject_uuid)
    return _resolve_view(team_id, subject_uuid)


def resolve_subject_by_name(team_id: int, name: str) -> SubjectRef | None:
    """The subject a query reaches under this name, or None when the name is no warehouse object.

    The inverse of :func:`resolve_subject`, for pinning what a run read while it still names the
    right object. None is not a failure: only warehouse tables and saved queries carry object-level
    access control, so a name that reaches neither has no identity worth recording.
    """
    resolved = warehouse_facade.resolve_object_by_name(team_id, name)
    if resolved is None:
        return None
    kind = _WAREHOUSE_OBJECT_SUBJECT_TYPES[resolved.kind]
    return SubjectRef(
        subject_type=kind,
        subject_uuid=str(resolved.id),
        name=name,
        queryable_name=name,
        exists=True,
    )


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


def resolve_subject_names(team_id: int, subjects: Iterable[SubjectIdentity]) -> dict[SubjectIdentity, str]:
    """The current name of every subject that still resolves, keyed by identity. Two queries.

    Authorization has to read the name the subject carries *now*, because denial is computed from
    the names that exist today. The name denormalized onto a check is only rewritten when the check
    runs, so a subject renamed since would otherwise stop matching its own denial. A subject that no
    longer resolves is absent rather than empty, so a caller can tell the two apart.
    """
    wanted = set(subjects)
    view_ids = [subject.subject_uuid for subject in wanted if subject.subject_type == SubjectType.VIEW]
    table_ids = [UUID(subject.subject_uuid) for subject in wanted if subject.subject_type == SubjectType.TABLE]

    names: dict[SubjectIdentity, str] = {
        SubjectIdentity(subject_type=SubjectType.VIEW.value, subject_uuid=saved_query_id): name
        for saved_query_id, name in data_modeling_facade.saved_query_names(team_id, view_ids).items()
    }
    for table_id, name in warehouse_facade.queryable_table_names(team_id, table_ids).items():
        names[SubjectIdentity(subject_type=SubjectType.TABLE.value, subject_uuid=str(table_id))] = name
    return names


def subject_identity(subject_type: str, subject_uuid: str | UUID) -> SubjectIdentity:
    """The identity of a subject as a row records it, from whichever form the caller holds."""
    return SubjectIdentity(subject_type=str(subject_type), subject_uuid=str(subject_uuid))


def subject_column_type(team_id: int, subject_type: str, subject_uuid: str | UUID, column_name: str) -> str | None:
    """The column's ClickHouse type, or None when the subject or the column cannot be established.

    None is unknown, not "untyped": a view records its columns only once it has run, so a check
    authored against a fresh view has nothing to read here.
    """
    if not column_name:
        return None
    kind = SubjectType(subject_type)
    if kind is SubjectType.TABLE:
        table = warehouse_facade.get_queryable_table(UUID(str(subject_uuid)), team_id)
        columns = table.columns if table else {}
    else:
        columns = data_modeling_facade.get_saved_query_columns(team_id, subject_uuid)
    entry = (columns or {}).get(column_name)
    # A table records either a bare type string (older rows) or a dict keyed "clickhouse", the same
    # two shapes hogql_fields_and_structure_for_columns handles; the saved-query facade already
    # unwrapped a view's entry to the string.
    if isinstance(entry, dict):
        entry = entry.get("clickhouse")
    return entry if isinstance(entry, str) else None


def _missing(kind: SubjectType, subject_uuid: str | UUID) -> SubjectRef:
    return SubjectRef(
        subject_type=kind,
        subject_uuid=str(subject_uuid),
        name="",
        queryable_name="",
        exists=False,
    )
