from typing import Any, cast
from uuid import UUID

from django.db import models
from django.db.models import Exists, OuterRef, Subquery

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_field
from rest_framework import filters, mixins, request, response, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.pagination import PageNumberPagination

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models import User
from posthog.rbac.query_access import assert_user_can_read_query

from products.data_modeling.backend.facade.api import (
    MaterializationForbiddenError,
    MaterializationRunDirection,
    delete_node,
    endpoint_link,
    get_declared_target,
    run_related_node_materializations,
    suspension_state,
    unsuspend_nodes,
)
from products.data_modeling.backend.facade.models import (
    SAVED_QUERY_NODE_TYPES,
    DataModelingJob,
    DataModelingJobEngine,
    Edge,
    LineageIssueKind,
    Node,
    NodeType,
)
from products.data_modeling.backend.presentation.views.edge import EdgeSerializer
from products.data_modeling.backend.presentation.views.metric_visibility import DELETE_DENIED, MetricNodeVisibilityMixin
from products.warehouse_sources.backend.facade.models import sync_frequency_interval_to_sync_frequency


class NodeSuspensionSerializer(serializers.Serializer):
    at = serializers.DateTimeField(help_text="When the node was suspended.")
    reason = serializers.CharField(help_text="Error from the materialization that tripped suspension.")
    job_id = serializers.CharField(help_text="Materialization job that tripped suspension.")


class NodeResumeSerializer(serializers.Serializer):
    resumed = serializers.BooleanField(help_text="False when the node was not suspended to begin with.")


class NodeRunSerializer(serializers.Serializer):
    direction = serializers.ChoiceField(
        choices=MaterializationRunDirection.choices,
        help_text="Run this view with all upstream dependencies or all downstream dependents.",
    )


class NodeRunResponseSerializer(serializers.Serializer):
    node_ids = serializers.ListField(
        child=serializers.UUIDField(),
        help_text="The nodes included in the dependency run.",
    )


class NodeEndpointSerializer(serializers.Serializer):
    name = serializers.CharField(help_text="Name of the endpoint this node's materialization backs.")
    version = serializers.IntegerField(help_text="Endpoint version this node's materialization backs.")


class LineageLookupError(Exception):
    """Raised when the lineage request names no node, or names one with an unparseable id."""


class NodeLookup(models.TextChoices):
    SAVED_QUERY = "saved_query"
    WAREHOUSE_TABLE = "warehouse_table"
    POSTHOG_TABLE = "posthog_table"
    METRIC = "metric"


class LineageIssueSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(
        choices=LineageIssueKind.choices,
        help_text="sync_failed when the last attempt to rebuild this node's edges ended in an error. "
        "unresolved when the rebuild finished but some of the names this node reads matched no node in the DAG.",
    )
    detail = serializers.CharField(
        help_text="The error for sync_failed, or the comma-separated names that did not resolve for unresolved."
    )
    at = serializers.DateTimeField(allow_null=True, help_text="When the issue was recorded.")


