"""
Per-person spend limit for gateway-routed model spend.

The limit is an ai-gateway attribution budget on the `user` node, keyed by the
person's gateway user node (`posthog.models.user_gateway_node`). Cloud runs pin
that same value into their scoped token and the desktop asserts it as
`X-PostHog-User`, so the node the gateway counts spend against is the node this
endpoint configures. Keying it on anything else (the user uuid, say) writes a
budget nothing ever debits.

Endpoints (all scoped to the requesting user, who can only reach their own):
- GET    /api/projects/:team_id/ai_gateway/@me/spend_limit/
- POST   /api/projects/:team_id/ai_gateway/@me/spend_limit/
- DELETE /api/projects/:team_id/ai_gateway/@me/spend_limit/clear/
"""

from __future__ import annotations

from decimal import Decimal
from typing import cast

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.llm.gateway_internal_client import (
    AIGatewayInternalError,
    AIGatewayNotConfigured,
    clear_user_budget,
    get_user_budget,
    set_user_budget,
)
from posthog.models import User
from posthog.models.user_gateway_node import gateway_user_node

# A window shorter than an hour would reset faster than settlement lands, so a
# limit set there could never bind. The ceiling matches the gateway's.
MIN_WINDOW_SECONDS = 3600
MAX_WINDOW_SECONDS = 366 * 24 * 60 * 60
MIN_LIMIT_USD = Decimal("0.01")
MAX_LIMIT_USD = Decimal("1000000000")


class UserSpendLimitSerializer(serializers.Serializer):
    limit_usd = serializers.CharField(
        allow_null=True,
        help_text="The limit in USD as a decimal string, or null when no limit is set.",
    )
    window_seconds = serializers.IntegerField(
        allow_null=True,
        help_text=(
            "Length of the accounting window the limit applies to, in seconds. The window is fixed rather than "
            "sliding: it starts at the first spend after a reset and the counter resets once per window. Null when "
            "no limit is set."
        ),
    )
    enforced = serializers.BooleanField(
        help_text=(
            "Whether the gateway can hold spend for this deployment. False means no limit can be set here, so any "
            "limit shown in the app informs only."
        ),
    )


class UserSpendLimitWriteSerializer(serializers.Serializer):
    limit_usd = serializers.DecimalField(
        max_digits=19,
        decimal_places=6,
        min_value=MIN_LIMIT_USD,
        max_value=MAX_LIMIT_USD,
        help_text="The limit in USD. Spend past it is refused for this person until the window resets.",
    )
    window_seconds = serializers.IntegerField(
        min_value=MIN_WINDOW_SECONDS,
        max_value=MAX_WINDOW_SECONDS,
        help_text="Length of the accounting window in seconds, at least an hour and at most 366 days.",
    )


class SpendLimitErrorSerializer(serializers.Serializer):
    detail = serializers.CharField(help_text="What went wrong, in a form that can be shown to a person.")


class UserSpendLimitViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    """The requesting user's own spend limit for model traffic through the gateway."""

    # The limit belongs to the person, not to the team's data, so it rides the
    # same scope as /api/users/@me/ rather than a team resource scope.
    scope_object = "user"
    # `list` on a plain ViewSet and a custom @action match none of
    # ScopeBasePermission's default action lists, so personal-API-key requests
    # 403 without these spelled out.
    scope_object_read_actions = ["list"]
    scope_object_write_actions = ["create", "clear"]
    serializer_class = UserSpendLimitSerializer
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="ai_gateway_user_spend_limit_retrieve",
        responses={
            200: UserSpendLimitSerializer,
            502: OpenApiResponse(response=SpendLimitErrorSerializer),
        },
    )
    def list(self, request: Request, **kwargs) -> Response:
        try:
            budget = get_user_budget(self.team_id, _scope_value(request))
        except AIGatewayNotConfigured:
            return Response(_unenforced())
        except AIGatewayInternalError:
            return _gateway_unreachable()
        if budget is None:
            return Response(_unenforced(enforced=True))
        return Response(
            UserSpendLimitSerializer(
                {"limit_usd": budget.limit_usd, "window_seconds": budget.window_seconds, "enforced": True}
            ).data
        )

    @validated_request(
        request_serializer=UserSpendLimitWriteSerializer,
        operation_id="ai_gateway_user_spend_limit_create",
        responses={
            200: OpenApiResponse(response=UserSpendLimitSerializer),
            502: OpenApiResponse(response=SpendLimitErrorSerializer),
            503: OpenApiResponse(response=SpendLimitErrorSerializer),
        },
    )
    def create(self, request: ValidatedRequest, **kwargs) -> Response:
        limit_usd = request.validated_data["limit_usd"]
        window_seconds = request.validated_data["window_seconds"]
        try:
            budget = set_user_budget(self.team_id, _scope_value(request), str(limit_usd), window_seconds)
        except AIGatewayNotConfigured:
            return _not_available()
        except AIGatewayInternalError:
            return _gateway_unreachable()
        return Response(
            UserSpendLimitSerializer(
                {"limit_usd": budget.limit_usd, "window_seconds": budget.window_seconds, "enforced": True}
            ).data
        )

    @extend_schema(
        operation_id="ai_gateway_user_spend_limit_clear",
        request=None,
        responses={
            200: UserSpendLimitSerializer,
            502: OpenApiResponse(response=SpendLimitErrorSerializer),
            503: OpenApiResponse(response=SpendLimitErrorSerializer),
        },
    )
    @action(detail=False, methods=["delete"])
    def clear(self, request: Request, **kwargs) -> Response:
        try:
            clear_user_budget(self.team_id, _scope_value(request))
        except AIGatewayNotConfigured:
            return _not_available()
        except AIGatewayInternalError:
            return _gateway_unreachable()
        return Response(_unenforced(enforced=True))


def _scope_value(request: Request | ValidatedRequest) -> str:
    # IsAuthenticated has already run, so the anonymous branch of the union
    # cannot be reached here.
    return gateway_user_node(cast(User, request.user))


def _unenforced(enforced: bool = False) -> dict[str, object]:
    return UserSpendLimitSerializer({"limit_usd": None, "window_seconds": None, "enforced": enforced}).data


def _not_available() -> Response:
    return Response(
        {"detail": "Spend limits aren't available on this deployment yet."},
        status=status.HTTP_503_SERVICE_UNAVAILABLE,
    )


def _gateway_unreachable() -> Response:
    return Response(
        {"detail": "Couldn't reach the spend limit service. Try again in a moment."},
        status=status.HTTP_502_BAD_GATEWAY,
    )
