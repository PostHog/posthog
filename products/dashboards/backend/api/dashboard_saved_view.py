from drf_spectacular.utils import extend_schema
from rest_framework import viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin


@extend_schema(exclude=True)
class LegacyDashboardSavedViewViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    # Browser tabs that loaded the frontend before saved views were removed still call this list on
    # the dashboards page. An empty page lets them render without a load error until they reload.
    scope_object = "INTERNAL"

    def list(self, request: Request, *args: object, **kwargs: object) -> Response:
        return Response({"next": None, "previous": None, "results": []})
