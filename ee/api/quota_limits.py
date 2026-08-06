"""Expose a team's quota-limit state.

Backs the LLM gateway's `QuotaResolver`, which forwards the caller's auth
header here to learn whether a given team is currently over its AI credits
quota. Project-nested so org membership and token `scoped_teams`/
`scoped_organizations` enforcement come from the standard
`TeamAndOrgViewSetMixin` permission chain — see
`posthog.permissions.APIScopePermission.check_team_and_org_permissions`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import structlog
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.constants import AvailableFeature

from products.tasks.backend.logic.services.sandbox_pricing import (
    COMPUTE_RATE_CARDS,
    ComputeRateCardConfigurationError,
    get_compute_rate_cards_for_period,
)

from ee.billing.quota_limiting import QuotaResource, get_fresh_team_limited_resources

logger = structlog.get_logger(__name__)


class QuotaResourceLimitSerializer(serializers.Serializer):
    limited = serializers.BooleanField(
        help_text="True when the team is currently over its quota for this resource and limits are in effect.",
    )
    usage = serializers.IntegerField(
        allow_null=True,
        help_text=(
            "Units of this resource the organization has used so far this billing period, in the "
            "resource's native unit (credits for credit buckets). Null when billing hasn't synced "
            "usage for the resource."
        ),
    )
    limit = serializers.IntegerField(
        allow_null=True,
        help_text="The organization's limit for this resource in the same unit. Null when unlimited or unknown.",
    )


def _resource_usage(summary: dict[str, Any]) -> int | None:
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
    version = serializers.CharField(help_text="Published compute rate-card version.")
    effective_at = serializers.DateTimeField(help_text="Timestamp when this rate card became effective.")
    expires_at = serializers.DateTimeField(
        allow_null=True, help_text="Timestamp when this rate card stopped applying, or null for the current version."
    )
    cpu_usd_per_core_second = serializers.DecimalField(
        max_digits=24,
        decimal_places=18,
        normalize_output=True,
        help_text="Published USD price per CPU core-second.",
    )
    memory_usd_per_gib_second = serializers.DecimalField(
        max_digits=24,
        decimal_places=18,
        normalize_output=True,
        help_text="Published USD price per memory GiB-second.",
    )


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
    posthog_code_compute_rate_cards = ComputeRateCardSerializer(
        many=True,
        allow_null=True,
        help_text=(
            "Published PostHog Desktop compute rate cards overlapping the synchronized billing period. "
            "Null means the configured rate cards are invalid; an empty list means compute pricing is inactive."
        ),
    )
    posthog_code_compute_rate_card_error = serializers.ChoiceField(
        choices=("invalid_configuration",),
        allow_null=True,
        help_text="Set when configured compute rates are invalid and therefore omitted.",
    )


def _billing_period(period: object) -> tuple[datetime | None, datetime | None]:
    start: datetime | None = None
    end: datetime | None = None
    if isinstance(period, list) and len(period) == 2:
        try:
            start, end = (datetime.fromisoformat(value.replace("Z", "+00:00")) for value in period)
        except (AttributeError, TypeError, ValueError):
            pass
    return start, end


def _compute_rate_cards(period: object) -> tuple[object, str | None]:
    start, end = _billing_period(period)
    try:
        return get_compute_rate_cards_for_period(start, end, COMPUTE_RATE_CARDS), None
    except ComputeRateCardConfigurationError:
        logger.exception("posthog_code_compute_rate_card_invalid")
        return None, "invalid_configuration"


@extend_schema(tags=["quota_limits"], extensions={"x-product": "tasks"})
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
        compute_rate_cards, compute_rate_card_error = _compute_rate_cards(org_usage.get("period"))
        return Response(
            QuotaLimitsResponseSerializer(
                {
                    "limited": limited,
                    "code_usage_billing_active": self.team.organization.is_feature_available(
                        AvailableFeature.POSTHOG_CODE_USAGE
                    ),
                    "posthog_code_compute_rate_cards": compute_rate_cards,
                    "posthog_code_compute_rate_card_error": compute_rate_card_error,
                }
            ).data
        )
