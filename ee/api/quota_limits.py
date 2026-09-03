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

from ee.billing.quota_limiting import INFORMATIONAL_USAGE_RESOURCES, QuotaResource, get_fresh_team_limited_resources


class QuotaResourceLimitSerializer(serializers.Serializer):
    limited = serializers.BooleanField(
        help_text=(
            "True when the team is currently over its quota for this resource and limits are in "
            "effect. A deactivated organization additionally reads as limited on the two credit "
            "buckets `ai_credits` and `posthog_code_credits`, regardless of usage."
        ),
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


class QuotaLimitsResponseSerializer(serializers.Serializer):
    limited = serializers.DictField(
        child=QuotaResourceLimitSerializer(),
        help_text=(
            "Per-resource limit state for every `QuotaResource` value, e.g. `ai_credits`, "
            "`posthog_code_credits`. Also carries the informational Desktop component resources "
            "(`posthog_code_token_credits`, `sandbox_compute_credits`, "
            "`sandbox_compute_cpu_millicore_seconds`, `sandbox_compute_memory_mib_seconds`) with "
            "usage in their native units, a null limit, and `limited` always false — they are never "
            "quota-enforced; only the combined `posthog_code_credits` is."
        ),
    )
    code_usage_billing_active = serializers.BooleanField(
        help_text=(
            "Whether the team's organization pays for PostHog Desktop usage: billing grants the "
            "`posthog_code_usage` product feature only on the Desktop usage product's paid plan, "
            "synced into the organization's available features. Consumers gate paid-tier Desktop "
            "behavior on this; an org unknown to billing reads as not paying. Always false for "
            "deactivated organizations."
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
        org_deactivated = self.team.organization.is_active is False
        # Fresh read on purpose: the gateway re-caches this answer for minutes, so serving
        # the 30s per-worker memo here would re-poison a just-invalidated gateway entry.
        # A deactivated org (for any reason) instead reads as limited on just the two credit
        # buckets the gateway enforces on — that blocks AI and Desktop spend without dropping
        # events, recordings, or syncs, and without depending on Redis being reachable.
        if org_deactivated:
            limited_resources = dict.fromkeys(QuotaResource, False)
            limited_resources[QuotaResource.AI_CREDITS] = True
            limited_resources[QuotaResource.POSTHOG_CODE_CREDITS] = True
        else:
            limited_resources = get_fresh_team_limited_resources(self.team.api_token)
        limited = {}
        for resource in QuotaResource:
            summary = org_usage.get(resource.value) or {}
            limited[resource.value] = {
                "limited": limited_resources[resource],
                "usage": _resource_usage(summary),
                "limit": summary.get("limit"),
            }
        for field in INFORMATIONAL_USAGE_RESOURCES:
            limited[field] = {
                "limited": False,
                "usage": _resource_usage(org_usage.get(field) or {}),
                "limit": None,
            }
        data = QuotaLimitsResponseSerializer(
            {
                "limited": limited,
                "code_usage_billing_active": not org_deactivated
                and self.team.organization.is_feature_available(AvailableFeature.POSTHOG_CODE_USAGE),
            }
        ).data
        return Response(data)
