"""
DRF views for apm.

Validate JSON via serializers, call facade methods,
return serialized responses. No business logic here.
"""

from dataclasses import asdict
from datetime import datetime, timedelta
from typing import Any, cast

from django.http import HttpRequest, HttpResponseBase
from django.utils import timezone

import structlog
from drf_spectacular.utils import extend_schema
from redis.exceptions import RedisError
from rest_framework import status, viewsets
from rest_framework.exceptions import PermissionDenied, Throttled, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.schema import ProductKey

from posthog.api.query import CONCURRENCY_LIMIT_USER_MESSAGE
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.auth import PersonalAPIKeyAuthentication
from posthog.clickhouse.client.limit import ConcurrencyLimitExceeded, ConcurrencySlot, get_logs_api_team_rate_limiter
from posthog.clickhouse.query_tagging import Feature, tag_queries
from posthog.dataclasses import frozen
from posthog.errors import CHQueryErrorTooManyBytes
from posthog.models import Team
from posthog.models.user import User

from products.apm.backend.facade.api import (
    get_dependencies,
    get_endpoint_time_spent,
    get_service_map,
    is_apm_enabled,
    list_deployments,
    list_endpoints_health,
    list_service_usage,
    list_services_health,
)
from products.apm.backend.presentation.serializers import (
    DependenciesRequestSerializer,
    DependenciesResponseSerializer,
    DeploymentsRequestSerializer,
    DeploymentsResponseSerializer,
    EndpointsHealthRequestSerializer,
    EndpointsHealthResponseSerializer,
    EndpointTimeSpentRequestSerializer,
    EndpointTimeSpentResponseSerializer,
    ServiceMapResponseSerializer,
    ServicesHealthRequestSerializer,
    ServicesHealthResponseSerializer,
    ServiceUsageResponseSerializer,
    WindowRequestSerializer,
)

logger = structlog.get_logger(__name__)

DEFAULT_WINDOW = timedelta(hours=1)
MAX_WINDOW = timedelta(days=7)


def _check_flag(team: Team, user: User) -> None:
    email = None if user.anonymize_data else user.email
    if not is_apm_enabled(team.pk, distinct_id=str(user.distinct_id), email=email):
        raise PermissionDenied("Application observability is not enabled for this project.")


@frozen
class HealthWindow:
    date_from: datetime
    date_to: datetime
    # None reads every environment. An empty string reads spans that set no environment.
    environment: str | None


def _window(params: WindowRequestSerializer) -> HealthWindow:
    """The window and environment every APM route reads, with the same defaults and cap."""
    params.is_valid(raise_exception=True)
    date_to = params.validated_data.get("date_to") or timezone.now()
    date_from = params.validated_data.get("date_from") or date_to - DEFAULT_WINDOW
    if date_from >= date_to or date_to - date_from > MAX_WINDOW:
        raise ValidationError("date_from must precede date_to by at most 7 days.")
    return HealthWindow(
        date_from=date_from,
        date_to=date_to,
        environment=params.validated_data.get("environment"),
    )


