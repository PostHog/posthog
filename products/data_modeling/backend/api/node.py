import asyncio
from dataclasses import asdict
from datetime import timedelta
from typing import Any, cast
from uuid import UUID, uuid4

from django.conf import settings
from django.db import models
from django.db.models import OuterRef, Subquery

import posthoganalytics
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_field
from rest_framework import filters, request, response, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from temporalio.common import RetryPolicy

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.scoped_related_fields import TeamScopedPrimaryKeyRelatedField
from posthog.models import Team, User
from posthog.temporal.common.client import sync_connect
from posthog.temporal.data_modeling.run_workflow import RunWorkflowInputs, Selector
from posthog.temporal.data_modeling.workflows.execute_dag import ExecuteDAGInputs
from posthog.temporal.data_modeling.workflows.materialize_view import MaterializeViewWorkflowInputs

from products.data_modeling.backend.api.edge import EdgeSerializer
from products.data_modeling.backend.models import DAG, Edge, Node, NodeType
from products.warehouse_sources.backend.models.external_data_schema import sync_frequency_interval_to_sync_frequency


class NodeSerializer(serializers.ModelSerializer):
    upstream_count = serializers.SerializerMethodField(
        read_only=True, help_text="Number of upstream (ancestor) nodes this node depends on, excluding raw table nodes."
    )
    downstream_count = serializers.SerializerMethodField(
        read_only=True,
        help_text="Number of downstream (descendant) nodes that depend on this node, excluding raw table nodes.",
    )
    last_run_at = serializers.SerializerMethodField(
        read_only=True, help_text="ISO timestamp of this node's most recent successful run, or null if it never ran."
    )
    last_run_status = serializers.SerializerMethodField(
        read_only=True, help_text="Status of this node's most recent run (e.g. Completed, Failed, Cancelled), or null."
    )
    user_tag = serializers.SerializerMethodField(
        read_only=True, help_text="Optional user-assigned tag for grouping/labelling this node, or null."
    )
    sync_interval = serializers.SerializerMethodField(
        read_only=True, help_text="Human-readable schedule on which this node materializes (e.g. '24hour'), or null."
    )
    dag_name = serializers.SerializerMethodField(read_only=True, help_text="Name of the DAG this node belongs to.")
    dag = TeamScopedPrimaryKeyRelatedField(queryset=DAG.objects.all(), help_text="ID of the DAG this node belongs to.")

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
        extra_kwargs = {
            "id": {"help_text": "Unique identifier of the node."},
            "name": {"help_text": "Name of the data model node (matches the saved query / table name)."},
            "type": {"help_text": "Node type: 'table' (raw source), 'view', 'matview' (materialized), or 'endpoint'."},
            "description": {"help_text": "Optional description of the node."},
            "saved_query_id": {
                "help_text": "ID of the backing data warehouse saved query, or null for raw table nodes."
            },
            "created_at": {"help_text": "ISO timestamp when the node was created."},
            "updated_at": {"help_text": "ISO timestamp when the node was last updated."},
        }

    @extend_schema_field(OpenApiTypes.INT)
    def get_upstream_count(self, node: Node) -> int:
        counts = self.context.get("node_counts")
        if counts and str(node.id) in counts:
            return counts[str(node.id)][0]
        return len(_get_upstream_nodes(node))

    @extend_schema_field(OpenApiTypes.INT)
    def get_downstream_count(self, node: Node) -> int:
        counts = self.context.get("node_counts")
        if counts and str(node.id) in counts:
            return counts[str(node.id)][1]
        return len(_get_downstream_nodes(node))

    @extend_schema_field(OpenApiTypes.STR)
    def get_last_run_at(self, node: Node) -> str | None:
        return node.properties.get("system", {}).get("last_run_at") or getattr(node, "_latest_job_run_at", None)

    @extend_schema_field(OpenApiTypes.STR)
    def get_last_run_status(self, node: Node) -> str | None:
        return node.properties.get("system", {}).get("last_run_status") or getattr(node, "_latest_job_status", None)

    @extend_schema_field(OpenApiTypes.STR)
    def get_user_tag(self, node: Node) -> str | None:
        return node.properties.get("user", {}).get("tag")

    @extend_schema_field(OpenApiTypes.STR)
    def get_sync_interval(self, node: Node) -> str | None:
        if node.saved_query:
            return sync_frequency_interval_to_sync_frequency(node.saved_query.sync_frequency_interval)
        return None

    @extend_schema_field(OpenApiTypes.STR)
    def get_dag_name(self, node: Node) -> str:
        return node.dag.name