class NodeSerializer(serializers.ModelSerializer):
    suspended = serializers.SerializerMethodField(read_only=True)
    endpoint = serializers.SerializerMethodField(read_only=True)
    upstream_count = serializers.SerializerMethodField(read_only=True)
    downstream_count = serializers.SerializerMethodField(read_only=True)
    last_run_at = serializers.SerializerMethodField(read_only=True)
    last_run_status = serializers.SerializerMethodField(read_only=True)
    last_run_error = serializers.SerializerMethodField(read_only=True)
    user_tag = serializers.SerializerMethodField(read_only=True)
    sync_interval = serializers.SerializerMethodField(read_only=True)
    lineage_issue = serializers.SerializerMethodField(read_only=True)
    origin = serializers.SerializerMethodField(read_only=True)
    warehouse_table_id = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Node
        fields = [
            "id",
            "name",
            "type",
            "description",
            "saved_query_id",
            "metric_id",
            "lineage_issue",
            "origin",
            "warehouse_table_id",
            "created_at",
            "updated_at",
            "upstream_count",
            "downstream_count",
            "last_run_at",
            "last_run_status",
            "last_run_error",
            "user_tag",
            "sync_interval",
            "suspended",
            "endpoint",
        ]
        read_only_fields = [
            "suspended",
            "endpoint",
            "upstream_count",
            "downstream_count",
            "last_run_at",
            "last_run_status",
            "user_tag",
            "sync_interval",
            "saved_query_id",
            "metric_id",
            "lineage_issue",
            "origin",
            "warehouse_table_id",
        ]

    @extend_schema_field(
        serializers.DictField(
            child=NodeSuspensionSerializer(),
            help_text="Engines this node is suspended for after repeated materialization failures. "
            "Suspended engines are skipped by scheduled DAG runs until the node is resumed.",
        )
    )
    def get_suspended(self, node: Node) -> dict[str, Any]:
        return {engine: NodeSuspensionSerializer(entry).data for engine, entry in suspension_state(node).items()}

    @extend_schema_field(
        NodeEndpointSerializer(
            allow_null=True,
            help_text="The endpoint version this node's materialization backs, or null for nodes that are not endpoints.",
        )
    )
    def get_endpoint(self, node: Node) -> dict[str, Any] | None:
        link = endpoint_link(node.properties)
        return NodeEndpointSerializer(link).data if link else None

    def get_upstream_count(self, node: Node) -> int:
        counts = self.context.get("node_counts")
        if counts and str(node.id) in counts:
            return counts[str(node.id)][0]
        return len(_get_upstream_nodes(node, hidden_types=self._hidden_types()))

    def get_downstream_count(self, node: Node) -> int:
        counts = self.context.get("node_counts")
        if counts and str(node.id) in counts:
            return counts[str(node.id)][1]
        return len(_get_downstream_nodes(node, hidden_types=self._hidden_types()))

    def _hidden_types(self) -> frozenset[str]:
        return self.context.get("hidden_node_types") or frozenset()

    def get_last_run_at(self, node: Node) -> str | None:
        run_at = getattr(node, "_latest_job_run_at", None)
        if run_at is not None:
            return run_at.isoformat()
        if getattr(node, "_has_serving_job", False):
            return None
        return node.properties.get("system", {}).get("last_run_at")

    def get_last_run_status(self, node: Node) -> str | None:
        """Skipped runs are written straight to the job table and never reach the stored status,
        so a blocked model would keep reporting the success before it."""
        return getattr(node, "_latest_job_status", None) or node.properties.get("system", {}).get("last_run_status")

    def get_last_run_error(self, node: Node) -> str | None:
        """Error of the run that last_run_status describes, so the two never disagree."""
        return getattr(node, "_latest_job_error", None) or None

    def get_user_tag(self, node: Node) -> str | None:
        return node.properties.get("user", {}).get("tag")

    def get_sync_interval(self, node: Node) -> str | None:
        # The node's freshness target is authoritative on tiered v2 teams (where the saved
        # query's interval is NULL); the saved-query interval covers v1 teams.
        target = get_declared_target(node)
        if target is not None:
            return sync_frequency_interval_to_sync_frequency(target)
        if node.saved_query:
            return sync_frequency_interval_to_sync_frequency(node.saved_query.sync_frequency_interval)
        return None

    @extend_schema_field(LineageIssueSerializer(allow_null=True))
    def get_lineage_issue(self, node: Node) -> dict[str, Any] | None:
        return node.lineage_issue

    @extend_schema_field(
        serializers.ChoiceField(
            choices=["posthog", "warehouse"],
            allow_null=True,
            help_text="Where a table originates, or null for legacy and unrecognized nodes.",
        )
    )
    def get_origin(self, node: Node) -> str | None:
        origin = node.properties.get("origin") if isinstance(node.properties, dict) else None
        return origin if origin in {"posthog", "warehouse"} else None

    @extend_schema_field(
        serializers.UUIDField(
            allow_null=True,
            help_text="Warehouse table identifier for an imported table, or null when unavailable.",
        )
    )
    def get_warehouse_table_id(self, node: Node) -> str | None:
        table_id = node.properties.get("warehouse_table_id") if isinstance(node.properties, dict) else None
        if not isinstance(table_id, str):
            return None
        try:
            return str(UUID(table_id))
        except ValueError:
            return None

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        # Managed viewsets (e.g. Revenue Analytics) own their views' nodes; the internal sync path
        # maintains them directly via the ORM and bypasses this serializer. Block users from
        # editing those nodes via the API.
        if self.instance is not None and self.instance.belongs_to_managed_viewset:
            raise serializers.ValidationError("Nodes of views PostHog manages cannot be modified.")
        if self.instance is not None and self.instance.type == NodeType.METRIC:
            raise serializers.ValidationError("Metric nodes are maintained by the data catalog.")
        node_type = attrs.get("type")
        if node_type is not None and self.instance is not None:
            # A full PUT round-trips the node's own type, so a type equal to the current one is
            # not a retype and must not be rejected.
            if node_type != self.instance.type:
                raise serializers.ValidationError("A node's type cannot be changed through the API.")
        return attrs


