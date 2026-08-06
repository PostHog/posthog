"""Expose a team's quota-limit state.

Backs the LLM gateway's `QuotaResolver`, which forwards the caller's auth
header here to learn whether a given team is currently over its AI credits
quota. Project-nested so org membership and token `scoped_teams`/
`scoped_organizations` enforcement come from the standard
`TeamAndOrgViewSetMixin` permission chain — see
`posthog.permissions.APIScopePermission.check_team_and_org_permissions`.
"""

from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal
from typing import Any

from drf_spectacular.utils import extend_schema
from rest_framework import serializers, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.constants import AvailableFeature

from products.tasks.backend.logic.services.sandbox_pricing import (
    COMPUTE_RATE_CARDS,
    ComputeRateCardConfigurationError,
    validate_compute_rate_cards,
)

from ee.billing.quota_limiting import QuotaResource, get_fresh_team_limited_resources

logger = logging.getLogger(__name__)

POSTHOG_CODE_COMPONENTS = (
    "posthog_code_token_credits",
    "sandbox_compute_credits",
    "sandbox_compute_cpu_millicore_seconds",
    "sandbox_compute_memory_mib_seconds",
    "sandbox_compute_cpu_cost_microusd",
    "sandbox_compute_memory_cost_microusd",
)


class QuotaResourceLimitSerializer(serializers.Serializer):
    limited = serializers.BooleanField(
        help_text="True when the team is currently over its quota for this resource and limits are in effect.",
    )
    usage = serializers.FloatField(
        allow_null=True,
        help_text=(
            "Units of this resource the organization has used so far this billing period, in the "
            "resource's native unit (credits for credit buckets). Null when billing hasn't synced "
            "usage for the resource."
        ),
    )
    limit = serializers.FloatField(
        allow_null=True,
        help_text="The organization's limit for this resource in the same unit. Null when unlimited or unknown.",
    )


def _resource_usage(summary: dict[str, Any]) -> float | None:
    """usage + todays_usage, the sum the quota limiter compares against the limit.

    None rather than 0 when billing has never synced the resource, so clients read
    it as unknown, not "$0 spent". The `limited` boolean stays authoritative for
    gating; grace periods and refund offsets live only in that limiting decision.
    """
    if not summary:
        return None
    usage = summary.get("usage")
    todays_usage = summary.get("todays_usage")
    if usage is None and todays_usage is None:
        return None
    return (usage or 0) + (todays_usage or 0)


class ComputeRateCardSerializer(serializers.Serializer):
    version = serializers.CharField()
    effective_at = serializers.DateTimeField()
    expires_at = serializers.DateTimeField(allow_null=True)
    cpu_usd_per_core_second = serializers.DecimalField(max_digits=24, decimal_places=18, normalize_output=True)
    memory_usd_per_gib_second = serializers.DecimalField(max_digits=24, decimal_places=18, normalize_output=True)


class PostHogCodeUsageSerializer(serializers.Serializer):
    token_credits = serializers.IntegerField(allow_null=True)
    token_used_usd = serializers.DecimalField(max_digits=20, decimal_places=2, allow_null=True, normalize_output=True)
    compute_credits = serializers.IntegerField(allow_null=True)
    compute_used_usd = serializers.DecimalField(max_digits=20, decimal_places=2, allow_null=True, normalize_output=True)
    cpu_millicore_seconds = serializers.IntegerField(allow_null=True)
    memory_mib_seconds = serializers.IntegerField(allow_null=True)
    cpu_cost_microusd = serializers.IntegerField(allow_null=True)
    memory_cost_microusd = serializers.IntegerField(allow_null=True)
    rate_cards = ComputeRateCardSerializer(many=True, allow_null=True)
    rate_card_error = serializers.ChoiceField(choices=("invalid_configuration",), allow_null=True)


class QuotaLimitsResponseSerializer(serializers.Serializer):
    limited = serializers.DictField(
        child=QuotaResourceLimitSerializer(),
        help_text="Per-resource limit state for every `QuotaResource` value, e.g. `ai_credits`, `posthog_code_credits`.",
    )
    code_usage_billing_active = serializers.BooleanField(
        help_text=(
            "Whether the team's organization pays for PostHog Desktop usage: billing grants the "
            "`posthog_code_usage` product feature only on the Desktop usage product's paid plan, "
            "synced into the organization's available features. Consumers gate paid-tier Desktop "
            "behavior on this; an org unknown to billing reads as not paying."
        ),
    )
    posthog_code_usage = PostHogCodeUsageSerializer(required=False, allow_null=True)