class LineageResponseSerializer(serializers.Serializer):
    """Response shape for the `lineage` and `graph` actions: a subgraph of nodes + edges."""

    nodes = NodeSerializer(many=True, read_only=True, help_text="Nodes in the returned subgraph.")
    edges = EdgeSerializer(many=True, read_only=True, help_text="Directed dependency edges between the returned nodes.")
    focal_id = serializers.UUIDField(
        allow_null=True,
        read_only=True,
        help_text="ID of the focal node the lineage is centered on, or null for the whole-DAG graph view.",
    )


class RunRequestSerializer(serializers.Serializer):
    direction = serializers.ChoiceField(
        choices=["upstream", "downstream"],
        help_text="'upstream' runs all ancestors plus this node; 'downstream' runs this node plus all descendants.",
    )


class RunResponseSerializer(serializers.Serializer):
    node_ids = serializers.ListField(
        child=serializers.CharField(),
        help_text="IDs of all nodes that were scheduled to run.",
    )


class DagRefSerializer(serializers.Serializer):
    id = serializers.CharField(help_text="DAG ID.")
    name = serializers.CharField(help_text="DAG name.")


class DagIdsResponseSerializer(serializers.Serializer):
    dag_ids = DagRefSerializer(many=True, help_text="All DAGs for the team.")


class NodePagination(PageNumberPagination):
    page_size = 1000


# TODO: consolidate graph traversal logic. similar implementations exist in:
# - products/data_warehouse/backend/api/lineage.py (get_upstream_dag) should be deleted after new system takes over
# - posthog/temporal/data_modeling/workflows/execute_dag.py (_get_edge_lookup, _get_downstream_lookup)
# - products/data_modeling/backend/graph.py (Graph) — shared in-memory graph used by list endpoint
# the temporal workflow and lineage API should migrate to Graph


