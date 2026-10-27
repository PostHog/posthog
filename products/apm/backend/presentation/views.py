"""
DRF views for apm.

Validate JSON via serializers, call facade methods,
return serialized responses. No business logic here.
"""

from dataclasses import asdict
from datetime import timedelta

from django.utils import timezone

from drf_spectacular.utils import extend_schema
from rest_framework import status, viewsets
from rest_framework.exceptions import PermissionDenied
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.schema import ProductKey

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.clickhouse.query_tagging import Feature, tag_queries

from products.apm.backend.facade.api import is_apm_enabled, list_services_health
from products.apm.backend.presentation.serializers import (
    ServicesHealthRequestSerializer,
    ServicesHealthResponseSerializer,
)

DEFAULT_WINDOW = timedelta(hours=1)
MAX_WINDOW = timedelta(days=7)
DEFAULT_ENVIRONMENT = "default"


class ServicesHealthViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    """One health row per service in an environment and window, worst first.

    Read-only, and dark for every team without the product flag: the flag gates the scene, the
    nav entry, and this endpoint together.
    """

    scope_object = "tracing"

    def _check_flag(self) -> None:
        if not is_apm_enabled(self.team.pk):
            raise PermissionDenied("Application observability is not enabled for this project.")

    @extend_schema(parameters=[ServicesHealthRequestSerializer], responses={200: ServicesHealthResponseSerializer})
    def list(self, request: Request, *args, **kwargs) -> Response:
        self._check_flag()
        tag_queries(product=ProductKey.TRACING, feature=Feature.QUERY)
        params = ServicesHealthRequestSerializer(data=request.query_params)
        params.is_valid(raise_exception=True)
        date_to = params.validated_data.get("date_to") or timezone.now()
        date_from = params.validated_data.get("date_from") or date_to - DEFAULT_WINDOW
        if date_from >= date_to or date_to - date_from > MAX_WINDOW:
            return Response(
                {"detail": "date_from must precede date_to by at most 7 days."}, status=status.HTTP_400_BAD_REQUEST
            )
        environment = params.validated_data.get("environment") or DEFAULT_ENVIRONMENT

        result = list_services_health(team=self.team, date_from=date_from, date_to=date_to, environment=environment)
        payload = {
            "results": [
                {**asdict(row), "status": row.status.value, "sparkline": list(row.sparkline)} for row in result.services
            ],
            "environments": result.environments,
            "environment": environment,
            "date_from": date_from,
            "date_to": date_to,
        }
        return Response(ServicesHealthResponseSerializer(payload).data, status=status.HTTP_200_OK)