def _integer_resource_usage(summary: dict[str, Any]) -> int | None:
    value = _resource_usage(summary)
    return int(value) if value is not None else None


def _rate_cards_for_period(period: object) -> tuple[list[dict[str, str | None]] | None, str | None]:
    if not COMPUTE_RATE_CARDS:
        return [], None
    try:
        cards = validate_compute_rate_cards(COMPUTE_RATE_CARDS)
    except ComputeRateCardConfigurationError:
        logger.exception("Invalid PostHog Desktop compute rate-card configuration")
        return None, "invalid_configuration"

    start: datetime | None = None
    end: datetime | None = None
    if isinstance(period, list) and len(period) == 2:
        try:
            start, end = (datetime.fromisoformat(value.replace("Z", "+00:00")) for value in period)
        except (AttributeError, TypeError, ValueError):
            pass

    applicable = cards
    if start is not None and end is not None:
        applicable = tuple(
            card for card in cards if card.effective_at < end and (card.expires_at is None or card.expires_at > start)
        )
    return [
        {
            "version": card.version,
            "effective_at": card.effective_at.isoformat(),
            "expires_at": card.expires_at.isoformat() if card.expires_at else None,
            "cpu_usd_per_core_second": str(card.cpu_core_second_usd),
            "memory_usd_per_gib_second": str(card.memory_gib_second_usd),
        }
        for card in applicable
    ], None


def _posthog_code_usage(org_usage: dict[str, Any]) -> dict[str, Any] | None:
    if not any(key in org_usage for key in POSTHOG_CODE_COMPONENTS):
        return None
    rate_cards, rate_card_error = _rate_cards_for_period(org_usage.get("period"))
    token_credits, compute_credits, cpu_quantity, memory_quantity, cpu_cost, memory_cost = (
        _integer_resource_usage(org_usage.get(key) or {}) for key in POSTHOG_CODE_COMPONENTS
    )
    return {
        "token_credits": token_credits,
        "token_used_usd": str(Decimal(token_credits) / 100) if token_credits is not None else None,
        "compute_credits": compute_credits,
        "compute_used_usd": str(Decimal(compute_credits) / 100) if compute_credits is not None else None,
        "cpu_millicore_seconds": cpu_quantity,
        "memory_mib_seconds": memory_quantity,
        "cpu_cost_microusd": cpu_cost,
        "memory_cost_microusd": memory_cost,
        "rate_cards": rate_cards,
        "rate_card_error": rate_card_error,
    }


@extend_schema(tags=["quota_limits"])
class QuotaLimitsViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    """Read-only view of a team's quota-limit state."""

    scope_object = "project"
    required_scopes = ["project:read"]
    http_method_names = ["get", "head", "options"]

    @extend_schema(
        summary="Get a team's quota-limit state",
        description=(
            "Return the current quota-limit state for the team identified in the URL, "
            "keyed by `QuotaResource` value. Used by the LLM gateway to gate billable "
            "products on AI credits exhaustion."
        ),
        responses={200: QuotaLimitsResponseSerializer},
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        org_usage = self.team.organization.usage or {}
        # Fresh read on purpose: the gateway re-caches this answer for minutes, so serving
        # the 30s per-worker memo here would re-poison a just-invalidated gateway entry.
        limited_resources = get_fresh_team_limited_resources(self.team.api_token)
        limited = {}
        for resource in QuotaResource:
            summary = org_usage.get(resource.value) or {}
            limited[resource.value] = {
                "limited": limited_resources[resource],
                "usage": _resource_usage(summary),
                "limit": summary.get("limit"),
            }
        return Response(
            QuotaLimitsResponseSerializer(
                {
                    "limited": limited,
                    "code_usage_billing_active": self.team.organization.is_feature_available(
                        AvailableFeature.POSTHOG_CODE_USAGE
                    ),
                    "posthog_code_usage": _posthog_code_usage(org_usage),
                }
            ).data
        )
