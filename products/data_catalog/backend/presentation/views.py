"""DRF views for data_catalog.

Thin: validate via the serializer, call the facade, serialize the result. Domain invariants
(name reservation, upsert, validation, drift, approval) live in the logic layer behind the facade.
"""

from typing import cast

from django.db.models import QuerySet

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action as drf_action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import BaseThrottle
from rest_framework.views import APIView

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action
from posthog.models import User
from posthog.rate_limit import ClickHouseBurstRateThrottle, ClickHouseSustainedRateThrottle, HogQLQueryThrottle

from ..facade import api
from ..facade.enums import HOGQL_DEFINITION_KIND, INSIGHT_DEFINITION_KINDS, NODE_DEFINITION_KINDS
from ..facade.models import Metric, RelationshipProposal, TableCertification
from .serializers import (
    CertificationCreateSerializer,
    CertificationSerializer,
    MetricRunQuerySerializer,
    MetricRunRequestSerializer,
    MetricRunResponseSerializer,
    MetricSerializer,
    RelationshipProposalSerializer,
    RelationshipRejectSerializer,
)

# Kinds that execute a ClickHouse query through the trends/funnels pipeline (node kinds run as a
# wrapped single-series trends query).
_STRUCTURED_QUERY_KINDS = {*INSIGHT_DEFINITION_KINDS, *NODE_DEFINITION_KINDS}


class MetricViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    """CRUD for catalog metrics, addressed by their reserved ``name`` (e.g. /metrics/mrr/)."""

    scope_object = "data_catalog"
    lookup_field = "name"
    serializer_class = MetricSerializer
    queryset = Metric.objects.unscoped()

    def safely_get_queryset(self, queryset: QuerySet[Metric]) -> QuerySet[Metric]:
        return queryset.filter(team_id=self.team_id, deleted=False).order_by("-created_at")

    def dangerously_get_required_scopes(self, request: Request, view: APIView) -> list[str] | None:
        if getattr(view, "action", None) not in ("create", "update", "partial_update"):
            return None
        if isinstance(request.data, dict) and request.data.get("source_insight_short_id"):
            return ["data_catalog:write", "insight:read"]
        return None

    def get_throttles(self) -> list[BaseThrottle]:
        # Running a metric executes a query, so it must carry the same query throttles as /query/;
        # markdown and definition-less metrics never reach ClickHouse and keep the API defaults.
        if getattr(self, "action", None) == "run":
            kind = (
                Metric.objects.for_team(self.team_id)
                .filter(name=self.kwargs.get("name"), deleted=False)
                .values_list("definition__kind", flat=True)
                .first()
            )
            if kind == HOGQL_DEFINITION_KIND:
                return [HogQLQueryThrottle()]
            if kind in _STRUCTURED_QUERY_KINDS:
                return [ClickHouseBurstRateThrottle(), ClickHouseSustainedRateThrottle()]
        return super().get_throttles()

    def list(self, request: Request, *args, **kwargs) -> Response:
        # Precompute drift for the whole page in one bulk query, so is_drifted doesn't fan out
        # into a per-metric insight lookup (an N+1 over the catalog list).
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        metrics = page if page is not None else list(queryset)
        context = {**self.get_serializer_context(), "drift_map": api.compute_drift(metrics)}
        serializer = self.get_serializer(metrics, many=True, context=context)
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)

    @extend_schema(description="Create a metric, or refine the one already holding this name for the team.")
    def create(self, request: Request, *args, **kwargs) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        # Pass only the fields the client actually sent, so an upsert that refines an existing metric
        # leaves omitted fields (a stored definition, provenance, ...) untouched rather than resetting them.
        optional = {
            key: data[key]
            for key in (
                "display_name",
                "unit",
                "definition",
                "source_insight_short_id",
                "created_source",
                "ai_model",
                "confidence",
                "reasoning",
            )
            if key in data
        }
        metric = api.upsert_metric(
            team=self.team,
            user=cast(User, request.user),
            name=data["name"],
            description=data["description"],
            **optional,
        )
        return Response(self.get_serializer(metric).data, status=status.HTTP_201_CREATED)

    def update(self, request: Request, *args, **kwargs) -> Response:
        partial = kwargs.pop("partial", False)
        metric = self.get_object()
        serializer = self.get_serializer(metric, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        fields = dict(serializer.validated_data)
        if "name" in fields and fields["name"] != metric.name:
            raise ValidationError({"name": "Metric name is write-once and cannot be changed."})
        fields.pop("name", None)
        metric = api.update_metric(metric, team=self.team, user=cast(User, request.user), **fields)
        return Response(self.get_serializer(metric).data)

    def perform_destroy(self, instance: Metric) -> None:
        api.soft_delete_metric(instance, cast(User, self.request.user))

    @action(
        detail=True,
        methods=["POST"],
        required_scopes=["data_catalog_approval:write", "data_catalog:read"],
        request=None,
        responses={200: MetricSerializer},
    )
    def approve(self, request: Request, **kwargs) -> Response:
        """Bless a metric as canonical. Returns 409 while the metric is drifted from its insight."""
        metric = api.approve_metric(self.get_object(), cast(User, request.user))
        return Response(self.get_serializer(metric).data)

    @action(
        detail=True,
        methods=["POST"],
        url_path="refresh_from_insight",
        required_scopes=["data_catalog:write", "insight:read"],
        request=None,
        responses={200: MetricSerializer},
    )
    def refresh_from_insight(self, request: Request, **kwargs) -> Response:
        """Re-snapshot the linked insight's current query into the definition."""
        metric = api.refresh_metric_from_insight(self.get_object(), cast(User, request.user))
        return Response(self.get_serializer(metric).data)

    # @extend_schema must sit OUTSIDE @action: DRF's @action resets func.kwargs, wiping any schema
    # annotation applied earlier — including @validated_request's — from the generated OpenAPI.
    @extend_schema(
        request=MetricRunRequestSerializer,
        parameters=[MetricRunQuerySerializer],
        responses={
            200: OpenApiResponse(response=MetricRunResponseSerializer, description="The normalized run envelope."),
            400: OpenApiResponse(
                description="The metric has no runnable definition, an override is invalid for its kind, or the query failed."
            ),
            429: OpenApiResponse(description="Query rate limit or concurrency limit exceeded."),
            500: OpenApiResponse(description="Unexpected error while executing the query."),
        },
    )
    @drf_action(
        detail=True,
        methods=["POST"],
        required_scopes=["data_catalog:read", "query:read"],
    )
    @validated_request(
        request_serializer=MetricRunRequestSerializer,
        query_serializer=MetricRunQuerySerializer,
    )
    def run(self, request: ValidatedRequest, **kwargs) -> Response:
        """Execute the metric's definition and return the normalized result envelope."""
        # required_scopes gates tokens on query:read, but session users carry no scopes and
        # AccessControlPermission only checks the data_catalog resource. Enforce query RBAC
        # explicitly so a member with query access denied can't read data through a metric run.
        if not self.user_access_control.check_access_level_for_resource("query", "viewer"):
            raise PermissionDenied("You need query access to run a metric.")
        overrides = request.validated_data
        envelope = api.run_metric(
            team=self.team,
            metric=self.get_object(),
            user=cast(User, request.user),
            refresh=request.validated_query_data.get("refresh"),
            date_from=overrides.get("date_from"),
            date_to=overrides.get("date_to"),
            interval=overrides.get("interval"),
            query_id=overrides.get("query_id"),
        )
        return Response(envelope)


class CertificationViewSet(
    TeamAndOrgViewSetMixin,
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """Trust marks on warehouse tables and views. Reads exclude soft-deleted targets."""

    scope_object = "data_catalog"
    serializer_class = CertificationSerializer
    queryset = TableCertification.objects.unscoped()

    def safely_get_queryset(self, queryset: QuerySet[TableCertification]) -> QuerySet[TableCertification]:
        return api.certifications_for_team(self.team)

    def dangerously_get_required_scopes(self, request: Request, view: APIView) -> list[str] | None:
        if getattr(view, "action", None) == "destroy":
            return ["data_catalog_approval:write", "data_catalog:read"]
        return None

    @extend_schema(request=CertificationCreateSerializer, responses={201: CertificationSerializer})
    def create(self, request: Request, *args, **kwargs) -> Response:
        serializer = CertificationCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        cert = api.propose_certification(team=self.team, user=cast(User, request.user), **serializer.validated_data)
        return Response(CertificationSerializer(cert).data, status=status.HTTP_201_CREATED)

    def perform_destroy(self, instance: TableCertification) -> None:
        api.revoke_certification(instance, cast(User, self.request.user))

    @action(
        detail=True,
        methods=["POST"],
        required_scopes=["data_catalog_approval:write", "data_catalog:read"],
        request=None,
        responses={200: CertificationSerializer},
    )
    def certify(self, request: Request, **kwargs) -> Response:
        """Mark the target as certified (prefer this source)."""
        cert = api.certify(self.get_object(), cast(User, request.user))
        return Response(CertificationSerializer(cert).data)

    @action(
        detail=True,
        methods=["POST"],
        required_scopes=["data_catalog_approval:write", "data_catalog:read"],
        request=None,
        responses={200: CertificationSerializer},
    )
    def deprecate(self, request: Request, **kwargs) -> Response:
        """Mark the target as deprecated (avoid this source)."""
        cert = api.deprecate(self.get_object(), cast(User, request.user))
        return Response(CertificationSerializer(cert).data)


class RelationshipProposalViewSet(
    TeamAndOrgViewSetMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    """Reviewed join facts. Accepting one promotes it to a real DataWarehouseJoin; rejections persist."""

    scope_object = "data_catalog"
    serializer_class = RelationshipProposalSerializer
    queryset = RelationshipProposal.objects.unscoped()

    def safely_get_queryset(self, queryset: QuerySet[RelationshipProposal]) -> QuerySet[RelationshipProposal]:
        proposals = api.relationships_for_team(self.team)
        status_filter = self.request.query_params.get("status")
        return proposals.filter(status=status_filter) if status_filter else proposals

    @extend_schema(
        parameters=[OpenApiParameter("status", OpenApiTypes.STR, description="Filter by proposed/accepted/rejected.")]
    )
    def list(self, request: Request, *args, **kwargs) -> Response:
        return super().list(request, *args, **kwargs)

    def create(self, request: Request, *args, **kwargs) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        proposal = api.propose_relationship(
            team=self.team,
            user=cast(User, request.user),
            source_table_name=data["source_table_name"],
            source_table_key=data["source_table_key"],
            joining_table_name=data["joining_table_name"],
            joining_table_key=data["joining_table_key"],
            field_name=data["field_name"],
            configuration=data.get("configuration"),
            confidence=data.get("confidence"),
            reasoning=data.get("reasoning", ""),
            evidence=data.get("evidence"),
        )
        return Response(self.get_serializer(proposal).data, status=status.HTTP_201_CREATED)

    @action(
        detail=True,
        methods=["POST"],
        required_scopes=["data_catalog_approval:write", "data_catalog:read", "query:read", "warehouse_view:write"],
        throttle_classes=[HogQLQueryThrottle],
        request=None,
        responses={200: RelationshipProposalSerializer},
    )
    def accept(self, request: Request, **kwargs) -> Response:
        """Promote the proposal to a real warehouse join after re-validating and probing it."""
        # required_scopes gates tokens, but session users carry no scopes and AccessControlPermission
        # only checks the data_catalog resource. Enforce the resources this action actually touches
        # explicitly: query (the ClickHouse acceptance probe) and warehouse_view (the join it creates).
        if not self.user_access_control.check_access_level_for_resource("query", "viewer"):
            raise PermissionDenied("You need query access to accept a relationship proposal.")
        if not self.user_access_control.check_access_level_for_resource("warehouse_view", "editor"):
            raise PermissionDenied("You need warehouse view edit access to accept a relationship proposal.")
        proposal = api.accept_proposal(self.get_object(), cast(User, request.user))
        return Response(self.get_serializer(proposal).data)

    @extend_schema(request=RelationshipRejectSerializer, responses={200: RelationshipProposalSerializer})
    @action(detail=True, methods=["POST"], required_scopes=["data_catalog_approval:write", "data_catalog:read"])
    def reject(self, request: Request, **kwargs) -> Response:
        """Reject the proposal. Persists forever so the pair is never re-proposed."""
        body = RelationshipRejectSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        proposal = api.reject_proposal(
            self.get_object(), cast(User, request.user), body.validated_data.get("rejection_reason", "")
        )
        return Response(self.get_serializer(proposal).data)