class _LogsClusterSlotMixin:
    """Takes a slot from the logs API's per-team concurrency cap for the whole request.

    APM reads the logs cluster through the same ClickHouse user as the logs API, so a burst of
    requests here can refuse logs queries for every team. By default only API keys take a slot,
    as in the logs API. A route whose single query is heavy takes one on every authenticator.
    """

    team_id: int
    slot_for_every_authenticator = False
    _logs_api_slot: ConcurrencySlot | None = None

    def initial(self, request: Request, *args: Any, **kwargs: Any) -> None:
        super().initial(request, *args, **kwargs)  # type: ignore[misc]
        if not self.slot_for_every_authenticator and not isinstance(
            request.successful_authenticator, PersonalAPIKeyAuthentication
        ):
            return
        try:
            self._logs_api_slot = get_logs_api_team_rate_limiter().use(team_id=self.team_id)
        except ConcurrencyLimitExceeded as error:
            logger.warning("apm_concurrency_limit_exceeded", team_id=self.team_id, detail=str(error))
            raise Throttled(wait=1, detail=CONCURRENCY_LIMIT_USER_MESSAGE) from error
        except RedisError:
            # The cap protects ClickHouse capacity. A Redis outage must not also make APM fail.
            logger.exception("apm_concurrency_limiter_unavailable", team_id=self.team_id)

    def dispatch(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponseBase:
        # DRF skips finalize_response when the exception handler re-raises, so only a finally block always releases.
        try:
            return super().dispatch(request, *args, **kwargs)  # type: ignore[misc]
        finally:
            if self._logs_api_slot is not None:
                try:
                    get_logs_api_team_rate_limiter().release(self._logs_api_slot)
                except RedisError:
                    logger.exception("apm_concurrency_slot_release_failed", team_id=self.team_id)
                self._logs_api_slot = None


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


class EndpointTimeSpentViewSet(_LogsClusterSlotMixin, TeamAndOrgViewSetMixin, viewsets.ViewSet):
    """Where one endpoint's request time goes, by service and inferred dependency. Same gate and window as services."""

    scope_object = "tracing"
    # Loads up to TIME_SPENT_SPAN_LIMIT spans per request, and the UI reloads it on every poll.
    slot_for_every_authenticator = True

    @extend_schema(
        parameters=[EndpointTimeSpentRequestSerializer], responses={200: EndpointTimeSpentResponseSerializer}
    )
    def list(self, request: Request, *args, **kwargs) -> Response:
        _check_flag(self.team, cast(User, request.user))
        tag_queries(product=ProductKey.TRACING, feature=Feature.QUERY)
        params = EndpointTimeSpentRequestSerializer(data=request.query_params)
        window = _window(params)
        service = params.validated_data["service"]
        endpoint = params.validated_data["endpoint"]

        result = get_endpoint_time_spent(
            team=self.team,
            date_from=window.date_from,
            date_to=window.date_to,
            environment=window.environment,
            service=service,
            endpoint=endpoint,
        )
        payload = {
            "components": [{**asdict(row), "kind": row.kind.value} for row in result.components],
            "request_count": result.request_count,
            "avg_duration_ms": result.avg_duration_ms,
            "service": service,
            "endpoint": endpoint,
            "environment": window.environment,
            "date_from": window.date_from,
            "date_to": window.date_to,
        }
        return Response(EndpointTimeSpentResponseSerializer(payload).data, status=status.HTTP_200_OK)


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


class DeploymentsViewSet(_LogsClusterSlotMixin, TeamAndOrgViewSetMixin, viewsets.ViewSet):
    """One service's versions in an environment and window, each compared with the one before. Same gate and window as services."""

    scope_object = "tracing"

    @extend_schema(parameters=[DeploymentsRequestSerializer], responses={200: DeploymentsResponseSerializer})
    def list(self, request: Request, *args, **kwargs) -> Response:
        _check_flag(self.team, cast(User, request.user))
        tag_queries(product=ProductKey.TRACING, feature=Feature.QUERY)
        params = DeploymentsRequestSerializer(data=request.query_params)
        window = _window(params)
        service = params.validated_data["service"]

        try:
            rows = list_deployments(
                team=self.team,
                date_from=window.date_from,
                date_to=window.date_to,
                environment=window.environment,
                service=service,
            )
        except CHQueryErrorTooManyBytes:
            raise ValidationError("This window reads too many spans. Pick a shorter window.")
        payload = {
            "results": [asdict(row) for row in rows],
            "service": service,
            "environment": window.environment,
            "date_from": window.date_from,
            "date_to": window.date_to,
        }
        return Response(DeploymentsResponseSerializer(payload).data, status=status.HTTP_200_OK)


class DependenciesViewSet(_LogsClusterSlotMixin, TeamAndOrgViewSetMixin, viewsets.ViewSet):
    """Caller to callee edges over the whole window, including inferred dependencies. Same gate and window as services."""

    scope_object = "tracing"
    # The whole-window self-join is the heaviest APM query, and the default throttles skip session requests.
    slot_for_every_authenticator = True

    @extend_schema(parameters=[DependenciesRequestSerializer], responses={200: DependenciesResponseSerializer})
    def list(self, request: Request, *args, **kwargs) -> Response:
        _check_flag(self.team, cast(User, request.user))
        tag_queries(product=ProductKey.TRACING, feature=Feature.QUERY)
        params = DependenciesRequestSerializer(data=request.query_params)
        window = _window(params)
        service = params.validated_data.get("service")

        try:
            result = get_dependencies(
                team=self.team,
                date_from=window.date_from,
                date_to=window.date_to,
                environment=window.environment,
                service=service,
            )
        except CHQueryErrorTooManyBytes:
            raise ValidationError("This window reads too many spans. Pick a shorter window or one service.")
        payload = {
            "edges": [{**asdict(edge), "kind": edge.kind.value} for edge in result.edges],
            "truncated": result.truncated,
            "environment": window.environment,
            "service": service,
            "date_from": window.date_from,
            "date_to": window.date_to,
        }
        return Response(DependenciesResponseSerializer(payload).data, status=status.HTTP_200_OK)


class ServiceUsageViewSet(_LogsClusterSlotMixin, TeamAndOrgViewSetMixin, viewsets.ViewSet):
    """How much each service sends across logs, traces, and metrics in a window. Same gate and window as services.

    Usage covers every environment: logs and metrics often carry no environment attribute, so a
    filter would hide the services that send the most.
    """

    scope_object = "tracing"
    # The response carries logs and metrics data too. Scopes gate tokens; access control gates members.
    required_scopes = ["tracing:read", "logs:read", "metrics:read"]

    @extend_schema(parameters=[WindowRequestSerializer], responses={200: ServiceUsageResponseSerializer})
    def list(self, request: Request, *args, **kwargs) -> Response:
        _check_flag(self.team, cast(User, request.user))
        for resource in ("logs", "metrics"):
            if not self.user_access_control.check_access_level_for_resource(resource, "viewer"):
                raise PermissionDenied(f"You do not have access to {resource}.")
        tag_queries(product=ProductKey.TRACING, feature=Feature.QUERY)
        window = _window(WindowRequestSerializer(data=request.query_params))

        result = list_service_usage(team=self.team, date_from=window.date_from, date_to=window.date_to)
        payload = {
            "results": [asdict(row) for row in result.services],
            "totals": asdict(result.totals),
            "unavailable_signals": [signal.value for signal in result.unavailable_signals],
            "date_from": window.date_from,
            "date_to": window.date_to,
        }
        return Response(ServiceUsageResponseSerializer(payload).data, status=status.HTTP_200_OK)
