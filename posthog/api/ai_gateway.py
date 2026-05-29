"""
Team-scoped read proxy for the ai-gateway billing service.

Surfaces:
    GET /api/projects/<team_id>/ai_gateway/wallet/
    GET /api/projects/<team_id>/ai_gateway/ledger/

Both forward to the ai-gateway billing service over the internal shared
secret (see posthog/ai_gateway/client.py). The runner does NOT go through
here — it talks to the gateway data plane directly with phc_.

Architecture: see docs/agent-platform/plans/ai-gateway-introspection.md.
"""

from __future__ import annotations

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.ai_gateway import BillingClient, BillingClientError, BillingMisconfigured
from posthog.api.routing import TeamAndOrgViewSetMixin


class AIGatewayAccountSerializer(serializers.Serializer):
    profile = serializers.ChoiceField(
        choices=[("A", "absorbed"), ("B", "internal_overage"), ("C", "external_prepay")],
        help_text="Billing profile: A=absorbed, B=internal overage, C=external prepay.",
    )
    overage_allowance_usd = serializers.CharField(
        help_text="USD overage allowance above the prepaid balance (decimal string)."
    )
    period = serializers.CharField(help_text="Billing period identifier — e.g. 'monthly'.")
    period_anchor = serializers.CharField(help_text="RFC3339 timestamp the billing period rolls over from.")
    rate_card_id = serializers.CharField(required=False, allow_null=True, help_text="Optional rate card identifier.")


class AIGatewayKillSwitchSerializer(serializers.Serializer):
    tripped = serializers.BooleanField(help_text="Whether the rolling-hour kill switch has fired.")
    threshold_usd = serializers.CharField(
        required=False, allow_null=True, help_text="USD spend threshold that trips the switch (decimal string)."
    )
    tripped_at = serializers.CharField(
        required=False, allow_null=True, help_text="RFC3339 timestamp the switch last tripped."
    )


class AIGatewayWalletSerializer(serializers.Serializer):
    team_id = serializers.IntegerField(help_text="PostHog team id this wallet belongs to.")
    available_usd = serializers.CharField(
        help_text="USD available to spend right now: balance minus pending holds (decimal string)."
    )
    pending_usd = serializers.CharField(help_text="USD reserved by in-flight session holds (decimal string).")
    balance_usd = serializers.CharField(
        help_text="Raw ledger balance in USD before subtracting holds (decimal string)."
    )
    spendable_usd = serializers.CharField(
        help_text="balance_usd plus the account's overage_allowance (decimal string)."
    )
    currency = serializers.CharField(help_text="ISO currency code. Always 'USD' at v0.")
    account = AIGatewayAccountSerializer(help_text="Account policy: profile, overage, period.")
    rolling_hour_usd = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="Rolling-hour spend that feeds the kill switch. Omitted when billing has not computed it yet.",
    )
    kill_switch = AIGatewayKillSwitchSerializer(help_text="Kill-switch state — tripped/threshold/tripped_at.")


class AIGatewayLedgerEntrySerializer(serializers.Serializer):
    id = serializers.CharField(help_text="Ledger entry uuid.")
    transaction_type = serializers.ChoiceField(
        choices=[
            ("debit", "debit"),
            ("topup", "topup"),
            ("refund", "refund"),
            ("adjustment", "adjustment"),
        ],
        help_text="Kind of ledger movement.",
    )
    source = serializers.CharField(help_text="Source bucket (funding | prepaid | revenue | adjustment).")
    destination = serializers.CharField(help_text="Destination bucket.")
    amount_usd = serializers.CharField(help_text="USD amount of the movement (decimal string).")
    list_cost_usd = serializers.CharField(
        required=False, allow_null=True, help_text="List price for a usage debit before any discount."
    )
    reference_id = serializers.CharField(
        required=False, allow_null=True, help_text="Idempotency key. Runner format: 'agent:<session_id>:<turn>'."
    )
    model = serializers.CharField(required=False, allow_null=True, help_text="Provider-prefixed model id.")
    provider = serializers.CharField(
        required=False, allow_null=True, help_text="Provider key (anthropic | openai | ...)."
    )
    input_tokens = serializers.IntegerField(required=False, allow_null=True, help_text="Input token count.")
    output_tokens = serializers.IntegerField(required=False, allow_null=True, help_text="Output token count.")
    distinct_id = serializers.CharField(
        required=False, allow_null=True, help_text="End-user identifier from X-PostHog-Distinct-Id."
    )
    created_at = serializers.CharField(help_text="RFC3339 timestamp the entry was settled.")


