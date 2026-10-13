"""Resolve a check's subject id to something queryable.

The check row carries the subject as a foreign key (``saved_query``, ``table`` or ``metric``); resolution still
goes through the owning product's facade rather than traversing the FK, so model instances never
cross the product boundary. A subject that no longer resolves marks the check orphaned, and the
denormalized name is refreshed on every run so renames self-heal.
"""

from collections.abc import Collection
from uuid import UUID

from posthog.schema import DatabaseSerializedFieldType

from products.data_catalog.backend.facade import api as data_catalog_facade
from products.data_catalog.backend.facade.enums import HOGQL_DEFINITION_KIND
from products.data_modeling.backend.facade import api as data_modeling_facade
from products.warehouse_sources.backend.facade import api as warehouse_facade
from products.warehouse_sources.backend.facade.contracts import WAREHOUSE_OBJECT_TABLE, WAREHOUSE_OBJECT_VIEW

from ..facade.contracts import MetricSubject, SelectableSubject
from ..facade.enums import SubjectType
from . import posthog_tables
from .contracts import SubjectRef

_WAREHOUSE_OBJECT_SUBJECT_TYPES = {
    WAREHOUSE_OBJECT_TABLE: SubjectType.TABLE,
    WAREHOUSE_OBJECT_VIEW: SubjectType.VIEW,
}


def resolve_subject(team_id: int, subject_type: str, subject_uuid: str | UUID) -> SubjectRef:
    """Look the subject up in its owning product. Never raises for a missing subject."""
    kind = SubjectType(subject_type)
    if kind is SubjectType.TABLE:
        return _resolve_table(team_id, subject_uuid)
    if kind is SubjectType.METRIC:
        return _resolve_metric(team_id, subject_uuid)
    if kind is SubjectType.POSTHOG_TABLE:
        return _resolve_posthog_table(subject_uuid)
    return _resolve_view(team_id, subject_uuid)


def _resolve_posthog_table(subject_uuid: str | UUID) -> SubjectRef:
    entry = posthog_tables.by_id(subject_uuid)
    if entry is None:
        return _missing(SubjectType.POSTHOG_TABLE, subject_uuid)
    return SubjectRef(
        subject_type=SubjectType.POSTHOG_TABLE,
        subject_uuid=str(entry.id),
        name=entry.name,
        queryable_name=entry.name,
        exists=True,
        time_column=entry.time_column,
    )


def unqueryable_table_ids(team_id: int) -> set[UUID]:
    """The tables the normal HogQL database leaves out, so no check should name one.

    A direct-access table is absent from the database build, so a check on it errors on every run.
    A materialized view's backing table answers to the view's own name, so a check on it reports
    against the wrong subject instead.
    """
    excluded = set(data_modeling_facade.backing_table_ids_by_saved_query(team_id))
    excluded.update(warehouse_facade.direct_access_table_ids(team_id))
    return excluded


def selectable_subjects(team_id: int, kinds: Collection[SubjectType]) -> list[SelectableSubject]:
    """Everything in this team a check can be authored on, of the kinds asked for.

    The catalog, not the gate: narrowing it to what the caller may read is the caller's job.
    """
    subjects: list[SelectableSubject] = []
    if SubjectType.TABLE in kinds:
        excluded_table_ids = unqueryable_table_ids(team_id)
        columns_by_id = warehouse_facade.all_queryable_table_columns(team_id)
        subjects.extend(
            SelectableSubject(
                subject_type=SubjectType.TABLE,
                id=str(table_id),
                name=name,
                columns=columns_by_id.get(table_id) or {},
            )
            for table_id, name in warehouse_facade.all_queryable_table_names(team_id).items()
            if table_id not in excluded_table_ids
        )
    if SubjectType.VIEW in kinds:
        columns_by_id = data_modeling_facade.all_saved_query_columns(team_id)
        subjects.extend(
            SelectableSubject(
                subject_type=SubjectType.VIEW,
                id=saved_query_id,
                name=name,
                columns=columns_by_id.get(saved_query_id) or {},
            )
            for saved_query_id, name in data_modeling_facade.all_saved_query_names(team_id).items()
        )
    if SubjectType.POSTHOG_TABLE in kinds:
        subjects.extend(
            SelectableSubject(
                subject_type=SubjectType.POSTHOG_TABLE,
                id=str(entry.id),
                name=entry.name,
                time_column=entry.time_column,
                columns=entry.columns,
            )
            for entry in posthog_tables.TABLES
        )
    if SubjectType.METRIC in kinds:
        subjects.extend(
            SelectableSubject(
                subject_type=SubjectType.METRIC,
                id=str(metric.id),
                name=metric.name,
                display_name=metric.display_name,
            )
            for metric in testable_metric_subjects(team_id)
        )
    return sorted(subjects, key=lambda subject: (subject.subject_type, subject.name))


def testable_metric_subjects(team_id: int) -> list[MetricSubject]:
    return [
        MetricSubject(id=metric.id, name=metric.name, display_name=metric.display_name)
        for metric in data_catalog_facade.live_metric_summaries(team_id)
        if metric.definition_kind == HOGQL_DEFINITION_KIND
    ]


def _resolve_metric(team_id: int, subject_uuid: str | UUID) -> SubjectRef:
    identifier = UUID(str(subject_uuid))
    return resolve_metric_subjects(team_id, [identifier])[identifier]


def resolve_metric_subjects(team_id: int, metric_ids: Collection[UUID]) -> dict[UUID, SubjectRef]:
    reads = data_catalog_facade.metric_reads_for_ids(team_id, metric_ids)
    return {
        metric_id: SubjectRef(
            subject_type=SubjectType.METRIC,
            subject_uuid=str(metric_id),
            name=reads[metric_id].summary.name,
            queryable_name="",
            exists=True,
            definition_kind=reads[metric_id].summary.definition_kind,
            metric_definition=reads[metric_id].hogql_definition,
        )
        if metric_id in reads
        else _missing(SubjectType.METRIC, metric_id)
        for metric_id in metric_ids
    }


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


def subject_column_type(team_id: int, subject_type: str, subject_uuid: str | UUID, column_name: str) -> str | None:
    """The column's ClickHouse type, or None when the subject or the column cannot be established.

    None is unknown, not "untyped": a view records its columns only once it has run, so a check
    authored against a fresh view has nothing to read here.
    """
    if not column_name:
        return None
    kind = SubjectType(subject_type)
    if kind is SubjectType.METRIC:
        return None
    if kind is SubjectType.POSTHOG_TABLE:
        entry = posthog_tables.by_id(subject_uuid)
        return entry.columns.get(column_name) if entry else None
    if kind is SubjectType.TABLE:
        table_id = UUID(str(subject_uuid))
        columns = warehouse_facade.all_queryable_table_columns(team_id, {table_id}).get(table_id, {})
    else:
        columns = data_modeling_facade.get_saved_query_columns(team_id, subject_uuid)
    return columns.get(column_name)


def posthog_table_column_is_selectable(subject_uuid: str | UUID, column_name: str) -> bool:
    """Whether the column is one the registry lists, or a path into one of its JSON columns."""
    entry = posthog_tables.by_id(subject_uuid)
    if entry is None:
        return False
    head, _, tail = column_name.partition(".")
    column_type = entry.columns.get(head)
    if column_type is None:
        return False
    return not tail or column_type == DatabaseSerializedFieldType.JSON.value


def _missing(kind: SubjectType, subject_uuid: str | UUID) -> SubjectRef:
    return SubjectRef(
        subject_type=kind,
        subject_uuid=str(subject_uuid),
        name="",
        queryable_name="",
        exists=False,
    )