class NodePagination(PageNumberPagination):
    page_size = 1000


# Nodes expose warehouse view/table names, types, edges, and the error that suspended a
# materialization, so reading them needs the same warehouse access as reading the views themselves.
_READ_DENIED = "Reading data models requires data warehouse read access."


# TODO: consolidate graph traversal logic. similar implementations exist in:
# - posthog/temporal/data_modeling/workflows/execute_dag.py (_get_edge_lookup, _get_downstream_lookup)
# - products/data_modeling/backend/graph.py (Graph) — shared in-memory graph used by list endpoint
# the temporal workflow and lineage API should migrate to Graph


def _get_upstream_nodes(
    node: Node, include_tables: bool = False, hidden_types: frozenset[str] = frozenset()
) -> set[str]:
    """Get all upstream (ancestor) node IDs recursively, optionally excluding TABLE nodes."""
    nodes: set[str] = set()
    current = [node.id]
    while current:
        qs = Edge.objects.filter(
            team_id=node.team_id,
            dag=node.dag,
            target_id__in=current,
        ).exclude(models.Q(source__saved_query__deleted=True) | models.Q(target__saved_query__deleted=True))
        if not include_tables:
            qs = qs.exclude(source__type=NodeType.TABLE)
        if hidden_types:
            qs = qs.exclude(source__type__in=hidden_types)
        current = list(qs.values_list("source_id", flat=True))
        nodes.update(str(i) for i in current)
    return nodes


def _feeds_a_managed_view(node: Node) -> bool:
    return node.outgoing_edges.filter(target__saved_query__managed_viewset__isnull=False).exists()


def _get_downstream_nodes(node: Node, hidden_types: frozenset[str] = frozenset()) -> set[str]:
    """Get all downstream (descendant) node IDs recursively, excluding TABLE nodes."""
    nodes: set[str] = set()
    current = [node.id]
    while current:
        qs = (
            Edge.objects.exclude(target__type=NodeType.TABLE)
            .filter(
                team_id=node.team_id,
                dag=node.dag,
                source_id__in=current,
            )
            .exclude(models.Q(source__saved_query__deleted=True) | models.Q(target__saved_query__deleted=True))
        )
        if hidden_types:
            qs = qs.exclude(target__type__in=hidden_types)
        current = list(qs.values_list("target_id", flat=True))
        nodes.update(str(i) for i in current)
    return nodes


def _annotate_latest_job(queryset: models.QuerySet) -> models.QuerySet:
    """Annotate the run state a reader is asking about: the newest ClickHouse job.

    Managed warehouse jobs can shadow a serving run and finish after it, so a shadow failure would
    otherwise label a model that served fine as failed.
    """
    serving_jobs = DataModelingJob.objects.filter(
        saved_query_id=OuterRef("saved_query_id"), engine=DataModelingJobEngine.CLICKHOUSE
    ).order_by("-last_run_at")
    return queryset.annotate(
        _has_serving_job=Exists(serving_jobs),
        _latest_job_status=Subquery(serving_jobs.values("status")[:1]),
        _latest_job_error=Subquery(serving_jobs.values("error")[:1]),
        _latest_job_run_at=Subquery(
            serving_jobs.filter(status=DataModelingJob.Status.COMPLETED).values("last_run_at")[:1]
        ),
    )


def _node_queryset_with_latest_job() -> models.QuerySet:
    return _annotate_latest_job(Node.objects.select_related("saved_query", "dag").all())


class LineageResponseSerializer(serializers.Serializer):
    nodes = NodeSerializer(many=True, help_text="Every node reachable from the requested one, plus the node itself.")
    edges = EdgeSerializer(many=True, help_text="Every edge between two of those nodes.")


