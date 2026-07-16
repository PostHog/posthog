"""Expose a team's quota-limit state.

Backs the LLM gateway's `QuotaResolver`, which forwards the caller's auth
header here to learn whether a given team is currently over its AI credits
quota. Project-nested so org membership and token `scoped_teams`/
`scoped_organizations` enforcement come from the standard
`TeamAndOrgViewSetMixin` permission chain — see
`posthog.permissions.APIScopePermission.check_team_and_org_permissions`.
"""

from __future__ import annotations

from typing import Any

from drf_spectacular.utils import extend_schema
from rest_framework import serializers, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.constants import AvailableFeature

from ee.billing.quota_limiting import QuotaLimitingCaches, QuotaResource, is_team_limited


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
    return (summary.get("usage") or 0) + (summary.get("todays_usage") or 0)


class QuotaLimitsResponseSerializer(serializers.Serializer):
    limited = serializers.DictField(
        child=QuotaResourceLimitSerializer(),
        help_text="Per-resource limit state for every `QuotaResource` value, e.g. `ai_credits`, `posthog_code_credits`.",
    )
    code_usage_billing_active = serializers.BooleanField(
        help_text=(
            "Whether the team's organization pays for PostHog Code usage: billing grants the "
            "`posthog_code_usage` product feature only on the Code usage product's paid plan, "
            "synced into the organization's available features. Consumers gate paid-tier Code "
            "behavior on this; an org unknown to billing reads as not paying."
        ),
    )


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
        limited = {}
        for resource in QuotaResource:
            summary = org_usage.get(resource.value) or {}
            limited[resource.value] = {
                "limited": is_team_limited(
                    self.team.api_token,
                    resource,
                    QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY,
                ),
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
                }
            ).data
        )
