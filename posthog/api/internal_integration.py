from typing import Any

import structlog
from rest_framework import viewsets
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.auth import InternalAPIAuthentication
from posthog.models.integration import Integration

logger = structlog.get_logger(__name__)


VALID_KINDS: set[str] = {value for value, _ in Integration.IntegrationKind.choices}


class InternalIntegrationViewSet(viewsets.ViewSet):
    """Service-to-service lookups across the global Integration table.

    Authenticated with `X-Internal-Api-Secret` and not exposed to external
    ingress. Used by sibling services (e.g. the chat SDK relay) to discover
    which PostHog team owns a given third-party identifier without knowing the
    team in advance.
    """

    authentication_classes = [InternalAPIAuthentication]
    permission_classes = [AllowAny]

    def lookup(self, request: Request, **kwargs: Any) -> Response:
        kind = request.data.get("kind")
        integration_id = request.data.get("integration_id")

        if not isinstance(kind, str) or kind not in VALID_KINDS:
            return Response({"error": "Invalid or unsupported kind"}, status=400)
        if not isinstance(integration_id, str) or not integration_id:
            return Response({"error": "integration_id is required"}, status=400)

        integration = (
            Integration.objects.filter(kind=kind, integration_id=integration_id)
            .select_related("team", "team__organization")
            .order_by("id")
            .first()
        )
        if integration is None:
            return Response({"error": "Integration not found"}, status=404)

        return Response(
            {
                "team_id": integration.team_id,
                "organization_id": str(integration.team.organization_id),
                "integration_pk": integration.id,
                "display_name": integration.display_name,
            }
        )
