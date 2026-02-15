import asyncio
from dataclasses import asdict
from datetime import timedelta
from typing import Any, cast
from uuid import uuid4

from django.conf import settings

import posthoganalytics
from rest_framework import filters, request, response, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from temporalio.common import RetryPolicy

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models import Team, User
from posthog.temporal.common.client import sync_connect
from posthog.temporal.data_modeling.run_workflow import RunWorkflowInputs, Selector
from posthog.temporal.data_modeling.workflows.execute_dag import ExecuteDAGInputs
from posthog.temporal.data_modeling.workflows.materialize_view import MaterializeViewWorkflowInputs

from products.data_modeling.backend.models import Edge, Node, NodeType
from products.data_warehouse.backend.models.external_data_schema import sync_frequency_interval_to_sync_frequency


class NodeSerializer(serializers.ModelSerializer):
    upstream_count = serializers.SerializerMethodField(read_only=True)
    downstream_count = serializers.SerializerMethodField(read_only=True)
    last_run_at = serializers.SerializerMethodField(read_only=True)
    last_run_status = serializers.SerializerMethodField(read_only=True)
    user_tag = serializers.SerializerMethodField(read_only=True)
    sync_interval = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Node
        fields = [
            "id",
            "name",
            "type",
            "dag_id",
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
        ]

    def get_upstream_count(self, node: Node) -> int:
        return len(_get_upstream_nodes(node))

    def get_downstream_count(self, node: Node) -> int:
        return len(_get_downstream_nodes(node))

    def get_last_run_at(self, node: Node) -> str | None:
        return node.properties.get("system", {}).get("last_run_at")

    def get_last_run_status(self, node: Node) -> str | None:
        return node.properties.get("system", {}).get("last_run_status")

    def get_user_tag(self, node: Node) -> str | None:
        return node.properties.get("user", {}).get("tag")

    def get_sync_interval(self, node: Node) -> str | None:
        if node.saved_query:
            return sync_frequency_interval_to_sync_frequency(node.saved_query.sync_frequency_interval)
        return None


class NodePagination(PageNumberPagination):
    page_size = 1000


# TODO: consolidate graph traversal logic. similar implementations exist in:
# - products/data_warehouse/backend/api/lineage.py (get_upstream_dag) should be deleted after new system takes over
# - posthog/temporal/data_modeling/workflows/execute_dag.py (_get_edge_lookup, _get_downstream_lookup)
# shared utility should exist and used between node viewset and workflow


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
    queryset = Node.objects.select_related("saved_query").all()
    serializer_class = NodeSerializer
    pagination_class = NodePagination
    filter_backends = [filters.SearchFilter]
    search_fields = ["name", "dag_id"]
    ordering = "name"

    def get_serializer_context(self) -> dict[str, Any]:
        return super().get_serializer_context()

    def safely_get_queryset(self, queryset):
        return queryset.filter(team_id=self.team_id, dag_id=f"posthog_{self.team_id}").order_by(self.ordering)

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
                dag_id=node.dag_id,
                node_ids=list(node_ids),
            )
            workflow_name = "data-modeling-execute-dag"
            workflow_id = f"execute-dag-{uuid4()}"
        else:
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

        if _is_v2_backend_enabled(cast(User, req.user), self.team):
            inputs: MaterializeViewWorkflowInputs | RunWorkflowInputs = MaterializeViewWorkflowInputs(
                team_id=self.team_id,
                dag_id=node.dag_id,
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
