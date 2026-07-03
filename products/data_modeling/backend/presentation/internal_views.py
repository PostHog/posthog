"""Read-only internal (service-to-service) API for the modeling-ops admin app.

Routes are wired manually in posthog/urls.py under ``api/internal/data_modeling_ops/`` —
Contour 403s that whole prefix at the edge, so these are unreachable from the internet,
and they are authenticated with OIDC ID tokens (see internal_auth.py).

The app reads across every team, so team is a ``?team_id=`` filter on lists rather than a
URL segment, and entities are fetched by their own globally unique id. A team-nested path
would read as a tenancy boundary, which this API deliberately does not have: any verified
operator may read any team.
"""

import uuid
from typing import Any, cast

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Count, Q, QuerySet

from drf_spectacular.utils import extend_schema
from rest_framework import pagination, serializers, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.documentation import _FallbackSerializer
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.auth import InternalAPIUser
from posthog.ph_client import feature_enabled_or_false

from products.data_modeling.backend.facade.models import (
    DAG,
    DataModelingJob,
    DataModelingJobStatus,
    DataWarehouseSavedQuery,
    Edge,
    Node,
)
from products.data_modeling.backend.logic.schedule_truth import SCHEDULE_CANDIDATE_CAP, describe_schedules
from products.data_modeling.backend.presentation.internal_auth import DataModelingOpsAuthenticationMixin
from products.data_modeling.backend.presentation.internal_serializers import (
    InternalDAGSummarySerializer,
    InternalDataModelingJobSerializer,
    InternalEdgeSerializer,
    InternalEntityScheduleSerializer,
    InternalNodeSerializer,
    InternalSavedQueryDetailSerializer,
    InternalSavedQuerySummarySerializer,
    InternalTeamOverviewSerializer,
)
from products.warehouse_sources.backend.facade.models import DataWarehouseTable

# Flag evaluation is project-group based, so any stable distinct_id gives the same answer.
DATA_MODELING_OPS_DISTINCT_ID = "data_modeling_ops_internal"


def _is_v2_backend_enabled(team_id: int, organization_id: str) -> bool:
    return feature_enabled_or_false(
        "data-modeling-backend-v2",
        DATA_MODELING_OPS_DISTINCT_ID,
        groups={
            "organization": organization_id,
            "project": str(team_id),
        },
        group_properties={
            "organization": {"id": organization_id},
            "project": {"id": str(team_id)},
        },
    )


def _saved_query_schedule_truth(saved_query: DataWarehouseSavedQuery, nodes: list[dict]) -> dict:
    """Which Temporal schedule covers this saved query: its own v1 schedule, a v2
    schedule on one of its DAGs, or none. Degrades to an error payload so a Temporal
    outage never takes down the detail endpoint."""
    try:
        own_id = str(saved_query.id)
        dag_ids = [str(node["dag_id"]) for node in nodes]
        descriptions = describe_schedules([own_id, *dag_ids])

        own = descriptions.get(own_id)
        dag_schedules = [
            {"dag_id": dag_id, "dag_name": node["dag_name"], "schedule": descriptions.get(dag_id)}
            for dag_id, node in zip(dag_ids, nodes)
        ]
        if any(entry["schedule"] and entry["schedule"]["kind"] == "v2_dag" for entry in dag_schedules):
            covered_by = "v2"
        elif own and own["kind"] == "v1_saved_query":
            covered_by = "v1"
        else:
            covered_by = "none"
        return {"covered_by": covered_by, "v1_schedule": own, "dag_schedules": dag_schedules}
    except Exception as error:
        return {"error": str(error)}


def team_id_filter(request: Request) -> int | None:
    """``?team_id=`` narrows a list to one team; absent means every team.

    The filter is deliberately not a URL segment: any verified operator may read any
    team here, so a team-nested path would imply a scoping guarantee this API does not
    make. Entities are found by their own (globally unique) id instead.
    """
    raw = request.query_params.get("team_id")
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        raise ValidationError({"team_id": "Must be an integer."})


