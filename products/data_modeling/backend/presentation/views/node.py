import asyncio
from dataclasses import asdict
from datetime import timedelta
from typing import Any, cast
from uuid import UUID, uuid4

from django.conf import settings
from django.db import models
from django.db.models import OuterRef, Subquery

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import filters, request, response, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.pagination import PageNumberPagination
from temporalio.common import RetryPolicy

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.scoped_related_fields import TeamScopedPrimaryKeyRelatedField
from posthog.models import Team, User
from posthog.ph_client import feature_enabled_or_false
from posthog.temporal.common.client import sync_connect
from posthog.temporal.data_modeling.run_workflow import RunWorkflowInputs, Selector
from posthog.temporal.data_modeling.workflows.execute_dag import ExecuteDAGInputs

from products.data_modeling.backend.facade.models import DAG, Edge, Node, NodeType
from products.warehouse_sources.backend.facade.models import sync_frequency_interval_to_sync_frequency


class NodeSerializer(serializers.ModelSerializer):
    upstream_count = serializers.SerializerMethodField(read_only=True)
    downstream_count = serializers.SerializerMethodField(read_only=True)
    last_run_at = serializers.SerializerMethodField(read_only=True)
    last_run_status = serializers.SerializerMethodField(read_only=True)
    user_tag = serializers.SerializerMethodField(read_only=True)
    sync_interval = serializers.SerializerMethodField(read_only=True)
    dag_name = serializers.SerializerMethodField(read_only=True)
    dag = TeamScopedPrimaryKeyRelatedField(queryset=DAG.objects.all())

    class Meta:
        model = Node
        fields = [
            "id",
            "name",
            "type",
            "dag",
            "dag_name",
            "description",
            "saved_query_id",
            "created_at",
            "updated_at",
            "upstream_count",
            "downstream_count",
            "last_run_at",
            "last_run_status",
            "user_tag",
            "sync_interval",
        ]
        read_only_fields = [
            "upstream_count",
            "downstream_count",
            "last_run_at",
            "last_run_status",
            "user_tag",
            "sync_interval",
            "dag_name",
            "saved_query_id",
        ]

    def get_upstream_count(self, node: Node) -> int:
        counts = self.context.get("node_counts")
        if counts and str(node.id) in counts:
            return counts[str(node.id)][0]
        return len(_get_upstream_nodes(node))

    def get_downstream_count(self, node: Node) -> int:
        counts = self.context.get("node_counts")
        if counts and str(node.id) in counts:
            return counts[str(node.id)][1]
        return len(_get_downstream_nodes(node))

    def get_last_run_at(self, node: Node) -> str | None:
        return node.properties.get("system", {}).get("last_run_at") or getattr(node, "_latest_job_run_at", None)

    def get_last_run_status(self, node: Node) -> str | None:
        return node.properties.get("system", {}).get("last_run_status") or getattr(node, "_latest_job_status", None)

    def get_user_tag(self, node: Node) -> str | None:
        return node.properties.get("user", {}).get("tag")

    def get_sync_interval(self, node: Node) -> str | None:
        if node.saved_query:
            return sync_frequency_interval_to_sync_frequency(node.saved_query.sync_frequency_interval)
        return None

    def get_dag_name(self, node: Node) -> str:
        return node.dag.name

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        # System-managed DAGs (e.g. Revenue Analytics) own their nodes; the internal sync path
        # maintains them directly via the ORM and bypasses this serializer. Block users from
        # editing managed nodes or moving any node into a managed DAG via the API.
        if self.instance is not None and self.instance.dag.is_managed:
            raise serializers.ValidationError("Nodes belonging to a system-managed DAG cannot be modified.")
        target_dag = attrs.get("dag")
        if target_dag is not None and target_dag.is_managed:
            raise serializers.ValidationError("Nodes cannot be created in or moved into a system-managed DAG.")
        return attrs


class NodePagination(PageNumberPagination):
    page_size = 1000


# TODO: consolidate graph traversal logic. similar implementations exist in:
# - posthog/temporal/data_modeling/workflows/execute_dag.py (_get_edge_lookup, _get_downstream_lookup)
# - products/data_modeling/backend/graph.py (Graph) — shared in-memory graph used by list endpoint
# the temporal workflow and lineage API should migrate to Graph


def _is_v2_backend_enabled(user: User, team: Team) -> bool:
    return feature_enabled_or_false(
        "data-modeling-backend-v2",
        str(user.distinct_id),
        groups={
            "organization": str(team.organization_id),
            "project": str(team.id),
        },
        group_properties={
            "organization": {"id": str(team.organization_id)},
            "project": {"id": str(team.id)},
        },
    )


def _get_upstream_nodes(node: Node, include_tables: bool = False) -> set[str]:
    """Get all upstream (ancestor) node IDs recursively, optionally excluding TABLE nodes."""
    nodes: set[str] = set()
    current = [node.id]
    while current:
        qs = Edge.objects.filter(
            team_id=node.team_id,
            dag=node.dag,
            target_id__in=current,
        )
        if not include_tables:
            qs = qs.exclude(source__type=NodeType.TABLE)
        current = list(qs.values_list("source_id", flat=True))
        nodes.update(str(i) for i in current)
    return nodes