class NodeViewSet(
    MetricNodeVisibilityMixin,
    TeamAndOrgViewSetMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    scope_object = "INTERNAL"
    queryset = Node.objects.select_related("saved_query", "dag").all()
    serializer_class = NodeSerializer
    pagination_class = NodePagination
    filter_backends = [filters.SearchFilter]
    search_fields = ["name"]
    ordering = "name"

    def get_serializer_context(self) -> dict[str, Any]:
        return {**super().get_serializer_context(), "hidden_node_types": self._hidden_node_types()}

    def perform_destroy(self, instance: Node) -> None:
        self._require_warehouse_access(level="editor", message=DELETE_DENIED)
        if instance.belongs_to_managed_viewset:
            raise serializers.ValidationError("Nodes of views PostHog manages cannot be deleted.")
        if _feeds_a_managed_view(instance):
            raise serializers.ValidationError("A view PostHog manages reads from this node, so it can't be deleted.")
        if instance.type == NodeType.METRIC:
            raise serializers.ValidationError("Metric nodes are deleted by deleting their metric.")
        delete_node(instance.team_id, instance.pk)

    def safely_get_object(self, queryset: models.QuerySet) -> Node:
        lookup = self.request.query_params.get("lookup")
        if not lookup:
            node = queryset.filter(pk=self.kwargs["pk"]).first()
        elif lookup == NodeLookup.SAVED_QUERY:
            node = queryset.filter(saved_query_id=self.kwargs["pk"]).order_by("created_at").first()
        elif lookup == NodeLookup.WAREHOUSE_TABLE:
            node = queryset.filter(properties__warehouse_table_id=self.kwargs["pk"]).order_by("created_at").first()
        elif lookup == NodeLookup.POSTHOG_TABLE:
            node = (
                queryset.filter(
                    name=self.kwargs["pk"],
                    type=NodeType.TABLE,
                    saved_query__isnull=True,
                    properties__origin="posthog",
                )
                .order_by("created_at")
                .first()
            )
        elif lookup == NodeLookup.METRIC:
            node = queryset.filter(metric_id=self.kwargs["pk"]).order_by("created_at").first()
        else:
            raise serializers.ValidationError({"lookup": f"Unsupported node lookup: {lookup}"})

        if node is None:
            raise NotFound()
        return node

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="lookup",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                enum=NodeLookup.values,
                description="Resolve the path ID as this backing resource type instead of a node ID.",
            )
        ]
    )
    def retrieve(self, request, *args, **kwargs):
        self._require_warehouse_access(level="viewer", message=_READ_DENIED)
        return super().retrieve(request, *args, **kwargs)

    def list(self, request, *args, **kwargs):
        from products.data_modeling.backend.facade.models import Graph

        self._require_warehouse_access(level="viewer", message=_READ_DENIED)

        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        nodes = page if page is not None else queryset

        graph = Graph(team_id=self.team_id, hidden_types=self._hidden_node_types())
        node_ids = [str(n.id) for n in nodes]
        counts = graph.batch_counts(node_ids)

        serializer = self.get_serializer(
            nodes, many=True, context={**self.get_serializer_context(), "node_counts": counts}
        )
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return response.Response(serializer.data)

    def safely_get_queryset(self, queryset):
        return _annotate_latest_job(self._exclude_hidden_nodes(queryset.filter(team_id=self.team_id))).order_by(
            self.ordering
        )

    @extend_schema(request=NodeRunSerializer, responses={200: NodeRunResponseSerializer})
    @action(methods=["POST"], detail=True)
    def run(self, req: request.Request, *args, **kwargs) -> response.Response:
        """Run this node with its upstream dependencies or downstream dependents."""
        body = NodeRunSerializer(data=req.data)
        if not body.is_valid():
            return response.Response(
                {"error": "direction must be 'upstream' or 'downstream'"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        node = self.get_object()

        if node.type not in SAVED_QUERY_NODE_TYPES:
            return response.Response(
                {"error": f"Cannot run a {node.type} node"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            node_ids = run_related_node_materializations(
                node.team_id,
                node.id,
                direction=body.validated_data["direction"],
                user=cast(User, req.user),
                hidden_types=self._hidden_node_types(),
            )
        except MaterializationForbiddenError as error:
            raise PermissionDenied(str(error))
        return response.Response({"node_ids": node_ids}, status=status.HTTP_200_OK)

    def _lineage_lookup(self, req: request.Request) -> dict[str, UUID]:
        by_param = {
            "id": req.query_params.get("node_id"),
            "saved_query_id": req.query_params.get("saved_query_id"),
            "metric_id": req.query_params.get("metric_id"),
        }
        given = {field: value for field, value in by_param.items() if value}
        if not given:
            raise LineageLookupError("node_id, saved_query_id or metric_id is required")
        field, value = next(iter(given.items()))
        try:
            return {field: UUID(value)}
        except ValueError:
            raise LineageLookupError("Invalid UUID")

    @extend_schema(
        parameters=[
            OpenApiParameter("node_id", OpenApiTypes.UUID, description="Node to build lineage for."),
            OpenApiParameter(
                "saved_query_id",
                OpenApiTypes.UUID,
                description="Saved query to build lineage for, resolved to its node. Alternative to node_id.",
            ),
            OpenApiParameter(
                "metric_id",
                OpenApiTypes.UUID,
                description="Data catalog metric to build lineage for, resolved to its node. Alternative to node_id.",
            ),
        ],
        responses={200: LineageResponseSerializer},
    )
    @action(methods=["GET"], detail=False)
    def lineage(self, req: request.Request, *args, **kwargs) -> response.Response:
        """Return the subgraph of nodes and edges reachable from a node (upstream + downstream).

        Accepts node_id, saved_query_id or metric_id, so a caller holding only the backing resource
        (the SQL editor, the metric page) doesn't need to resolve the node itself.
        """
        # Lineage exposes the same metadata the deleted `warehouse_view`-scoped upstream endpoint
        # gated on.
        self._require_warehouse_access(level="viewer", message="Reading lineage requires data warehouse read access.")

        try:
            lookup = self._lineage_lookup(req)
        except LineageLookupError as error:
            return response.Response({"error": str(error)}, status=status.HTTP_400_BAD_REQUEST)

        # saved_query is a non-unique FK: a saved query synced into multiple DAGs has multiple nodes.
        # Order for a deterministic pick (the graphs are equivalent for lineage purposes).
        node = (
            self._exclude_hidden_nodes(Node.objects.filter(team_id=self.team_id, **lookup))
            .order_by("created_at")
            .first()
        )
        if node is None:
            return response.Response({"error": "Node not found"}, status=status.HTTP_404_NOT_FOUND)

        hidden_types = self._hidden_node_types()
        upstream_ids = _get_upstream_nodes(node, include_tables=True, hidden_types=hidden_types)
        downstream_ids = _get_downstream_nodes(node, hidden_types=hidden_types)
        all_ids = upstream_ids | downstream_ids | {str(node.id)}

        nodes = self._exclude_hidden_nodes(
            _node_queryset_with_latest_job().filter(id__in=all_ids, team_id=self.team_id)
        )
        edges = self._exclude_hidden_edges(
            Edge.objects.select_related("source", "target", "dag").filter(
                team_id=self.team_id, source_id__in=all_ids, target_id__in=all_ids
            )
        )

        return response.Response(
            LineageResponseSerializer({"nodes": nodes, "edges": edges}, context=self.get_serializer_context()).data
        )

    @action(methods=["POST"], detail=True)
    def materialize(self, req: request.Request, *args, **kwargs) -> response.Response:
        """Materialize just this single node."""
        from products.data_modeling.backend.facade.api import start_node_materialization

        node = self.get_object()

        if node.type not in SAVED_QUERY_NODE_TYPES:
            return response.Response(
                {"error": f"Cannot materialize a {node.type} node"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Publishes the same rows as a DAG run of this node, so it needs the same check as `run`.
        # A DB constraint guarantees non-table nodes have a saved query, so the None branch never
        # skips the check for a real node; it exists because the FK is typed as nullable.
        if node.saved_query is not None:
            assert_user_can_read_query(node.saved_query.query, self.team_id, cast(User, req.user))

        start_node_materialization(node, triggered_by_id=req.user.pk)

        return response.Response(status=status.HTTP_200_OK)

    @extend_schema(request=None, responses={200: NodeResumeSerializer})
    @action(methods=["POST"], detail=True)
    def resume(self, req: request.Request, *args, **kwargs) -> response.Response:
        """Resume a node suspended after repeated failed materializations.

        Scheduled runs skip a suspended node and its descendants, so it cannot succeed its way back
        on its own. Resuming also gives it a fresh failure window rather than re-suspending on the
        next failure.
        """
        # Resuming puts a model back on the materialization schedule, so it needs write access.
        self._require_warehouse_access(level="editor", message="Resuming a node requires data warehouse write access.")

        resumed = unsuspend_nodes([self.get_object()], by="api")

        return response.Response({"resumed": bool(resumed)}, status=status.HTTP_200_OK)
