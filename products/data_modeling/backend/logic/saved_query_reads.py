"""Contract-shaped reads of saved queries for consumers outside this product."""

from collections.abc import Iterable
from uuid import UUID

from django.conf import settings

from ..facade.contracts import SavedQuerySummary
from ..models.datawarehouse_saved_query import DataWarehouseSavedQuery
from ..models.node import Node


def _clickhouse_type(entry: object) -> str | None:
    """The stored ClickHouse type, reading a current dict entry keyed ``clickhouse`` or a legacy
    bare type string. None for anything else, so a column with no readable type is dropped."""
    if isinstance(entry, dict):
        entry = entry.get("clickhouse")
    return entry if isinstance(entry, str) else None


def get_saved_query_columns(team_id: int, saved_query_id: UUID | str) -> dict[str, str]:
    """Each column's ClickHouse type, including any ``Nullable()`` wrapper.

    Empty for a view that has not run yet, since the columns are only recorded once a run has
    established them. A caller must treat that as unknown rather than as having no columns.

    The ``columns`` map stores each value as a bare type string (legacy rows) or a dict keyed
    ``clickhouse`` (current rows); both are unwrapped here so a consumer reads a plain type string.
    """
    stored = (
        DataWarehouseSavedQuery.objects.filter(team_id=team_id, id=saved_query_id)
        .exclude(deleted=True)
        .values_list("columns", flat=True)
        .first()
    )
    return {name: type_ for name, entry in (stored or {}).items() if (type_ := _clickhouse_type(entry)) is not None}


def get_saved_query_summary(team_id: int, saved_query_id: UUID | str) -> SavedQuerySummary | None:
    """The saved query only if it still resolves, else None.

    Soft-deleted rows are excluded because ``soft_delete`` rewrites ``name`` to a tombstone -- a
    caller holding a stored reference must not query that name.
    """
    saved_query = (
        DataWarehouseSavedQuery.objects.filter(team_id=team_id, id=saved_query_id).exclude(deleted=True).first()
    )
    if saved_query is None:
        return None
    return SavedQuerySummary(
        id=str(saved_query.id),
        team_id=saved_query.team_id,
        name=saved_query.name,
        last_run_at=saved_query.last_run_at,
    )


def saved_query_names(team_id: int, saved_query_ids: Iterable[UUID | str]) -> dict[str, str]:
    """The current name of each saved query that still resolves. One query; anything gone is absent.

    The bulk form of ``get_saved_query_summary`` for a caller that only needs names, so authorizing
    a page of stored references costs one query rather than one per reference. Soft-deleted rows are
    excluded for the same reason: ``soft_delete`` rewrites ``name`` to a tombstone.
    """
    ids = [str(saved_query_id) for saved_query_id in saved_query_ids]
    if not ids:
        return {}
    rows = (
        DataWarehouseSavedQuery.objects.filter(team_id=team_id, id__in=ids)
        .exclude(deleted=True)
        .values_list("id", "name")
    )
    return {str(saved_query_id): name for saved_query_id, name in rows}


def get_materialized_table_uri(team_id: int, saved_query_id: UUID | str) -> str | None:
    """The S3 Delta table a materialized view's rows live in, for a consumer that reads them directly.

    None when the view no longer resolves or was never materialized — either way there is no Delta
    table to read. The path is built from the same two model properties the materialization activity
    writes to (``_build_model_table_uri``), so a reader lands on the table that run produced.
    """
    saved_query = (
        DataWarehouseSavedQuery.objects.filter(team_id=team_id, id=saved_query_id).exclude(deleted=True).first()
    )
    if saved_query is None or not saved_query.is_materialized:
        return None
    return f"{settings.BUCKET_URL}/{saved_query.folder_path}/{saved_query.normalized_name}"


def get_node_ids_for_saved_queries(team_id: int, saved_query_ids: Iterable[UUID | str]) -> dict[str, str]:
    """The DAG node each of these saved queries sits on, as one query.

    A saved query can appear in several DAGs; the lowest node id wins so a link built from this
    stays put across refreshes instead of following whichever row the database returned first.
    """
    ids = list(saved_query_ids)
    if not ids:
        return {}
    rows = (
        Node.objects.filter(team_id=team_id, saved_query_id__in=ids).order_by("id").values_list("saved_query_id", "id")
    )
    nodes: dict[str, str] = {}
    for saved_query_id, node_id in rows:
        nodes.setdefault(str(saved_query_id), str(node_id))
    return nodes


def get_saved_query_ids_for_nodes(team_id: int, node_ids: Iterable[UUID | str]) -> list[str]:
    """The saved queries behind these DAG nodes. Source-table nodes have none and are dropped."""
    rows = Node.objects.filter(team_id=team_id, id__in=list(node_ids), saved_query__isnull=False).values_list(
        "saved_query_id", flat=True
    )
    return [str(saved_query_id) for saved_query_id in rows]
