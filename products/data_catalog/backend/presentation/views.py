"""DRF views for data_catalog.

Thin: validate via the serializer, call the facade, serialize the result. Domain invariants
(name reservation, upsert, validation, drift, approval) live in the logic layer behind the facade.
"""

from typing import cast

from django.db.models import QuerySet

from drf_spectacular.utils import extend_schema
from rest_framework import status, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action
from posthog.models import User
from posthog.utils import refresh_requested_by_client

from ..facade import api
from ..facade.models import Metric
from .serializers import MetricRunRequestSerializer, MetricRunResponseSerializer, MetricSerializer


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

    @action(
        detail=True,
        methods=["POST"],
        required_scopes=["data_catalog:read", "query:read"],
        request=MetricRunRequestSerializer,
        responses={200: MetricRunResponseSerializer},
    )
    def run(self, request: Request, **kwargs) -> Response:
        """Execute the metric's definition and return the normalized result envelope."""
        envelope = api.run_metric(
            team=self.team,
            metric=self.get_object(),
            user=cast(User, request.user),
            refresh=refresh_requested_by_client(request),
            date_from=request.data.get("date_from"),
            date_to=request.data.get("date_to"),
            interval=request.data.get("interval"),
            query_id=request.data.get("query_id"),
        )
        return Response(envelope)
