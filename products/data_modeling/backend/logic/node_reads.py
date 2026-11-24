from collections.abc import Callable, Collection, Sequence
from typing import TYPE_CHECKING
from uuid import UUID

from django.db.models import Exists, OuterRef, Q, QuerySet, Subquery

from posthog.paging import Page, PageRequest
from posthog.queryset_paging import select_page

from products.data_modeling.backend.facade.contracts import NodeRunState
from products.data_modeling.backend.facade.enums import DataModelingJobEngine, NodeLookup, NodeType
from products.data_modeling.backend.logic.node_visibility import exclude_hidden_edges, exclude_hidden_nodes
from products.data_modeling.backend.models.data_modeling_job import DataModelingJob
from products.data_modeling.backend.models.edge import Edge
from products.data_modeling.backend.models.node import Node

if TYPE_CHECKING:
    from posthog.models.team import Team

    from products.access_control.backend.facade.user_access_control import UserAccessControl


def with_latest_serving_job(nodes: QuerySet[Node]) -> QuerySet[Node]:
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


def visible_nodes(team: "Team", user_access_control: "UserAccessControl") -> QuerySet[Node]:
    return exclude_hidden_nodes(Node.objects.filter(team_id=team.id), team, user_access_control)


def _visible_edges(team: "Team", user_access_control: "UserAccessControl") -> QuerySet[Edge]:
    return exclude_hidden_edges(Edge.objects.filter(team_id=team.id), team, user_access_control)


def list_node_ids(
    team: "Team",
    user_access_control: "UserAccessControl",
    *,
    page: PageRequest,
    search_terms: Sequence[str] = (),
) -> Page[UUID]:
    nodes = visible_nodes(team, user_access_control)
    for term in search_terms:
        nodes = nodes.filter(name__icontains=term)
    return select_page(nodes.order_by("name").only("id"), page).map(lambda node: node.id)


_NODE_LOOKUP_FILTERS: dict[NodeLookup, Callable[[UUID | str], Q]] = {
    NodeLookup.SAVED_QUERY: lambda key: Q(saved_query_id=key),
    NodeLookup.WAREHOUSE_TABLE: lambda key: Q(properties__warehouse_table_id=key),
    NodeLookup.POSTHOG_TABLE: lambda key: Q(
        name=key, type=NodeType.TABLE, saved_query__isnull=True, properties__origin="posthog"
    ),
    NodeLookup.METRIC: lambda key: Q(metric_id=key),
}


def _lookup_filter(lookup: NodeLookup | None, key: UUID | str) -> Q:
    return Q(pk=key) if lookup is None else _NODE_LOOKUP_FILTERS[lookup](key)


def find_node_id(
    team: "Team",
    user_access_control: "UserAccessControl",
    *,
    key: UUID | str,
    lookup: NodeLookup | None = None,
    include_hidden: bool = False,
) -> UUID | None:
    nodes = Node.objects.filter(_lookup_filter(lookup, key), team_id=team.id)
    if not include_hidden:
        nodes = exclude_hidden_nodes(nodes, team, user_access_control)
    return nodes.order_by("created_at").values_list("id", flat=True).first()


_RUN_STATE_FIELDS = ("id", "_has_serving_job", "_latest_job_status", "_latest_job_error", "_latest_job_run_at")


def node_run_states(team_id: int, node_ids: Collection[UUID]) -> dict[UUID, NodeRunState]:
    nodes = with_latest_serving_job(Node.objects.filter(team_id=team_id, id__in=node_ids))
    return {
        row["id"]: NodeRunState(
            has_serving_job=row["_has_serving_job"],
            status=row["_latest_job_status"],
            error=row["_latest_job_error"],
            completed_at=row["_latest_job_run_at"],
        )
        for row in nodes.values(*_RUN_STATE_FIELDS)
    }


def visible_node_ids_in_dags_of_saved_query(
    team: "Team", user_access_control: "UserAccessControl", *, saved_query_id: UUID | str
) -> frozenset[UUID]:
    dag_ids = Node.objects.filter(team_id=team.id, saved_query_id=saved_query_id).values("dag_id")
    return frozenset(visible_nodes(team, user_access_control).filter(dag_id__in=dag_ids).values_list("id", flat=True))


def visible_node_ids_among(
    team: "Team", user_access_control: "UserAccessControl", *, node_ids: Collection[UUID]
) -> frozenset[UUID]:
    return frozenset(visible_nodes(team, user_access_control).filter(id__in=node_ids).values_list("id", flat=True))


def list_edge_ids(team: "Team", user_access_control: "UserAccessControl", *, page: PageRequest) -> Page[UUID]:
    edges = _visible_edges(team, user_access_control).order_by("-created_at").only("id")
    return select_page(edges, page).map(lambda edge: edge.id)


def lineage_edge_ids(
    team: "Team", user_access_control: "UserAccessControl", *, node_ids: Collection[UUID]
) -> list[UUID]:
    edges = _visible_edges(team, user_access_control).filter(source_id__in=node_ids, target_id__in=node_ids)
    return list(edges.order_by("-created_at").values_list("id", flat=True))


def find_edge_id(team: "Team", user_access_control: "UserAccessControl", *, edge_id: UUID) -> UUID | None:
    return _visible_edges(team, user_access_control).filter(id=edge_id).values_list("id", flat=True).first()
