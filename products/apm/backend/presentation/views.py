"""
DRF views for apm.

Validate JSON via serializers, call facade methods,
return serialized responses. No business logic here.
"""

from dataclasses import asdict
from datetime import datetime, timedelta
from typing import cast

from django.utils import timezone

from drf_spectacular.utils import extend_schema
from rest_framework import status, viewsets
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.schema import ProductKey

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.clickhouse.query_tagging import Feature, tag_queries
from posthog.dataclasses import frozen
from posthog.models import Team
from posthog.models.user import User

from products.apm.backend.facade.api import get_service_map, is_apm_enabled, list_endpoints_health, list_services_health
from products.apm.backend.presentation.serializers import (
    EndpointsHealthRequestSerializer,
    EndpointsHealthResponseSerializer,
    ServiceMapResponseSerializer,
    ServicesHealthRequestSerializer,
    ServicesHealthResponseSerializer,
)

DEFAULT_WINDOW = timedelta(hours=1)
MAX_WINDOW = timedelta(days=7)
DEFAULT_ENVIRONMENT = "default"


def _check_flag(team: Team, user: User) -> None:
    email = None if user.anonymize_data else user.email
    if not is_apm_enabled(team.pk, distinct_id=str(user.distinct_id), email=email):
        raise PermissionDenied("Application observability is not enabled for this project.")


@frozen
class HealthWindow:
    date_from: datetime
    date_to: datetime
    environment: str


def _window(params: ServicesHealthRequestSerializer) -> HealthWindow:
    """The window and environment every APM health route reads, with the same defaults and cap."""
    params.is_valid(raise_exception=True)
    date_to = params.validated_data.get("date_to") or timezone.now()
    date_from = params.validated_data.get("date_from") or date_to - DEFAULT_WINDOW
    if date_from >= date_to or date_to - date_from > MAX_WINDOW:
        raise ValidationError("date_from must precede date_to by at most 7 days.")
    return HealthWindow(
        date_from=date_from,
        date_to=date_to,
        environment=params.validated_data.get("environment") or DEFAULT_ENVIRONMENT,
    )


class ServicesHealthViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    """One health row per service in an environment and window, worst first.

    Read-only, and dark for every team without the product flag: the flag gates the scene, the
    nav entry, and this endpoint together.
    """

    scope_object = "tracing"

    @extend_schema(parameters=[ServicesHealthRequestSerializer], responses={200: ServicesHealthResponseSerializer})
    def list(self, request: Request, *args, **kwargs) -> Response:
        _check_flag(self.team, cast(User, request.user))
        tag_queries(product=ProductKey.TRACING, feature=Feature.QUERY)
        window = _window(ServicesHealthRequestSerializer(data=request.query_params))

        result = list_services_health(
            team=self.team, date_from=window.date_from, date_to=window.date_to, environment=window.environment
        )
        payload = {
            "results": [
                {**asdict(row), "status": row.status.value, "sparkline": list(row.sparkline)} for row in result.services
            ],
            "environments": result.environments,
            "environment": window.environment,
            "date_from": window.date_from,
            "date_to": window.date_to,
        }
        return Response(ServicesHealthResponseSerializer(payload).data, status=status.HTTP_200_OK)


class EndpointsHealthViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    """One health row per service and entry span name, worst first. Same gate and window as services."""

    scope_object = "tracing"

    @extend_schema(parameters=[EndpointsHealthRequestSerializer], responses={200: EndpointsHealthResponseSerializer})
    def list(self, request: Request, *args, **kwargs) -> Response:
        _check_flag(self.team, cast(User, request.user))
        tag_queries(product=ProductKey.TRACING, feature=Feature.QUERY)
        params = EndpointsHealthRequestSerializer(data=request.query_params)
        window = _window(params)
        service = params.validated_data.get("service")

        rows = list_endpoints_health(
            team=self.team,
            date_from=window.date_from,
            date_to=window.date_to,
            environment=window.environment,
            service=service,
        )
        payload = {
            "results": [{**asdict(row), "status": row.status.value} for row in rows],
            "environment": window.environment,
            "service": service,
            "date_from": window.date_from,
            "date_to": window.date_to,
        }
        return Response(EndpointsHealthResponseSerializer(payload).data, status=status.HTTP_200_OK)


class ServiceMapViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    """Service-to-service call edges in an environment and window. Same gate and window as services."""

    scope_object = "tracing"

    @extend_schema(parameters=[ServicesHealthRequestSerializer], responses={200: ServiceMapResponseSerializer})
    def list(self, request: Request, *args, **kwargs) -> Response:
        _check_flag(self.team, cast(User, request.user))
        tag_queries(product=ProductKey.TRACING, feature=Feature.QUERY)
        window = _window(ServicesHealthRequestSerializer(data=request.query_params))

        result = get_service_map(
            team=self.team, date_from=window.date_from, date_to=window.date_to, environment=window.environment
        )
        payload = {
            "edges": [asdict(edge) for edge in result.edges],
            "trace_count": result.trace_count,
            "environment": window.environment,
            "date_from": window.date_from,
            "date_to": window.date_to,
        }
        return Response(ServiceMapResponseSerializer(payload).data, status=status.HTTP_200_OK)
