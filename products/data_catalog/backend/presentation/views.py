"""DRF views for data_catalog.

Thin: validate via the serializer, call the facade, serialize the result. Domain invariants
(name reservation, upsert, validation) live in the logic layer behind the facade.
"""

from typing import cast

from django.db.models import QuerySet

from drf_spectacular.utils import extend_schema
from rest_framework import status, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models import User

from ..facade import api
from ..facade.models import Metric
from .serializers import MetricSerializer


class MetricViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    """CRUD for catalog metrics, addressed by their reserved ``name`` (e.g. /metrics/mrr/)."""

    scope_object = "data_catalog"
    lookup_field = "name"
    serializer_class = MetricSerializer
    queryset = Metric.objects.unscoped()

    def safely_get_queryset(self, queryset: QuerySet[Metric]) -> QuerySet[Metric]:
        return queryset.filter(team_id=self.team_id, deleted=False).order_by("-created_at")

    @extend_schema(description="Create a metric, or refine the one already holding this name for the team.")
    def create(self, request: Request, *args, **kwargs) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        # Pass only the fields the client actually sent, so an upsert that refines an existing metric
        # leaves omitted fields (a stored definition, provenance, ...) untouched rather than resetting them.
        optional = {
            key: data[key]
            for key in ("display_name", "unit", "definition", "created_source", "ai_model", "confidence", "reasoning")
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
        api.soft_delete_metric(instance)