def _is_v2_backend_enabled(user: User, team: Team) -> bool:
    return posthoganalytics.feature_enabled(
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
    from products.data_modeling.backend.models.data_modeling_job import DataModelingJob

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
    scope_object = "warehouse_view"
    queryset = Node.objects.select_related("saved_query", "dag").all()
    serializer_class = NodeSerializer
    pagination_class = NodePagination
    filter_backends = [filters.SearchFilter]
    search_fields = ["name", "dag__name"]
    ordering = "name"

    def get_serializer_context(self) -> dict[str, Any]:
        return super().get_serializer_context()

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "search",
                OpenApiTypes.STR,
                OpenApiParameter.QUERY,
                required=False,
                description="Case-insensitive substring match on node name or DAG name.",
            ),
            OpenApiParameter(
                "dag",
                OpenApiTypes.UUID,
                OpenApiParameter.QUERY,
                required=False,
                description="Restrict results to a single DAG by ID.",
            ),
        ],
    )
    def list(self, request, *args, **kwargs):
        from products.data_modeling.backend.graph import Graph

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

    @extend_schema(request=RunRequestSerializer, responses=RunResponseSerializer)
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

    def _serialize_subgraph(self, nodes_qs, edges_qs, focal_id: str | None) -> dict[str, Any]:
        """Serialize a node/edge subgraph with batched upstream/downstream counts."""
        from products.data_modeling.backend.graph import Graph

        graph = Graph(team_id=self.team_id)
        counts = graph.batch_counts([str(n.id) for n in nodes_qs])
        return {
            "nodes": NodeSerializer(
                nodes_qs, many=True, context={**self.get_serializer_context(), "node_counts": counts}
            ).data,
            "edges": EdgeSerializer(edges_qs, many=True).data,
            "focal_id": focal_id,
        }

    @extend_schema(responses=LineageResponseSerializer)
    @action(methods=["GET"], detail=True)
    def lineage(self, req: request.Request, *args, **kwargs) -> response.Response:
        """Return the subgraph of nodes and edges reachable from this node (upstream + downstream)."""
        node = self.get_object()
        upstream_ids = _get_upstream_nodes(node, include_tables=True)
        downstream_ids = _get_downstream_nodes(node)
        all_ids = upstream_ids | downstream_ids | {str(node.id)}

        nodes = _node_queryset_with_latest_job().filter(id__in=all_ids, team_id=self.team_id)
        edges = Edge.objects.select_related("source", "target", "dag").filter(
            team_id=self.team_id, source_id__in=all_ids, target_id__in=all_ids
        )

        return response.Response(self._serialize_subgraph(nodes, edges, focal_id=str(node.id)))

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "dag",
                OpenApiTypes.UUID,
                OpenApiParameter.QUERY,
                required=False,
                description="Restrict the graph to a single DAG by ID; otherwise returns the team's whole DAG.",
            ),
        ],
        responses=LineageResponseSerializer,
    )
    @action(methods=["GET"], detail=False)
    def graph(self, req: request.Request, *args, **kwargs) -> response.Response:
        """Return the whole data modeling DAG (all nodes and edges) for the team, optionally scoped to one DAG."""
        dag_id = self._get_dag_id_param()

        nodes = _node_queryset_with_latest_job().filter(team_id=self.team_id)
        edges = Edge.objects.select_related("source", "target", "dag").filter(team_id=self.team_id)
        if dag_id:
            nodes = nodes.filter(dag_id=dag_id)
            edges = edges.filter(dag_id=dag_id)

        return response.Response(self._serialize_subgraph(nodes, edges, focal_id=None))

    @extend_schema(responses=DagIdsResponseSerializer)
    @action(methods=["GET"], detail=False)
    def dag_ids(self, req: request.Request, *args, **kwargs) -> response.Response:
        """Get all distinct DAGs for the team."""
        dags = list(DAG.objects.filter(team_id=self.team_id).order_by("name").values("id", "name"))
        dag_ids = [{"id": str(dag["id"]), "name": dag["name"]} for dag in dags]
        return response.Response({"dag_ids": dag_ids}, status=status.HTTP_200_OK)

    @extend_schema(request=None, responses={200: None})
    @action(methods=["POST"], detail=True)
    def materialize(self, req: request.Request, *args, **kwargs) -> response.Response:
        """Materialize just this single node."""
        node = self.get_object()

        if node.type == NodeType.TABLE:
            return response.Response(
                {"error": "Cannot materialize a table node"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if _is_v2_backend_enabled(cast(User, req.user), self.team):
            inputs: MaterializeViewWorkflowInputs | RunWorkflowInputs = MaterializeViewWorkflowInputs(
                team_id=self.team_id,
                dag_id=str(node.dag_id),
                node_id=str(node.id),
            )
            workflow_name = "data-modeling-materialize-view"
            workflow_id = f"materialize-view-{node.id}-{uuid4()}"
        else:
            inputs = RunWorkflowInputs(
                team_id=self.team_id,
                select=[Selector(label=str(node.saved_query_id), ancestors=0, descendants=0)],
            )
            workflow_name = "data-modeling-run"
            workflow_id = f"data-modeling-run-{node.id}-{uuid4()}"

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

        return response.Response(status=status.HTTP_200_OK)
