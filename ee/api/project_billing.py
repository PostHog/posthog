"""Billing reads for one project: its usage and its share of the organization's spend.

Every read is the organization read pinned to the project's teams. A project's numbers match what
the organization routes report for it, and billing serves no new query.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, Optional

from django.http import StreamingHttpResponse

import requests
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import permissions, serializers
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.auth import ProjectSecretAPIKeyAuthentication
from posthog.models import Team
from posthog.permissions import PostHogFeatureFlagPermission
from posthog.rate_limit import BillingReadBurstRateThrottle, BillingReadSustainedRateThrottle

from ee.api.billing import BillingExportThrottle, BillingQueryTimeout, BillingUsageRequestSerializer
from ee.api.organization_billing import (
    BETA_NOTICE,
    BillingPeriodSerializer,
    BillingReadViewSet,
    PaginatedBillingTimeSeriesPointListSerializer,
    _billing_period,
)
from ee.billing.grants import BillingEntitlement

PROJECT_BREAKDOWNS_MESSAGE = 'Pass `["type"]` for a series per product, or omit breakdowns for one series.'


class ProjectTimeseriesRequestSerializer(BillingUsageRequestSerializer):
    """One project's series: the organization series' parameters without the project filter, the
    project fold and paging, because the route already names the project."""

    team_ids = None  # type: ignore[assignment]
    top_projects = None  # type: ignore[assignment]
    page_size = None  # type: ignore[assignment]
    after = None  # type: ignore[assignment]
    breakdowns = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        help_text=(
            'JSON-encoded array of breakdown dimensions. Omit it for one series across the project. Pass `["type"]` '
            "for a series per product."
        ),
    )

    def validate_breakdowns(self, value: Optional[str]) -> Optional[str]:
        value = super().validate_breakdowns(value)
        if value and json.loads(value) not in ([], ["type"]):
            raise serializers.ValidationError(PROJECT_BREAKDOWNS_MESSAGE)
        return value


class ProjectUsageItemSerializer(serializers.Serializer):
    usage_key = serializers.CharField(help_text="The usage counter, as the usage series names it.")
    name = serializers.CharField(help_text="The counter's display name.")
    usage = serializers.FloatField(help_text="The project's usage of the counter so far this billing period.")


class ProjectUsageSummarySerializer(serializers.Serializer):
    billing_period = BillingPeriodSerializer(
        allow_null=True,
        help_text=(
            "The period the usage covers. Null when the organization has no billing period yet, and the usage then "
            "covers the current calendar month in UTC."
        ),
    )
    results = ProjectUsageItemSerializer(many=True, help_text="One entry per usage counter the project reported.")


PROJECT_BILLING_READ_ACTIONS = ["usage", "usage_timeseries", "spend_timeseries", "usage_export", "spend_export"]
EXPORT_THROTTLES = [BillingReadBurstRateThrottle, BillingReadSustainedRateThrottle, BillingExportThrottle]


@extend_schema(extensions={"x-product": "billing"})
class ProjectBillingViewSet(BillingReadViewSet):
    """Read one project's usage and its share of the organization's spend.

    A credential reaches a project when it covers the project. An organization-wide session, personal
    key or OAuth token covers every project. A project-scoped key covers its projects, and a project
    secret key with `billing:read` covers its own project.
    """

    authentication_classes = [ProjectSecretAPIKeyAuthentication]
    psak_allowed_actions = PROJECT_BILLING_READ_ACTIONS
    scope_object_read_actions = PROJECT_BILLING_READ_ACTIONS
    # The routing mixin adds the project membership check for project routes.
    permission_classes = [permissions.IsAuthenticated, PostHogFeatureFlagPermission]

    def _project_team_ids(self) -> list[int]:
        """Every team in the project. Billing reports usage per team, and a project's environments are
        its teams."""
        return sorted(
            Team.objects.filter(project_id=self.team.project_id, organization_id=self.organization.id).values_list(
                "id", flat=True
            )
        )

    @extend_schema(
        operation_id="billing_project_usage_retrieve",
        summary="Get a project's usage so far this billing period",
        description=BETA_NOTICE,
        responses={200: OpenApiResponse(response=ProjectUsageSummarySerializer)},
    )
    @action(methods=["GET"], detail=False, url_path="usage")
    def usage(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        organization = self.organization
        grants = self._grants(request, organization)
        self._require(grants, BillingEntitlement.USAGE_READ)
        manager = self._manager()
        period = _billing_period(manager.get_organization_subscription(organization, grants).get("billing_period"))
        today = datetime.now(UTC).date()
        period_start = (period or {}).get("current_period_start")
        start_date = period_start[:10] if period_start else today.replace(day=1).isoformat()
        params: dict[str, Any] = {
            "start_date": start_date,
            "end_date": today.isoformat(),
            "breakdowns": json.dumps(["type"]),
            "team_ids": json.dumps(self._project_team_ids()),
        }
        self._scope_projects(request, grants, organization, params)
        try:
            data = manager.get_organization_timeseries(organization, grants, "usage", params)
        except requests.Timeout:
            raise BillingQueryTimeout()
        results = [
            {
                "usage_key": _usage_key(series.get("breakdown_value")),
                "name": series.get("label") or "",
                "usage": float(sum(value or 0 for value in series.get("data") or [])),
            }
            for series in data.get("results", [])
        ]
        return Response({"billing_period": period, "results": results})

    @extend_schema(
        operation_id="billing_project_usage_timeseries_retrieve",
        summary="A project's usage over time",
        description=BETA_NOTICE,
        parameters=[ProjectTimeseriesRequestSerializer],
        responses={200: OpenApiResponse(response=PaginatedBillingTimeSeriesPointListSerializer)},
    )
    @action(methods=["GET"], detail=False, url_path="usage/timeseries")
    def usage_timeseries(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return self._timeseries(
            request, "usage", ProjectTimeseriesRequestSerializer, pinned_team_ids=self._project_team_ids()
        )

    @extend_schema(
        operation_id="billing_project_spend_timeseries_retrieve",
        summary="A project's share of spend over time",
        description=BETA_NOTICE,
        parameters=[ProjectTimeseriesRequestSerializer],
        responses={200: OpenApiResponse(response=PaginatedBillingTimeSeriesPointListSerializer)},
    )
    @action(methods=["GET"], detail=False, url_path="spend/timeseries")
    def spend_timeseries(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return self._timeseries(
            request, "spend", ProjectTimeseriesRequestSerializer, pinned_team_ids=self._project_team_ids()
        )

    @extend_schema(
        operation_id="billing_project_usage_export_download",
        summary="Export a project's usage as CSV",
        description=BETA_NOTICE,
        parameters=[ProjectTimeseriesRequestSerializer],
        responses={(200, "text/csv"): OpenApiResponse(response=bytes)},
    )
    @action(methods=["GET"], detail=False, url_path="usage/export", throttle_classes=EXPORT_THROTTLES)
    def usage_export(self, request: Request, *args: Any, **kwargs: Any) -> StreamingHttpResponse:
        return self._export(
            request, "usage", ProjectTimeseriesRequestSerializer, pinned_team_ids=self._project_team_ids()
        )

    @extend_schema(
        operation_id="billing_project_spend_export_download",
        summary="Export a project's share of spend as CSV",
        description=BETA_NOTICE,
        parameters=[ProjectTimeseriesRequestSerializer],
        responses={(200, "text/csv"): OpenApiResponse(response=bytes)},
    )
    @action(methods=["GET"], detail=False, url_path="spend/export", throttle_classes=EXPORT_THROTTLES)
    def spend_export(self, request: Request, *args: Any, **kwargs: Any) -> StreamingHttpResponse:
        return self._export(
            request, "spend", ProjectTimeseriesRequestSerializer, pinned_team_ids=self._project_team_ids()
        )


def _usage_key(breakdown_value: Any) -> str:
    """The product dimension of a series broken down by type. Billing sends it alone or as the first
    of the breakdown's values."""
    if isinstance(breakdown_value, list):
        return str(breakdown_value[0]) if breakdown_value else ""
    return str(breakdown_value or "")
