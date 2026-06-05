from django.contrib import admin
from django.shortcuts import render

import httpx
import structlog
from rest_framework import serializers, status, viewsets
from rest_framework.permissions import IsAdminUser
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.llm.gateway_client import GatewayAdminError, get_posthog_code_usage, reset_posthog_code_usage

logger = structlog.get_logger(__name__)


class LLMGatewayResetSerializer(serializers.Serializer):
    reset_cost = serializers.BooleanField(default=True, help_text="Reset the live per-user cost counters")
    reset_request = serializers.BooleanField(
        default=False, help_text="Reset the (dormant) per-user request-rate counters"
    )
    reset_product_total = serializers.BooleanField(
        default=False, help_text="Reset the shared product-wide cost pool (affects all users)"
    )
    dry_run = serializers.BooleanField(default=False, help_text="Count keys without deleting")


def _gateway_error_response(exc: Exception) -> Response:
    if isinstance(exc, GatewayAdminError):
        # Misconfiguration (missing URL / secret) — a 503 reads as "feature not wired up".
        logger.warning("llm_gateway_admin_not_configured", error=str(exc))
        return Response({"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    logger.exception("llm_gateway_admin_call_failed")
    return Response({"detail": "LLM gateway request failed"}, status=status.HTTP_502_BAD_GATEWAY)


class LLMGatewayLimitsViewSet(viewsets.ViewSet):
    """Staff admin proxy to the LLM gateway's PostHog Code rate-limit endpoints.

    Django can't reach the gateway's rate-limit Redis directly, so these methods
    call the gateway over HTTP (authenticated with the shared admin secret). Access
    is restricted to staff via IsAdminUser, on top of the admin site's own gate.
    """

    permission_classes = [IsAdminUser]

    def retrieve(self, request: Request, user_id: str) -> Response:
        try:
            return Response(get_posthog_code_usage(int(user_id)))
        except (httpx.HTTPError, GatewayAdminError) as exc:
            return _gateway_error_response(exc)

    def reset(self, request: Request, user_id: str) -> Response:
        serializer = LLMGatewayResetSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            result = reset_posthog_code_usage(
                int(user_id),
                reset_cost=serializer.validated_data["reset_cost"],
                reset_request=serializer.validated_data["reset_request"],
                reset_product_total=serializer.validated_data["reset_product_total"],
                dry_run=serializer.validated_data["dry_run"],
            )
        except (httpx.HTTPError, GatewayAdminError) as exc:
            return _gateway_error_response(exc)
        logger.info(
            "llm_gateway_limits_reset",
            target_user_id=user_id,
            by=getattr(request.user, "email", None),
            dry_run=serializer.validated_data["dry_run"],
            result=result,
        )
        return Response(result)


def llm_gateway_limits_view(request):
    """Admin template view — thin wrapper that renders the HTML admin page."""
    context = {
        "title": "PostHog Code rate limits",
        "has_view_permission": True,
        "site_title": admin.site.site_title,
        "site_header": admin.site.site_header,
        "site_url": admin.site.site_url,
        "has_permission": True,
    }
    return render(request, "admin/llm_gateway_limits.html", context)