def scoped_to_team(queryset: QuerySet, team_id: int | None) -> QuerySet:
    return queryset if team_id is None else queryset.filter(team_id=team_id)


class InternalDataModelingOpsPagination(pagination.LimitOffsetPagination):
    default_limit = 100
    max_limit = 500


class InternalDataModelingOpsViewSet(
    DataModelingOpsAuthenticationMixin, TeamAndOrgViewSetMixin, viewsets.GenericViewSet
):
    """Internal read-only endpoints for the modeling-ops admin app.

    Authenticated with OIDC ID tokens only (no session/PAT/OAuth fallback); not exposed
    through Contour ingress.
    """

    scope_object = "INTERNAL"
    serializer_class = _FallbackSerializer

    def _paginate(
        self, request: Request, queryset: QuerySet, serializer_class: type[serializers.Serializer]
    ) -> Response:
        paginator = InternalDataModelingOpsPagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        serializer = serializer_class(page, many=True)
        return paginator.get_paginated_response(serializer.data)

    @extend_schema(exclude=True)
    def internal_team_detail(self, request: Request, team_id: str, **kwargs: Any) -> Response:
        # Manual (non-router) paths don't populate the mixin's parents_query_dict. The
        # authenticator resolves this route's team_id kwarg, so reuse it here.
        user = cast(InternalAPIUser, request.user)
        team_pk = int(team_id)
        saved_queries = DataWarehouseSavedQuery.objects.filter(team_id=team_pk).exclude(deleted=True)
        saved_query_counts = saved_queries.aggregate(
            total=Count("id"),
            materialized=Count("id", filter=Q(is_materialized=True)),
            failing=Count("id", filter=Q(status=DataWarehouseSavedQuery.Status.FAILED)),
            with_sync_frequency=Count("id", filter=Q(sync_frequency_interval__isnull=False)),
            endpoint_origin=Count("id", filter=Q(origin=DataWarehouseSavedQuery.Origin.ENDPOINT)),
        )
        serializer = InternalTeamOverviewSerializer(
            {
                "team_id": team_pk,
                "v2_backend_enabled": _is_v2_backend_enabled(team_pk, str(user.current_organization_id)),
                "dag_count": DAG.objects.filter(team_id=team_pk).count(),
                "node_count": Node.objects.filter(team_id=team_pk).count(),
                "saved_query_count": saved_query_counts["total"],
                "materialized_saved_query_count": saved_query_counts["materialized"],
                "failing_saved_query_count": saved_query_counts["failing"],
                "saved_queries_with_sync_frequency_count": saved_query_counts["with_sync_frequency"],
                "endpoint_origin_saved_query_count": saved_query_counts["endpoint_origin"],
            }
        )
        return Response(serializer.data)

    @extend_schema(exclude=True)
    def internal_saved_queries(self, request: Request, **kwargs: Any) -> Response:
        queryset = scoped_to_team(
            DataWarehouseSavedQuery.objects.exclude(deleted=True), team_id_filter(request)
        ).order_by("-created_at")
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
    def internal_saved_query_detail(self, request: Request, saved_query_id: str, **kwargs: Any) -> Response:
        try:
            saved_query = (
                DataWarehouseSavedQuery.objects.select_related("table", "created_by")
                .exclude(deleted=True)
                .get(id=saved_query_id)
            )
        except (DataWarehouseSavedQuery.DoesNotExist, DjangoValidationError, ValueError):
            return Response({"error": "Saved query not found"}, status=404)

        # The saved query's own team scopes everything below it; the caller does not
        # supply one, since the id already identifies the row across every team.
        team_pk = saved_query.team_id
        saved_query_nodes = list(Node.objects.filter(team_id=team_pk, saved_query=saved_query).select_related("dag"))
        node_ids = [node.id for node in saved_query_nodes]
        upstream_by_node: dict[uuid.UUID, list[str]] = {}
        for target_id, source_name in Edge.objects.filter(team_id=team_pk, target_id__in=node_ids).values_list(
            "target_id", "source__name"
        ):
            upstream_by_node.setdefault(target_id, []).append(source_name)
        downstream_by_node: dict[uuid.UUID, list[str]] = {}
        for source_id, target_name in Edge.objects.filter(team_id=team_pk, source_id__in=node_ids).values_list(
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
            DataWarehouseTable.objects.filter(team_id=team_pk, name=saved_query.name).exclude(deleted=True)
        )
        last_successful_job_at = (
            DataModelingJob.objects.filter(
                team_id=team_pk, saved_query=saved_query, status=DataModelingJobStatus.COMPLETED
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
                "schedule_truth": _saved_query_schedule_truth(saved_query, nodes),
            },
        )
        return Response(serializer.data)

    @extend_schema(exclude=True)
    def internal_schedules(self, request: Request, team_id: str) -> Response:
        entities = [
            {"entity_type": "dag", "entity_id": str(dag["id"]), "entity_name": dag["name"]}
            for dag in DAG.objects.filter(team_id=int(team_id)).values("id", "name")
        ] + [
            {"entity_type": "saved_query", "entity_id": str(sq["id"]), "entity_name": sq["name"]}
            for sq in DataWarehouseSavedQuery.objects.filter(team_id=int(team_id))
            .exclude(deleted=True)
            .filter(Q(is_materialized=True) | Q(sync_frequency_interval__isnull=False))
            .values("id", "name")
        ]
        truncated = len(entities) > SCHEDULE_CANDIDATE_CAP
        entities = entities[:SCHEDULE_CANDIDATE_CAP]

        descriptions = describe_schedules([entity["entity_id"] for entity in entities])
        results = [{**entity, "schedule": descriptions.get(entity["entity_id"])} for entity in entities]
        return Response(
            {
                "results": InternalEntityScheduleSerializer(results, many=True).data,
                "truncated": truncated,
            }
        )

    @extend_schema(exclude=True)
    def internal_saved_query_jobs(self, request: Request, saved_query_id: str, **kwargs: Any) -> Response:
        try:
            parent = (
                DataWarehouseSavedQuery.objects.filter(id=saved_query_id)
                .exclude(deleted=True)
                .values_list("team_id", flat=True)
                .first()
            )
        except (DjangoValidationError, ValueError):
            return Response({"error": "Saved query not found"}, status=404)
        if parent is None:
            return Response({"error": "Saved query not found"}, status=404)

        queryset = DataModelingJob.objects.filter(team_id=parent, saved_query_id=saved_query_id).order_by("-created_at")
        return self._paginate(request, queryset, InternalDataModelingJobSerializer)

    @extend_schema(exclude=True)
    def internal_dags(self, request: Request, **kwargs: Any) -> Response:
        queryset = (
            scoped_to_team(DAG.objects.all(), team_id_filter(request))
            .annotate(node_count=Count("node"))
            .order_by("name")
        )
        return self._paginate(request, queryset, InternalDAGSummarySerializer)

    @extend_schema(exclude=True)
    def internal_dag_detail(self, request: Request, dag_id: str, **kwargs: Any) -> Response:
        try:
            dag = DAG.objects.annotate(node_count=Count("node")).get(id=dag_id)
        except (DAG.DoesNotExist, DjangoValidationError, ValueError):
            return Response({"error": "DAG not found"}, status=404)

        nodes = Node.objects.filter(team_id=dag.team_id, dag=dag).order_by("name")
        edges = Edge.objects.filter(team_id=dag.team_id, dag=dag)
        return Response(
            {
                "dag": InternalDAGSummarySerializer(dag).data,
                "nodes": InternalNodeSerializer(nodes, many=True).data,
                "edges": InternalEdgeSerializer(edges, many=True).data,
            }
        )
