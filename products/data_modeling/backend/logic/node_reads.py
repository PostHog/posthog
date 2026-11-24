from collections.abc import Collection, Sequence
from typing import TYPE_CHECKING
from uuid import UUID

from django.db.models import Exists, OuterRef, QuerySet, Subquery

from posthog.models.utils import strict_fetch

from products.data_modeling.backend.facade.enums import DataModelingJobEngine, NodeType
from products.data_modeling.backend.logic.node_visibility import exclude_hidden_edges, exclude_hidden_nodes
from products.data_modeling.backend.models.data_modeling_job import DataModelingJob
from products.data_modeling.backend.models.edge import Edge
from products.data_modeling.backend.models.node import Node

if TYPE_CHECKING:
    from posthog.models.team import Team

    from products.access_control.backend.facade.user_access_control import UserAccessControl


def _with_latest_serving_job(nodes: QuerySet[Node]) -> QuerySet[Node]:
    """Annotate the run state a reader is asking about: the newest ClickHouse job.

    Managed warehouse jobs can shadow a serving run and finish after it, so a shadow failure would
    otherwise label a model that served fine as failed.
    """
    serving_jobs = DataModelingJob.objects.filter(
        saved_query_id=OuterRef("saved_query_id"), engine=DataModelingJobEngine.CLICKHOUSE
    ).order_by("-last_run_at")
    return nodes.annotate(
        _has_serving_job=Exists(serving_jobs),
        _latest_job_status=Subquery(serving_jobs.values("status")[:1]),
        _latest_job_error=Subquery(serving_jobs.values("error")[:1]),
        _latest_job_run_at=Subquery(
            serving_jobs.filter(status=DataModelingJob.Status.COMPLETED).values("last_run_at")[:1]
        ),
    )


def _visible_nodes(team: "Team", user_access_control: "UserAccessControl") -> QuerySet[Node]:
    return exclude_hidden_nodes(Node.objects.filter(team_id=team.id), team, user_access_control)


def _visible_edges(team: "Team", user_access_control: "UserAccessControl") -> QuerySet[Edge]:
    return exclude_hidden_edges(Edge.objects.filter(team_id=team.id), team, user_access_control)


def list_nodes(
    team: "Team", user_access_control: "UserAccessControl", *, search_terms: Sequence[str] = ()
) -> list[Node]:
    nodes = _with_latest_serving_job(_visible_nodes(team, user_access_control).select_related("saved_query", "dag"))
    for term in search_terms:
        nodes = nodes.filter(name__icontains=term)
    return list(strict_fetch(nodes.order_by("name")))


def get_node(
    team: "Team",
    user_access_control: "UserAccessControl",
    *,
    node_id: UUID | str,
    lookup: str | None = None,
    include_hidden: bool = False,
) -> Node | None:
    nodes = Node.objects.filter(team_id=team.id).select_related("saved_query", "dag")
    if not include_hidden:
        nodes = exclude_hidden_nodes(nodes, team, user_access_control)
    nodes = _with_latest_serving_job(nodes)
    lookup_filter = {"pk": node_id}
    if lookup is not None:
        lookup_filter = {
            "saved_query": {"saved_query_id": node_id},
            "warehouse_table": {"properties__warehouse_table_id": node_id},
            "metric": {"metric_id": node_id},
        }.get(lookup, lookup_filter)
    return nodes.filter(**lookup_filter).order_by("created_at").first()


def get_posthog_table_node(
    team: "Team", user_access_control: "UserAccessControl", *, name: str, include_hidden: bool = False
) -> Node | None:
    nodes = Node.objects.filter(
        team_id=team.id,
        name=name,
        type=NodeType.TABLE,
        saved_query__isnull=True,
        properties__origin="posthog",
    ).select_related("saved_query", "dag")
    if not include_hidden:
        nodes = exclude_hidden_nodes(nodes, team, user_access_control)
    return _with_latest_serving_job(nodes).order_by("created_at").first()


def visible_node_ids_for_saved_query(
    team: "Team", user_access_control: "UserAccessControl", *, saved_query_id: UUID | str
) -> frozenset[UUID]:
    dag_ids = Node.objects.filter(team_id=team.id, saved_query_id=saved_query_id).values("dag_id")
    return frozenset(_visible_nodes(team, user_access_control).filter(dag_id__in=dag_ids).values_list("id", flat=True))


def list_lineage_nodes(
    team: "Team", user_access_control: "UserAccessControl", *, node_ids: Collection[UUID]
) -> list[Node]:
    nodes = _with_latest_serving_job(
        _visible_nodes(team, user_access_control).filter(id__in=node_ids).select_related("saved_query", "dag")
    )
    return list(strict_fetch(nodes))


def list_edges(
    team: "Team",
    user_access_control: "UserAccessControl",
    *,
    node_ids: Collection[UUID] | None = None,
) -> list[Edge]:
    edges = _visible_edges(team, user_access_control)
    if node_ids is not None:
        edges = edges.filter(source_id__in=node_ids, target_id__in=node_ids).select_related("source", "target", "dag")
    return list(strict_fetch(edges.order_by("-created_at")))


def get_edge(team: "Team", user_access_control: "UserAccessControl", *, edge_id: UUID | str) -> Edge | None:
    return (
        _visible_edges(team, user_access_control)
        .select_related("dag", "source__saved_query", "target__saved_query")
        .filter(id=edge_id)
        .first()
    )