class AIGatewayLedgerListSerializer(serializers.Serializer):
    results = AIGatewayLedgerEntrySerializer(many=True, help_text="Ledger entries in newest-first order.")
    next_cursor = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="Opaque cursor for the next page. Absent when there are no more rows.",
    )


@extend_schema(tags=["ai_gateway"])
class AIGatewayViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    """Team-scoped read proxy into the ai-gateway billing service.

    All actions forward to billing over an internal shared secret. The
    viewset never reads the local Django DB; team isolation is enforced
    by the mixin (path team_id must match the requester's permissions),
    and billing receives that same team id as a query param.
    """

    scope_object = "ai_gateway"
    scope_object_read_actions = ["wallet", "ledger"]
    scope_object_write_actions: list[str] = []

    @extend_schema(
        operation_id="ai_gateway_wallet_retrieve",
        responses={200: AIGatewayWalletSerializer},
    )
    @action(detail=False, methods=["get"])
    def wallet(self, request: Request, **kwargs) -> Response:
        try:
            client = BillingClient.from_settings()
        except BillingMisconfigured:
            return Response({"error": "ai_gateway_not_configured"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        try:
            data = client.wallet(self.team_id)
        except BillingClientError as e:
            return _map_billing_error(e)
        return Response(data)

    @extend_schema(
        operation_id="ai_gateway_ledger_list",
        parameters=[
            OpenApiParameter(
                name="limit",
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Page size (default 50, max 200).",
            ),
            OpenApiParameter(
                name="cursor",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Opaque keyset cursor returned by a prior request.",
            ),
            OpenApiParameter(
                name="transaction_type",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                enum=["debit", "topup", "refund", "adjustment"],
                description="Filter to entries of a single transaction type.",
            ),
            OpenApiParameter(
                name="reference_id_prefix",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Filter to entries whose reference_id starts with this prefix. Use 'agent:<session_id>:' to scope to one session.",
            ),
        ],
        responses={200: AIGatewayLedgerListSerializer},
    )
    @action(detail=False, methods=["get"])
    def ledger(self, request: Request, **kwargs) -> Response:
        try:
            client = BillingClient.from_settings()
        except BillingMisconfigured:
            return Response({"error": "ai_gateway_not_configured"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        q = request.query_params
        limit = q.get("limit")
        try:
            limit_int = int(limit) if limit is not None else None
        except ValueError:
            return Response({"error": "limit must be an integer"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            data = client.ledger(
                self.team_id,
                limit=limit_int,
                cursor=q.get("cursor"),
                transaction_type=q.get("transaction_type"),
                reference_id_prefix=q.get("reference_id_prefix"),
            )
        except BillingClientError as e:
            return _map_billing_error(e)
        return Response(data)


def _map_billing_error(e: BillingClientError) -> Response:
    if e.status_code == 400:
        return Response({"error": "bad_request", "billing_body": e.body}, status=status.HTTP_400_BAD_REQUEST)
    if e.status_code == 404:
        return Response({"error": "not_found"}, status=status.HTTP_404_NOT_FOUND)
    if e.status_code == 503:
        return Response({"error": "ai_gateway_not_configured"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    # 401 from billing means our shared secret is wrong — surface as 502
    # rather than 401 to the API caller; their auth is fine, ours isn't.
    return Response(
        {"error": "billing_unavailable", "billing_status": e.status_code}, status=status.HTTP_502_BAD_GATEWAY
    )