def _get_downstream_nodes(node: Node) -> set[str]:
    """Get all downstream (descendant) node IDs recursively, excluding TABLE nodes."""
    nodes: set[str] = set()
    current = [node.id]
    while current:
        current = list(
            Edge.objects.exclude(target__type=NodeType.TABLE)
            .filter(
                team_id=node.team_id,
                dag=node.dag,
                source_id__in=current,
            )
            .values_list("target_id", flat=True)
        )
        nodes.update(str(i) for i in current)
    return nodes


def _node_queryset_with_latest_job() -> models.QuerySet:
    """Node queryset annotated with the latest DataModelingJob status and last_run_at.

    This lets the serializer fall back to job data when node.properties["system"] is unpopulated.
    - _latest_job_status: status of the most recent job (any status)
    - _latest_job_run_at: last_run_at of the most recent *successful* job
    """
    from products.data_modeling.backend.facade.models import DataModelingJob

    latest_job = DataModelingJob.objects.filter(saved_query_id=OuterRef("saved_query_id")).order_by("-last_run_at")
    latest_completed_job = latest_job.filter(status=DataModelingJob.Status.COMPLETED)
    return (
        Node.objects.select_related("saved_query", "dag")
        .annotate(
            _latest_job_status=Subquery(latest_job.values("status")[:1]),
            _latest_job_run_at=Subquery(latest_completed_job.values("last_run_at")[:1]),
        )
        .all()
    )


class NodeViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "INTERNAL"
    queryset = Node.objects.select_related("saved_query", "dag").all()
    serializer_class = NodeSerializer
    pagination_class = NodePagination
    filter_backends = [filters.SearchFilter]
    search_fields = ["name", "dag__name"]
    ordering = "name"

    def get_serializer_context(self) -> dict[str, Any]:
        return super().get_serializer_context()

    def perform_destroy(self, instance: Node) -> None:
        if instance.dag.is_managed:
            raise serializers.ValidationError("Nodes belonging to a system-managed DAG cannot be deleted.")
        instance.delete()

    def list(self, request, *args, **kwargs):
        from products.data_modeling.backend.facade.models import Graph

        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        nodes = page if page is not None else queryset

        dag_id = self._get_dag_id_param()
        graph = Graph(team_id=self.team_id, dag_id=dag_id)
        node_ids = [str(n.id) for n in nodes]
        counts = graph.batch_counts(node_ids)

        serializer = self.get_serializer(
            nodes, many=True, context={**self.get_serializer_context(), "node_counts": counts}
        )
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return response.Response(serializer.data)

    def _get_dag_id_param(self) -> str | None:
        dag_id = self.request.query_params.get("dag")
        if dag_id:
            try:
                UUID(dag_id)
            except ValueError:
                return None
        return dag_id

    def safely_get_queryset(self, queryset):
        qs = queryset.filter(team_id=self.team_id)
        dag_id = self._get_dag_id_param()
        if dag_id:
            qs = qs.filter(dag_id=dag_id)
        return qs.order_by(self.ordering)

    @action(methods=["POST"], detail=True)
    def run(self, req: request.Request, *args, **kwargs) -> response.Response:
        """
        Run this node and its upstream or downstream dependencies.

        Request body:
            direction: "upstream" | "downstream" (required)
                - "upstream": Run all ancestors of this node, plus this node
                - "downstream": Run this node and all its descendants
        """
        node = self.get_object()
        direction = req.data.get("direction")

        if direction not in ("upstream", "downstream"):
            return response.Response(
                {"error": "direction must be 'upstream' or 'downstream'"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if node.type == NodeType.TABLE:
            return response.Response(
                {"error": "Cannot run a table node"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if direction == "upstream":
            node_ids = _get_upstream_nodes(node)
        else:
            node_ids = _get_downstream_nodes(node)

        node_ids.add(str(node.id))

        if _is_v2_backend_enabled(cast(User, req.user), self.team):
            inputs: ExecuteDAGInputs | RunWorkflowInputs = ExecuteDAGInputs(
                team_id=self.team_id,
                dag_id=str(node.dag_id),
                node_ids=list(node_ids),
            )
            workflow_name = "data-modeling-execute-dag"
            workflow_id = f"execute-dag-{uuid4()}"
        else:
            # v1 workflow is frozen — do not extend this branch.
            # v2 lives at posthog/temporal/data_modeling/workflows/. Teams are
            # being migrated off v1 via the `_is_v2_backend_enabled` flag.
            saved_query_ids = list(
                # nosemgrep: idor-lookup-without-team (node_ids from prior team-scoped graph traversal)
                Node.objects.filter(
                    id__in=node_ids,
                    saved_query_id__isnull=False,
                ).values_list("saved_query_id", flat=True)
            )
            selectors = [
                Selector(
                    label=str(sq_id),
                    ancestors="ALL" if direction == "upstream" else 0,
                    descendants="ALL" if direction == "downstream" else 0,
                )
                for sq_id in saved_query_ids
            ]
            inputs = RunWorkflowInputs(team_id=self.team_id, select=selectors)
            workflow_name = "data-modeling-run"
            workflow_id = f"data-modeling-run-{node.dag_id}-{uuid4()}"

        temporal = sync_connect()
        asyncio.run(
            temporal.start_workflow(
                workflow_name,
                asdict(inputs),
                id=workflow_id,
                task_queue=str(settings.DATA_MODELING_TASK_QUEUE),
                retry_policy=RetryPolicy(
                    initial_interval=timedelta(seconds=10),
                    maximum_interval=timedelta(seconds=60),
                    maximum_attempts=3,
                    non_retryable_error_types=["NondeterminismError", "CancelledError"],
                ),
            )
        )

        return response.Response({"node_ids": list(node_ids)}, status=status.HTTP_200_OK)

    @extend_schema(
        parameters=[
            OpenApiParameter("node_id", OpenApiTypes.UUID, description="Node to build lineage for."),
            OpenApiParameter(
                "saved_query_id",
                OpenApiTypes.UUID,
                description="Saved query to build lineage for, resolved to its node. Alternative to node_id.",
            ),
        ]
    )
    @action(methods=["GET"], detail=False)
    def lineage(self, req: request.Request, *args, **kwargs) -> response.Response:
        """Return the subgraph of nodes and edges reachable from a node (upstream + downstream).

        Accepts either node_id or saved_query_id, so a caller holding only a saved query (the SQL
        editor) doesn't need to resolve the node itself.
        """
        from products.data_modeling.backend.presentation.views.edge import EdgeSerializer

        # NodeViewSet is `scope_object = "INTERNAL"`, so AccessControlPermission does not gate it on
        # any resource. Lineage exposes warehouse view/table names, types, and edges — the same
        # metadata the deleted `warehouse_view`-scoped upstream endpoint gated on. Re-apply that gate
        # here so warehouse RBAC still governs the read (warehouse_view inherits warehouse_objects).
        if not self.user_access_control.check_access_level_for_resource("warehouse_view", required_level="viewer"):
            raise PermissionDenied("Reading lineage requires data warehouse read access.")

        node_id = req.query_params.get("node_id")
        saved_query_id = req.query_params.get("saved_query_id")
        if not node_id and not saved_query_id:
            return response.Response(
                {"error": "node_id or saved_query_id is required"}, status=status.HTTP_400_BAD_REQUEST
            )
        # Parse UUIDs up front: unlike the detail route, query params aren't validated by URL
        # routing, so an invalid string would surface as a 500 from the ORM instead of a 400.
        try:
            lookup = {"id": UUID(node_id)} if node_id else {"saved_query_id": UUID(cast(str, saved_query_id))}
        except ValueError:
            return response.Response({"error": "Invalid UUID"}, status=status.HTTP_400_BAD_REQUEST)

        # saved_query is a non-unique FK: a saved query synced into multiple DAGs has multiple nodes.
        # Order for a deterministic pick (the graphs are equivalent for lineage purposes).
        node = Node.objects.filter(team_id=self.team_id, **lookup).order_by("created_at").first()
        if node is None:
            return response.Response({"error": "Node not found"}, status=status.HTTP_404_NOT_FOUND)

        upstream_ids = _get_upstream_nodes(node, include_tables=True)
        downstream_ids = _get_downstream_nodes(node)
        all_ids = upstream_ids | downstream_ids | {str(node.id)}

        nodes = _node_queryset_with_latest_job().filter(id__in=all_ids, team_id=self.team_id)
        edges = Edge.objects.select_related("source", "target", "dag").filter(
            team_id=self.team_id, source_id__in=all_ids, target_id__in=all_ids
        )

        return response.Response(
            {
                "nodes": NodeSerializer(nodes, many=True, context=self.get_serializer_context()).data,
                "edges": EdgeSerializer(edges, many=True).data,
            }
        )

    @action(methods=["GET"], detail=False)
    def dag_ids(self, req: request.Request, *args, **kwargs) -> response.Response:
        """Get all distinct DAGs for the team."""
        dags = list(DAG.objects.filter(team_id=self.team_id).order_by("name").values("id", "name"))
        dag_ids = [{"id": str(dag["id"]), "name": dag["name"]} for dag in dags]
        return response.Response({"dag_ids": dag_ids}, status=status.HTTP_200_OK)

    @action(methods=["POST"], detail=True)
    def materialize(self, req: request.Request, *args, **kwargs) -> response.Response:
        """Materialize just this single node."""
        from products.data_modeling.backend.facade.api import start_node_materialization

        node = self.get_object()

        if node.type == NodeType.TABLE:
            return response.Response(
                {"error": "Cannot materialize a table node"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        start_node_materialization(node, is_v2=_is_v2_backend_enabled(cast(User, req.user), self.team))

        return response.Response(status=status.HTTP_200_OK)
