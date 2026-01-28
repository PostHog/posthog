import asyncio
from dataclasses import asdict
from datetime import timedelta
from typing import Any
from uuid import uuid4

from django.conf import settings

from rest_framework import filters, request, response, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from temporalio.common import RetryPolicy

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.temporal.common.client import sync_connect
from posthog.temporal.data_modeling.workflows.execute_dag import ExecuteDAGInputs
from posthog.temporal.data_modeling.workflows.materialize_view import MaterializeViewWorkflowInputs

from products.data_modeling.backend.models import Edge, Node, NodeType


class NodeSerializer(serializers.ModelSerializer):
    upstream_count = serializers.SerializerMethodField(read_only=True)
    downstream_count = serializers.SerializerMethodField(read_only=True)
    last_run_at = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Node
        fields = [
            "id",
            "name",
            "type",
            "dag_id",
            "saved_query_id",
            "properties",
            "created_at",
            "updated_at",
            "upstream_count",
            "downstream_count",
            "last_run_at",
        ]
        read_only_fields = [
            "id",
            "created_at",
            "updated_at",
            "upstream_count",
            "downstream_count",
            "last_run_at",
        ]

    def get_upstream_count(self, node: Node) -> int:
        return len(_get_upstream_nodes(node))

    def get_downstream_count(self, node: Node) -> int:
        return len(_get_downstream_nodes(node))

    def get_last_run_at(self, node: Node) -> str | None:
        return node.properties.get("system", {}).get("last_run_at")


class NodePagination(PageNumberPagination):
    page_size = 100


# TODO: consolidate graph traversal logic. similar implementations exist in:
# - products/data_warehouse/backend/api/lineage.py (get_upstream_dag) should be deleted after new system takes over
# - posthog/temporal/data_modeling/workflows/execute_dag.py (_get_edge_lookup, _get_downstream_lookup)
# shared utility should exist and used between node viewset and workflow


def _get_upstream_nodes(node: Node) -> set[str]:
    """Get all upstream (ancestor) node IDs recursively, excluding TABLE nodes."""
    nodes: set[str] = set()
    current = [node.id]
    while current:
        current = list(
            Edge.objects.exclude(source__type=NodeType.TABLE)
            .filter(
                team_id=node.team_id,
                dag_id=node.dag_id,
                target_id__in=current,
            )
            .values_list("source_id", flat=True)
        )
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
                dag_id=node.dag_id,
                source_id__in=current,
            )
            .values_list("target_id", flat=True)
        )
        nodes.update(str(i) for i in current)
    return nodes


class NodeViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "INTERNAL"
    queryset = Node.objects.all()
    serializer_class = NodeSerializer
    pagination_class = NodePagination
    filter_backends = [filters.SearchFilter]
    search_fields = ["name", "dag_id"]
    ordering = "name"

    def get_serializer_context(self) -> dict[str, Any]:
        return super().get_serializer_context()

    def safely_get_queryset(self, queryset):
        return queryset.filter(team_id=self.team_id).order_by(self.ordering)

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

        inputs = ExecuteDAGInputs(
            team_id=self.team_id,
            dag_id=node.dag_id,
            node_ids=list(node_ids),
        )

        temporal = sync_connect()
        asyncio.run(
            temporal.start_workflow(
                "execute-dag",
                asdict(inputs),
                id=f"execute-dag-{node.dag_id}-{uuid4()}",
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

    @action(methods=["GET"], detail=False)
    def dag_ids(self, req: request.Request, *args, **kwargs) -> response.Response:
        """Get all distinct dag_ids for the team's nodes."""
        dag_ids = list(
            Node.objects.filter(team_id=self.team_id).values_list("dag_id", flat=True).distinct().order_by("dag_id")
        )
        return response.Response({"dag_ids": dag_ids}, status=status.HTTP_200_OK)

    @action(methods=["POST"], detail=True)
    def materialize(self, req: request.Request, *args, **kwargs) -> response.Response:
        """Materialize just this single node."""
        node = self.get_object()

        if node.type == NodeType.TABLE:
            return response.Response(
                {"error": "Cannot materialize a table node"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        inputs = MaterializeViewWorkflowInputs(
            team_id=self.team_id,
            dag_id=node.dag_id,
            node_id=str(node.id),
        )

        temporal = sync_connect()
        asyncio.run(
            temporal.start_workflow(
                "materialize-view",
                asdict(inputs),
                id=f"materialize-view-{node.id}-{uuid4()}",
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
