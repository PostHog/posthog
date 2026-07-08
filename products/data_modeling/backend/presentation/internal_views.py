"""Read-only internal (service-to-service) API for the modeling-ops admin app.

Routes are wired manually in posthog/urls.py under
``api/projects/<team_id>/internal/data_modeling_ops/`` — Contour 403s the ``internal``
prefix at the edge, so these are unreachable from the internet and authenticated with
scoped JWTs (see internal_auth.py).
"""

import uuid

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Count, Q, QuerySet

from drf_spectacular.utils import extend_schema
from rest_framework import pagination, serializers, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.documentation import _FallbackSerializer
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models import Team
from posthog.ph_client import feature_enabled_or_false

from products.data_modeling.backend.facade.models import (
    DAG,
    DataModelingJob,
    DataModelingJobStatus,
    DataWarehouseSavedQuery,
    Edge,
    Node,
)
from products.data_modeling.backend.presentation.internal_auth import DataModelingOpsJWTAuthentication
from products.data_modeling.backend.presentation.internal_serializers import (
    InternalDAGSummarySerializer,
    InternalDataModelingJobSerializer,
    InternalEdgeSerializer,
    InternalNodeSerializer,
    InternalSavedQueryDetailSerializer,
    InternalSavedQuerySummarySerializer,
    InternalTeamOverviewSerializer,
)
from products.warehouse_sources.backend.facade.models import DataWarehouseTable

# Flag evaluation is project-group based, so any stable distinct_id gives the same answer.
DATA_MODELING_OPS_DISTINCT_ID = "data_modeling_ops_internal"


def _is_v2_backend_enabled_for_team(team: Team) -> bool:
    return feature_enabled_or_false(
        "data-modeling-backend-v2",
        DATA_MODELING_OPS_DISTINCT_ID,
        groups={
            "organization": str(team.organization_id),
            "project": str(team.id),
        },
        group_properties={
            "organization": {"id": str(team.organization_id)},
            "project": {"id": str(team.id)},
        },
    )


class InternalDataModelingOpsPagination(pagination.LimitOffsetPagination):
    default_limit = 100
    max_limit = 500


class InternalDataModelingOpsViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """Internal read-only endpoints for the modeling-ops admin app.

    Authenticated with scoped JWTs (DATA_MODELING_OPS_JWT_SECRET); not exposed through
    Contour ingress.
    """

    scope_object = "INTERNAL"
    serializer_class = _FallbackSerializer
    authentication_classes = [DataModelingOpsJWTAuthentication]

    def _paginate(
        self, request: Request, queryset: QuerySet, serializer_class: type[serializers.Serializer]
    ) -> Response:
        paginator = InternalDataModelingOpsPagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        serializer = serializer_class(page, many=True)
        return paginator.get_paginated_response(serializer.data)

    @extend_schema(exclude=True)
    def internal_overview(self, request: Request, team_id: str) -> Response:
        # Manual (non-router) paths don't populate the mixin's parents_query_dict, so the
        # team comes from the URL arg — the auth class already pinned the token to it.
        team = Team.objects.get(id=int(team_id))
        saved_queries = DataWarehouseSavedQuery.objects.filter(team_id=team.id).exclude(deleted=True)
        saved_query_counts = saved_queries.aggregate(
            total=Count("id"),
            materialized=Count("id", filter=Q(is_materialized=True)),
            failing=Count("id", filter=Q(status=DataWarehouseSavedQuery.Status.FAILED)),
            with_sync_frequency=Count("id", filter=Q(sync_frequency_interval__isnull=False)),
            endpoint_origin=Count("id", filter=Q(origin=DataWarehouseSavedQuery.Origin.ENDPOINT)),
        )
        serializer = InternalTeamOverviewSerializer(
            {
                "team_id": team.id,
                "v2_backend_enabled": _is_v2_backend_enabled_for_team(team),
                "dag_count": DAG.objects.filter(team_id=team.id).count(),
                "node_count": Node.objects.filter(team_id=team.id).count(),
                "saved_query_count": saved_query_counts["total"],
                "materialized_saved_query_count": saved_query_counts["materialized"],
                "failing_saved_query_count": saved_query_counts["failing"],
                "saved_queries_with_sync_frequency_count": saved_query_counts["with_sync_frequency"],
                "endpoint_origin_saved_query_count": saved_query_counts["endpoint_origin"],
            }
        )
        return Response(serializer.data)

    @extend_schema(exclude=True)
    def internal_saved_queries(self, request: Request, team_id: str) -> Response:
        queryset = (
            DataWarehouseSavedQuery.objects.filter(team_id=int(team_id)).exclude(deleted=True).order_by("-created_at")
        )
        status_filter = request.query_params.get("status")
        if status_filter:
            valid_statuses = set(DataWarehouseSavedQuery.Status.values)
            if status_filter not in valid_statuses:
                return Response(
                    {"error": f"Unknown status; expected one of {', '.join(sorted(valid_statuses))}"}, status=400
                )
            queryset = queryset.filter(status=status_filter)
        return self._paginate(request, queryset, InternalSavedQuerySummarySerializer)

    @extend_schema(exclude=True)
    def internal_saved_query_detail(self, request: Request, team_id: str, saved_query_id: str) -> Response:
        try:
            saved_query = DataWarehouseSavedQuery.objects.select_related("table", "created_by").get(
                team_id=int(team_id), id=saved_query_id
            )
        except (DataWarehouseSavedQuery.DoesNotExist, DjangoValidationError, ValueError):
            return Response({"error": "Saved query not found"}, status=404)

        saved_query_nodes = list(
            Node.objects.filter(team_id=int(team_id), saved_query=saved_query).select_related("dag")
        )
        node_ids = [node.id for node in saved_query_nodes]
        upstream_by_node: dict[uuid.UUID, list[str]] = {}
        for target_id, source_name in Edge.objects.filter(team_id=int(team_id), target_id__in=node_ids).values_list(
            "target_id", "source__name"
        ):
            upstream_by_node.setdefault(target_id, []).append(source_name)
        downstream_by_node: dict[uuid.UUID, list[str]] = {}
        for source_id, target_name in Edge.objects.filter(team_id=int(team_id), source_id__in=node_ids).values_list(
            "source_id", "target__name"
        ):
            downstream_by_node.setdefault(source_id, []).append(target_name)

        nodes = [
            {
                "node_id": node.id,
                "dag_id": node.dag_id,
                "dag_name": node.dag.name,
                "node_type": node.type,
                "upstream": upstream_by_node.get(node.id, []),
                "downstream": downstream_by_node.get(node.id, []),
            }
            for node in saved_query_nodes
        ]

        backing_tables = list(
            DataWarehouseTable.objects.filter(team_id=int(team_id), name=saved_query.name).exclude(deleted=True)
        )
        last_successful_job_at = (
            DataModelingJob.objects.filter(
                team_id=int(team_id), saved_query=saved_query, status=DataModelingJobStatus.COMPLETED
            )
            .order_by("-updated_at")
            .values_list("updated_at", flat=True)
            .first()
        )

        serializer = InternalSavedQueryDetailSerializer(
            saved_query,
            context={
                "nodes": nodes,
                "backing_tables": backing_tables,
                "linked_table_id": saved_query.table_id,
                "last_successful_job_at": last_successful_job_at,
            },
        )
        return Response(serializer.data)

    @extend_schema(exclude=True)
    def internal_saved_query_jobs(self, request: Request, team_id: str, saved_query_id: str) -> Response:
        try:
            queryset = DataModelingJob.objects.filter(team_id=int(team_id), saved_query_id=saved_query_id).order_by(
                "-created_at"
            )
            return self._paginate(request, queryset, InternalDataModelingJobSerializer)
        except (DjangoValidationError, ValueError):
            return Response({"error": "Saved query not found"}, status=404)

    @extend_schema(exclude=True)
    def internal_dags(self, request: Request, team_id: str) -> Response:
        queryset = DAG.objects.filter(team_id=int(team_id)).annotate(node_count=Count("node")).order_by("name")
        serializer = InternalDAGSummarySerializer(queryset, many=True)
        return Response({"results": serializer.data})

    @extend_schema(exclude=True)
    def internal_dag_detail(self, request: Request, team_id: str, dag_id: str) -> Response:
        try:
            dag = DAG.objects.annotate(node_count=Count("node")).get(team_id=int(team_id), id=dag_id)
        except (DAG.DoesNotExist, DjangoValidationError, ValueError):
            return Response({"error": "DAG not found"}, status=404)

        nodes = Node.objects.filter(team_id=int(team_id), dag=dag).order_by("name")
        edges = Edge.objects.filter(team_id=int(team_id), dag=dag)
        return Response(
            {
                "dag": InternalDAGSummarySerializer(dag).data,
                "nodes": InternalNodeSerializer(nodes, many=True).data,
                "edges": InternalEdgeSerializer(edges, many=True).data,
            }
        )
